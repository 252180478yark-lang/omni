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
    Write-Host "[PASS] $Name" -ForegroundColor Green
  } else {
    Write-Host "[FAIL] $Name -> $ErrorMessage" -ForegroundColor Red
  }

  return [PSCustomObject]@{
    Name = $Name
    Ok = $Ok
    Error = $ErrorMessage
  }
}

function Invoke-Json {
  param(
    [string]$Method,
    [string]$Uri,
    [string]$Body = "",
    [hashtable]$Headers = $null
  )

  $params = @{
    Method = $Method
    Uri = $Uri
  }

  if ($Body -ne "") {
    $params.ContentType = "application/json"
    $params.Body = $Body
  }

  if ($Headers -ne $null) {
    $params.Headers = $Headers
  }

  return Invoke-RestMethod @params
}

function Ensure-Services {
  param([switch]$StartServices)

  $infraFile = "services/infra-core/docker-compose.infra.yml"
  $spFile = "services/docker-compose.sp1-sp4.yml"

  if ($StartServices) {
    docker network inspect omni-network > $null 2>&1
    if ($LASTEXITCODE -ne 0) {
      docker network create omni-network > $null
      Write-Host "[PASS] Created docker network omni-network" -ForegroundColor Green
    } else {
      Write-Host "[PASS] Docker network omni-network already exists" -ForegroundColor Green
    }

    docker compose -f $infraFile up -d | Out-Null
    Write-Host "[PASS] Infra services started" -ForegroundColor Green

    docker compose -f $spFile up -d --build | Out-Null
    Write-Host "[PASS] SP1-SP4 services started" -ForegroundColor Green
  }

  docker compose -f $spFile ps
}

$results = @()
$accessToken = $null
$kbId = $null

Write-Host "SP1-SP4 verification started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Yellow

Write-Section "Docker Services"
try {
  Ensure-Services -StartServices:$AutoStart
  $results += Record-Step -Name "Compose services visible" -Ok $true
} catch {
  $results += Record-Step -Name "Compose services visible" -Ok $false -ErrorMessage $_.Exception.Message
}

Write-Section "Health Checks"
try {
  $res = Invoke-Json -Method "Get" -Uri "http://localhost:8000/health"
  if ($res.status -ne "healthy") { throw "status != healthy" }
  $results += Record-Step -Name "identity-service /health (8000)" -Ok $true
} catch {
  $results += Record-Step -Name "identity-service /health (8000)" -Ok $false -ErrorMessage $_.Exception.Message
}

try {
  $res = Invoke-Json -Method "Get" -Uri "http://localhost:8001/health"
  if ($res.status -ne "healthy") { throw "status != healthy" }
  $results += Record-Step -Name "ai-provider-hub /health (8001)" -Ok $true
} catch {
  $results += Record-Step -Name "ai-provider-hub /health (8001)" -Ok $false -ErrorMessage $_.Exception.Message
}

try {
  $res = Invoke-Json -Method "Get" -Uri "http://localhost:8002/health"
  if ($res.status -ne "healthy") { throw "status != healthy" }
  $results += Record-Step -Name "knowledge-engine /health (8002)" -Ok $true
} catch {
  $results += Record-Step -Name "knowledge-engine /health (8002)" -Ok $false -ErrorMessage $_.Exception.Message
}

Write-Section "SP2 Auth Flow"
$email = "test+$(Get-Random)@example.com"
$password = "Test1234!"
$registerBody = @{ email = $email; password = $password; display_name = "Verifier User" } | ConvertTo-Json -Compress
$loginBody = @{ email = $email; password = $password } | ConvertTo-Json -Compress

try {
  $registerRes = Invoke-Json -Method "Post" -Uri "http://localhost:8000/api/v1/auth/register" -Body $registerBody
  if (-not $registerRes.data.email) { throw "missing user email in response" }
  $results += Record-Step -Name "POST /api/v1/auth/register" -Ok $true
} catch {
  $results += Record-Step -Name "POST /api/v1/auth/register" -Ok $false -ErrorMessage $_.Exception.Message
}

try {
  $loginRes = Invoke-Json -Method "Post" -Uri "http://localhost:8000/api/v1/auth/login" -Body $loginBody
  $accessToken = $loginRes.data.access_token
  if (-not $accessToken) { throw "missing access_token" }
  $results += Record-Step -Name "POST /api/v1/auth/login" -Ok $true
} catch {
  $results += Record-Step -Name "POST /api/v1/auth/login" -Ok $false -ErrorMessage $_.Exception.Message
}

