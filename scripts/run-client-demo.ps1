param(
    [int]$Port = 8000,
    [switch]$NoOpen,
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    python -m venv .venv
}

Write-Host "Checking Python dependencies..."
& .\.venv\Scripts\python.exe -m pip install -r .\v2-api\requirements-dev.txt | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

$env:PYTHONPATH = Join-Path $root "v2-api"
$baseUrl = "http://127.0.0.1:$Port"
$healthUrl = "$baseUrl/health"
$loginUrl = "$baseUrl/login"

$healthy = $false
try {
    Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 1 | Out-Null
    $healthy = $true
}
catch {
    $healthy = $false
}

if (-not $healthy) {
    Write-Host "Starting local FastAPI server on port $Port..."
    Start-Process -FilePath ".\.venv\Scripts\python.exe" `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port" `
        -WorkingDirectory (Join-Path $root "v2-api") `
        -WindowStyle Hidden
} else {
    Write-Host "Local FastAPI server is already running on port $Port."
}

for ($i = 0; $i -lt 40; $i++) {
    try {
        Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 1 | Out-Null
        $healthy = $true
        break
    }
    catch {
        Start-Sleep -Milliseconds 500
    }
}

if (-not $healthy) {
    throw "Client demo server did not become healthy at $healthUrl"
}

Write-Host "Ensuring visible demo review photos..."
.\.venv\Scripts\python.exe .\scripts\seed-client-demo-data.py --base-url $baseUrl

if (-not $SkipSmoke) {
    Write-Host "Running client demo smoke check..."
    .\.venv\Scripts\python.exe .\scripts\smoke-client-demo.py
}

Write-Host ""
Write-Host "Client demo is ready:"
Write-Host "  Login:        $loginUrl"
Write-Host "  Admin board:  $baseUrl/project-board"
Write-Host "  Review desk:  $baseUrl/task-hall"
Write-Host "  Claim tasks:  $baseUrl/claim-tasks"
Write-Host "  Sync status:  $baseUrl/sync-config"
Write-Host ""
Write-Host "Demo accounts:"
Write-Host "  Admin:    admin / admin123"
Write-Host "  Reviewer: reviewer / review123"

if (-not $NoOpen) {
    Start-Process $loginUrl
}
