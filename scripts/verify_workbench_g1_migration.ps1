# G1 disposable PostgreSQL migration verification. Never reads or connects to a shared database.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeAllocationScript = Join-Path $repoRoot "scripts\runtime_allocation.py"
$migrationScript = Join-Path $repoRoot "scripts\apply_migrations.py"
$image = "pgvector/pgvector:pg16"
$suffix = [Guid]::NewGuid().ToString("N").Substring(0, 16)
$containerName = "omni-g1-migration-$suffix"
$owner = "codex-g1-migration-$suffix"
$changeId = "g1-migration-$suffix"
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$tempDir = [IO.Path]::GetFullPath((Join-Path $tempRoot "omni-g1-migration-$suffix"))
$stateDir = Join-Path $tempDir "runtime-state"
$allocation = $null
$allocationFile = $null
$anonymousVolume = $null
$containerAttempted = $false
$success = $false
$summary = $null
$cleanupFailures = New-Object System.Collections.Generic.List[string]
$originalEnvironment = @{}

if (-not $tempDir.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "temporary verification directory escaped the system temp root"
}

function Invoke-NativeCapture {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $captured = @(& $FilePath @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = (($captured | ForEach-Object { [string]$_ }) -join [Environment]::NewLine)
    }
}

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $result = Invoke-NativeCapture -FilePath $FilePath -Arguments $Arguments
    if ($result.ExitCode -ne 0) {
        throw "$Label failed (exit=$($result.ExitCode))"
    }
}

function Set-ProcessEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowNull()][string]$Value
    )
    if (-not $originalEnvironment.ContainsKey($Name)) {
        $originalEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
    }
    [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
}

function Get-DisposablePort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return [int]$listener.LocalEndpoint.Port
    }
    finally {
        $listener.Stop()
    }
}

function Wait-DisposablePostgres {
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        $probe = Invoke-NativeCapture -FilePath "docker" -Arguments @(
            "exec", $containerName, "pg_isready", "--username", $dbUser, "--dbname", $database
        )
        if ($probe.ExitCode -eq 0) { return }
        Start-Sleep -Seconds 1
    }
    throw "disposable PostgreSQL did not become ready"
}

function Invoke-Psql {
    param(
        [Parameter(Mandatory = $true)][string]$Sql,
        [string]$Database = $database,
        [string]$Label = "SQL assertion"
    )
    $result = Invoke-NativeCapture -FilePath "docker" -Arguments @(
        "exec", $containerName,
        "psql", "-X", "--set", "ON_ERROR_STOP=1",
        "--username", $dbUser, "--dbname", $Database,
        "--command", $Sql
    )
    if ($result.ExitCode -ne 0) {
        $safeDetail = @($result.Output -split "`r?`n" | Where-Object {
            $_ -match '^(psql:)?\s*ERROR:'
        } | Select-Object -First 1)
        $safeText = if ($safeDetail.Count -eq 1) { [string]$safeDetail[0] } else { "postgres assertion rejected" }
        $safeText = $safeText -replace '(?i)postgresql://\S+', '[redacted-dsn]'
        $safeText = $safeText -replace '(?i)(password|database_url)\s*=\s*\S+', '$1=[redacted]'
        if ($safeText.Length -gt 240) { $safeText = $safeText.Substring(0, 240) }
        throw "$Label failed (exit=$($result.ExitCode); $safeText)"
    }
}

