#requires -Version 5.1
<#
.SYNOPSIS
    Omni-Vibe local dev launcher (rewritten v2 — Windows + Playwright safe)

.DESCRIPTION
    Starts Postgres + Redis (Docker), applies migrations, then launches every
    Python service via `_dev_server.py` (sets Windows ProactorEventLoop so
    Playwright Chromium can spawn) and the Next.js frontend.

    Each service lands in its own Hidden window with stdout/err redirected to
    .dev-logs\<service>.log{,.err}. PIDs are tracked in .dev-pids for clean
    shutdown by dev-stop.ps1.

.PARAMETER SkipDocker
    Don't touch Docker Compose (assumes Postgres/Redis already up).

.PARAMETER SkipFrontend
    Don't start the Next.js frontend.

.PARAMETER Only
    Comma-separated subset of services to start (e.g. -Only scout-agent,frontend).

.PARAMETER NoOptional
    Skip identity-service and news-aggregator.  Approval/login UI will be
    degraded because Identity is a required dependency of that surface.

.EXAMPLE
    .\dev-start.ps1
    .\dev-start.ps1 -Only scout-agent,frontend -SkipDocker
    .\dev-start.ps1 -NoOptional
#>

param(
    [switch]$SkipDocker,
    [switch]$SkipFrontend,
    [string[]]$Only,
    [switch]$NoOptional,
    [string]$ChangeId = "local-dev",
    [string]$Owner = "local-developer"
)

$ErrorActionPreference = "Stop"
$ROOT    = $PSScriptRoot
$LOG_DIR = Join-Path $ROOT ".dev-logs"
$PID_FILE = Join-Path $ROOT ".dev-pids"
$DEV_RUNTIME_LAUNCHER = Join-Path $ROOT "scripts\dev_runtime_environment.py"

