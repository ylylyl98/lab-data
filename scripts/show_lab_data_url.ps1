<#
.SYNOPSIS
Prints the current host's candidate browser URLs for the lab-data server.

.DESCRIPTION
Read-only address discovery: lists IPv4 addresses on connected interfaces,
preferring interfaces that carry the default route (typically the campus
Wi-Fi/CMU-Secure link), and prints http://<ip>:<port>/ for each plus
http://127.0.0.1:<port>/. No network, firewall, or configuration changes.

.PARAMETER Host
Bound host to display URLs for. Default 0.0.0.0, which triggers discovery.
Falls back to LAB_DATA_HOST when omitted.

.PARAMETER Port
Port to show in URLs. Default 8765. Falls back to LAB_DATA_PORT when omitted.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/show_lab_data_url.ps1
#>

[CmdletBinding()]
param(
    [Alias('Host')]
    [string] $ListenHost = '0.0.0.0',
    [int] $Port = 8765
)

$ErrorActionPreference = 'Stop'

function Fail([string] $Message) {
    [Console]::Error.WriteLine("error: $Message")
    exit 1
}

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

$candidates = New-Object System.Collections.Generic.List[object]
if ($ListenHost -eq '0.0.0.0' -or $ListenHost -eq '::' -or $ListenHost -eq '*') {
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
        $candidates.Add([PSCustomObject]@{
            Url = "http://$($address.IPAddress):$Port/"
            Interface = $address.InterfaceAlias
        })
    }
}
else {
    $candidates.Add([PSCustomObject]@{ Url = "http://${ListenHost}:${Port}/"; Interface = 'bound host' })
}

foreach ($candidate in $candidates) {
    Write-Host ("  {0,-40} ({1})" -f $candidate.Url, $candidate.Interface)
}
Write-Host ("  {0,-40} (localhost)" -f "http://127.0.0.1:$Port/")
exit 0
