param(
    [string]$Version = "3.1.0",
    [string]$PerformanceReport = "",
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"

if ($Version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') {
    throw "Release Version must be a semantic version such as 3.0.84."
}

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$sourceCommit = (& git rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $sourceCommit -notmatch '^[0-9a-f]{40}$') {
    throw "Unable to resolve the full Git source commit for this release."
}
$worktreeChanges = @(git status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify Git worktree state before packaging."
}
if ($worktreeChanges.Count -ne 0) {
    throw "Refusing to package a dirty Git worktree. Commit or remove every source change first."
}
if ([string]::IsNullOrWhiteSpace($PerformanceReport)) {
    throw "Performance report is required for V3.1.0 packaging."
}
$performanceReportPath = if ([System.IO.Path]::IsPathRooted($PerformanceReport)) {
    [System.IO.Path]::GetFullPath($PerformanceReport)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $root $PerformanceReport))
}
if (-not (Test-Path -LiteralPath $performanceReportPath -PathType Leaf)) {
    throw "Performance report is missing: $performanceReportPath"
}

$releaseRoot = Join-Path $root "build\server-release"
$packageName = "module-manager-v2-server-$Version"
$staging = Join-Path $releaseRoot $packageName
$zipPath = Join-Path $releaseRoot "$packageName.zip"

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null

$resolvedReleaseRoot = [System.IO.Path]::GetFullPath($releaseRoot)
$resolvedStaging = [System.IO.Path]::GetFullPath($staging)
if (-not $resolvedStaging.StartsWith($resolvedReleaseRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to clean staging path outside release root: $resolvedStaging"
}

if (Test-Path $staging) {
    Remove-Item -Recurse -Force -LiteralPath $staging
}
if (Test-Path $zipPath) {
    Remove-Item -Force -LiteralPath $zipPath
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    python -m venv .venv
}

Write-Host "Verifying administrator release notes..."
node .\scripts\verify_admin_release_notes.js
if ($LASTEXITCODE -ne 0) {
    throw "Administrator release notes verification failed."
}

Write-Host "Checking Python dependencies..."
& .\.venv\Scripts\python.exe -m pip install -r .\v2-api\requirements-dev.txt | Out-Null
if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
}

