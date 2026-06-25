param(
    [string]$Version = "final-delivery-ready",
    [int]$Port = 8000,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )
    Write-Host ""
    Write-Host "==> $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Name"
    }
}

function Clear-SmokeUploads {
    $uploadDir = Join-Path $root "v2-api\app\static\uploads\manual"
    if (-not (Test-Path $uploadDir)) {
        return 0
    }
    $resolvedUploadDir = [System.IO.Path]::GetFullPath($uploadDir)
    $staticDir = [System.IO.Path]::GetFullPath((Join-Path $root "v2-api\app\static"))
    if (-not $resolvedUploadDir.StartsWith($staticDir, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean uploads outside static dir: $resolvedUploadDir"
    }
    Get-ChildItem -Path $uploadDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "g-05103-*" -or $_.Length -le 20 } |
        Remove-Item -Force
    return (Get-ChildItem -Path $uploadDir -File -ErrorAction SilentlyContinue | Measure-Object).Count
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    python -m venv .venv
}

Invoke-Step "Install Python dependencies" {
    .\.venv\Scripts\python.exe -m pip install -r .\v2-api\requirements-dev.txt | Out-Null
}

Invoke-Step "Run backend and workflow tests" {
    .\.venv\Scripts\python.exe -m pytest -q
}

Invoke-Step "Verify strict Vue production pages" {
    .\.venv\Scripts\python.exe .\scripts\verify_vue_migration_gate.py --strict-native
}

Invoke-Step "Audit PostgreSQL cutover status" {
    .\.venv\Scripts\python.exe .\scripts\verify_postgres_cutover_gate.py
}

Invoke-Step "Verify deployment readiness samples" {
    .\.venv\Scripts\python.exe .\scripts\verify-production-readiness.py --example
}

Invoke-Step "Run client demo smoke" {
    powershell -ExecutionPolicy Bypass -File .\scripts\run-client-demo.ps1 -Port $Port -NoOpen
}

if (-not $NoBuild) {
    Invoke-Step "Build client release package" {
        powershell -ExecutionPolicy Bypass -File .\scripts\build-client-release.ps1 -Version $Version
    }

    $zipPath = Join-Path $root "build\client-release\module-manager-v2-client-demo-$Version.zip"
    Invoke-Step "Verify release package" {
        .\.venv\Scripts\python.exe .\scripts\verify-client-release.py $zipPath
    }
}

$remainingUploads = Clear-SmokeUploads

Write-Host ""
Write-Host "Client acceptance gate passed."
Write-Host "  Port: $Port"
Write-Host "  Version: $Version"
Write-Host "  Remaining manual upload files: $remainingUploads"
if (-not $NoBuild) {
    Write-Host "  Release zip: build\client-release\module-manager-v2-client-demo-$Version.zip"
}
