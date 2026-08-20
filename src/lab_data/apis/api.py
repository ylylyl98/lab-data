"""Read-only user-facing catalog search API for the NOMAD plugin."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from nomad.config import config
from pydantic import BaseModel, ConfigDict, Field

from lab_data.artifact_previews import read_artifact_preview_asset
from lab_data.catalog_retrieval import (
    Page,
    find_device_documents,
    find_device_experiments,
    get_artifact_preview,
    search_artifacts,
    search_devices,
    search_experiments,
)
from lab_data.scientific_catalog import SQLiteCatalogStore, open_read_only_catalog

CATALOG_PATH_ENV = 'LAB_DATA_CATALOG_PATH'
PREVIEW_ROOT_ENV = 'LAB_DATA_PREVIEW_ROOT'

api_entry_point = config.get_plugin_entry_point('lab_data.apis:api_entry_point')


def _root_path() -> str:
    return f'{config.services.api_base_path}/{api_entry_point.prefix}'


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return None if not value else Path(value)


def _env_catalog_path() -> Path | None:
    return _env_path(CATALOG_PATH_ENV)


def _env_preview_root() -> Path | None:
    return _env_path(PREVIEW_ROOT_ENV)


@contextmanager
def _read_only_catalog(path: Path | None) -> Iterator[SQLiteCatalogStore]:
    if path is None:
        raise HTTPException(status_code=503, detail='catalog is not configured')
    try:
        store = open_read_only_catalog(path)
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail='catalog is unavailable') from error
    try:
        yield store
    finally:
        store.close()


def _envelope(page: Page, limit: int, offset: int) -> dict[str, Any]:
    return {
        'items': list(page.items),
        'total_count': page.total_count,
        'limit': limit,
        'offset': offset,
    }


class DeviceFilters(BaseModel):
    model_config = ConfigDict(extra='forbid')

    device_id: str | None = None
    display_label: str | None = None
    maker_namespace: str | None = None
    local_device_id: str | None = None
    device_type: str | None = None
    review_state: str | None = None
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)
    q: str | None = None


class ExperimentFilters(BaseModel):
    model_config = ConfigDict(extra='forbid')

    experiment_id: str | None = None
    needs_review: bool | None = None
    confidence: float | None = None
    measurement_point_label: str | None = None
    sample_id: str | None = None
    measurement_type: str | None = None
    temperature_K: float | None = None
    magnetic_field_T: float | None = None
    excitation_wavelength_nm: float | None = None
    center_wavelength_nm: float | None = None
    excitation_power_uW: float | None = None
    integration_time_s: float | None = None
    averages: int | None = None
    grating_grooves_per_mm: int | None = None
    stage_position: int | None = None
    fixed_top_gate_V: float | None = None
    active_gate_configuration: str | None = None
    bias_start_V: float | None = None
    bias_stop_V: float | None = None
    back_gate_topology: str | None = None
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)
    q: str | None = None


class ArtifactFilters(BaseModel):
    model_config = ConfigDict(extra='forbid')

    artifact_id: str | None = None
    device_id: str | None = None
    experiment_id: str | None = None
    role: str | None = None
    category: str | None = None
    extension: str | None = None
    media_type: str | None = None
    review_state: str | None = None
    storage_source_id: str | None = None
    relative_path: str | None = None
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)
    q: str | None = None
    kind: Literal['document', 'image', 'data', 'other'] | None = None


def create_app(
    catalog_path: Path | None,
    preview_root: Path | None,
) -> FastAPI:
    app = FastAPI(root_path=_root_path())

    @app.get('/')
    async def root() -> dict[str, str]:
        return {'message': 'Hello World'}

    @app.get('/summary')
    def summary() -> dict[str, int]:
        with _read_only_catalog(catalog_path) as store:
            return {
                'devices': store.count_devices(),
                'experiments': store.count_experiments(),
                'artifacts': store.count_artifacts(),
            }

    @app.get('/devices')
    def list_devices(filters: Annotated[DeviceFilters, Query()]) -> dict[str, Any]:
        with _read_only_catalog(catalog_path) as store:
            return _envelope(
                search_devices(
                    store,
                    filters=filters.model_dump(
                        exclude={'limit', 'offset', 'q'}, exclude_none=True
                    ),
                    q=filters.q,
                    limit=filters.limit,
                    offset=filters.offset,
                ),
                filters.limit,
                filters.offset,
            )

    @app.get('/experiments')
    def list_experiments(
        filters: Annotated[ExperimentFilters, Query()],
    ) -> dict[str, Any]:
        with _read_only_catalog(catalog_path) as store:
            return _envelope(
                search_experiments(
                    store,
                    filters=filters.model_dump(
                        exclude={'limit', 'offset', 'q'}, exclude_none=True
                    ),
                    q=filters.q,
                    limit=filters.limit,
                    offset=filters.offset,
                ),
                filters.limit,
                filters.offset,
            )

    @app.get('/artifacts')
    def list_artifacts(filters: Annotated[ArtifactFilters, Query()]) -> dict[str, Any]:
        with _read_only_catalog(catalog_path) as store:
            return _envelope(
                search_artifacts(
                    store,
                    filters=filters.model_dump(
                        exclude={'limit', 'offset', 'q', 'kind'}, exclude_none=True
                    ),
                    q=filters.q,
                    kind=filters.kind,
                    limit=filters.limit,
                    offset=filters.offset,
                ),
                filters.limit,
                filters.offset,
            )

    @app.get('/devices/{device_id}/experiments')
    def device_experiments(
        device_id: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        q: Annotated[str | None, Query()] = None,
    ) -> dict[str, Any]:
        with _read_only_catalog(catalog_path) as store:
            return _envelope(
                find_device_experiments(
                    store, device_id, q=q, limit=limit, offset=offset
                ),
                limit,
                offset,
            )

    @app.get('/devices/{device_id}/documents')
    def device_documents(
        device_id: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        q: Annotated[str | None, Query()] = None,
    ) -> dict[str, Any]:
        with _read_only_catalog(catalog_path) as store:
            return _envelope(
                find_device_documents(
                    store, device_id, q=q, limit=limit, offset=offset
                ),
                limit,
                offset,
            )

    @app.get('/artifacts/{artifact_id}/preview')
    def artifact_preview(artifact_id: str) -> dict[str, Any] | None:
        if preview_root is None:
            raise HTTPException(
                status_code=503, detail='preview cache is not configured'
            )
        with _read_only_catalog(catalog_path) as store:
            try:
                return get_artifact_preview(
                    store, artifact_id, preview_root=preview_root
                )
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get('/artifacts/{artifact_id}/preview/assets/{asset_path:path}')
    def artifact_preview_asset(artifact_id: str, asset_path: str) -> Response:
        if preview_root is None:
            raise HTTPException(
                status_code=503, detail='preview cache is not configured'
            )
        with _read_only_catalog(catalog_path) as store:
            result = read_artifact_preview_asset(
                store, artifact_id, asset_path, preview_root=preview_root
            )
        if result is None:
            raise HTTPException(status_code=404, detail='preview asset not found')
        data, media_type = result
        return Response(content=data, media_type=media_type)

    return app


app = create_app(_env_catalog_path(), _env_preview_root())
