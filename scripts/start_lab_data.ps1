<#
.SYNOPSIS
Starts the single-origin lab-data server for campus (CMU-Secure) use.

.DESCRIPTION
Resolves configuration from parameters or LAB_DATA_* environment variables,
validates the catalog, preview root, and frontend build, refuses to start when
the port is already in use, prints the browser URLs, then launches
scripts/serve_lab_data.py with the repository virtual environment.

The default host is 0.0.0.0 so lab members on the campus network can reach the
server. The existing inbound firewall rule for TCP 8765 (display name
"lab-data server inbound TCP 8765 (CMU-Secure Public)") scopes campus access;
this script never modifies firewall or network policy.

.PARAMETER Host
Bind address. Default 0.0.0.0; use 127.0.0.1 for local-only serving.
Falls back to LAB_DATA_HOST when omitted.

.PARAMETER Port
Listen port. Default 8765. Falls back to LAB_DATA_PORT when omitted.

.PARAMETER Catalog
Read-only SQLite catalog file. Falls back to LAB_DATA_CATALOG_PATH.

.PARAMETER PreviewRoot
Preview cache directory. Falls back to LAB_DATA_PREVIEW_ROOT.

.PARAMETER FrontendDir
Built frontend directory. Defaults to <repo>/frontend/dist, or
FRONTEND_DIST when set.

.PARAMETER DryRun
Validate configuration, check the port, and print URLs without starting the
server. Alias: -NoLaunch.

.PARAMETER ShowAddress
Print the current host's candidate URLs and exit. No catalog validation.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_lab_data.ps1

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_lab_data.ps1 -DryRun

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_lab_data.ps1 -Host 127.0.0.1 -Port 8000
#>

[CmdletBinding()]
param(
    [Alias('Host')]
    [string] $ListenHost = '0.0.0.0',
    [int] $Port = 8765,
    [string] $Catalog,
    [string] $PreviewRoot,
    [string] $FrontendDir,
    [Alias('NoLaunch')]
    [switch] $DryRun,
    [switch] $ShowAddress
)

$ErrorActionPreference = 'Stop'

function Fail([string] $Message) {
    [Console]::Error.WriteLine("error: $Message")
    exit 1
}

function Get-LabDataUrls {
    param(
        [string] $HostAddress,
        [int] $ListenPort
    )
    $urls = New-Object System.Collections.Generic.List[object]
    if ($HostAddress -eq '0.0.0.0' -or $HostAddress -eq '::' -or $HostAddress -eq '*') {
        $defaultRouteIfIndex = @(
            Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty ifIndex
        )
        $addresses = @(
            Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.AddressState -eq 'Preferred' -and
                    $_.IPAddress -ne '127.0.0.1' -and
                    $_.IPAddress -notlike '169.254.*'
                }
        )
        $ordered = @(
            @($addresses | Where-Object { $defaultRouteIfIndex -contains $_.InterfaceIndex }) +
            @($addresses | Where-Object { $defaultRouteIfIndex -notcontains $_.InterfaceIndex })
        )
        foreach ($address in $ordered) {
            $urls.Add([PSCustomObject]@{
                Url = "http://$($address.IPAddress):$ListenPort/"
                Interface = $address.InterfaceAlias
            })
        }
    }
    else {
        $urls.Add([PSCustomObject]@{
            Url = "http://${HostAddress}:${ListenPort}/"
            Interface = 'bound host'
        })
    }
    return $urls
}

function Write-LabDataUrls([string] $HostAddress, [int] $ListenPort) {
    $candidateUrls = Get-LabDataUrls -HostAddress $HostAddress -ListenPort $ListenPort
    foreach ($candidate in $candidateUrls) {
        Write-Host ("  {0,-40} ({1})" -f $candidate.Url, $candidate.Interface)
    }
    Write-Host ("  {0,-40} (localhost)" -f "http://127.0.0.1:$ListenPort/")
}