function Assert-PsqlRejected {
    param(
        [Parameter(Mandatory = $true)][string]$Sql,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $result = Invoke-NativeCapture -FilePath "docker" -Arguments @(
        "exec", $containerName,
        "psql", "-X", "--set", "ON_ERROR_STOP=1",
        "--username", $dbUser, "--dbname", $database,
        "--command", $Sql
    )
    if ($result.ExitCode -eq 0) {
        throw "$Label was unexpectedly allowed"
    }
}

function Invoke-MigrationRunner {
    param(
        [Parameter(Mandatory = $true)][string]$ReceiptDirectory,
        [string[]]$AdditionalArguments = @()
    )
    $arguments = @(
        "-B", "-X", "utf8", $migrationScript,
        "--receipt-dir", $ReceiptDirectory
    ) + $AdditionalArguments
    Invoke-NativeChecked -FilePath "python" -Arguments $arguments -Label "canonical migration runner"
}

try {
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    $port = Get-DisposablePort

    $allocationResult = Invoke-NativeCapture -FilePath "python" -Arguments @(
        "-B", "-X", "utf8", $runtimeAllocationScript,
        "--root", $repoRoot,
        "--state-dir", $stateDir,
        "acquire",
        "--change-id", $changeId,
        "--owner", $owner,
        "--mode", "write",
        "--risk-level", "R2",
        "--path", "verification/g1-migration/**",
        "--port", "postgres=$port",
        "--json"
    )
    if ($allocationResult.ExitCode -ne 0) {
        throw "disposable RuntimeAllocation acquire failed (exit=$($allocationResult.ExitCode))"
    }
    $allocation = $allocationResult.Output | ConvertFrom-Json
    $allocationFile = Join-Path $stateDir "allocations.json"
    if (-not (Test-Path -LiteralPath $allocationFile -PathType Leaf)) {
        throw "disposable RuntimeAllocation evidence file is missing"
    }
    if ($allocation.allocation.canonical -ne $false) {
        throw "verification refused a canonical RuntimeAllocation"
    }
    if ([int]$allocation.allocation.ports.postgres -ne $port) {
        throw "RuntimeAllocation port does not match the disposable port"
    }
    $database = [string]$allocation.allocation.database
    if ($database -notmatch '^omni_verify_[a-z0-9_]{1,51}$') {
        throw "verification refused a non-disposable database identity"
    }

    foreach ($property in $allocation.environment.PSObject.Properties) {
        Set-ProcessEnvironment -Name $property.Name -Value ([string]$property.Value)
    }
    Set-ProcessEnvironment -Name "OMNI_RUNTIME_ALLOCATION_FILE" -Value $allocationFile
    Set-ProcessEnvironment -Name "OMNI_DATABASE_DISPOSABLE" -Value "true"
    Set-ProcessEnvironment -Name "OMNI_ALLOW_SHARED_MIGRATION" -Value "false"
    Set-ProcessEnvironment -Name "PYTHONDONTWRITEBYTECODE" -Value "1"

    $dbUser = "omni_g1"
    $randomBytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($randomBytes)
    $dbPassword = ([BitConverter]::ToString($randomBytes)).Replace("-", "").ToLowerInvariant()
    Set-ProcessEnvironment -Name "POSTGRES_USER" -Value $dbUser
    Set-ProcessEnvironment -Name "POSTGRES_PASSWORD" -Value $dbPassword
    Set-ProcessEnvironment -Name "POSTGRES_DB" -Value $database
    $safeUser = [Uri]::EscapeDataString($dbUser)
    $safePassword = [Uri]::EscapeDataString($dbPassword)
    Set-ProcessEnvironment -Name "DATABASE_URL" -Value "postgresql://${safeUser}:${safePassword}@127.0.0.1:$port/$database"

    Invoke-NativeChecked -FilePath "docker" -Arguments @("info", "--format", "{{.ServerVersion}}") -Label "Docker engine check"
    $containerAttempted = $true
    $runResult = Invoke-NativeCapture -FilePath "docker" -Arguments @(
        "run", "--detach",
        "--name", $containerName,
        "--publish", "127.0.0.1:${port}:5432",
        "--mount", "type=volume,destination=/var/lib/postgresql/data",
        "--env", "POSTGRES_USER",
        "--env", "POSTGRES_PASSWORD",
        "--env", "POSTGRES_DB",
        "--health-cmd", "pg_isready -U $dbUser -d $database",
        "--health-interval", "1s",
        "--health-timeout", "5s",
        "--health-retries", "90",
        $image
    )
    if ($runResult.ExitCode -ne 0) {
        throw "disposable PostgreSQL container startup failed (exit=$($runResult.ExitCode))"
    }
    Wait-DisposablePostgres

    $mountResult = Invoke-NativeCapture -FilePath "docker" -Arguments @(
        "inspect", "--format", "{{json .Mounts}}", $containerName
    )
    if ($mountResult.ExitCode -ne 0) {
        throw "anonymous PostgreSQL volume inspection failed"
    }
    try {
        $mounts = @($mountResult.Output | ConvertFrom-Json)
    }
    catch {
        throw "anonymous PostgreSQL volume metadata is invalid"
    }
    $dataMounts = @($mounts | Where-Object {
        $_.Destination -eq "/var/lib/postgresql/data" -and $_.Type -eq "volume"
    })
    if ($dataMounts.Count -ne 1) {
        throw "PostgreSQL data mount is not one anonymous volume"
    }
    $anonymousVolume = [string]$dataMounts[0].Name
    if ($anonymousVolume -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{1,127}$') {
        throw "PostgreSQL data mount is not an anonymous disposable volume"
    }

    $migrationFiles = @(Get-ChildItem -LiteralPath (Join-Path $repoRoot "migrations") -Filter "*.sql" -File | Sort-Object Name)
    if ($migrationFiles.Count -eq 0 -or $migrationFiles[-1].Name -ne "104_workbench_context_and_agent_binding.sql") {
        throw "G1 migration 104 is not the repository head"
    }
    $through103 = @($migrationFiles | Where-Object { [int](($_.Name -split "_", 2)[0]) -le 103 })
    if ($through103.Count -eq 0 -or $through103[-1].Name -notlike "103_*") {
        throw "migration 103 baseline is unavailable"
    }
    $selectors103 = ($through103 | ForEach-Object { $_.Name }) -join ","

    Invoke-NativeChecked -FilePath "python" -Arguments @(
        "-B", "-X", "utf8", $migrationScript, "--dry-run", "--verify"
    ) -Label "repository migration parity"

    $cleanReceipts = Join-Path $tempDir "clean-receipts"
    Invoke-MigrationRunner -ReceiptDirectory $cleanReceipts -AdditionalArguments @("--allocation-aware")

    $ledgerAssertion = @'
DO $verify$
DECLARE
    ledger_count INTEGER;
    ledger_head TEXT;
BEGIN
    SELECT COUNT(*), MAX(filename) INTO ledger_count, ledger_head
    FROM public.schema_migrations;
    IF ledger_count <> __MIGRATION_COUNT__ THEN
        RAISE EXCEPTION 'migration ledger count mismatch';
    END IF;
    IF ledger_head <> '104_workbench_context_and_agent_binding.sql' THEN
        RAISE EXCEPTION 'migration ledger head mismatch';
    END IF;
    IF EXISTS (SELECT 1 FROM public.schema_migrations WHERE checksum IS NULL) THEN
        RAISE EXCEPTION 'migration ledger contains a null checksum';
    END IF;
END
$verify$;
'@.Replace("__MIGRATION_COUNT__", [string]$migrationFiles.Count)
    Invoke-Psql -Sql $ledgerAssertion -Label "clean database head/checksum assertion"

    Invoke-Psql -Database "postgres" -Sql (
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$database' AND pid <> pg_backend_pid()"
    ) -Label "disposable database connection reset"
    Invoke-Psql -Database "postgres" -Sql ("DROP DATABASE `"$database`"") -Label "disposable clean database removal"
    Invoke-Psql -Database "postgres" -Sql ("CREATE DATABASE `"$database`"") -Label "disposable existing database creation"

    $existingReceipts = Join-Path $tempDir "existing-receipts"
    Invoke-MigrationRunner -ReceiptDirectory $existingReceipts -AdditionalArguments @("--only", $selectors103)

    $legacyRows = @'
INSERT INTO mcp.runtime_executions(trace_id, execution_id, session_id)
VALUES ('legacy-trace', 'legacy-execution', 'legacy-session');

INSERT INTO mcp.agent_session_contracts(
    session_id, runner_provider, runner_session_id, project_dir_hash,
    model, effort, status, trace_id
) VALUES (
    'legacy-session', 'codex', 'legacy-runner-session',
    'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'legacy-model', 'medium', 'active', 'legacy-trace'
);

INSERT INTO mcp.approval_operations(
    request_id, requested_by, permission_snapshot_hash, trace_id, handler,
    risk, idempotency_strategy, request_hash, payload_hash,
    redacted_payload, target, state, expires_at
) VALUES (
    'legacy-approval', 'legacy-owner',
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    'legacy-trace', 'legacy.handler', 'R3', 'transactional',
    'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
    'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
    '{}'::jsonb, '{}'::jsonb, 'pending', NOW() + INTERVAL '1 hour'
);
'@
    Invoke-Psql -Sql $legacyRows -Label "legacy fixture insertion"

    Invoke-MigrationRunner -ReceiptDirectory $existingReceipts -AdditionalArguments @(
        "--allocation-aware", "--only", "104_workbench_context_and_agent_binding.sql"
    )

    $legacyAssertion = @'
DO $verify$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM mcp.agent_session_contracts
        WHERE session_id = 'legacy-session'
          AND contract_version IS NULL
          AND context_snapshot_id IS NULL
          AND provider_accepted_at IS NULL
    ) THEN
        RAISE EXCEPTION 'legacy agent session was not preserved';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM mcp.runtime_executions
        WHERE trace_id = 'legacy-trace'
          AND context_snapshot_id IS NULL
          AND idempotency_key_hash IS NULL
    ) THEN
        RAISE EXCEPTION 'legacy runtime execution was not preserved';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM mcp.approval_operations
        WHERE request_id = 'legacy-approval'
          AND context_snapshot_id IS NULL
          AND agent_session_id IS NULL
    ) THEN
        RAISE EXCEPTION 'legacy approval operation was not preserved';
    END IF;
