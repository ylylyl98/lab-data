"""Local-only MCP stdio adapter over the scientific tool layer.

This module exposes ``ScientificToolLayer`` through the Model Context
Protocol over stdio.  It is deliberately read-only, local-only, and
unauthenticated in this phase: the server binds no network interface and must
never be exposed to CMU-Secure or the Internet directly.  Every tool maps one
to one onto a ``ScientificToolLayer`` method and returns its JSON-safe payload
verbatim; there is no direct catalog access, no SQL, no caller-supplied
filesystem path, and no external model call.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from lab_data.scientific_tools import MAX_LIMIT, MIN_LIMIT, ScientificToolLayer

CATALOG_PATH_ENV = 'LAB_DATA_CATALOG_PATH'
PREVIEW_ROOT_ENV = 'LAB_DATA_PREVIEW_ROOT'

SERVER_NAME = 'lab-data-scientific-tools'
_STARTUP_BANNER = (
    'lab-data MCP adapter: local-only stdio server; unauthenticated. '
    'Do not expose it to CMU-Secure or the Internet.'
)


def load_mcp_config() -> tuple[Path, Path]:
    """Resolve and validate catalog and preview root from environment."""

    catalog_value = os.environ.get(CATALOG_PATH_ENV)
    preview_value = os.environ.get(PREVIEW_ROOT_ENV)
    if not catalog_value or not preview_value:
        raise ValueError(
            f'{CATALOG_PATH_ENV} and {PREVIEW_ROOT_ENV} must both be set '
            f'(current values: {CATALOG_PATH_ENV}={catalog_value!r}, '
            f'{PREVIEW_ROOT_ENV}={preview_value!r})'
        )
    catalog_path = Path(catalog_value)
    preview_root = Path(preview_value)
    if not catalog_path.is_file():
        raise ValueError(
            f'{CATALOG_PATH_ENV} does not point to a readable catalog file: '
            f'{catalog_path}'
        )
    if not preview_root.is_dir():
        raise ValueError(
            f'{PREVIEW_ROOT_ENV} does not point to a preview directory: '
            f'{preview_root}'
        )
    return catalog_path, preview_root


_SearchLimit = Annotated[int, Field(ge=MIN_LIMIT, le=MAX_LIMIT)]
_Offset = Annotated[int, Field(ge=0)]
_NonEmptyId = Annotated[str, Field(min_length=1)]


def create_server(layer: ScientificToolLayer) -> FastMCP:
    """Build an MCP server that wraps one read-only tool layer."""

    server = FastMCP(SERVER_NAME)

    @server.tool()
    def search_devices(
        q: str | None = None,
        limit: _SearchLimit = 20,
        offset: _Offset = 0,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Search device records by substring or exact filter; q is a search string, not a canonical ID."""
        return layer.search_devices(
            q, limit=limit, offset=offset, filters=filters
        )

    @server.tool()
    def search_experiments(
        q: str | None = None,
        limit: _SearchLimit = 20,
        offset: _Offset = 0,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Search experiments by substring or exact structured filters (e.g. measurement_type, temperature_K); surfaces review state."""
        return layer.search_experiments(
            q, limit=limit, offset=offset, filters=filters
        )

    @server.tool()
    def search_artifacts(
        q: str | None = None,
        limit: _SearchLimit = 20,
        offset: _Offset = 0,
        kind: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Search artifact (file-like) records by substring, kind, or exact filter; q is a search string, not a canonical ID."""
        return layer.search_artifacts(
            q, limit=limit, offset=offset, kind=kind, filters=filters
        )

    @server.tool()
    def get_device(device_id: _NonEmptyId) -> dict[str, Any] | None:
        """Return one exact device by its canonical device_id, or None when absent."""
        return layer.get_device(device_id)

    @server.tool()
    def get_experiment(experiment_id: _NonEmptyId) -> dict[str, Any] | None:
        """Return one exact experiment by its canonical experiment_id, including files by role, measured_on, and review state."""
        return layer.get_experiment(experiment_id)

    @server.tool()
    def get_artifact(artifact_id: _NonEmptyId) -> dict[str, Any] | None:
        """Return one exact artifact by its canonical artifact_id, including derived_from edges."""
        return layer.get_artifact(artifact_id)

    @server.tool()
    def find_device_experiments(
        device_id: _NonEmptyId,
        limit: _SearchLimit = 50,
        offset: _Offset = 0,
        q: str | None = None,
    ) -> dict[str, Any]:
        """Return the bounded page of experiments explicitly measured on one device (persisted measured_on relationships)."""
        return layer.find_device_experiments(
            device_id, limit=limit, offset=offset, q=q
        )

    @server.tool()
    def find_device_documents(
        device_id: _NonEmptyId,
        limit: _SearchLimit = 50,
        offset: _Offset = 0,
        q: str | None = None,
    ) -> dict[str, Any]:
        """Return the bounded page of PDF/PPT/PPTX documents bound to one device."""
        return layer.find_device_documents(
            device_id, limit=limit, offset=offset, q=q
        )

    @server.tool()
    def get_provenance(
        subject_type: _NonEmptyId, subject_id: _NonEmptyId
    ) -> list[dict[str, Any]]:
        """Return persisted metadata claims for one subject (why/how a value is known, with source and review status); nothing is inferred."""
        return layer.get_provenance(subject_type, subject_id)

    @server.tool()
    def get_lineage(
        entity_type: _NonEmptyId, entity_id: _NonEmptyId
    ) -> list[dict[str, Any]]:
        """Return persisted relationship edges touching one entity, oriented upstream source to downstream target (raw -> processed -> figure)."""
        return layer.get_lineage(entity_type, entity_id)

    @server.tool()
    def get_artifact_preview(artifact_id: _NonEmptyId) -> dict[str, Any] | None:
        """Return the validated metadata-only preview report (manifest plus asset metadata) for one artifact; binary content is not served."""
        return layer.get_artifact_preview(artifact_id)

    return server


def build_mcp_server(catalog_path: Path, preview_root: Path) -> FastMCP:
    """Build a server over a catalog opened read-only with a preview root."""

    layer = ScientificToolLayer.from_catalog(catalog_path, preview_root=preview_root)
    return create_server(layer)


def main() -> None:
    """Validate configuration and run the stdio server (no network binding)."""

    try:
        catalog_path, preview_root = load_mcp_config()
        server = build_mcp_server(catalog_path, preview_root)
    except (ValueError, FileNotFoundError) as error:
        print(f'lab-data MCP adapter: {error}', file=sys.stderr)
        raise SystemExit(1) from error
    print(_STARTUP_BANNER, file=sys.stderr)
    server.run(transport='stdio')


if __name__ == '__main__':
    main()
