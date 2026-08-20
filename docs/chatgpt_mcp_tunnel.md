# ChatGPT Access via the OpenAI Secure MCP Tunnel

The local MCP adapter is a **stdio-only server**: it never binds a TCP port,
so ChatGPT cannot connect to it directly over the network. To use the same
11 read-only scientific tools from ChatGPT, this page documents the
**OpenAI Secure MCP Tunnel** path: a small `tunnel-client` binary runs inside
this network, opens an **outbound** HTTPS connection to OpenAI, and forwards
JSON-RPC messages between ChatGPT and the local stdio adapter. No inbound
firewall port is opened and the adapter is never exposed to CMU-Secure or the
public Internet.

> Local stdio cannot connect to ChatGPT directly (expected: no). The Secure
> MCP Tunnel is required for remote ChatGPT use; the stdio adapter stays
> local-only.

## Architecture

```text
ChatGPT (developer mode)
  -> OpenAI-hosted MCP tunnel endpoint (api.openai.com:443, outbound only)
  -> tunnel-client (inside this network; long-polls for queued work)
  -> local stdio MCP adapter (python -m lab_data.mcp_adapter)
  -> ScientificToolLayer
  -> CatalogStore (SQLite, read-only)
```

OpenAI products send MCP requests to the OpenAI-hosted tunnel endpoint.
`tunnel-client` long-polls that endpoint, forwards each JSON-RPC request to
the private MCP server over stdio, and posts the response back through the
tunnel. The private MCP server never needs a public listener.

## Requirements (Personal ChatGPT Account)

Verified against the official
[Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels):

- **Platform tunnel settings access** for a personal Platform organization
  (use the personal Platform organization that belongs to your account).
- A **`tunnel_id`** created in Platform tunnel settings.
- A **runtime API key** for `tunnel-client` (create it under Platform runtime
  API keys). A control-plane API key / mTLS client certificate is optional
  when control-plane mTLS is configured.
- **Tunnel permissions**: Tunnels Read + Manage to create or edit a tunnel;
  Tunnels Read + Use to run `tunnel-client` or select the tunnel while
  creating an app.
- **ChatGPT developer-mode access**: a separate workspace permission. Ask the
  ChatGPT workspace admin for developer-mode access, then enable it in
  Settings -> Security and login.
- The tunnel is **associated with the target ChatGPT workspace** so it is
  listed when creating an app there.
- The host running `tunnel-client` can make **outbound HTTPS requests to
  `api.openai.com:443`** (or `mtls.api.openai.com:443` when control-plane
  mTLS is configured) and can reach the private MCP server over stdio.

Public plugin submission is not supported by the tunnel; Secure MCP Tunnel is
for private connections, including developer-mode testing.

## Install tunnel-client