END
$verify$;
'@
    Invoke-Psql -Sql $legacyAssertion -Label "legacy row preservation assertion"
    Invoke-Psql -Sql $ledgerAssertion -Label "existing database head/checksum assertion"

    Invoke-NativeChecked -FilePath "docker" -Arguments @("restart", $containerName) -Label "disposable PostgreSQL restart"
    Wait-DisposablePostgres
    Invoke-MigrationRunner -ReceiptDirectory $existingReceipts -AdditionalArguments @(
        "--allocation-aware", "--rerun", "--only", "104_workbench_context_and_agent_binding.sql"
    )
    Invoke-Psql -Sql $legacyAssertion -Label "post-restart legacy row assertion"
    Invoke-Psql -Sql $ledgerAssertion -Label "post-restart idempotent ledger assertion"

    $legalContexts = @'
INSERT INTO mcp.workbench_context_snapshots(
    snapshot_id, context_ref, revision, workspace_ref, shop_ref, sku_ref,
    project_ref, environment_ref, task_ref, evidence_refs, origin_surface_ref,
    permission_scope_hash, availability, rebind_reason
) VALUES
(
    'context-snapshot-1', 'context-family-1', 1, 'workspace-1', 'shop-1', 'sku-a',
    'project-1', 'environment-1', 'task-1', jsonb_build_array('evidence-1'), 'sku-detail',
    'sha256:1111111111111111111111111111111111111111111111111111111111111111',
    'available', NULL
),
(
    'context-snapshot-2', 'context-family-1', 2, 'workspace-1', 'shop-1', 'sku-b',
    'project-1', 'environment-1', 'task-2', jsonb_build_array('evidence-2'), 'sku-detail',
    'sha256:2222222222222222222222222222222222222222222222222222222222222222',
    'available', 'business_object_changed'
),
(
    'context-snapshot-3', 'context-family-2', 1, 'workspace-1', NULL, NULL,
    NULL, NULL, NULL, '[]'::jsonb, 'run-center',
    'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'available', NULL
);
'@
    Invoke-Psql -Sql $legalContexts -Label "legal workbench.v1 context insertion"

