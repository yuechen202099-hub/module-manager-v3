param(
    [string]$Version = "",
    [int]$Port = 8000,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$versionArtifactPath = Join-Path $root "v2-web\src\version.json"
if (-not (Test-Path -LiteralPath $versionArtifactPath -PathType Leaf)) {
    throw "Machine version source is missing: $versionArtifactPath"
}
try {
    $versionArtifact = Get-Content -LiteralPath $versionArtifactPath -Raw -Encoding UTF8 | ConvertFrom-Json
}
catch {
    throw "Machine version source is not valid JSON: $versionArtifactPath"
}
$machineVersion = [string]$versionArtifact.version
if ($machineVersion -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') {
    throw "Machine version source must contain one semantic version."
}
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = $machineVersion
}
elseif ($Version -ne $machineVersion) {
    throw "Release Version '$Version' must match the machine version source '$machineVersion'."
}

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

Invoke-Step "Verify administrator release notes" {
    node .\scripts\verify_admin_release_notes.js
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

Invoke-Step "Verify task claim completion state" {
    node .\scripts\verify_claim_tasks_completion_status.js
}

$sourceCommit = (& git rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $sourceCommit -notmatch '^[0-9a-f]{40}$') {
    throw "Unable to resolve the full Git source commit for release acceptance."
}

$performanceOutput = Join-Path $root "build\release-evidence\v$Version-task-review.json"
Invoke-Step "Verify task and review performance" {
    .\.venv\Scripts\python.exe .\v2-api\scripts\verify_task_review_performance.py `
        --base-url "http://127.0.0.1:$Port" `
        --output $performanceOutput `
        --source-commit $sourceCommit
}

Invoke-Step "Verify V3.1 release candidate" {
    .\.venv\Scripts\python.exe .\v2-api\scripts\verify_v3_1_release.py `
        --repo-root $root `
        --performance-report $performanceOutput `
        --expected-source-commit $sourceCommit
}

if (-not $NoBuild) {
    Invoke-Step "Build client release package" {
        powershell -ExecutionPolicy Bypass -File .\scripts\build-client-release.ps1 -Version $Version -PerformanceReport $performanceOutput
    }

    $zipPath = Join-Path $root "build\server-release\module-manager-v2-server-$Version.zip"
    Invoke-Step "Verify release package" {
        .\.venv\Scripts\python.exe .\scripts\verify-client-release.py $zipPath --expected-source-commit $sourceCommit
    }
}

$remainingUploads = Clear-SmokeUploads

Write-Host ""
Write-Host "Client acceptance gate passed."
Write-Host "  Port: $Port"
Write-Host "  Version: $Version"
Write-Host "  Remaining manual upload files: $remainingUploads"
if (-not $NoBuild) {
    Write-Host "  Release zip: build\server-release\module-manager-v2-server-$Version.zip"
}
