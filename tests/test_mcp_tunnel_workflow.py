"""Focused tests for the ChatGPT Secure MCP Tunnel workflow.

Covers the Windows tunnel workflow script (syntax, dry run, validation,
secret masking) and re-verifies that the local MCP adapter surface stays
exactly the 11 read-only tools with metadata-only previews. No network calls.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_mcp_adapter import (
    EXPECTED_TOOL_COUNT,
    EXPECTED_TOOLS,
    _assert_no_absolute_paths,
    _corpus,
    _mcp_session,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / 'scripts'
TUNNEL_SCRIPT = SCRIPTS / 'start_lab_data_mcp_tunnel.ps1'
TUNNEL_DOC = REPO_ROOT / 'docs' / 'chatgpt_mcp_tunnel.md'

requires_windows = pytest.mark.skipif(
    sys.platform != 'win32', reason='PowerShell workflow script is Windows-only'
)

_WRITE_TOKENS = (
    'create',
    'update',
    'delete',
    'write',
    'upload',
    'save',
    'insert',
)


def _run_script(
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
            str(TUNNEL_SCRIPT),
            *args,
        ],
        cwd=REPO_ROOT,
        env=process_env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _write_valid_config(tmp_path: Path) -> tuple[Path, Path]:
    catalog = tmp_path / 'catalog.sqlite'
    catalog.write_bytes(b'not-a-real-catalog')
    preview_root = tmp_path / 'previews'
    preview_root.mkdir()
    return catalog, preview_root


@requires_windows
def test_tunnel_script_parses_without_errors():
    result = subprocess.run(
        [
            'powershell',
            '-NoProfile',
            '-Command',
            f"[scriptblock]::Create((Get-Content -Raw -LiteralPath '{TUNNEL_SCRIPT}'))",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@requires_windows
def test_dry_run_prints_commands_and_exits_zero(tmp_path):
    catalog, preview_root = _write_valid_config(tmp_path)
    result = _run_script(
        '-DryRun',
        env={
            'LAB_DATA_CATALOG_PATH': str(catalog),
            'LAB_DATA_PREVIEW_ROOT': str(preview_root),
        },
    )
    assert result.returncode == 0, result.stderr
    assert '-m lab_data.mcp_adapter' in result.stdout
    assert 'init --sample sample_mcp_stdio_local' in result.stdout
    assert 'run --profile lab-data-stdio' in result.stdout
    assert '/ui' in result.stdout
    assert '11 read-only tools' in result.stdout
    assert 'dry run: configuration is valid' in result.stdout


@requires_windows
def test_dry_run_missing_catalog_fails_clearly(tmp_path):
    preview_root = tmp_path / 'previews'
    preview_root.mkdir()
    missing = tmp_path / 'missing-catalog.sqlite'
    result = _run_script(
        '-DryRun',
        env={
            'LAB_DATA_CATALOG_PATH': str(missing),
            'LAB_DATA_PREVIEW_ROOT': str(preview_root),
        },
    )
    assert result.returncode == 1
    assert 'catalog file not found' in result.stderr


@requires_windows
def test_run_mode_requires_tunnel_id_and_api_key(tmp_path):
    catalog, preview_root = _write_valid_config(tmp_path)
    result = _run_script(
        env={
            'LAB_DATA_CATALOG_PATH': str(catalog),
            'LAB_DATA_PREVIEW_ROOT': str(preview_root),
        },
    )
    assert result.returncode == 1
    assert 'no tunnel id' in result.stderr
    assert 'LAB_DATA_MCP_TUNNEL_ID' in result.stderr


@requires_windows
def test_run_mode_requires_api_key_when_tunnel_id_present(tmp_path):
    catalog, preview_root = _write_valid_config(tmp_path)
    result = _run_script(
        env={
            'LAB_DATA_CATALOG_PATH': str(catalog),
            'LAB_DATA_PREVIEW_ROOT': str(preview_root),
            'LAB_DATA_MCP_TUNNEL_ID': 'tunnel_test_id',
        },
    )
    assert result.returncode == 1
    assert 'no runtime API key' in result.stderr
    assert 'LAB_DATA_MCP_RUNTIME_API_KEY' in result.stderr


@requires_windows
def test_dry_run_never_prints_argument_supplied_api_key(tmp_path):
    catalog, preview_root = _write_valid_config(tmp_path)
    secret = 'secret-test-arg-value-1234'
    result = _run_script(
        '-DryRun',
        '-TunnelId',
        'tunnel_test_id',
        '-RuntimeApiKey',
        secret,
        env={
            'LAB_DATA_CATALOG_PATH': str(catalog),
            'LAB_DATA_PREVIEW_ROOT': str(preview_root),
        },
    )
    assert result.returncode == 0, result.stderr
    assert secret not in result.stdout
    assert secret not in result.stderr


@requires_windows
def test_dry_run_never_prints_env_supplied_api_key(tmp_path):
    catalog, preview_root = _write_valid_config(tmp_path)
    secret = 'secret-test-env-value-5678'
    result = _run_script(
        '-DryRun',
        '-TunnelId',
        'tunnel_test_id',
        env={
            'LAB_DATA_CATALOG_PATH': str(catalog),
            'LAB_DATA_PREVIEW_ROOT': str(preview_root),
            'LAB_DATA_MCP_RUNTIME_API_KEY': secret,
        },
    )
    assert result.returncode == 0, result.stderr
    assert secret not in result.stdout
    assert secret not in result.stderr


def test_tunnel_doc_covers_requirements_without_secrets():
    text = TUNNEL_DOC.read_text(encoding='utf-8')
    for required in (
        'Secure MCP Tunnel',
        'tunnel-client',
        'api.openai.com:443',
        'tunnel_id',
        'runtime API key',
        'Tunnels Read',
        'developer-mode',
        'stdio',
        '11 read-only tools',
        'lab-data-scientific-tools',
    ):
        assert required in text, f'missing {required!r} in tunnel doc'
    assert 'sk-' not in text


@pytest.mark.asyncio
async def test_adapter_still_exposes_exactly_eleven_readonly_tools(tmp_path):
    async with _mcp_session(*_corpus(tmp_path)) as client:
        tools = (await client.list_tools()).tools
        names = {tool.name for tool in tools}
        assert names == EXPECTED_TOOLS
        assert len(tools) == EXPECTED_TOOL_COUNT
        for tool in tools:
            assert not any(token in tool.name for token in _WRITE_TOKENS)


@pytest.mark.asyncio
async def test_preview_remains_metadata_only_without_absolute_paths(tmp_path):
    async with _mcp_session(*_corpus(tmp_path)) as client:
        result = await client.call_tool(
            'get_artifact_preview', {'artifact_id': 'art-preview'}
        )
        assert not result.isError
        payload = json.loads(result.content[0].text)
        assert payload['artifact_id'] == 'art-preview'
        assert payload['status'] == 'ready'
        assert all(not Path(asset['path']).is_absolute() for asset in payload['assets'])
        assert 'object_dir' not in payload and 'manifest_path' not in payload
        _assert_no_absolute_paths(payload)