try {
  if (-not $accessToken) { throw "token not ready" }
  $meRes = Invoke-Json -Method "Get" -Uri "http://localhost:8000/api/v1/auth/me" -Headers @{ Authorization = "Bearer $accessToken" }
  if ($meRes.data.email -ne $email) { throw "returned email mismatch" }
  $results += Record-Step -Name "GET /api/v1/auth/me" -Ok $true
} catch {
  $results += Record-Step -Name "GET /api/v1/auth/me" -Ok $false -ErrorMessage $_.Exception.Message
}

Write-Section "SP3 AI Flow"
$chatBody = @{ messages = @(@{ role = "user"; content = "hello" }); provider = "openai" } | ConvertTo-Json -Compress -Depth 5
$embeddingBody = @{ texts = @("hello world"); provider = "openai" } | ConvertTo-Json -Compress

try {
  $chatRes = Invoke-Json -Method "Post" -Uri "http://localhost:8001/api/v1/ai/chat" -Body $chatBody
  if (-not $chatRes.content) { throw "chat response empty" }
  $results += Record-Step -Name "POST /api/v1/ai/chat" -Ok $true
} catch {
  $results += Record-Step -Name "POST /api/v1/ai/chat" -Ok $false -ErrorMessage $_.Exception.Message
}

try {
  $embedRes = Invoke-Json -Method "Post" -Uri "http://localhost:8001/api/v1/ai/embedding" -Body $embeddingBody
  if (-not $embedRes.embeddings -or $embedRes.embeddings.Count -lt 1) { throw "embedding result empty" }
  $results += Record-Step -Name "POST /api/v1/ai/embedding" -Ok $true
} catch {
  $results += Record-Step -Name "POST /api/v1/ai/embedding" -Ok $false -ErrorMessage $_.Exception.Message
}

Write-Section "SP4 Knowledge Flow"
$kbBody = @{ name = "verify-kb-$(Get-Random)"; description = "SP1-SP4 verification kb" } | ConvertTo-Json -Compress

try {
  $kbRes = Invoke-Json -Method "Post" -Uri "http://localhost:8002/api/v1/knowledge/bases" -Body $kbBody
  $kbId = $kbRes.data.id
  if (-not $kbId) { throw "missing kb_id" }
  $results += Record-Step -Name "POST /api/v1/knowledge/bases" -Ok $true
} catch {
  $results += Record-Step -Name "POST /api/v1/knowledge/bases" -Ok $false -ErrorMessage $_.Exception.Message
}

try {
  if (-not $kbId) { throw "kb_id not ready" }
  $ingestBody = @{
    kb_id = $kbId
    title = "Verification Doc"
    text = "Omni-Vibe OS is an e-commerce operating system."
  } | ConvertTo-Json -Compress
  $ingestRes = Invoke-Json -Method "Post" -Uri "http://localhost:8002/api/v1/knowledge/ingest" -Body $ingestBody
  if ($ingestRes.code -ne 202) { throw "expected 202 accepted" }
  if (-not $ingestRes.data.task_id) { throw "missing task_id" }
  $results += Record-Step -Name "POST /api/v1/knowledge/ingest" -Ok $true
} catch {
  $results += Record-Step -Name "POST /api/v1/knowledge/ingest" -Ok $false -ErrorMessage $_.Exception.Message
}

try {
  if (-not $kbId) { throw "kb_id not ready" }
  $queryBody = @{ kb_id = $kbId; query = "What is Omni-Vibe OS?"; top_k = 5 } | ConvertTo-Json -Compress
  $queryRes = Invoke-Json -Method "Post" -Uri "http://localhost:8002/api/v1/knowledge/query" -Body $queryBody
  if (-not $queryRes.data -or $queryRes.data.Count -lt 1) { throw "query returned no data" }
  $results += Record-Step -Name "POST /api/v1/knowledge/query" -Ok $true
} catch {
  $results += Record-Step -Name "POST /api/v1/knowledge/query" -Ok $false -ErrorMessage $_.Exception.Message
}

Write-Section "Summary"
$total = $results.Count
$passed = ($results | Where-Object { $_.Ok -eq $true }).Count
$failed = $total - $passed

Write-Host "Total : $total"
Write-Host "Passed: $passed" -ForegroundColor Green
Write-Host "Failed: $failed" -ForegroundColor Red

if ($failed -gt 0) {
  Write-Host ""
  Write-Host "Verification failed. Please check FAIL items." -ForegroundColor Red
  exit 1
}

Write-Host ""
Write-Host "SP1-SP4 verification passed." -ForegroundColor Green
exit 0