$legalSessions = @'
INSERT INTO mcp.agent_session_contracts(
    session_id, runner_provider, runner_session_id, project_dir_hash, status,
    contract_version, context_snapshot_id, requested_provider,
    resolved_runner_mode, fallback_reason_code, provider_accepted_at,
    parent_session_id, project_handle, project_display_name
) VALUES (
    'session-g1', 'codex', 'runner-session-g1',
    'sha256:3333333333333333333333333333333333333333333333333333333333333333',
    'active', 'workbench.v1', 'context-snapshot-1', 'codex', 'host', NULL,
    NOW(), NULL, 'project-g1', 'Omni G1'
);

INSERT INTO mcp.agent_session_contracts(
    session_id, runner_provider, runner_session_id, project_dir_hash, status,
    contract_version, context_snapshot_id, requested_provider,
    resolved_runner_mode, fallback_reason_code, provider_accepted_at,
    parent_session_id, project_handle, project_display_name
) VALUES (
    'session-g1-alt', 'codex', 'runner-session-g1-alt',
    'sha256:4444444444444444444444444444444444444444444444444444444444444444',
    'active', 'workbench.v1', 'context-snapshot-2', 'codex', 'host', NULL,
    NOW(), NULL, 'project-g1-alt', 'Omni G1 Alt'
);
'@
    Invoke-Psql -Sql $legalSessions -Label "legal workbench.v1 session insertion"

