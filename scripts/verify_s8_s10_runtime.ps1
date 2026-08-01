# S8/S9 disposable PostgreSQL verification. Never points at the canonical DB.
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$owner = "codex-s8-s10-verifier"
$changeId = "s8-s10-v" + [DateTimeOffset]::UtcNow.ToString("yyyyMMddHHmmss")
$allocation = $null
$sideEffectsStarted = $false

function Read-DotEnvValue([string]$Name, [string]$Fallback) {
    $path = Join-Path $repoRoot ".env"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $Fallback }
    $line = Get-Content -LiteralPath $path | Where-Object { $_ -match "^$([regex]::Escape($Name))=" } | Select-Object -Last 1
    if (-not $line) { return $Fallback }
    return ($line -split "=", 2)[1]
}

try {
    $allocationText = & python -B (Join-Path $repoRoot "scripts\runtime_allocation.py") --root $repoRoot acquire `
        --change-id $changeId --owner $owner --risk-level R2 `
        --path "verification/s8-s10/**" --json
    if ($LASTEXITCODE -ne 0) { throw "RuntimeAllocation acquire failed" }
    $allocation = $allocationText | ConvertFrom-Json
    foreach ($property in $allocation.environment.PSObject.Properties) {
        [Environment]::SetEnvironmentVariable($property.Name, [string]$property.Value, "Process")
    }
    if ($env:OMNI_DATABASE_DISPOSABLE -ne "true" -or $env:POSTGRES_DB -notlike "omni_verify_*") {
        throw "verification refused a non-disposable database"
    }
    $receiptDir = Join-Path ([System.IO.Path]::GetTempPath()) ("omni-s8-s10-migration-receipts-" + $allocation.allocation.allocation_id)
    $env:OMNI_MIGRATION_RECEIPT_DIR = $receiptDir
    $compose = Join-Path $repoRoot "docker-compose.yml"
    $sideEffectsStarted = $true
    & docker compose -f $compose up -d --build postgres
    if ($LASTEXITCODE -ne 0) { throw "disposable PostgreSQL startup failed" }
    & docker compose -f $compose run --rm migrate
    if ($LASTEXITCODE -ne 0) { throw "allocation-aware migration failed" }

    $dbUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { Read-DotEnvValue "POSTGRES_USER" "omni_user" }
    $dbPassword = if ($env:POSTGRES_PASSWORD) { $env:POSTGRES_PASSWORD } else { Read-DotEnvValue "POSTGRES_PASSWORD" "changeme_in_production" }
    $safeUser = [uri]::EscapeDataString($dbUser)
    $safePassword = [uri]::EscapeDataString($dbPassword)
    $env:OMNI_TEST_DATABASE_URL = "postgresql://${safeUser}:${safePassword}@127.0.0.1:$($env:POSTGRES_PORT)/$($env:POSTGRES_DB)"
    & python -m pytest services/knowledge-engine/tests/test_runtime_trace_postgres.py -q
    if ($LASTEXITCODE -ne 0) { throw "real PostgreSQL runtime trace verification failed" }
    Write-Output "S8_S10_POSTGRES_VERIFIED allocation=$($allocation.allocation.allocation_id) database_mode=disposable"
}
finally {
    if ($sideEffectsStarted -and $allocation) {
        & docker compose -f (Join-Path $repoRoot "docker-compose.yml") down --volumes --remove-orphans | Out-Null
    }
    if ($allocation -and $allocation.created -eq $true) {
        & python -B (Join-Path $repoRoot "scripts\runtime_allocation.py") --root $repoRoot release `
            --allocation-id $allocation.allocation.allocation_id --owner $owner `
            --expected-revision $allocation.allocation.revision --json | Out-Null
    }
    Remove-Item Env:OMNI_TEST_DATABASE_URL -ErrorAction SilentlyContinue
}