Download the official `tunnel-client` release binary from
[`openai/tunnel-client`](https://github.com/openai/tunnel-client): use the
download link shown in Platform tunnel settings, or the latest public release
under GitHub releases. Do not hard-code a specific release URL; keep the
runbook pointed at the latest release. As of this writing the official docs
list only binary distribution (plus Homebrew for macOS); there is no
documented `pip` or `npx` install path, so this repo documents the binary
download only.

Verify the binary once installed:

```powershell
tunnel-client --version
tunnel-client help quickstart
```

## Startup Workflow

1. Set the catalog environment and verify the stdio adapter starts:

   ```powershell
   $env:LAB_DATA_CATALOG_PATH = "C:\NOMAD_Test_Output\scientific_catalog_readiness\yz247_yzdev_catalog.sqlite"
   $env:LAB_DATA_PREVIEW_ROOT = "C:\NOMAD_Test_Output\scientific_catalog_readiness\artifact_previews"
   python -m lab_data.mcp_adapter
   ```

   It prints a local-only banner and stays running over stdio. It binds no
   TCP port. Kill it after the check; the tunnel profile spawns its own
   adapter instance below.

2. Configure `tunnel-client` once per machine with a profile that points at
   the stdio command (profile name used here: `lab-data-stdio`):

   ```powershell
   $env:CONTROL_PLANE_API_KEY = "<runtime API key>"
   tunnel-client init --sample sample_mcp_stdio_local --profile lab-data-stdio `
     --tunnel-id "<tunnel_id>" `
     --mcp-command "<repo>\.venv\Scripts\python.exe -m lab_data.mcp_adapter"
   tunnel-client doctor --profile lab-data-stdio --explain
   ```

   The runtime API key belongs in the environment, never on the command line.
   Keep `tunnel-client run ...` healthy while you create or test the app.

3. Run `tunnel-client` and keep it running:

   ```powershell
   $env:CONTROL_PLANE_API_KEY = "<runtime API key>"
   tunnel-client run --profile lab-data-stdio
   ```

   `tunnel-client` prints a loopback-only admin UI at
   `http://127.0.0.1:<port>/ui` (plus `/healthz`, `/readyz`, `/metrics`)
   showing whether the client is healthy, ready, and connected.

4. Create or select the app in ChatGPT Developer Mode using the tunnel (see
   below), then test the tools.

### One-command launcher

`scripts/start_lab_data_mcp_tunnel.ps1` automates the same workflow. It
validates `LAB_DATA_CATALOG_PATH` and `LAB_DATA_PREVIEW_ROOT`, prints the
exact commands, launches the stdio adapter in its own window (unless
`-SkipMcp`), and runs `tunnel-client` in the foreground with the runtime key
passed only through the `CONTROL_PLANE_API_KEY` environment variable.

```powershell
$env:LAB_DATA_CATALOG_PATH = "C:\NOMAD_Test_Output\scientific_catalog_readiness\yz247_yzdev_catalog.sqlite"
$env:LAB_DATA_PREVIEW_ROOT = "C:\NOMAD_Test_Output\scientific_catalog_readiness\artifact_previews"
$env:LAB_DATA_MCP_TUNNEL_ID = "<tunnel_id>"
$env:LAB_DATA_MCP_RUNTIME_API_KEY = "<runtime API key>"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_lab_data_mcp_tunnel.ps1
```

`-DryRun` validates and prints the planned commands without launching
anything. `-TunnelClient` points at a tunnel-client binary that is not on
PATH. The key and tunnel id can also be passed as `-RuntimeApiKey` /
`-TunnelId`; the key is never printed or written to disk.

## ChatGPT Developer Mode Setup Packet

- **App / server name suggestion**: `lab-data-scientific-tools` (the name the
  adapter registers with MCP).
- **MCP endpoint**: the OpenAI-hosted tunnel endpoint **generated by
  Platform** after tunnel creation (for example a
  `https://.../mcp` URL or the tunnel-based endpoint shown in the Platform /
  App UI). Use the endpoint the Platform shows; do not hard-code one here.
- **Authentication mode**: the runtime API key is used by `tunnel-client`
  (via `CONTROL_PLANE_API_KEY`); the ChatGPT-side app authenticates through
  the OpenAI tunnel, so no additional credentials are configured in the app.
- **Selection in ChatGPT**: Developer Mode -> Apps -> create app / add MCP
  server -> select the tunnel associated with your workspace.
- **Expected tool scan**: exactly the 11 read-only tools
  (`search_devices`, `search_experiments`, `search_artifacts`, `get_device`,
  `get_experiment`, `get_artifact`, `find_device_experiments`,
  `find_device_documents`, `get_provenance`, `get_lineage`,
  `get_artifact_preview`). There are **no write tools**; do not add any.

## Security Boundary

- The MCP adapter is **stdio only**: no inbound listener, no `0.0.0.0`, no
  CMU-Secure exposure.
- `tunnel-client` initiates the only network connection, outbound HTTPS to
  OpenAI; the tunnel is the sole remote access path.
- The exposed surface is the same read-only tool layer: no SQL, no arbitrary
  filesystem paths, no absolute paths in responses, no preview bypass, and no
  caller-supplied paths.
- No credentials are committed to git. Runtime keys are held in environment
  variables at runtime and never printed, logged, or stored by the launcher
  script.

## Tests

`tests/test_mcp_tunnel_workflow.py` covers the launcher script (syntax, dry
run, missing-catalog failure, missing tunnel id / runtime key failure in run
mode, secret masking) and re-verifies the adapter exposes exactly 11 read-only
tools with metadata-only previews. No network calls are made.