$legalRuntime = @'
INSERT INTO mcp.runtime_executions(
    trace_id, execution_id, session_id, context_snapshot_id, idempotency_key_hash
) VALUES (
    'trace-g1', 'execution-g1', 'session-g1', 'context-snapshot-1',
    'sha256:5555555555555555555555555555555555555555555555555555555555555555'
);
'@
    Invoke-Psql -Sql $legalRuntime -Label "legal workbench.v1 runtime insertion"

$legalApproval = @'
INSERT INTO mcp.approval_operations(
    request_id, requested_by, permission_snapshot_hash, trace_id, handler,
    risk, idempotency_strategy, request_hash, payload_hash,
    redacted_payload, target, state, expires_at,
    context_snapshot_id, agent_session_id
) VALUES (
    'approval-g1', 'owner-g1',
    '6666666666666666666666666666666666666666666666666666666666666666',
    'trace-g1', 'workbench.handler', 'R3', 'transactional',
    '7777777777777777777777777777777777777777777777777777777777777777',
    '8888888888888888888888888888888888888888888888888888888888888888',
    '{}'::jsonb, '{}'::jsonb, 'pending', NOW() + INTERVAL '1 hour',
    'context-snapshot-1', 'session-g1'
);
'@
    Invoke-Psql -Sql $legalApproval -Label "legal workbench.v1 approval insertion"

    Assert-PsqlRejected -Label "immutable context update" -Sql @'
UPDATE mcp.workbench_context_snapshots
SET availability = 'unavailable'
WHERE snapshot_id = 'context-snapshot-1';
'@
    Assert-PsqlRejected -Label "immutable context delete" -Sql @'
DELETE FROM mcp.workbench_context_snapshots
WHERE snapshot_id = 'context-snapshot-3';
'@
    Assert-PsqlRejected -Label "accepted provider rebind" -Sql @'
UPDATE mcp.agent_session_contracts
SET runner_provider = 'claude',
    fallback_reason_code = 'provider_rebind_test'
WHERE session_id = 'session-g1';
'@
    Assert-PsqlRejected -Label "accepted session context rebind" -Sql @'
UPDATE mcp.agent_session_contracts
SET context_snapshot_id = 'context-snapshot-2'
WHERE session_id = 'session-g1';
'@
    Assert-PsqlRejected -Label "agent session self-parent check" -Sql @'
INSERT INTO mcp.agent_session_contracts(
    session_id, runner_provider, project_dir_hash, status, contract_version,
    context_snapshot_id, requested_provider, resolved_runner_mode,
    fallback_reason_code, provider_accepted_at, parent_session_id,
    project_handle, project_display_name
) VALUES (
    'session-self-parent', 'codex',
    'sha256:9999999999999999999999999999999999999999999999999999999999999999',
    'resolving', 'workbench.v1', 'context-snapshot-1', 'codex', NULL,
    NULL, NULL, 'session-self-parent', 'project-self', 'Omni Self'
);
'@
    Assert-PsqlRejected -Label "runtime context rebind" -Sql @'
UPDATE mcp.runtime_executions
SET context_snapshot_id = 'context-snapshot-2'
WHERE trace_id = 'trace-g1';
'@
    Assert-PsqlRejected -Label "runtime idempotency rebind" -Sql @'
UPDATE mcp.runtime_executions
SET idempotency_key_hash = 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
WHERE trace_id = 'trace-g1';
'@
    Assert-PsqlRejected -Label "approval context rebind" -Sql @'
UPDATE mcp.approval_operations
SET context_snapshot_id = 'context-snapshot-2'
WHERE request_id = 'approval-g1';
'@
    Assert-PsqlRejected -Label "approval agent session rebind" -Sql @'
UPDATE mcp.approval_operations
SET agent_session_id = 'session-g1-alt'
WHERE request_id = 'approval-g1';
'@
    Assert-PsqlRejected -Label "raw project context ref" -Sql @'