# Acquire and verify isolation before creating directories, containers,
# processes, or SQL side effects.
$allocationArgs = @(
    "-B", (Join-Path $ROOT "scripts\runtime_allocation.py"),
    "--root", $ROOT, "acquire",
    "--change-id", $ChangeId, "--owner", $Owner, "--risk-level", "R2",
    "--path", "docker-compose.yml", "--path", "docker-compose.dev.yml", "--path", "dev-start.ps1",
    "--path", "migrations/**", "--path", "scripts/apply_migrations.py",
    "--path", "scripts/dev_runtime_environment.py",
    "--path", "services/**", "--path", "frontend/**", "--json"
)
$allocationText = & python @allocationArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: RuntimeAllocation failed; no service was started." -ForegroundColor Red
    exit 1
}
try { $allocation = $allocationText | ConvertFrom-Json } catch {
    Write-Host "  ERROR: RuntimeAllocation returned invalid JSON; no service was started." -ForegroundColor Red
    exit 1
}
$runtimeSideEffectsStarted = $false
function Release-NewUnusedAllocation {
    if ($allocation.created -eq $true -and -not $runtimeSideEffectsStarted) {
        & python -B (Join-Path $ROOT "scripts\runtime_allocation.py") --root $ROOT release `
            --allocation-id $allocation.allocation.allocation_id `
            --owner $Owner --expected-revision $allocation.allocation.revision --json | Out-Null
    }
}
foreach ($property in $allocation.environment.PSObject.Properties) {
    [Environment]::SetEnvironmentVariable($property.Name, [string]$property.Value, "Process")
}
& python -B (Join-Path $ROOT "scripts\runtime_guard.py") allocation-preflight `
    --allocation-file $env:OMNI_RUNTIME_ALLOCATION_SOURCE --json | Out-Null
if ($LASTEXITCODE -ne 0) {
    Release-NewUnusedAllocation
    Write-Host "  ERROR: RuntimeAllocation preflight failed; no service was started." -ForegroundColor Red
    exit 1
}

$allocatedPorts = @{
    "identity-service" = [int]$env:IDENTITY_SERVICE_PORT
    "ai-provider-hub" = [int]$env:AI_PROVIDER_HUB_PORT
    "knowledge-engine" = [int]$env:KNOWLEDGE_ENGINE_PORT
    "news-aggregator" = [int]$env:NEWS_AGGREGATOR_PORT
    "video-analysis" = [int]$env:VIDEO_ANALYSIS_PORT
    "livestream-analysis" = [int]$env:LIVESTREAM_ANALYSIS_PORT
    "ad-review-service" = [int]$env:AD_REVIEW_PORT
    "scout-agent" = [int]$env:SCOUT_AGENT_PORT
    "frontend" = [int]$env:FRONTEND_PORT
    "postgres" = [int]$env:POSTGRES_PORT
    "redis" = [int]$env:REDIS_PORT
}

# ── Service catalog ──────────────────────────────────────────────────────────
# Every Python service is launched via `python _dev_server.py <port>`
# (ProactorEventLoop is set there before uvicorn imports asyncio).
$SERVICES = @(
    @{ Name = "identity-service";    Port = $allocatedPorts["identity-service"]; Optional = $true  }
    # ai-provider-hub and knowledge-engine run as containers in this exact
    # RuntimeAllocation.  Host services reach their allocated loopback ports;
    # they never reuse the canonical 8001/8002 runtime.
    @{ Name = "news-aggregator";     Port = $allocatedPorts["news-aggregator"]; Optional = $true  }
    @{ Name = "video-analysis";      Port = $allocatedPorts["video-analysis"]; Optional = $false }
    @{ Name = "livestream-analysis"; Port = $allocatedPorts["livestream-analysis"]; Optional = $false }
    @{ Name = "ad-review-service";   Port = $allocatedPorts["ad-review-service"]; Optional = $false }
    @{ Name = "scout-agent";         Port = $allocatedPorts["scout-agent"]; Optional = $false }
)

# ── Header ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "  Omni-Vibe Dev Launcher  (v2, Playwright-safe)" -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""
if ($NoOptional) {
    Write-Host "  WARNING: -NoOptional disables Identity; login/approval UI health is degraded." -ForegroundColor DarkYellow
    Write-Host ""
}

# ── 0. Ensure dirs exist ─────────────────────────────────────────────────────
if (-not (Test-Path $LOG_DIR)) { New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null }
$REQUIRED_DIRS = @(
    "services\knowledge-engine\data\images",
    "services\video-analysis\data\video-analysis",
    "services\livestream-analysis\data",
    "services\ad-review-service\data",
    "services\scout-agent\sessions",
    "services\scout-agent\downloads",
    "services\scout-agent\snapshots"
)
foreach ($d in $REQUIRED_DIRS) {
    $full = Join-Path $ROOT $d
    if (-not (Test-Path $full)) { New-Item -ItemType Directory -Path $full -Force | Out-Null }
}

# ── 1. Docker (Postgres + Redis) + migrations ────────────────────────────────
if (-not $SkipDocker) {
    Write-Host "[1/4] Docker infra (Postgres + Redis)" -ForegroundColor Yellow

    cmd /c "docker info >nul 2>&1"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Docker not running, starting Docker Desktop..." -ForegroundColor DarkYellow
        Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -ErrorAction SilentlyContinue
        for ($i = 0; $i -lt 60; $i++) {
            Start-Sleep -Seconds 3
            cmd /c "docker info >nul 2>&1"
            if ($LASTEXITCODE -eq 0) { break }
        }
        if ($LASTEXITCODE -ne 0) {
            Release-NewUnusedAllocation
            Write-Host "  ERROR: Docker not available." -ForegroundColor Red
            exit 1
        }
    }

    $composeFile = Join-Path $ROOT "docker-compose.yml"
    $runtimeSideEffectsStarted = $true
    docker compose -f $composeFile up -d postgres redis | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: docker compose failed." -ForegroundColor Red
        exit 1
    }

    Write-Host "  Waiting for Postgres health..." -ForegroundColor Gray
    for ($i = 0; $i -lt 30; $i++) {
        $postgresId = docker compose -f $composeFile ps -q postgres
        $h = if ($postgresId) { docker inspect --format='{{.State.Health.Status}}' $postgresId 2>$null } else { "missing" }
        if ($h -eq "healthy") { break }
        Start-Sleep -Seconds 2
    }
    $pgColor = if ($h -eq "healthy") { "Green" } else { "DarkYellow" }
    Write-Host "  Postgres: $h" -ForegroundColor $pgColor

    Write-Host "  Applying migrations through the allocation-aware one-shot runner..." -ForegroundColor Gray
    if (-not $env:OMNI_MIGRATION_RECEIPT_DIR) {
        $env:OMNI_MIGRATION_RECEIPT_DIR = Join-Path $ROOT ".runtime\migration-receipts"
    }
    docker compose -f $composeFile run --rm migrate `
        2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: allocation-aware migration runner failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "  Starting allocated AI Provider Hub and Knowledge Engine..." -ForegroundColor Gray
    docker compose -f $composeFile up -d ai-provider-hub knowledge-engine | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: allocated core application services failed to start." -ForegroundColor Red
        exit 1
    }
    Write-Host ""
} else {
    Write-Host "[1/4] Docker skipped (-SkipDocker)" -ForegroundColor DarkGray
}

