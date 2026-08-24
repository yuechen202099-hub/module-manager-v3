param(
    [string]$Version = "3.2.7",
    [string]$PerformanceReport = "",
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"

if ($Version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') {
    throw "Release Version must be a semantic version such as 3.0.84."
}

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$releaseInputs = @(
    "scripts\verify_v3_2_0_role_routes.py",
    "scripts\verify_v3_2_0_data_center_ui.py",
    "scripts\verify_v3_2_0_dashboard_drilldown.py",
    "scripts\verify_v3_2_0_export_center_ui.py",
    "scripts\verify_v3_2_0_single_export_entry.py",
    "scripts\verify_v3_2_1_installer_kpi_restore.py",
    "scripts\verify_v3_2_2_release.py",
    "scripts\verify_v3_2_3_release.py",
    "scripts\test_verify_v3_2_3_release.py",
    "scripts\verify_v3_2_4_release.py",
    "scripts\test_verify_v3_2_4_release.py",
    "scripts\verify_v3_2_5_release.py",
    "scripts\test_verify_v3_2_5_release.py",
    "scripts\verify_v3_2_6_release.py",
    "scripts\test_verify_v3_2_6_release.py",
    "scripts\verify_v3_2_7_release.py",
    "scripts\test_verify_v3_2_7_release.py",
    "scripts\patch_export_retirement_nginx.py",
    "scripts\test_patch_export_retirement_nginx.py",
    "scripts\oss_local_export.py",
    "scripts\test_oss_local_export.py",
    "docs\sop\09-export-retirement-and-oss-local-export.md",
    "v2-api\alembic\versions\0013_data_center_query_indexes.py",
    "v2-api\alembic\versions\0014_export_center_jobs.py",
    "v2-api\alembic\versions\0015_collector_transfer_workbench.py",
    "v2-api\app\api\routes\collector_transfer.py",
    "v2-api\app\domain\collector_transfer.py",
    "v2-api\app\services\collector_transfer.py",
    "v2-api\tests\test_collector_transfer_api.py",
    "v2-api\tests\test_collector_transfer_domain.py",
    "v2-api\tests\test_collector_transfer_postgres_integration.py",
    "v2-api\tests\test_collector_transfer_service.py",
    "v2-api\app\api\routes\groups.py",
    "v2-api\app\api\routes\exports.py",
    "v2-api\app\schemas\data_center.py",
    "v2-api\app\schemas\export_center.py",
    "v2-api\app\services\construction_task_rules.py",
    "v2-api\app\services\data_center.py",
    "v2-api\app\services\export_center.py",
    "v2-api\app\services\photo_storage.py",
    "v2-api\tests\test_photo_storage.py",
    "v2-web\src\components\data-center\DataCenterFilters.vue",
    "v2-web\src\components\data-center\DataCenterReviewDialog.vue",
    "v2-web\src\views\GlobalSearchView.vue",
    "v2-web\src\composables\useDataCenterQuery.ts",
    "v2-web\src\utils\dataCenterDrilldown.ts",
    "v2-web\src\components\InstallerKpiDialog.vue",
    "v2-web\src\utils\installerKpi.ts",
    "v2-web\src\views\CollectorBatchManagementView.vue",
    "v2-web\src\views\CollectorInventoryView.vue",
    "v2-web\src\views\CollectorWorkbenchView.vue",
    "v2-api\scripts\migrate_external_photos_to_oss.py",
    "v2-api\tests\test_migrate_external_photos_to_oss.py",
    "ops\releases\V3.2.0.md",
    "ops\releases\V3.2.1.md",
    "ops\releases\V3.2.2.md",
    "ops\releases\V3.2.3.md",
    "ops\releases\V3.2.4.md",
    "ops\releases\V3.2.5.md",
    "ops\releases\V3.2.6.md",
    "ops\releases\V3.2.7.md"
)
foreach ($releaseInput in $releaseInputs) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $releaseInput) -PathType Leaf)) {
        throw "Release input is missing: $releaseInput"
    }
}

$sourceCommit = (& git rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $sourceCommit -notmatch '^[0-9a-f]{40}$') {
    throw "Unable to resolve the full Git source commit for this release."
}
$sourceBranch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $sourceBranch -ne "production/V3/3.2.7") {
    throw "Refusing to package branch '$sourceBranch'. Expected production/V3/3.2.7."
}
$worktreeChanges = @(
    git status --porcelain --untracked-files=all |
        Where-Object { $_ -notmatch '^\?\? v2-api/uv\.lock$' }
)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify Git worktree state before packaging."
}
if ($worktreeChanges.Count -ne 0) {
    throw "Refusing to package a dirty Git worktree. Commit or remove every source change first."
}
if ([string]::IsNullOrWhiteSpace($PerformanceReport)) {
    throw "Performance report is required for V3.2.7 packaging."
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
    throw "V3.1 performance evidence verification failed."
}