INSERT INTO mcp.workbench_context_snapshots(
    snapshot_id, context_ref, revision, workspace_ref, shop_ref, sku_ref,
    project_ref, environment_ref, task_ref, evidence_refs, origin_surface_ref,
    permission_scope_hash, availability, rebind_reason
) VALUES (
    'context-raw-project', 'context-raw-project', 1, 'workspace-1', NULL, NULL,
    'project:C:/Users/owner/omni', NULL, NULL, '[]'::jsonb, 'assistant',
    'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    'available', NULL
);
'@
    Assert-PsqlRejected -Label "raw evidence context ref" -Sql @'
INSERT INTO mcp.workbench_context_snapshots(
    snapshot_id, context_ref, revision, workspace_ref, shop_ref, sku_ref,
    project_ref, environment_ref, task_ref, evidence_refs, origin_surface_ref,
    permission_scope_hash, availability, rebind_reason
) VALUES (
    'context-raw-evidence', 'context-raw-evidence', 1, 'workspace-1', NULL, NULL,
    NULL, NULL, NULL, jsonb_build_array('evidence:file:///tmp'), 'assistant',
    'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
    'available', NULL
);
'@
    Assert-PsqlRejected -Label "duplicate evidence refs" -Sql @'
INSERT INTO mcp.workbench_context_snapshots(
    snapshot_id, context_ref, revision, workspace_ref, shop_ref, sku_ref,
    project_ref, environment_ref, task_ref, evidence_refs, origin_surface_ref,
    permission_scope_hash, availability, rebind_reason
) VALUES (
    'context-duplicate-evidence', 'context-duplicate-evidence', 1, 'workspace-1',
    NULL, NULL, NULL, NULL, NULL,
    jsonb_build_array('evidence-duplicate', 'evidence-duplicate'), 'assistant',
    'sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
    'available', NULL
);
'@
    Assert-PsqlRejected -Label "invalid rebind reason code" -Sql @'
INSERT INTO mcp.workbench_context_snapshots(
    snapshot_id, context_ref, revision, workspace_ref, shop_ref, sku_ref,
    project_ref, environment_ref, task_ref, evidence_refs, origin_surface_ref,
    permission_scope_hash, availability, rebind_reason
) VALUES (
    'context-invalid-rebind', 'context-invalid-rebind', 1, 'workspace-1',
    NULL, NULL, NULL, NULL, NULL, '[]'::jsonb, 'assistant',
    'sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
    'available', 'Bad reason/too free'
);
'@
    Assert-PsqlRejected -Label "unsafe project display whitespace" -Sql @'
INSERT INTO mcp.agent_session_contracts(
    session_id, runner_provider, project_dir_hash, status, contract_version,
    context_snapshot_id, requested_provider, resolved_runner_mode,
    fallback_reason_code, provider_accepted_at, parent_session_id,
    project_handle, project_display_name
) VALUES (
    'session-tab-display', 'codex',
    'sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff',
    'resolving', 'workbench.v1', 'context-snapshot-1', 'codex', NULL,
    NULL, NULL, NULL, 'project-tab-display', E'\tOmni\t'
);
'@
    Assert-PsqlRejected -Label "active provider without runner session" -Sql @'
INSERT INTO mcp.agent_session_contracts(
    session_id, runner_provider, runner_session_id, project_dir_hash, status,
    contract_version, context_snapshot_id, requested_provider,
    resolved_runner_mode, fallback_reason_code, provider_accepted_at,
    parent_session_id, project_handle, project_display_name
) VALUES (
    'session-missing-runner', 'codex', NULL,
    'sha256:abababababababababababababababababababababababababababababababab',
    'active', 'workbench.v1', 'context-snapshot-1', 'codex', 'host', NULL,
    NOW(), NULL, 'project-missing-runner', 'Omni Missing Runner'
);
'@

    $immutabilityAssertion = @'