# ── 2. Backend services ──────────────────────────────────────────────────────
Write-Host "[2/4] Backend services" -ForegroundColor Yellow

# Bypass Windows system proxy for localhost calls (Clash/V2Ray etc. otherwise
# tunnel localhost traffic and break inter-service HTTP).
$env:NO_PROXY = "localhost,127.0.0.1,::1,0.0.0.0,*.local"
$env:no_proxy = $env:NO_PROXY

if (Test-Path $PID_FILE) { Remove-Item $PID_FILE -Force }

# Reliable port-free check: actually try to bind. Get-NetTCPConnection caches
# stale listeners across PowerShell sessions; TcpListener tells the truth.
function Test-PortFree {
    param([int]$Port)
    try {
        $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
        $l.Start()
        $l.Stop()
        return $true
    } catch { return $false }
}

$started = @()
foreach ($svc in $SERVICES) {
    if ($Only -and $Only -notcontains $svc.Name) { continue }
    if ($NoOptional -and $svc.Optional) {
        Write-Host "  [$($svc.Name)] skipped (optional + -NoOptional)" -ForegroundColor DarkGray
        continue
    }

    $svcDir = Join-Path $ROOT "services\$($svc.Name)"
    if (-not (Test-Path "$svcDir\_dev_server.py")) {
        Write-Host "  [$($svc.Name)] no _dev_server.py — skipped" -ForegroundColor Red
        continue
    }

    # Skip if port already taken (real bind test, not the cached netstat view)
    if (-not (Test-PortFree -Port $svc.Port)) {
        Write-Host "  [$($svc.Name)] :$($svc.Port) already in use — skipped" -ForegroundColor DarkYellow
        continue
    }

    # knowledge-engine harvester needs HARVESTER_IMAGE_DIR
    if ($svc.Name -eq "knowledge-engine") {
        $env:HARVESTER_IMAGE_DIR = "$svcDir\data\images"
    }

    $log = Join-Path $LOG_DIR "$($svc.Name).log"
    $err = "$log.err"

    $launchArgs = @(
        "-B", $DEV_RUNTIME_LAUNCHER, "launch",
        "--service", $svc.Name, "--cwd", $svcDir,
        "--stdout", $log, "--stderr", $err, "--",
        "python", "_dev_server.py", "$($svc.Port)"
    )
    $launchText = & python @launchArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [$($svc.Name)] isolated child launch blocked" -ForegroundColor Red
        continue
    }
    try { $launched = $launchText | ConvertFrom-Json } catch {
        Write-Host "  [$($svc.Name)] launcher returned invalid metadata" -ForegroundColor Red
        continue
    }
    $childPid = [int]$launched.pid
    Add-Content -Path $PID_FILE -Value "$childPid|$($svc.Name)|$($svc.Port)"
    Write-Host "  [$($svc.Name)] :$($svc.Port) PID $childPid" -ForegroundColor Green
    $started += $svc
}

Write-Host ""

