param(
    [int]$Port = 7777,
    [string]$Bind = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$serviceRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $serviceRoot "..\..")).Path

if (-not $env:OMNI_HOST_TOKEN_FILE -or -not (Test-Path -LiteralPath $env:OMNI_HOST_TOKEN_FILE -PathType Leaf)) {
    throw "OMNI_HOST_TOKEN_FILE must point to a repository-external token file"
}
if (-not $env:OMNI_HOST_ALLOWED_PROJECT_ROOTS) { $env:OMNI_HOST_ALLOWED_PROJECT_ROOTS = (Split-Path $repoRoot -Parent) }
if (-not $env:OMNI_HOST_STATE_DIR) {
    $localState = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { [System.IO.Path]::GetTempPath() }
    $env:OMNI_HOST_STATE_DIR = Join-Path $localState "Omni\host-bridge"
}
if (-not $env:OMNI_PROJECT_DIR) { $env:OMNI_PROJECT_DIR = $repoRoot }
if (-not $env:OMNI_HOST_INSTANCE_ID) { $env:OMNI_HOST_INSTANCE_ID = "host:local" }

python -m uvicorn host_bridge.app:app --app-dir $serviceRoot --host $Bind --port $Port