DO $verify$
BEGIN
    IF (SELECT COUNT(*) FROM mcp.workbench_context_snapshots) <> 3 THEN
        RAISE EXCEPTION 'immutable context rows changed';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM mcp.agent_session_contracts
        WHERE session_id = 'session-g1'
          AND runner_provider = 'codex'
          AND context_snapshot_id = 'context-snapshot-1'
    ) THEN
        RAISE EXCEPTION 'accepted agent session binding changed';
    END IF;
    IF EXISTS (
        SELECT 1 FROM mcp.agent_session_contracts
        WHERE session_id = 'session-self-parent'
    ) THEN
        RAISE EXCEPTION 'self-parent agent session was inserted';
    END IF;
    IF EXISTS (
        SELECT 1 FROM mcp.agent_session_contracts
        WHERE session_id = 'session-tab-display'
    ) THEN
        RAISE EXCEPTION 'unsafe project display name was inserted';
    END IF;
    IF EXISTS (
        SELECT 1 FROM mcp.agent_session_contracts
        WHERE session_id = 'session-missing-runner'
    ) THEN
        RAISE EXCEPTION 'active session without runner identity was inserted';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM mcp.runtime_executions
        WHERE trace_id = 'trace-g1'
          AND context_snapshot_id = 'context-snapshot-1'
          AND idempotency_key_hash = 'sha256:5555555555555555555555555555555555555555555555555555555555555555'
    ) THEN
        RAISE EXCEPTION 'runtime binding changed';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM mcp.approval_operations
        WHERE request_id = 'approval-g1'
          AND context_snapshot_id = 'context-snapshot-1'
          AND agent_session_id = 'session-g1'
    ) THEN
        RAISE EXCEPTION 'approval binding changed';
    END IF;
END
$verify$;
'@
    Invoke-Psql -Sql $immutabilityAssertion -Label "final immutable binding assertion"
    Invoke-Psql -Sql $legacyAssertion -Label "final legacy row assertion"
    Invoke-Psql -Sql $ledgerAssertion -Label "final migration ledger assertion"

    $success = $true
    $summary = "WORKBENCH_G1_MIGRATION_VERIFIED image=$image clean_head=104 legacy_rows=3 immutable_checks=9 contract_rejections=6 restart_idempotent=true"
}
finally {
    if ($containerAttempted) {
        $containerInspection = Invoke-NativeCapture -FilePath "docker" -Arguments @("container", "inspect", $containerName)
        if ($containerInspection.ExitCode -eq 0) {
            $containerRemoval = Invoke-NativeCapture -FilePath "docker" -Arguments @(
                "container", "rm", "--force", "--volumes", $containerName
            )
            if ($containerRemoval.ExitCode -ne 0) {
                $cleanupFailures.Add("container")
            }
        }
    }
    if ($anonymousVolume) {
        $volumeInspection = Invoke-NativeCapture -FilePath "docker" -Arguments @("volume", "inspect", $anonymousVolume)
        if ($volumeInspection.ExitCode -eq 0) {
            $volumeRemoval = Invoke-NativeCapture -FilePath "docker" -Arguments @(
                "volume", "rm", "--force", $anonymousVolume
            )
            if ($volumeRemoval.ExitCode -ne 0) {
                $cleanupFailures.Add("anonymous-volume")
            }
        }
    }
    if ($allocation) {
        $releaseResult = Invoke-NativeCapture -FilePath "python" -Arguments @(
            "-B", "-X", "utf8", $runtimeAllocationScript,
            "--root", $repoRoot,
            "--state-dir", $stateDir,
            "release",
            "--allocation-id", ([string]$allocation.allocation.allocation_id),
            "--owner", $owner,
            "--expected-revision", ([string]$allocation.allocation.revision),
            "--json"
        )
        if ($releaseResult.ExitCode -ne 0) {
            $cleanupFailures.Add("runtime-allocation")
        }
    }
    foreach ($entry in $originalEnvironment.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable([string]$entry.Key, $entry.Value, "Process")
    }
    if (Test-Path -LiteralPath $tempDir) {
        try {
            $resolvedTempDir = [IO.Path]::GetFullPath($tempDir)
            if (-not $resolvedTempDir.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
                throw "temporary cleanup target escaped the system temp root"
            }
            Remove-Item -LiteralPath $resolvedTempDir -Recurse -Force
        }
        catch {
            $cleanupFailures.Add("temporary-directory")
        }
    }
    if ($success -and $cleanupFailures.Count -gt 0) {
        throw "disposable verification cleanup failed: $($cleanupFailures -join ',')"
    }
}

Write-Output $summary
