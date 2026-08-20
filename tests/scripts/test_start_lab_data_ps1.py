"""Focused tests for the Windows startup script (PowerShell 5.1)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / 'scripts'
START_SCRIPT = SCRIPTS / 'start_lab_data.ps1'
SHOW_SCRIPT = SCRIPTS / 'show_lab_data_url.ps1'

requires_windows = pytest.mark.skipif(
    sys.platform != 'win32', reason='PowerShell startup script is Windows-only'
)


def _run_script(
    script: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    process_env.update(env or {})
    return subprocess.run(
        [
            'powershell',
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-File',
            str(script),
            *args,
        ],
        cwd=REPO_ROOT,
        env=process_env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _write_valid_config(tmp_path: Path) -> tuple[Path, Path, Path]:
    catalog = tmp_path / 'catalog.sqlite'
    catalog.write_bytes(b'not-a-real-catalog')
    preview_root = tmp_path / 'previews'
    preview_root.mkdir()
    frontend = tmp_path / 'frontend-dist'
    frontend.mkdir()
    (frontend / 'index.html').write_text('<html></html>', encoding='utf-8')
    return catalog, preview_root, frontend


@requires_windows
def test_scripts_parse_without_errors():
    for script in (START_SCRIPT, SHOW_SCRIPT):
        result = subprocess.run(
            [
                'powershell',
                '-NoProfile',
                '-Command',
                '[scriptblock]::Create((Get-Content -Raw -LiteralPath '
                f"'{script}'))",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stderr


@requires_windows
def test_dry_run_valid_config_prints_urls_and_exits_zero(tmp_path):
    catalog, preview_root, frontend = _write_valid_config(tmp_path)
    port = _free_port()
    result = _run_script(
        START_SCRIPT,
        '-DryRun',
        '-Port',
        str(port),
        '-Catalog',
        str(catalog),
        '-PreviewRoot',
        str(preview_root),
        '-FrontendDir',
        str(frontend),
    )
    assert result.returncode == 0, result.stderr
    assert f'http://127.0.0.1:{port}/' in result.stdout
    assert 'not starting the server' in result.stdout


@requires_windows
def test_dry_run_env_fallback_exits_zero(tmp_path):
    catalog, preview_root, frontend = _write_valid_config(tmp_path)
    port = _free_port()
    result = _run_script(
        START_SCRIPT,
        '-DryRun',
        env={
            'LAB_DATA_CATALOG_PATH': str(catalog),
            'LAB_DATA_PREVIEW_ROOT': str(preview_root),
            'FRONTEND_DIST': str(frontend),
            'LAB_DATA_PORT': str(port),
        },
    )
    assert result.returncode == 0, result.stderr
    assert f'http://127.0.0.1:{port}/' in result.stdout


@requires_windows
def test_dry_run_missing_catalog_fails_clearly(tmp_path):
    _, preview_root, frontend = _write_valid_config(tmp_path)
    missing = tmp_path / 'missing-catalog.sqlite'
    result = _run_script(
        START_SCRIPT,
        '-DryRun',
        '-Catalog',
        str(missing),
        '-PreviewRoot',
        str(preview_root),
        '-FrontendDir',
        str(frontend),
    )
    assert result.returncode == 1
    assert 'catalog file not found' in result.stderr


@requires_windows
def test_dry_run_occupied_port_fails_clearly(tmp_path):
    catalog, preview_root, frontend = _write_valid_config(tmp_path)
    with socket.socket() as held:
        held.bind(('127.0.0.1', 0))
        held.listen()
        port = held.getsockname()[1]
        result = _run_script(
            START_SCRIPT,
            '-DryRun',
            '-Port',
            str(port),
            '-Catalog',
            str(catalog),
            '-PreviewRoot',
            str(preview_root),
            '-FrontendDir',
            str(frontend),
        )
    assert result.returncode == 1
    assert 'already in use' in result.stderr


@requires_windows
def test_show_address_script_exits_zero():
    result = _run_script(SHOW_SCRIPT)
    assert result.returncode == 0, result.stderr
    assert 'http://127.0.0.1:8765/' in result.stdout
