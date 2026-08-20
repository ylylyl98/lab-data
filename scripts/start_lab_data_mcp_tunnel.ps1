<#
.SYNOPSIS
Starts the lab-data local stdio MCP adapter and runs the OpenAI Secure MCP
Tunnel client so ChatGPT can reach the read-only scientific tools.

.DESCRIPTION
Validates LAB_DATA_CATALOG_PATH and LAB_DATA_PREVIEW_ROOT, prints the exact
launch commands (local stdio MCP adapter, tunnel-client init sample, and
tunnel-client run), optionally launches the adapter in its own window, then
runs tunnel-client in the foreground with the runtime API key passed through
the CONTROL_PLANE_API_KEY environment variable.

This script never binds a TCP port, never modifies firewall or network
policy, never exposes the adapter to CMU-Secure or the Internet, and never
writes the runtime API key to disk or prints it.

.PARAMETER TunnelId
OpenAI Platform tunnel id (tunnel_...). Falls back to
LAB_DATA_MCP_TUNNEL_ID when omitted. Required when running; dry run prints a
placeholder.

.PARAMETER RuntimeApiKey
OpenAI runtime API key used by tunnel-client. Falls back to
LAB_DATA_MCP_RUNTIME_API_KEY when omitted. Passed to tunnel-client only
through the CONTROL_PLANE_API_KEY environment variable; never printed or
stored. Required when running; dry run prints a placeholder.

.PARAMETER TunnelClient
Path to the tunnel-client binary. Defaults to 'tunnel-client' on PATH.

.PARAMETER DryRun
Validate configuration and print the planned commands without launching
anything.

.PARAMETER SkipMcp
Do not launch the MCP adapter window; assume it is already running in a
separate window.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_lab_data_mcp_tunnel.ps1 -DryRun

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_lab_data_mcp_tunnel.ps1 -TunnelId tunnel_<your_tunnel_id>
#>

[CmdletBinding()]
param(
    [string] $TunnelId,
    [string] $RuntimeApiKey,
    [string] $TunnelClient,
    [switch] $DryRun,
    [switch] $SkipMcp
)

$ErrorActionPreference = 'Stop'

function Fail([string] $Message) {
    [Console]::Error.WriteLine("error: $Message")
    exit 1
}

