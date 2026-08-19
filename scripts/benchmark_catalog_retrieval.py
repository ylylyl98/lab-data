"""Opt-in, read-only benchmark for catalog retrieval operations."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lab_data.catalog_retrieval import (
    find_device_documents,
    find_device_experiments,
    get_artifact_preview,
    search_artifacts,
    search_devices,
    search_experiments,
)
from lab_data.scientific_catalog import open_read_only_catalog


def _measure(operation: Callable[[], Any]) -> tuple[float, Any]:
    started = time.perf_counter()
    result = operation()
    return time.perf_counter() - started, result


def _operation_payload(elapsed: float, result: Any) -> dict[str, Any]:
    return {
        'seconds': elapsed,
        'result_count': len(result) if isinstance(result, (tuple, list)) else 0,
        'result_present': result is not None,
    }


def _summarize_runs(runs: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    names = runs[0]
    return {
        name: {
            'median_seconds': statistics.median(run[name] for run in runs),
            'max_seconds': max(run[name] for run in runs),
        }
        for name in names
    }


def run_benchmark(  # noqa: PLR0913
    catalog: Path,
    preview_root: Path,
    *,
    device_id: str = 'D356',
    sample_id: str = 'YZ247',
    artifact_id: str | None = None,
    image_preview_id: str | None = None,
    table_preview_id: str | None = None,
    slide_preview_id: str | None = None,
) -> dict[str, Any]:
    """Run cold, warmed, and five-run retrieval timings."""

    preview_root = preview_root.resolve()
    store = open_read_only_catalog(catalog)
    try:
        device_artifacts = store.list_artifacts(device_id=device_id)
        all_artifacts = store.list_artifacts()
        exact_artifact_id = artifact_id or (
            device_artifacts[0].artifact_id if device_artifacts else None
        )

        def choose_preview(explicit: str | None, kinds: set[str]) -> str | None:
            if explicit is not None:
                return explicit
            for artifact in all_artifacts:
                extension = artifact.extension.casefold().lstrip('.')
                category = artifact.category.casefold()
                if extension in kinds or category in kinds:
                    return artifact.artifact_id
            return None

        preview_ids = {
            'image': choose_preview(
                image_preview_id, {'png', 'jpg', 'jpeg', 'tif', 'tiff', 'image'}
            ),
            'table': choose_preview(table_preview_id, {'csv', 'tsv', 'dat', 'table'}),
            'slide': choose_preview(slide_preview_id, {'ppt', 'pptx', 'slide'}),
        }

        def preview_operation(preview_id: str | None) -> Callable[[], Any]:
            if preview_id is None:
                return lambda: None
            return lambda: get_artifact_preview(
                store, preview_id, preview_root=preview_root
            )

        if exact_artifact_id is None:

            def exact_artifact_operation() -> tuple[Any, ...]:
                return ()
        else:

            def exact_artifact_operation() -> tuple[dict[str, Any], ...]:
                return search_artifacts(
                    store, filters={'artifact_id': exact_artifact_id}
                )

        operations: dict[str, Callable[[], Any]] = {
            'device_D356': lambda: search_devices(
                store, filters={'device_id': device_id}
            ),
            'device_YZ247_absent': lambda: search_devices(
                store, filters={'device_id': sample_id}
            ),
            'artifact_exact_id': exact_artifact_operation,
            'artifacts_D356': lambda: search_artifacts(
                store, filters={'device_id': device_id}
            ),
            'documents_D356': lambda: find_device_documents(store, device_id),
            'experiments_for_D356': lambda: find_device_experiments(store, device_id),
            'sample_YZ247': lambda: search_experiments(
                store, filters={'sample_id': sample_id}
            ),
            'experiment_YZ247_0001': lambda: search_experiments(
                store, filters={'experiment_id': f'{sample_id}-0001'}
            ),
            'experiment_YZ247_0432': lambda: search_experiments(
                store, filters={'experiment_id': f'{sample_id}-0432'}
            ),
            'experiment_YZ247_1505': lambda: search_experiments(
                store, filters={'experiment_id': f'{sample_id}-1505'}
            ),
            'preview_image': preview_operation(preview_ids['image']),
            'preview_table': preview_operation(preview_ids['table']),
            'preview_slide': preview_operation(preview_ids['slide']),
        }

        def run_once() -> tuple[dict[str, dict[str, Any]], float]:
            started = time.perf_counter()
            results = {}
            for name, operation in operations.items():
                elapsed, result = _measure(operation)
                results[name] = _operation_payload(elapsed, result)
            return results, time.perf_counter() - started

        cold, cold_combined = run_once()
        run_once()
        warm_runs: list[dict[str, float]] = []
        warm_combined: list[float] = []
        for _ in range(5):
            started = time.perf_counter()
            timings: dict[str, float] = {}
            for name, operation in operations.items():
                elapsed, _ = _measure(operation)
                timings[name] = elapsed
            warm_runs.append(timings)
            warm_combined.append(time.perf_counter() - started)

        return {
            'catalog': str(catalog),
            'preview_root': str(preview_root),
            'workload': {
                'device_id': device_id,
                'sample_id': sample_id,
                'artifact_id': exact_artifact_id,
                'preview_ids': preview_ids,
            },
            'cold': {'operations': cold, 'combined_seconds': cold_combined},
            'warm_5_run': {
                'operations': _summarize_runs(warm_runs),
                'combined_seconds': {
                    'median_seconds': statistics.median(warm_combined),
                    'max_seconds': max(warm_combined),
                },
            },
        }
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--preview-root', type=Path, required=True)
    parser.add_argument('--device-id', default='D356')
    parser.add_argument('--sample-id', default='YZ247')
    parser.add_argument('--artifact-id')
    parser.add_argument('--image-preview-id')
    parser.add_argument('--table-preview-id')
    parser.add_argument('--slide-preview-id')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    payload = json.dumps(
        run_benchmark(
            args.catalog,
            args.preview_root,
            device_id=args.device_id,
            sample_id=args.sample_id,
            artifact_id=args.artifact_id,
            image_preview_id=args.image_preview_id,
            table_preview_id=args.table_preview_id,
            slide_preview_id=args.slide_preview_id,
        ),
        indent=2,
        sort_keys=True,
    )
    if args.output is None:
        print(payload)
    else:
        args.output.write_text(payload + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
