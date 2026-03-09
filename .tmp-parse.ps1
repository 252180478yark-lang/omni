param(
  [switch]$AutoStart
)

$ErrorActionPreference = "Stop"

function Write-Section {
  param([string]$Name)
  Write-Host ""
  Write-Host "==== $Name ====" -ForegroundColor Cyan
}

function Record-Step {
  param(
    [string]$Name,
    [bool]$Ok,
    [string]$ErrorMessage = ""
  )

  if ($Ok) {
