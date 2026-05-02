#requires -Version 5.1
<#
.SYNOPSIS
    Omni-Vibe local dev shutdown (rewritten v2)

.DESCRIPTION
    Kills every process listening on the known service ports (3000 + 8000-8009),
    plus their direct children (catches uvicorn / npm wrappers), then optionally
    stops the Postgres + Redis containers.

.PARAMETER KeepDocker
    Don't touch Docker Compose (leave Postgres/Redis running for next boot).

.PARAMETER NukePython
    Extra-safe mode: also kills any python.exe whose CommandLine references this
    repo's services\ folder. Use when -NormalStop leaves zombies behind.

.EXAMPLE
    .\dev-stop.ps1
    .\dev-stop.ps1 -KeepDocker
    .\dev-stop.ps1 -NukePython
#>

param(
    [switch]$KeepDocker,
    [switch]$NukePython
)

$ROOT     = $PSScriptRoot
$PID_FILE = Join-Path $ROOT ".dev-pids"
$PORTS    = @(3000, 8000, 8001, 8002, 8005, 8006, 8007, 8008, 8009)

Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "  Omni-Vibe Dev Shutdown  (v2)" -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""

# ── Helper: kill a process tree ──────────────────────────────────────────────
function Stop-ProcessTree {
    param([int]$ProcId)
    try {
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcId" -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-ProcessTree -ProcId $_.ProcessId }
        Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue
    } catch {}
}

# ── 1. Stop services by port ─────────────────────────────────────────────────
Write-Host "[1/3] Stopping services by port" -ForegroundColor Yellow

$killed = 0
foreach ($port in $PORTS) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "  :$port (not running)" -ForegroundColor DarkGray
        continue
    }
    foreach ($c in $conns) {
        $procId = $c.OwningProcess
        $name = (Get-Process -Id $procId -ErrorAction SilentlyContinue).ProcessName
        Stop-ProcessTree -ProcId $procId
        Write-Host "  :$port stopped (PID $procId, $name)" -ForegroundColor Green
        $killed++
    }
}

# ── 2. Sweep .dev-pids for orphaned wrappers ─────────────────────────────────
Write-Host ""
Write-Host "[2/3] Cleaning PID file orphans" -ForegroundColor Yellow

if (Test-Path $PID_FILE) {
    Get-Content $PID_FILE | ForEach-Object {
        $parts = $_.Split("|")
        if ($parts.Length -ge 1) {
            $procId = [int]$parts[0]
            if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
                Stop-ProcessTree -ProcId $procId
                Write-Host "  orphan PID $procId stopped ($($parts[1]))" -ForegroundColor Green
            }
        }
    }
    Remove-Item $PID_FILE -Force -ErrorAction SilentlyContinue
    Write-Host "  .dev-pids removed" -ForegroundColor DarkGray
} else {
    Write-Host "  no .dev-pids file" -ForegroundColor DarkGray
}

# ── 2b. Optional nuclear: kill any python referencing services\ ──────────────
if ($NukePython) {
    Write-Host ""
    Write-Host "  -NukePython: hunting stray python.exe in this repo..." -ForegroundColor DarkYellow
    $repoPattern = ($ROOT -replace '\\', '\\\\') + '\\\\services\\\\'
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $repoPattern } |
        ForEach-Object {
            Stop-ProcessTree -ProcId $_.ProcessId
            Write-Host "    nuked PID $($_.ProcessId)" -ForegroundColor Yellow
        }
}

# ── 3. Stop Docker infra ─────────────────────────────────────────────────────
Write-Host ""
if (-not $KeepDocker) {
    Write-Host "[3/3] Stopping Docker (Postgres + Redis)" -ForegroundColor Yellow
    docker-compose -f "$ROOT\docker-compose.dev.yml" down 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Docker containers stopped." -ForegroundColor Green
    } else {
        Write-Host "  Docker stop skipped (not running)." -ForegroundColor DarkGray
    }
} else {
    Write-Host "[3/3] Docker kept running (-KeepDocker)" -ForegroundColor DarkGray
}

# ── Verify ports actually free ───────────────────────────────────────────────
Start-Sleep -Seconds 2
$stillUp = @()
foreach ($port in $PORTS) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        $stillUp += $port
    }
}

Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
if ($stillUp.Count -eq 0) {
    Write-Host "  All clear ($killed killed)." -ForegroundColor Green
} else {
    Write-Host "  Still listening: $($stillUp -join ', ')" -ForegroundColor Red
    Write-Host "  Try: .\dev-stop.ps1 -NukePython" -ForegroundColor DarkYellow
}
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""
