# Omni-Vibe OS Ultra — 本地开发一键启动
# 用法: .\dev-start.ps1
#   -SkipDocker     跳过 Docker 基础设施启动
#   -SkipFrontend   只启动后端服务
#   -Only <names>   只启动指定服务, 如 -Only knowledge-engine,frontend
#
# Docker 只跑 Postgres + Redis，应用服务全部本地运行

param(
    [switch]$SkipDocker,
    [switch]$SkipFrontend,
    [string[]]$Only
)

$ErrorActionPreference = "Stop"
$ROOT = $PSScriptRoot
$LOG_DIR = Join-Path $ROOT ".dev-logs"

Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host "  Omni-Vibe  Dev Mode Launcher" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# ── 0. 准备工作：日志目录 & 数据目录 ──
if (-not (Test-Path $LOG_DIR)) { New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null }

$requiredDirs = @(
    "services\knowledge-engine\data\images",
    "services\video-analysis\data\video-analysis"
)
foreach ($dir in $requiredDirs) {
    $full = Join-Path $ROOT $dir
    if (-not (Test-Path $full)) {
        New-Item -ItemType Directory -Path $full -Force | Out-Null
        Write-Host "  [init] Created $dir" -ForegroundColor Gray
    }
}

# ── 1. 启动 Docker 基础设施 (Postgres + Redis) ──
if (-not $SkipDocker) {
    Write-Host "[1/4] Starting Docker infra (Postgres + Redis)..." -ForegroundColor Yellow

    $dockerTest = cmd /c "docker info 2>&1"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Docker is not running. Attempting to start Docker Desktop..." -ForegroundColor DarkYellow
        Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -ErrorAction SilentlyContinue
        $retries = 0
        while ($retries -lt 60) {
            Start-Sleep -Seconds 3
            $retries++
            cmd /c "docker info >nul 2>&1"
            if ($LASTEXITCODE -eq 0) { break }
            Write-Host "  ... waiting for Docker ($retries)" -ForegroundColor Gray
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: Docker failed to start. Please start Docker Desktop manually." -ForegroundColor Red
            exit 1
        }
        Write-Host "  Docker is ready!" -ForegroundColor Green
    }

    docker-compose -f "$ROOT\docker-compose.dev.yml" up -d
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Docker Compose startup failed!" -ForegroundColor Red
        exit 1
    }

    Write-Host "  Waiting for Postgres to be healthy..." -ForegroundColor Gray
    $retries = 0
    while ($retries -lt 30) {
        $health = docker inspect --format='{{.State.Health.Status}}' omni-postgres 2>$null
        if ($health -eq "healthy") { break }
        Start-Sleep -Seconds 2
        $retries++
        Write-Host "  ... waiting ($retries)" -ForegroundColor Gray
    }
    if ($health -ne "healthy") {
        Write-Host "WARNING: Postgres may not be ready yet, proceeding anyway." -ForegroundColor DarkYellow
    } else {
        Write-Host "  Postgres is healthy!" -ForegroundColor Green
    }
    Write-Host ""
} else {
    Write-Host "[1/4] Skipping Docker (--SkipDocker)" -ForegroundColor DarkGray
}

# ── 2. 定义服务列表 ──
$services = @(
    @{ Name = "ai-provider-hub";      Port = 8001; Dir = "services\ai-provider-hub" },
    @{ Name = "knowledge-engine";     Port = 8002; Dir = "services\knowledge-engine" },
    @{ Name = "news-aggregator";      Port = 8005; Dir = "services\news-aggregator" },
    @{ Name = "video-analysis";       Port = 8006; Dir = "services\video-analysis" },
    @{ Name = "livestream-analysis";  Port = 8007; Dir = "services\livestream-analysis" }
)

# ── 3. 启动 Python 后端服务 ──
Write-Host "[2/4] Starting backend services..." -ForegroundColor Yellow

$pidFile = "$ROOT\.dev-pids"
if (Test-Path $pidFile) { Remove-Item $pidFile }

foreach ($svc in $services) {
    if ($Only -and $Only -notcontains $svc.Name) { continue }

    $svcDir = Join-Path $ROOT $svc.Dir
    $envDev = Join-Path $svcDir ".env.dev"
    $envTarget = Join-Path $svcDir ".env"

    if (Test-Path $envDev) {
        Copy-Item $envDev $envTarget -Force
        Write-Host "  [$($svc.Name)] .env.dev -> .env" -ForegroundColor Gray
    }

    # Check if port is already in use
    $existing = Get-NetTCPConnection -LocalPort $svc.Port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq "Listen" }
    if ($existing) {
        Write-Host "  [$($svc.Name)] port $($svc.Port) already in use (PID: $($existing.OwningProcess | Select-Object -First 1)), skipping" -ForegroundColor DarkYellow
        continue
    }

    $logFile = Join-Path $LOG_DIR "$($svc.Name).log"

    if ($svc.Name -eq "knowledge-engine") {
        # knowledge-engine needs ProactorEventLoop for Playwright subprocess on Windows;
        # use _dev_server.py helper to set the policy before uvicorn starts.
        $env:HARVESTER_IMAGE_DIR = "$svcDir\data\images"
        $proc = Start-Process -FilePath python -ArgumentList "_dev_server.py", "$($svc.Port)" `
            -WorkingDirectory $svcDir -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
    } else {
        $proc = Start-Process -FilePath python -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$($svc.Port)", "--reload" `
            -WorkingDirectory $svcDir -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
    }

    Write-Host "  [$($svc.Name)] starting on port $($svc.Port) (PID: $($proc.Id))" -ForegroundColor Green
    Add-Content -Path $pidFile -Value "$($proc.Id)|$($svc.Name)|$($svc.Port)"
}

