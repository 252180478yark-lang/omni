# Omni-Vibe OS Ultra - local one-click backup
# Usage:
#   .\scripts\backup.ps1
#   .\scripts\backup.ps1 -OutputDir E:\omni-backups

param(
    [string]$OutputDir,
    [switch]$SkipDatabase,
    [switch]$SkipDockerData,
    [switch]$SkipLocalData
)

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $PSScriptRoot
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

if (-not $OutputDir) {
    $OutputDir = Join-Path $ROOT "backups"
}

$backupDir = Join-Path $OutputDir "omni-backup-$timestamp"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host $Message -ForegroundColor Cyan
}

function Test-DockerAvailable {
    try {
        docker info *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Get-DockerContainer([string]$Name) {
    docker ps -a --format "{{.Names}}" | Where-Object { $_ -eq $Name } | Select-Object -First 1
}

function Backup-Postgres {
    Write-Step "[1/4] Backing up PostgreSQL"

    $container = Get-DockerContainer "omni-postgres"
    if (-not $container) {
        Write-Host "  omni-postgres container not found, skipping database backup." -ForegroundColor DarkYellow
        return
    }

    $running = docker inspect -f "{{.State.Running}}" $container 2>$null
    if ($running -ne "true") {
        Write-Host "  omni-postgres is not running, skipping database backup." -ForegroundColor DarkYellow
        return
    }

    $dbUser = $env:POSTGRES_USER
    if (-not $dbUser) { $dbUser = "omni_user" }
    $dbName = $env:POSTGRES_DB
    if (-not $dbName) { $dbName = "omni_vibe_db" }

    $tmpFile = "/tmp/omni-vibe-$timestamp.dump"
    $hostFile = Join-Path $backupDir "postgres-$dbName.dump"

    docker exec $container pg_dump -U $dbUser -d $dbName -Fc -f $tmpFile
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }

    docker cp "${container}:$tmpFile" $hostFile
    if ($LASTEXITCODE -ne 0) { throw "docker cp database dump failed" }

    docker exec $container rm -f $tmpFile *> $null
    Write-Host "  Saved: $hostFile" -ForegroundColor Green
}

function Backup-DockerMount([string]$ContainerName, [string]$MountPath, [string]$ArchiveName) {
    $container = Get-DockerContainer $ContainerName
    if (-not $container) {
        Write-Host "  [$ContainerName] container not found, skipping." -ForegroundColor DarkGray
        return
    }

    $source = docker inspect -f "{{range .Mounts}}{{if eq .Destination `"$MountPath`"}}{{if .Name}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}" $container 2>$null
    if (-not $source) {
        Write-Host "  [$ContainerName] mount $MountPath not found, skipping." -ForegroundColor DarkGray
        return
    }

    docker run --rm -v "${source}:/data:ro" -v "${backupDir}:/backup" alpine sh -c "cd /data && tar czf /backup/$ArchiveName ."
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Saved: $ArchiveName" -ForegroundColor Green
    } else {
        Write-Host "  [$ContainerName] backup failed." -ForegroundColor DarkYellow
    }
}

function Backup-DockerData {
    Write-Step "[2/4] Backing up Docker data volumes"

    $mounts = @(
        @{ Container = "omni-ai-provider-hub";    Path = "/app/data"; Archive = "docker-ai-hub-data.tgz" },
        @{ Container = "omni-knowledge-engine";   Path = "/app/data"; Archive = "docker-knowledge-data.tgz" },
        @{ Container = "omni-video-analysis";     Path = "/app/data"; Archive = "docker-video-analysis-data.tgz" },
        @{ Container = "omni-livestream-analysis"; Path = "/app/data"; Archive = "docker-livestream-analysis-data.tgz" },
        @{ Container = "omni-ad-review";          Path = "/app/data"; Archive = "docker-ad-review-data.tgz" },
        @{ Container = "omni-redis";              Path = "/data";     Archive = "docker-redis-data.tgz" }
    )

    foreach ($item in $mounts) {
        Backup-DockerMount -ContainerName $item.Container -MountPath $item.Path -ArchiveName $item.Archive
    }
}

function Backup-LocalDirectory([string]$RelativePath, [string]$ArchiveName) {
    $path = Join-Path $ROOT $RelativePath
    if (-not (Test-Path $path)) {
        Write-Host "  [$RelativePath] not found, skipping." -ForegroundColor DarkGray
        return
    }

    $target = Join-Path $backupDir $ArchiveName
    Compress-Archive -Path $path -DestinationPath $target -Force
    Write-Host "  Saved: $ArchiveName" -ForegroundColor Green
}

function Backup-LocalData {
    Write-Step "[3/4] Backing up local dev data"

    $dirs = @(
        @{ Path = "services\ai-provider-hub\data";      Archive = "local-ai-hub-data.zip" },
        @{ Path = "services\knowledge-engine\data";     Archive = "local-knowledge-data.zip" },
        @{ Path = "services\video-analysis\data";       Archive = "local-video-analysis-data.zip" },
        @{ Path = "services\livestream-analysis\data";  Archive = "local-livestream-analysis-data.zip" },
        @{ Path = "services\ad-review-service\data";    Archive = "local-ad-review-data.zip" }
    )

    foreach ($dir in $dirs) {
        Backup-LocalDirectory -RelativePath $dir.Path -ArchiveName $dir.Archive
    }
}

function Write-Manifest {
    Write-Step "[4/4] Writing manifest"

    $manifest = [ordered]@{
        createdAt = (Get-Date).ToString("o")
        root = $ROOT
        backupDir = $backupDir
        database = -not $SkipDatabase
        dockerData = -not $SkipDockerData
        localData = -not $SkipLocalData
        note = "Restore database with pg_restore. Extract tgz/zip archives back to matching Docker volumes or service data directories."
    }

    $manifestPath = Join-Path $backupDir "manifest.json"
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -Path $manifestPath -Encoding UTF8
    Write-Host "  Saved: $manifestPath" -ForegroundColor Green
}

Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host "  Omni-Vibe Local Backup" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host "  Target: $backupDir" -ForegroundColor White

$dockerAvailable = Test-DockerAvailable

if (-not $SkipDatabase) {
    if ($dockerAvailable) {
        Backup-Postgres
    } else {
        Write-Host "Docker is not available, skipping database backup." -ForegroundColor DarkYellow
    }
}

if (-not $SkipDockerData) {
    if ($dockerAvailable) {
        Backup-DockerData
    } else {
        Write-Host "Docker is not available, skipping Docker data backup." -ForegroundColor DarkYellow
    }
}

if (-not $SkipLocalData) {
    Backup-LocalData
}

Write-Manifest

Write-Host ""
Write-Host "Backup complete: $backupDir" -ForegroundColor Green
Write-Host ""