Write-Host "Verifying source-bound V3.1 performance evidence..."
& .\.venv\Scripts\python.exe .\v2-api\scripts\verify_v3_1_release.py `
    --repo-root $root `
    --performance-report $performanceReportPath `
    --expected-source-commit $sourceCommit
if ($LASTEXITCODE -ne 0) {
    throw "V3.1 release verification failed."
}

if (-not $SkipSmoke) {
    Write-Host "Running release smoke check before packaging..."
    .\.venv\Scripts\python.exe .\scripts\smoke-client-demo.py
    if ($LASTEXITCODE -ne 0) {
        throw "Release smoke check failed."
    }
}

New-Item -ItemType Directory -Force -Path $staging | Out-Null

$sourceCommitPath = Join-Path $staging "SOURCE_COMMIT"
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($sourceCommitPath, $sourceCommit + [Environment]::NewLine, $utf8NoBom)

function Copy-ReleaseItem {
    param(
        [string]$Source,
        [string]$Destination
    )
    $target = Join-Path $staging $Destination
    $parent = Split-Path -Parent $target
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Copy-Item -Recurse -Force -LiteralPath (Join-Path $root $Source) -Destination $target
}

Copy-ReleaseItem "README.md" "README.md"
Copy-ReleaseItem "AGENTS.md" "AGENTS.md"
Copy-ReleaseItem ".gitattributes" ".gitattributes"
Copy-ReleaseItem ".env.example" ".env.example"
Copy-ReleaseItem "docker-compose.yml" "docker-compose.yml"

Copy-ReleaseItem "docs\CLIENT_ACCEPTANCE_REPORT.md" "docs\CLIENT_ACCEPTANCE_REPORT.md"
Copy-ReleaseItem "docs\CLIENT_FINAL_AUDIT.md" "docs\CLIENT_FINAL_AUDIT.md"
Copy-ReleaseItem "docs\CLIENT_DEMO_READINESS.md" "docs\CLIENT_DEMO_READINESS.md"
Copy-ReleaseItem "docs\CLIENT_DEMO_SCRIPT.md" "docs\CLIENT_DEMO_SCRIPT.md"
Copy-ReleaseItem "docs\CLIENT_SIGNOFF_CHECKLIST.md" "docs\CLIENT_SIGNOFF_CHECKLIST.md"
Copy-ReleaseItem "docs\CLIENT_VISUAL_QA.md" "docs\CLIENT_VISUAL_QA.md"
Copy-ReleaseItem "docs\SERVER_DEPLOYMENT_PREP.md" "docs\SERVER_DEPLOYMENT_PREP.md"
Copy-ReleaseItem "docs\PROJECT_DECISIONS.md" "docs\PROJECT_DECISIONS.md"
Copy-ReleaseItem "docs\STATIC_TO_VUE_MIGRATION.md" "docs\STATIC_TO_VUE_MIGRATION.md"
Copy-ReleaseItem "docs\database\postgresql-schema.md" "docs\database\postgresql-schema.md"
Copy-ReleaseItem "docs\sop" "docs\sop"
Copy-ReleaseItem "ops" "ops"

Copy-ReleaseItem "infra" "infra"
Copy-ReleaseItem "scripts\build-client-release.ps1" "scripts\build-client-release.ps1"
Copy-ReleaseItem "scripts\run-client-acceptance-gate.ps1" "scripts\run-client-acceptance-gate.ps1"
Copy-ReleaseItem "scripts\run-client-demo.ps1" "scripts\run-client-demo.ps1"
Copy-ReleaseItem "scripts\smoke-client-demo.py" "scripts\smoke-client-demo.py"
Copy-ReleaseItem "scripts\seed-client-demo-data.py" "scripts\seed-client-demo-data.py"
Copy-ReleaseItem "scripts\verify_vue_migration_gate.py" "scripts\verify_vue_migration_gate.py"
Copy-ReleaseItem "scripts\verify_postgres_cutover_gate.py" "scripts\verify_postgres_cutover_gate.py"
Copy-ReleaseItem "scripts\verify-production-readiness.py" "scripts\verify-production-readiness.py"
Copy-ReleaseItem "scripts\verify-client-release.py" "scripts\verify-client-release.py"
Copy-ReleaseItem "scripts\verify_admin_release_notes.js" "scripts\verify_admin_release_notes.js"
Copy-ReleaseItem "scripts\audit_production_security.py" "scripts\audit_production_security.py"
Copy-ReleaseItem "scripts\verify_security_hardening.py" "scripts\verify_security_hardening.py"
Copy-ReleaseItem "scripts\verify_frontend_auth_expiry.js" "scripts\verify_frontend_auth_expiry.js"
Copy-ReleaseItem "scripts\verify_claim_tasks_completion_status.js" "scripts\verify_claim_tasks_completion_status.js"
Copy-ReleaseItem "scripts\verify_claim_tasks_construction_priority.js" "scripts\verify_claim_tasks_construction_priority.js"
Copy-ReleaseItem "scripts\verify_construction_one_click_upload.js" "scripts\verify_construction_one_click_upload.js"
Copy-ReleaseItem "scripts\verify_construction_draft_photo_cache.js" "scripts\verify_construction_draft_photo_cache.js"
Copy-ReleaseItem "scripts\verify_construction_priority_import_dialog.js" "scripts\verify_construction_priority_import_dialog.js"
Copy-ReleaseItem "scripts\verify_installer_workload_completion_visibility.js" "scripts\verify_installer_workload_completion_visibility.js"
Copy-ReleaseItem "scripts\verify_release_sop.py" "scripts\verify_release_sop.py"
Copy-ReleaseItem "scripts\verify_release_retention_policy.py" "scripts\verify_release_retention_policy.py"
Copy-ReleaseItem "scripts\verify_project_board_photo_dialog.js" "scripts\verify_project_board_photo_dialog.js"
Copy-ReleaseItem "scripts\verify_project_board_data_center_photos.js" "scripts\verify_project_board_data_center_photos.js"
Copy-ReleaseItem "scripts\verify_project_board_unmatched_review.js" "scripts\verify_project_board_unmatched_review.js"
Copy-ReleaseItem "scripts\verify_review_image_inspector.js" "scripts\verify_review_image_inspector.js"
Copy-ReleaseItem "scripts\verify_task_hall_region_scan.js" "scripts\verify_task_hall_region_scan.js"
Copy-ReleaseItem "scripts\verify_task_hall_pagination.js" "scripts\verify_task_hall_pagination.js"
Copy-ReleaseItem "scripts\verify_dialog_information_integration.js" "scripts\verify_dialog_information_integration.js"
Copy-ReleaseItem "scripts\production_backup.sh" "scripts\production_backup.sh"
Copy-ReleaseItem "scripts\cleanup_old_releases.sh" "scripts\cleanup_old_releases.sh"
Copy-ReleaseItem "scripts\run_photo_barcode_maintenance.sh" "scripts\run_photo_barcode_maintenance.sh"
Copy-ReleaseItem "scripts\run_photo_barcode_maintenance_slice.sh" "scripts\run_photo_barcode_maintenance_slice.sh"
Copy-ReleaseItem "scripts\run_photo_barcode_not_matched_rescan.sh" "scripts\run_photo_barcode_not_matched_rescan.sh"
Copy-ReleaseItem "scripts\production_health_check.py" "scripts\production_health_check.py"

Copy-ReleaseItem "v2-api\app" "v2-api\app"
Copy-ReleaseItem "v2-api\alembic" "v2-api\alembic"
Copy-ReleaseItem "v2-api\alembic.ini" "v2-api\alembic.ini"
Copy-ReleaseItem "v2-api\Dockerfile" "v2-api\Dockerfile"
Copy-ReleaseItem "v2-api\pyproject.toml" "v2-api\pyproject.toml"
Copy-ReleaseItem "v2-api\requirements.txt" "v2-api\requirements.txt"
Copy-ReleaseItem "v2-api\requirements-dev.txt" "v2-api\requirements-dev.txt"
Copy-ReleaseItem "v2-api\tests" "v2-api\tests"
Copy-ReleaseItem "v2-api\scripts" "v2-api\scripts"
Copy-ReleaseItem "v2-api\scripts\preview_v3_1_backfill.py" "v2-api\scripts\preview_v3_1_backfill.py"
Copy-ReleaseItem "v2-api\scripts\verify_v3_1_release.py" "v2-api\scripts\verify_v3_1_release.py"
$webSource = Join-Path $root "v2-web"
$webTarget = Join-Path $staging "v2-web"
New-Item -ItemType Directory -Force -Path $webTarget | Out-Null
robocopy $webSource $webTarget /E /XD node_modules dist .vite .cache /XF *.log | Out-Null
if ($LASTEXITCODE -gt 7) {
    throw "Failed to copy v2-web release sources. Robocopy exit code: $LASTEXITCODE"
}
$global:LASTEXITCODE = 0

$stagedStaticDir = Join-Path $staging "v2-api\app\static"
if (Test-Path $stagedStaticDir) {
    Get-ChildItem -LiteralPath $stagedStaticDir -File -Filter "*.html" -Force |
        Remove-Item -Force
    $stagedUploadsDir = Join-Path $stagedStaticDir "uploads"
    if (Test-Path $stagedUploadsDir) {
        Remove-Item -Recurse -Force -LiteralPath $stagedUploadsDir
    }
}

$stagedVueDir = Join-Path $staging "v2-api\app\static\vue"
$previousVueOutDir = $env:MODULE_MANAGER_VUE_OUT_DIR
$env:MODULE_MANAGER_VUE_OUT_DIR = $stagedVueDir
Write-Host "Building Vue production bundle..."
Push-Location .\v2-web
try {
    npm run build
    if ($LASTEXITCODE -ne 0) {
        throw "Vue production build failed."
    }
}
finally {
    Pop-Location
    if ($null -eq $previousVueOutDir) {
        Remove-Item Env:\MODULE_MANAGER_VUE_OUT_DIR -ErrorAction SilentlyContinue
    }
    else {
        $env:MODULE_MANAGER_VUE_OUT_DIR = $previousVueOutDir
    }
}

$versionArtifacts = @(
    (Join-Path $root "v2-web\src\version.json"),
    (Join-Path $stagedVueDir "version.json")
)
foreach ($versionArtifact in $versionArtifacts) {
    if (-not (Test-Path -LiteralPath $versionArtifact -PathType Leaf)) {
        throw "Vue version artifact missing after build: $versionArtifact"
    }
}

Get-ChildItem -LiteralPath $staging -Recurse -Directory -Force |
    Where-Object { $_.Name -in @("__pycache__", ".pytest_cache") } |
    Remove-Item -Recurse -Force

Get-ChildItem -LiteralPath $staging -Recurse -File -Force |
    Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
    Remove-Item -Force

# Normalize server shell scripts to LF so Linux bash can execute release helpers.
Get-ChildItem -LiteralPath $staging -Recurse -File -Filter "*.sh" -Force |
    ForEach-Object {
        $content = [System.IO.File]::ReadAllText($_.FullName)
        $normalized = $content -replace "`r`n", "`n" -replace "`r", "`n"
        [System.IO.File]::WriteAllText($_.FullName, $normalized, $utf8NoBom)
    }