if (-not $PSScriptRoot) {
    Fail 'this script must be run from a file (use powershell -File scripts/start_lab_data.ps1)'
}

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path

if (-not $PSBoundParameters.ContainsKey('ListenHost') -and -not $PSBoundParameters.ContainsKey('Host')) {
    if ($env:LAB_DATA_HOST) { $ListenHost = $env:LAB_DATA_HOST }
}
if (-not $PSBoundParameters.ContainsKey('Port')) {
    if ($env:LAB_DATA_PORT) {
        try {
            $Port = [int]$env:LAB_DATA_PORT
        }
        catch {
            Fail "LAB_DATA_PORT must be an integer, got '$env:LAB_DATA_PORT'"
        }
    }
}
if ($Port -lt 1 -or $Port -gt 65535) {
    Fail "port must be between 1 and 65535, got $Port"
}

if ($ShowAddress) {
    Write-Host 'lab-data candidate URLs:'
    Write-LabDataUrls -HostAddress $ListenHost -ListenPort $Port
    exit 0
}

if (-not $Catalog) { $Catalog = $env:LAB_DATA_CATALOG_PATH }
if (-not $PreviewRoot) { $PreviewRoot = $env:LAB_DATA_PREVIEW_ROOT }
if (-not $FrontendDir) { $FrontendDir = $env:FRONTEND_DIST }
if (-not $FrontendDir) { $FrontendDir = Join-Path $RepoRoot 'frontend\dist' }

if (-not $Catalog) {
    Fail 'LAB_DATA_CATALOG_PATH is not set and -Catalog was not provided'
}
if (-not $PreviewRoot) {
    Fail 'LAB_DATA_PREVIEW_ROOT is not set and -PreviewRoot was not provided'
}
if (-not (Test-Path -LiteralPath $Catalog -PathType Leaf)) {
    Fail "catalog file not found: $Catalog"
}
if (-not (Test-Path -LiteralPath $PreviewRoot -PathType Container)) {
    Fail "preview root directory not found: $PreviewRoot"
}
if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir 'index.html') -PathType Leaf)) {
    Fail "frontend build not found at $FrontendDir (run `npm run build` in frontend/ or set FRONTEND_DIST)"
}

$listeners = @()
try {
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}
catch {
    Fail "could not check port ${Port}: $($_.Exception.Message)"
}
if ($listeners.Count -gt 0) {
    foreach ($listener in $listeners) {
        $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
        if ($process) {
            $owner = "$($process.ProcessName) (PID $($listener.OwningProcess))"
        }
        else {
            $owner = "PID $($listener.OwningProcess)"
        }
        [Console]::Error.WriteLine(
            "error: port $Port is already in use by $owner (listening on $($listener.LocalAddress):$Port); choose another port with -Port"
        )
    }
    exit 1
}

Write-Host 'lab-data server configuration:'
Write-Host ("  catalog:      {0}" -f $Catalog)
Write-Host ("  preview root: {0}" -f $PreviewRoot)
Write-Host ("  frontend:     {0}" -f $FrontendDir)
Write-Host ("  host:         {0}" -f $ListenHost)
Write-Host ("  port:         {0}" -f $Port)
Write-Host 'URLs:'
Write-LabDataUrls -HostAddress $ListenHost -ListenPort $Port

if ($DryRun) {
    Write-Host 'dry run: configuration is valid, not starting the server'
    exit 0
}

$python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python'
}

$env:LAB_DATA_HOST = $ListenHost
$env:LAB_DATA_PORT = [string]$Port
$env:LAB_DATA_CATALOG_PATH = $Catalog
$env:LAB_DATA_PREVIEW_ROOT = $PreviewRoot
$env:FRONTEND_DIST = $FrontendDir

$serverArgs = @(Join-Path $RepoRoot 'scripts\serve_lab_data.py')
$serverArgs += @('--frontend-dir', $FrontendDir)

& $python @serverArgs
exit $LASTEXITCODE