Write-Host "Running V3.2.7 focused release gates..."
$releaseVerifiers = @(
    "scripts\verify_v3_2_0_role_routes.py",
    "scripts\verify_v3_2_0_data_center_ui.py",
    "scripts\verify_v3_2_0_dashboard_drilldown.py",
    "scripts\verify_v3_2_0_export_center_ui.py",
    "scripts\verify_v3_2_0_single_export_entry.py",
    "scripts\verify_v3_2_1_installer_kpi_restore.py",
    "scripts\verify_v3_2_7_release.py"
)
foreach ($releaseVerifier in $releaseVerifiers) {
    if ($releaseVerifier -eq "scripts\verify_v3_2_7_release.py") {
        & .\.venv\Scripts\python.exe (Join-Path $root $releaseVerifier) --phase source
    } else {
        & .\.venv\Scripts\python.exe (Join-Path $root $releaseVerifier)
    }
    if ($LASTEXITCODE -ne 0) {
        throw "V3.2.7 release gate failed: $releaseVerifier"
    }
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
Copy-ReleaseItem "scripts\verify_dialog_information_integration.js" "scripts\verify_dialog_information_integration.js"
Copy-ReleaseItem "scripts\verify_v3_2_0_role_routes.py" "scripts\verify_v3_2_0_role_routes.py"
Copy-ReleaseItem "scripts\verify_v3_2_0_data_center_ui.py" "scripts\verify_v3_2_0_data_center_ui.py"
Copy-ReleaseItem "scripts\verify_v3_2_0_dashboard_drilldown.py" "scripts\verify_v3_2_0_dashboard_drilldown.py"
Copy-ReleaseItem "scripts\verify_v3_2_0_export_center_ui.py" "scripts\verify_v3_2_0_export_center_ui.py"
Copy-ReleaseItem "scripts\verify_v3_2_0_single_export_entry.py" "scripts\verify_v3_2_0_single_export_entry.py"
Copy-ReleaseItem "scripts\verify_v3_2_0_release.py" "scripts\verify_v3_2_0_release.py"
Copy-ReleaseItem "scripts\verify_v3_2_1_installer_kpi_restore.py" "scripts\verify_v3_2_1_installer_kpi_restore.py"
Copy-ReleaseItem "scripts\verify_v3_2_2_release.py" "scripts\verify_v3_2_2_release.py"
Copy-ReleaseItem "scripts\verify_v3_2_3_release.py" "scripts\verify_v3_2_3_release.py"
Copy-ReleaseItem "scripts\test_verify_v3_2_3_release.py" "scripts\test_verify_v3_2_3_release.py"
Copy-ReleaseItem "scripts\verify_v3_2_4_release.py" "scripts\verify_v3_2_4_release.py"
Copy-ReleaseItem "scripts\test_verify_v3_2_4_release.py" "scripts\test_verify_v3_2_4_release.py"
Copy-ReleaseItem "scripts\verify_v3_2_5_release.py" "scripts\verify_v3_2_5_release.py"
Copy-ReleaseItem "scripts\test_verify_v3_2_5_release.py" "scripts\test_verify_v3_2_5_release.py"
Copy-ReleaseItem "scripts\verify_v3_2_6_release.py" "scripts\verify_v3_2_6_release.py"
Copy-ReleaseItem "scripts\test_verify_v3_2_6_release.py" "scripts\test_verify_v3_2_6_release.py"
Copy-ReleaseItem "scripts\verify_v3_2_7_release.py" "scripts\verify_v3_2_7_release.py"
Copy-ReleaseItem "scripts\test_verify_v3_2_7_release.py" "scripts\test_verify_v3_2_7_release.py"
Copy-ReleaseItem "scripts\patch_export_retirement_nginx.py" "scripts\patch_export_retirement_nginx.py"
Copy-ReleaseItem "scripts\test_patch_export_retirement_nginx.py" "scripts\test_patch_export_retirement_nginx.py"
Copy-ReleaseItem "scripts\oss_local_export.py" "scripts\oss_local_export.py"
Copy-ReleaseItem "scripts\test_oss_local_export.py" "scripts\test_oss_local_export.py"
Copy-ReleaseItem "docs\sop\09-export-retirement-and-oss-local-export.md" "docs\sop\09-export-retirement-and-oss-local-export.md"
Copy-ReleaseItem "v2-web\src\components\InstallerKpiDialog.vue" "v2-web\src\components\InstallerKpiDialog.vue"
Copy-ReleaseItem "v2-web\src\utils\installerKpi.ts" "v2-web\src\utils\installerKpi.ts"
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

$forbiddenReleaseDirectoryNames = @(
    "data",
    "uploads",
    "node_modules",
    "dist",
    ".vite",
    ".cache",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "coverage",
    "htmlcov",
    "test-results",
    "playwright-report",
    ".nyc_output",
    "build"
)

$forbiddenReleaseFileNames = @(".coverage", "coverage.xml", "junit.xml")
$forbiddenReleaseFileSuffixes = @(
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".sql",
    ".dump",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".log",
    ".pyc",
    ".pyo"
)

function Test-ForbiddenReleasePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [bool]$IsDirectory
    )

    $resolvedStagingPath = [System.IO.Path]::GetFullPath($staging)
    $resolvedPath = [System.IO.Path]::GetFullPath($Path)
    $stagingPrefix = (
        $resolvedStagingPath.TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        ) + [System.IO.Path]::DirectorySeparatorChar
    )
    if (-not $resolvedPath.StartsWith(
        $stagingPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Release cleanup path is outside staging: $resolvedPath"
    }
    $normalizedRelativePath = (
        $resolvedPath.Substring($stagingPrefix.Length).Replace("\", "/")
    ).ToLowerInvariant()
    $normalizedComponents = @(
        $normalizedRelativePath.Split(
            "/",
            [System.StringSplitOptions]::RemoveEmptyEntries
        )
    )
    foreach ($component in $normalizedComponents) {
        if (
            $component -in $forbiddenReleaseDirectoryNames -or
            $component -eq ".env" -or
            $component.StartsWith(".env.")
        ) {
            return $true
        }
    }
    if ($IsDirectory -or $normalizedComponents.Count -eq 0) {
        return $false
    }

    $leafName = $normalizedComponents[-1]
    $leafSuffix = [System.IO.Path]::GetExtension($leafName)
    $leafStem = [System.IO.Path]::GetFileNameWithoutExtension($leafName)
    return (
        $leafName -in $forbiddenReleaseFileNames -or
        $leafSuffix -in $forbiddenReleaseFileSuffixes -or
        $leafStem -in @("migration-report", "migration_report", "allowed-hosts", "allowed_hosts") -or
        (
            $leafSuffix -eq ".zip" -and
            (
                $leafName.StartsWith("oss-local-export-") -or
                $leafName.StartsWith("oss_local_export_")
            )
        )
    )
}

function Remove-ForbiddenReleaseItems {
    Get-ChildItem -LiteralPath $staging -Recurse -Directory -Force |
        Where-Object {
            Test-ForbiddenReleasePath -Path $_.FullName -IsDirectory $true
        } |
        Sort-Object { $_.FullName.Length } -Descending |
        ForEach-Object {
            if (Test-Path -LiteralPath $_.FullName) {
                Remove-Item -Recurse -Force -LiteralPath $_.FullName
            }
        }

    Get-ChildItem -LiteralPath $staging -Recurse -File -Force |
        Where-Object {
            Test-ForbiddenReleasePath -Path $_.FullName -IsDirectory $false
        } |
        Remove-Item -Force
}

Remove-ForbiddenReleaseItems

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

Remove-ForbiddenReleaseItems

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

.\scripts\build-client-release.ps1 -Version $Version -PerformanceReport .\build\release-evidence\v$Version-task-review.json

.\.venv\Scripts\python.exe .\scripts\smoke-client-demo.py

.\.venv\Scripts\python.exe .\scripts\verify_vue_migration_gate.py --strict-native

.\.venv\Scripts\python.exe .\scripts\verify_postgres_cutover_gate.py

.\.venv\Scripts\python.exe .\scripts\verify-production-readiness.py --example

.\.venv\Scripts\python.exe .\scripts\verify-client-release.py

.\.venv\Scripts\python.exe .\scripts\verify_release_sop.py --version V$Version

## Verified During Packaging

- Release smoke check passes unless -SkipSmoke was used
- Source-bound V3.1 task/review performance evidence passes the release verifier
- V3.2.0 inherited gates, immutable historical release contracts, and the active V3.2.7 project-scoped collector inventory contract pass before package staging
- Demo admin and constructor login are available only for local walkthrough when enabled
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
$finalWorktreeChanges = @(
    git status --porcelain --untracked-files=all |
        Where-Object { $_ -notmatch '^\?\? v2-api/uv\.lock$' }
)
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
