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
    Skip identity-service and news-aggregator (they currently have driver issues
    and are not needed for single-user / Path-A MVP usage).

.EXAMPLE
    .\dev-start.ps1
    .\dev-start.ps1 -Only scout-agent,frontend -SkipDocker
    .\dev-start.ps1 -NoOptional
#>

param(
    [switch]$SkipDocker,
    [switch]$SkipFrontend,
    [string[]]$Only,
    [switch]$NoOptional
)

$ErrorActionPreference = "Stop"
$ROOT    = $PSScriptRoot
$LOG_DIR = Join-Path $ROOT ".dev-logs"
$PID_FILE = Join-Path $ROOT ".dev-pids"

# ── Service catalog ──────────────────────────────────────────────────────────
# Every Python service is launched via `python _dev_server.py <port>`
# (ProactorEventLoop is set there before uvicorn imports asyncio).
$SERVICES = @(
    @{ Name = "identity-service";    Port = 8000; Optional = $true  }
    @{ Name = "ai-provider-hub";     Port = 8001; Optional = $false }
    @{ Name = "knowledge-engine";    Port = 8002; Optional = $false }
    @{ Name = "news-aggregator";     Port = 8005; Optional = $true  }
    @{ Name = "video-analysis";      Port = 8006; Optional = $false }
    @{ Name = "livestream-analysis"; Port = 8007; Optional = $false }
    @{ Name = "ad-review-service";   Port = 8008; Optional = $false }
    @{ Name = "scout-agent";         Port = 8009; Optional = $false }
)

# ── Header ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "  Omni-Vibe Dev Launcher  (v2, Playwright-safe)" -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""

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
            Write-Host "  ERROR: Docker not available." -ForegroundColor Red
            exit 1
        }
    }

    docker-compose -f "$ROOT\docker-compose.dev.yml" up -d | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: docker-compose failed." -ForegroundColor Red
        exit 1
    }

    Write-Host "  Waiting for Postgres health..." -ForegroundColor Gray
    for ($i = 0; $i -lt 30; $i++) {
        $h = docker inspect --format='{{.State.Health.Status}}' omni-postgres 2>$null
        if ($h -eq "healthy") { break }
        Start-Sleep -Seconds 2
    }
    Write-Host "  Postgres: $h" -ForegroundColor (if ($h -eq "healthy") { "Green" } else { "DarkYellow" })

    Write-Host "  Applying migrations..." -ForegroundColor Gray
    $env:DATABASE_URL = "postgresql://omni_user:changeme_in_production@localhost:5432/omni_vibe_db"
    & python "$ROOT\scripts\apply_migrations.py" 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
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

    # Copy .env.dev -> .env if present
    if (Test-Path "$svcDir\.env.dev") {
        Copy-Item "$svcDir\.env.dev" "$svcDir\.env" -Force
    } elseif ($svc.Name -eq "identity-service" -and (Test-Path "$svcDir\.env.example") -and (-not (Test-Path "$svcDir\.env"))) {
        Copy-Item "$svcDir\.env.example" "$svcDir\.env" -Force
        Add-Content -Path "$svcDir\.env" -Value "DATABASE_URL=postgresql+asyncpg://omni_user:changeme_in_production@localhost:5432/omni_vibe_db"
        Add-Content -Path "$svcDir\.env" -Value "REDIS_URL=redis://:changeme_redis@localhost:6379/3"
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

    $p = Start-Process -FilePath "python" `
        -ArgumentList "_dev_server.py", "$($svc.Port)" `
        -WorkingDirectory $svcDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $log `
        -RedirectStandardError $err `
        -PassThru

    Add-Content -Path $PID_FILE -Value "$($p.Id)|$($svc.Name)|$($svc.Port)"
    Write-Host "  [$($svc.Name)] :$($svc.Port) PID $($p.Id)" -ForegroundColor Green
    $started += $svc
}

Write-Host ""

# ── 3. Frontend ──────────────────────────────────────────────────────────────
if (-not $SkipFrontend -and (-not $Only -or $Only -contains "frontend")) {
    Write-Host "[3/4] Frontend (Next.js)" -ForegroundColor Yellow

    if (-not (Test-PortFree -Port 3000)) {
        Write-Host "  [frontend] :3000 already in use — skipped" -ForegroundColor DarkYellow
    } else {
        $feLog = Join-Path $LOG_DIR "frontend.log"
        $p = Start-Process -FilePath "cmd.exe" `
            -ArgumentList "/c", "npm run dev -- -H 127.0.0.1" `
            -WorkingDirectory (Join-Path $ROOT "frontend") `
            -WindowStyle Hidden `
            -RedirectStandardOutput $feLog `
            -RedirectStandardError "$feLog.err" `
            -PassThru
        Add-Content -Path $PID_FILE -Value "$($p.Id)|frontend|3000"
        Write-Host "  [frontend] :3000 PID $($p.Id)" -ForegroundColor Green
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
Write-Host "  Frontend            http://localhost:3000" -ForegroundColor White
Write-Host "  AI Provider Hub     http://localhost:8001" -ForegroundColor White
Write-Host "  Knowledge Engine    http://localhost:8002" -ForegroundColor White
Write-Host "  Video Analysis      http://localhost:8006" -ForegroundColor White
Write-Host "  Livestream Analysis http://localhost:8007" -ForegroundColor White
Write-Host "  Ad Review Service   http://localhost:8008" -ForegroundColor White
Write-Host "  Scout Agent         http://localhost:8009" -ForegroundColor White
Write-Host ""
Write-Host "  Logs:    .dev-logs\" -ForegroundColor DarkGray
Write-Host "  Stop:    .\dev-stop.ps1" -ForegroundColor DarkGray
Write-Host ""