# ── 3. Frontend ──────────────────────────────────────────────────────────────
if (-not $SkipFrontend -and (-not $Only -or $Only -contains "frontend")) {
    Write-Host "[3/4] Frontend (Next.js)" -ForegroundColor Yellow

    $frontendPort = $allocatedPorts["frontend"]
    if (-not (Test-PortFree -Port $frontendPort)) {
        Write-Host "  [frontend] :$frontendPort already in use — skipped" -ForegroundColor DarkYellow
    } else {
        $feLog = Join-Path $LOG_DIR "frontend.log"
        $frontendDir = Join-Path $ROOT "frontend"
        $launchArgs = @(
            "-B", $DEV_RUNTIME_LAUNCHER, "launch",
            "--service", "frontend", "--cwd", $frontendDir,
            "--stdout", $feLog, "--stderr", "$feLog.err", "--",
            "cmd.exe", "/c", "npm", "run", "dev", "--", "-H", "127.0.0.1", "-p", "$frontendPort"
        )
        $launchText = & python @launchArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [frontend] isolated child launch blocked" -ForegroundColor Red
        } else {
            try { $launched = $launchText | ConvertFrom-Json } catch { $launched = $null }
            if (-not $launched) {
                Write-Host "  [frontend] launcher returned invalid metadata" -ForegroundColor Red
            } else {
                $childPid = [int]$launched.pid
                Add-Content -Path $PID_FILE -Value "$childPid|frontend|$frontendPort"
                Write-Host "  [frontend] :$frontendPort PID $childPid" -ForegroundColor Green
            }
        }
    }
} else {
    Write-Host "[3/4] Frontend skipped" -ForegroundColor DarkGray
}

Write-Host ""

# ── 4. Health check ──────────────────────────────────────────────────────────
Write-Host "[4/4] Health check (30s budget)" -ForegroundColor Yellow

$allEntries = if (Test-Path $PID_FILE) {
    Get-Content $PID_FILE | ForEach-Object {
        $parts = $_.Split("|")
        @{ Name = $parts[1]; Port = [int]$parts[2]; ProcId = [int]$parts[0] }
    }
} else { @() }

$deadline = (Get-Date).AddSeconds(30)
do {
    $allUp = $true
    foreach ($e in $allEntries) {
        if (Test-PortFree -Port $e.Port) { $allUp = $false; break }
    }
    if ($allUp) { break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)

$failed = @()
foreach ($e in $allEntries) {
    $up = -not (Test-PortFree -Port $e.Port)
    if ($up) {
        Write-Host "  [$($e.Name)] :$($e.Port) OK" -ForegroundColor Green
    } else {
        Write-Host "  [$($e.Name)] :$($e.Port) FAILED" -ForegroundColor Red
        $failed += $e.Name
        $errLog = Join-Path $LOG_DIR "$($e.Name).log.err"
        if (Test-Path $errLog) {
            Get-Content $errLog -Tail 6 -ErrorAction SilentlyContinue | ForEach-Object {
                Write-Host "      $_" -ForegroundColor DarkYellow
            }
        }
    }
}

# ── Footer ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
if ($failed.Count -eq 0) {
    Write-Host "  All up." -ForegroundColor Green
} else {
    Write-Host "  Started with errors. Failed: $($failed -join ', ')" -ForegroundColor Yellow
    Write-Host "  Tail logs: Get-Content .dev-logs\<svc>.log.err -Tail 30" -ForegroundColor DarkGray
}
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Frontend            http://localhost:$($allocatedPorts['frontend'])" -ForegroundColor White
Write-Host "  AI Provider Hub     http://localhost:$($allocatedPorts['ai-provider-hub'])" -ForegroundColor White
Write-Host "  Knowledge Engine    http://localhost:$($allocatedPorts['knowledge-engine'])" -ForegroundColor White
Write-Host "  Video Analysis      http://localhost:$($allocatedPorts['video-analysis'])" -ForegroundColor White
Write-Host "  Livestream Analysis http://localhost:$($allocatedPorts['livestream-analysis'])" -ForegroundColor White
Write-Host "  Ad Review Service   http://localhost:$($allocatedPorts['ad-review-service'])" -ForegroundColor White
Write-Host "  Scout Agent         http://localhost:$($allocatedPorts['scout-agent'])" -ForegroundColor White
Write-Host ""
Write-Host "  Logs:    .dev-logs\" -ForegroundColor DarkGray
Write-Host "  Stop:    .\dev-stop.ps1" -ForegroundColor DarkGray
Write-Host ""
