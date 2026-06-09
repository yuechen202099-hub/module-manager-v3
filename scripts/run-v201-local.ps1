param(
    [int]$Port = 8000,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install -r .\v2-api\requirements-dev.txt

$env:PYTHONPATH = Join-Path $root "v2-api"
Start-Process -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port", "--reload" `
    -WorkingDirectory (Join-Path $root "v2-api") `
    -WindowStyle Hidden

$url = "http://127.0.0.1:$Port/v201"
$healthUrl = "http://127.0.0.1:$Port/health"

for ($i = 0; $i -lt 30; $i++) {
    try {
        Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 1 | Out-Null
        break
    }
    catch {
        Start-Sleep -Milliseconds 500
    }
}

Write-Host "V2.1 local workbench: $url"

if (-not $NoOpen) {
    Start-Process $url
}