Write-Host ""

# ── 4. 启动 Frontend ──
if (-not $SkipFrontend) {
    if ($Only -and $Only -notcontains "frontend") {
        Write-Host "[3/4] Skipping frontend (not in -Only list)" -ForegroundColor DarkGray
    } else {
        $existingFe = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue | Where-Object { $_.State -eq "Listen" }
        if ($existingFe) {
            Write-Host "[3/4] Frontend port 3000 already in use, skipping" -ForegroundColor DarkYellow
        } else {
            Write-Host "[3/4] Starting frontend (Next.js)..." -ForegroundColor Yellow
            $frontendDir = Join-Path $ROOT "frontend"
            $feLog = Join-Path $LOG_DIR "frontend.log"
            $proc = Start-Process -FilePath cmd.exe -ArgumentList "/c", "npm run dev" `
                -WorkingDirectory $frontendDir -PassThru -WindowStyle Hidden `
                -RedirectStandardOutput $feLog -RedirectStandardError "$feLog.err"
            Write-Host "  [frontend] starting on port 3000 (PID: $($proc.Id))" -ForegroundColor Green
            Add-Content -Path $pidFile -Value "$($proc.Id)|frontend|3000"
        }
    }
} else {
    Write-Host "[3/4] Skipping frontend (--SkipFrontend)" -ForegroundColor DarkGray
}

Write-Host ""

# ── 5. 健康检查 ──
Write-Host "[4/4] Health check..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

$allPorts = @()
if (Test-Path $pidFile) {
    $allPorts = Get-Content $pidFile | ForEach-Object {
        $parts = $_.Split("|")
        @{ Name = $parts[1]; Port = [int]$parts[2]; PID = [int]$parts[0] }
    }
}

$maxWait = 20
$elapsed = 0
do {
    $allReady = $true
    foreach ($svc in $allPorts) {
        $conn = Get-NetTCPConnection -LocalPort $svc.Port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq "Listen" }
        if (-not $conn) { $allReady = $false; break }
    }
    if ($allReady) { break }
    Start-Sleep -Seconds 2
    $elapsed += 2
    Write-Host "  ... waiting for services ($elapsed s)" -ForegroundColor Gray
} while ($elapsed -lt $maxWait)

$failedServices = @()
foreach ($svc in $allPorts) {
    $conn = Get-NetTCPConnection -LocalPort $svc.Port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq "Listen" }
    if ($conn) {
        Write-Host "  [$($svc.Name)] :$($svc.Port) OK" -ForegroundColor Green
    } else {
        Write-Host "  [$($svc.Name)] :$($svc.Port) FAILED" -ForegroundColor Red
        $errLog = Join-Path $LOG_DIR "$($svc.Name).log.err"
        if (Test-Path $errLog) {
            $errContent = Get-Content $errLog -Tail 5 -ErrorAction SilentlyContinue
            if ($errContent) {
                Write-Host "    Last errors:" -ForegroundColor DarkYellow
                $errContent | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkYellow }
            }
        }
        $failedServices += $svc.Name
    }
}

Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
if ($failedServices.Count -eq 0) {
    Write-Host "  All services started!" -ForegroundColor Green
} else {
    Write-Host "  Started with errors!" -ForegroundColor Yellow
    Write-Host "  Failed: $($failedServices -join ', ')" -ForegroundColor Red
    Write-Host "  Check logs: .dev-logs\<service>.log.err" -ForegroundColor DarkYellow
}
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Frontend:            http://localhost:3000" -ForegroundColor White
Write-Host "  AI Provider Hub:     http://localhost:8001" -ForegroundColor White
Write-Host "  Knowledge Engine:    http://localhost:8002" -ForegroundColor White
Write-Host "  News Aggregator:     http://localhost:8005" -ForegroundColor White
Write-Host "  Video Analysis:      http://localhost:8006" -ForegroundColor White
Write-Host "  Livestream Analysis: http://localhost:8007" -ForegroundColor White
Write-Host ""
Write-Host "  Logs:     .dev-logs\" -ForegroundColor DarkGray
Write-Host "  Stop all: .\dev-stop.ps1" -ForegroundColor DarkGray
Write-Host ""