$manifestPath = Join-Path $staging "RELEASE_MANIFEST.md"
$generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
$manifest = @"
# Module Manager V2 Production Server Release

## Package

- Name: $packageName
- Version: $Version
- Generated at: $generatedAt

## Included

- FastAPI application source under v2-api/app
- Vue production bundle under v2-api/app/static/vue
- v2-web source required by docker-compose.yml
- Alembic migration files
- JSON/PostgreSQL and photo migration scripts under v2-api/scripts
- Requirements and Dockerfile
- Client acceptance gate, demo startup, smoke-check, strict Vue migration verification, PostgreSQL cutover audit, production-readiness verification, and release verification scripts under scripts
- Local static review images and the demo data seed script for pre-production smoke checks
- Nginx and systemd deployment samples under infra
- Client acceptance, final audit, visual QA, signoff, demo, deployment, and production SOP documents under docs
- Production release and incident record templates under ops

## Excluded

- Local virtual environments such as .venv
- Local .env files and secrets
- Python caches such as __pycache__, .pyc, and .pytest_cache
- Generated build/runtime folders outside this release package

## Demo Commands

.\scripts\run-client-demo.ps1

.\scripts\run-client-acceptance-gate.ps1

.\scripts\build-client-release.ps1 -Version $Version -PerformanceReport .\outputs\performance\v$Version-task-review.json

