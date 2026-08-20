# MCP Adapter (Local-Only)

`lab_data.mcp_adapter` exposes the read-only scientific tools over the Model
Context Protocol (MCP) using the official Python SDK, transported over stdio.

> The MCP adapter is local-only and unauthenticated in this phase. Do not
> expose it directly to CMU-Secure or the Internet.

For how to point a real MCP-capable client (Claude Desktop, ChatGPT, or any
stdio MCP client) at this server, see
[MCP Client Setup](mcp_client_setup.md).

## Architecture

```text
MCP client (stdio) -> lab_data.mcp_adapter -> ScientificToolLayer -> CatalogStore (SQLite, read-only)
```

The adapter wraps `ScientificToolLayer` only. It adds no direct catalog
access, no SQL, no arbitrary filesystem paths, no filename parsing, no
identity or relationship inference, and no preview bypass. Every MCP tool maps
one to one onto a layer method and returns that method's JSON-safe payload
verbatim. `preview_root` is configuration supplied at startup, never a
per-call caller-supplied path.

## Local Setup

The MCP SDK is an optional dependency. Install it with:

```powershell
pip install -e ".[mcp]"
```

The `mcp` extra pins `mcp>=1.29.0,<2.0.0` (the maintained 1.x line whose
`FastMCP` stdio API is used here; 2.0.0 restructured the server API).

## Local Start

Set the same environment variables as the browser deployment and run the
module entry point. It validates configuration, prints a local-only banner to
stderr, and runs a stdio server; it never binds a TCP port.

```powershell
$env:LAB_DATA_CATALOG_PATH = "C:\NOMAD_Test_Output\scientific_catalog_readiness\yz247_yzdev_catalog.sqlite"
$env:LAB_DATA_PREVIEW_ROOT = "C:\NOMAD_Test_Output\scientific_catalog_readiness\artifact_previews"
python -m lab_data.mcp_adapter
```

Startup fails with a clear message and a non-zero exit when either variable is
missing or does not point at a readable catalog file or preview directory.

### Launch contract

The server is launched as a Python module over stdio and never binds a TCP
port. The launch contract is:

```text
command:  <repo>\.venv\Scripts\python.exe
args:     -m lab_data.mcp_adapter
env:      LAB_DATA_CATALOG_PATH=<catalog .sqlite>
          LAB_DATA_PREVIEW_ROOT=<preview cache directory>
cwd:      <repo>
```

On the current host, `<repo>` is `C:\CodexRepos\lab-data` and the interpreter
is `C:\CodexRepos\lab-data\.venv\Scripts\python.exe`. These host-specific
values belong only in a client's server configuration; the source code reads
everything from environment variables and contains no machine-specific paths.
Only `LAB_DATA_CATALOG_PATH` and `LAB_DATA_PREVIEW_ROOT` are required.
`LAB_DATA_HOST`, `LAB_DATA_PORT`, and `FRONTEND_DIST` are browser-deployment
settings and are not read by the MCP adapter.

## Local Test and Smoke

```powershell
pytest tests\test_mcp_adapter.py
pytest tests\test_mcp_adapter.py::test_real_corpus_mcp_smoke -s
```

The fixture tests confirm: the exposed tool set is exactly the read-only
list; search limits stay within `1..200`; empty IDs and unknown filters are
rejected; preview responses are metadata-only with relative asset paths;
missing artifacts return `None` instead of touching the filesystem; and no
response contains an absolute path. The real-corpus smoke (skipped when the
YZ247/YZDEV catalog is absent) exercises every tool against the verified
corpus and prints one JSON summary per call.

## Tools

| Tool | Arguments | Notes |
|---|---|---|
| `search_devices` | `q?`, `limit=20`, `offset=0`, `filters?` | Bounded, stably ordered |
| `search_experiments` | `q?`, `limit=20`, `offset=0`, `filters?` | Canonically ordered |
| `search_artifacts` | `q?`, `limit=20`, `offset=0`, `kind?`, `filters?` | Kind-filtered |
| `get_device` | `device_id` | Exact, or `None` |
| `get_experiment` | `experiment_id` | Exact, with review state |
| `get_artifact` | `artifact_id` | Exact, with `derived_from` |
| `find_device_experiments` | `device_id`, `limit=50`, `offset=0`, `q?` | Explicit measured-on |
| `find_device_documents` | `device_id`, `limit=50`, `offset=0`, `q?` | PDF/PPT/PPTX only |
| `get_provenance` | `subject_type`, `subject_id` | Persisted claims only |
| `get_lineage` | `entity_type`, `entity_id` | Persisted edges only |
| `get_artifact_preview` | `artifact_id` | Validated report only |

Search `limit` is constrained to `1..200` and `offset` to `>= 0` at the
schema boundary; the layer revalidates. `filters` pass through unchanged and
are allowlisted by `ScientificToolLayer` (experiment filters include
`measurement_type`, `temperature_K`, `magnetic_field_T`,
`measurement_point_label`, `excitation_wavelength_nm`, plus the metadata keys
the layer supports). Unknown filters and kinds are rejected with the layer's
messages. There is no natural-language interpretation: tools only pass
structured arguments.

## Preview Support

`get_artifact_preview` returns the validated preview report (metadata only):
the manifest plus asset entries with storage-relative paths and media types.
Binary image transport over MCP is not implemented in this phase. A later
phase may add MCP resources that serve validated asset bytes under the same
preview root; asset bytes are already available through
`lab_data.artifact_previews.read_artifact_preview_asset` behind the same
validation.

## Future Access Path

Authenticated remote access is not implemented. If MCP access is ever exposed
beyond the local machine, it must sit behind the same access-control boundary
as the browser UI (campus or VPN reachability), with authentication enforced
in front of the server. Until then, keep this stdio server local-only.

For connecting the stdio adapter to ChatGPT without opening any inbound
listener, see
[ChatGPT Access via the OpenAI Secure MCP Tunnel](chatgpt_mcp_tunnel.md).