if (-not $PSScriptRoot) {
    Fail 'this script must be run from a file (use powershell -File scripts/start_lab_data_mcp_tunnel.ps1)'
}

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$ProfileName = 'lab-data-stdio'
$McpCommand = "`"$python`" -m lab_data.mcp_adapter"

if (-not $TunnelId) { $TunnelId = $env:LAB_DATA_MCP_TUNNEL_ID }
if (-not $RuntimeApiKey) { $RuntimeApiKey = $env:LAB_DATA_MCP_RUNTIME_API_KEY }
if (-not $TunnelClient) { $TunnelClient = 'tunnel-client' }

$Catalog = $env:LAB_DATA_CATALOG_PATH
$PreviewRoot = $env:LAB_DATA_PREVIEW_ROOT
if (-not $Catalog) {
    Fail 'LAB_DATA_CATALOG_PATH is not set (read-only catalog .sqlite file)'
}
if (-not $PreviewRoot) {
    Fail 'LAB_DATA_PREVIEW_ROOT is not set (preview cache directory)'
}
if (-not (Test-Path -LiteralPath $Catalog -PathType Leaf)) {
    Fail "catalog file not found: $Catalog"
}
if (-not (Test-Path -LiteralPath $PreviewRoot -PathType Container)) {
    Fail "preview root directory not found: $PreviewRoot"
}
if (-not (Test-Path -LiteralPath $python)) {
    Fail "repository virtual environment python not found: $python"
}

if (-not $DryRun) {
    if (-not $TunnelId) {
        Fail 'no tunnel id: pass -TunnelId or set LAB_DATA_MCP_TUNNEL_ID (create the tunnel in Platform tunnel settings first)'
    }
    if (-not $RuntimeApiKey) {
        Fail 'no runtime API key: pass -RuntimeApiKey or set LAB_DATA_MCP_RUNTIME_API_KEY (create it in Platform runtime API keys)'
    }
}

if ($TunnelId) { $TunnelLabel = $TunnelId } else { $TunnelLabel = '<not set: pass -TunnelId or set LAB_DATA_MCP_TUNNEL_ID>' }
if ($RuntimeApiKey) { $KeyLabel = '<provided via environment only; not printed>' } else { $KeyLabel = '<not set: pass -RuntimeApiKey or set LAB_DATA_MCP_RUNTIME_API_KEY>' }

Write-Host 'lab-data Secure MCP Tunnel workflow (local stdio MCP adapter -> OpenAI Secure MCP Tunnel -> ChatGPT):'
Write-Host ("  repo root:     {0}" -f $RepoRoot)
Write-Host ("  catalog:       {0}" -f $Catalog)
Write-Host ("  preview root:  {0}" -f $PreviewRoot)
Write-Host ("  mcp adapter:   {0} -m lab_data.mcp_adapter (stdio; no TCP listener)" -f $python)
Write-Host ("  tunnel id:     {0}" -f $TunnelLabel)
Write-Host ("  runtime key:   {0}" -f $KeyLabel)
Write-Host ("  tunnel-client: {0}" -f $TunnelClient)
Write-Host ''
Write-Host 'Planned commands:'
Write-Host ''
Write-Host '1) Local MCP adapter (stdio only; tunnel-client spawns its own instance from the profile):'
if ($SkipMcp) {
    Write-Host '   skipped (-SkipMcp): keep your existing adapter window running. Manual launch for reference:'
    Write-Host ('   $env:LAB_DATA_CATALOG_PATH = ''{0}''' -f $Catalog)
    Write-Host ('   $env:LAB_DATA_PREVIEW_ROOT = ''{0}''' -f $PreviewRoot)
    Write-Host ('   & ''{0}'' -m lab_data.mcp_adapter' -f $python)
}
else {
    Write-Host ("   Start-Process -FilePath '{0}' -ArgumentList '-m','lab_data.mcp_adapter' -WorkingDirectory '{1}'" -f $python, $RepoRoot)
    Write-Host '   (opens a verification window with the adapter banner; or run it manually and use -SkipMcp)'
}
Write-Host ''
Write-Host '2) tunnel-client init (once per machine; skip if the profile already exists):'
Write-Host '   $env:CONTROL_PLANE_API_KEY = ''<runtime API key>''   # set in your shell; never on the command line'
Write-Host ("   & '{0}' init --sample sample_mcp_stdio_local --profile {1} --tunnel-id {2} --mcp-command {3}" -f $TunnelClient, $ProfileName, $TunnelLabel, $McpCommand)
Write-Host ("   & '{0}' doctor --profile {1} --explain" -f $TunnelClient, $ProfileName)
Write-Host ''
Write-Host '3) tunnel-client run (launched below; keep it running):'
Write-Host ("   & '{0}' run --profile {1}   # CONTROL_PLANE_API_KEY comes from -RuntimeApiKey or LAB_DATA_MCP_RUNTIME_API_KEY" -f $TunnelClient, $ProfileName)
Write-Host ''
Write-Host '4) Verify in ChatGPT:'
Write-Host '   - tunnel-client prints a loopback-only admin UI (http://127.0.0.1:<port>/ui) showing healthy/ready/connected.'
Write-Host '   - In ChatGPT Developer Mode, create/select the app with the tunnel and expect exactly 11 read-only tools (no write tools).'

if ($DryRun) {
    Write-Host ''
    Write-Host 'dry run: configuration is valid, nothing was launched'
    exit 0
}

$env:LAB_DATA_CATALOG_PATH = $Catalog
$env:LAB_DATA_PREVIEW_ROOT = $PreviewRoot

if (-not $SkipMcp) {
    Write-Host ''
    Write-Host 'Starting the local MCP adapter in its own window...'
    Start-Process -FilePath $python -ArgumentList @('-m', 'lab_data.mcp_adapter') -WorkingDirectory $RepoRoot | Out-Null
    Start-Sleep -Seconds 2
}

$env:CONTROL_PLANE_API_KEY = $RuntimeApiKey
& $TunnelClient run --profile $ProfileName
exit $LASTEXITCODE