.\.venv\Scripts\python.exe .\scripts\smoke-client-demo.py

.\.venv\Scripts\python.exe .\scripts\verify_vue_migration_gate.py --strict-native

.\.venv\Scripts\python.exe .\scripts\verify_postgres_cutover_gate.py

.\.venv\Scripts\python.exe .\scripts\verify-production-readiness.py --example

.\.venv\Scripts\python.exe .\scripts\verify-client-release.py

.\.venv\Scripts\python.exe .\scripts\verify_release_sop.py --version V$Version

## Verified During Packaging

- Release smoke check passes unless -SkipSmoke was used
- Source-bound V3.1 task/review performance evidence passes the release verifier
- Demo admin and reviewer login are available only for local walkthrough when enabled
- Reviewer task ownership uses the logged-in reviewer identity, not a local debug reviewer id
- Vue strict-native production pages are required
- PostgreSQL cutover audit must be reviewed before production deployment
- Production mode disables demo accounts by default
- Production mode disables /docs, /redoc, and /openapi.json by default
- Required client documents and deployment samples are present
- Client signoff checklist is included for payment acceptance
- Production SOP files and release record templates are present

## Production Notes

- Set APP_ENV=production
- Set DEMO_AUTH_ENABLED=false
- Replace APP_SECRET, JWT_SECRET, ADMIN_USERNAME, and ADMIN_PASSWORD
- Confirm /docs, /redoc, and /openapi.json return 404 in production
- Enable HTTPS before real project data is exposed
- Configure PostgreSQL backup before production import
- Use build/server-release packages for production deployment
- Record each production release under ops/releases/
"@
Set-Content -LiteralPath $manifestPath -Value $manifest -Encoding UTF8

@"
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

staging = Path.cwd() / "build" / "server-release" / "$packageName"
zip_path = Path.cwd() / "build" / "server-release" / "$packageName.zip"
if zip_path.exists():
    zip_path.unlink()
with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
    for path in sorted(staging.rglob("*")):
        if path.is_file():
            archive.write(path, path.relative_to(staging).as_posix())
"@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create release zip."
}

$finalSourceCommit = (& git rev-parse HEAD).Trim().ToLowerInvariant()
$finalWorktreeChanges = @(git status --porcelain --untracked-files=all)
if (
    $LASTEXITCODE -ne 0 -or
    $finalSourceCommit -ne $sourceCommit -or
    $finalWorktreeChanges.Count -ne 0
) {
    Remove-Item -Force -LiteralPath $zipPath -ErrorAction SilentlyContinue
    throw "Release source commit or worktree changed during packaging."
}

& .\.venv\Scripts\python.exe .\scripts\verify-client-release.py $zipPath --expected-source-commit $sourceCommit
if ($LASTEXITCODE -ne 0) {
    Remove-Item -Force -LiteralPath $zipPath -ErrorAction SilentlyContinue
    throw "Release package verification failed."
}

Write-Host ""
Write-Host "Server release package created:"
Write-Host "  Folder: $staging"
Write-Host "  Zip:    $zipPath"
