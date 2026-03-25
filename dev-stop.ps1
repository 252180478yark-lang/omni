# Omni-Vibe OS Ultra — 本地开发一键停止
# 用法: .\dev-stop.ps1
#   -KeepDocker   保留 Postgres + Redis 容器运行

param(
    [switch]$KeepDocker
)

$ROOT = $PSScriptRoot
$pidFile = "$ROOT\.dev-pids"

Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host "  Omni-Vibe  Dev Mode Shutdown" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. 按端口杀掉所有已知服务 (最可靠的方式) ──
Write-Host "[1/2] Stopping application services..." -ForegroundColor Yellow

$knownPorts = @(
    @{ Name = "frontend";           Port = 3000 },
    @{ Name = "ai-provider-hub";    Port = 8001 },
    @{ Name = "knowledge-engine";   Port = 8002 },
    @{ Name = "news-aggregator";    Port = 8005 },
    @{ Name = "video-analysis";     Port = 8006 },
    @{ Name = "livestream-analysis"; Port = 8007 }
)

foreach ($svc in $knownPorts) {
    $conns = Get-NetTCPConnection -LocalPort $svc.Port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq "Listen" }
    if ($conns) {
        foreach ($conn in $conns) {
            $procId = $conn.OwningProcess
            try {
                $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
                if ($proc) {
                    Get-CimInstance Win32_Process -Filter "ParentProcessId = $procId" -ErrorAction SilentlyContinue | ForEach-Object {
                        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                    }
                    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                    Write-Host "  [$($svc.Name)] :$($svc.Port) stopped (PID: $procId)" -ForegroundColor Green
                }
            } catch {
                Write-Host "  [$($svc.Name)] :$($svc.Port) could not stop PID $procId : $_" -ForegroundColor DarkYellow
            }
        }
    } else {
        Write-Host "  [$($svc.Name)] :$($svc.Port) not running" -ForegroundColor DarkGray
    }
}

# Also clean up any PIDs from the pid file that might be orphaned wrapper shells
if (Test-Path $pidFile) {
    $lines = Get-Content $pidFile
    foreach ($line in $lines) {
        $parts = $line.Split("|")
        $procId = [int]$parts[0]
        try {
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc) {
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            }
        } catch { }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

Write-Host ""

# ── 2. 停止 Docker 基础设施 ──
if (-not $KeepDocker) {
    Write-Host "[2/2] Stopping Docker infra..." -ForegroundColor Yellow
    docker-compose -f "$ROOT\docker-compose.dev.yml" down 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Docker containers stopped." -ForegroundColor Green
    } else {
        Write-Host "  Docker stop skipped (Docker not running or no containers)." -ForegroundColor DarkGray
    }
} else {
    Write-Host "[2/2] Keeping Docker infra running (-KeepDocker)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host "  All services stopped." -ForegroundColor Green
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""
