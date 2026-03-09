param(
  [Parameter(Mandatory = $true)]
  [string]$Target,
  [int]$Timeout = 30,
  [switch]$Strict,
  [string]$CommandToRun = ""
)

function Test-PortOpen {
  param(
    [string]$HostName,
    [int]$Port
  )

  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $iar = $client.BeginConnect($HostName, $Port, $null, $null)
    $ok = $iar.AsyncWaitHandle.WaitOne(800)
    if (-not $ok) {
      $client.Close()
      return $false
    }
    $client.EndConnect($iar)
    $client.Close()
    return $true
  } catch {
    return $false
  }
}

$parts = $Target.Split(":")
if ($parts.Length -ne 2) {
  Write-Error "Target format must be host:port"
  exit 1
}

$hostName = $parts[0]
[int]$port = $parts[1]

$start = Get-Date
Write-Host "[wait-for-it] waiting for $hostName`:$port, timeout=${Timeout}s"

while ($true) {
  if (Test-PortOpen -HostName $hostName -Port $port) {
    Write-Host "[wait-for-it] $hostName`:$port is available"
    if ($CommandToRun -ne "") {
      Invoke-Expression $CommandToRun
      exit $LASTEXITCODE
    }
    exit 0
  }

  $elapsed = ((Get-Date) - $start).TotalSeconds
  if ($elapsed -ge $Timeout) {
    Write-Host "[wait-for-it] timeout after ${Timeout}s for $hostName`:$port"
    if ($Strict) {
      exit 1
    }
    if ($CommandToRun -ne "") {
      Invoke-Expression $CommandToRun
      exit $LASTEXITCODE
    }
    exit 0
  }

  Start-Sleep -Seconds 1
}
