from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


V328_CONTRACT_INPUTS = frozenset(
    {
        "AGENTS.md",
        "README.md",
        "RELEASE_MANIFEST.md",
        "docs/CLIENT_SIGNOFF_CHECKLIST.md",
        "docs/superpowers/specs/2026-08-23-collector-transfer-workbench-design.md",
        "ops/releases/V3.2.7.md",
        "ops/releases/V3.2.8.md",
        "scripts/build-client-release.ps1",
        "scripts/verify-client-release.py",
        "scripts/verify_release_sop.py",
        "scripts/verify_v3_2_8_release.py",
        "scripts/test_verify_v3_2_8_release.py",
        "v2-api/alembic/versions/0015_collector_transfer_workbench.py",
        "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py",
        "v2-api/app/api/routes/collector_transfer.py",
        "v2-api/app/main.py",
        "v2-api/app/models.py",
        "v2-api/app/services/collector_transfer.py",
        "v2-api/app/services/ops_status.py",
        "v2-api/pyproject.toml",
        "v2-api/scripts/verify_v3_1_release.py",
        "v2-api/tests/test_collector_transfer_api.py",
        "v2-api/tests/test_collector_transfer_domain.py",
        "v2-api/tests/test_collector_transfer_postgres_integration.py",
        "v2-api/tests/test_collector_transfer_service.py",
        "v2-api/tests/test_collector_transfer_scale.py",
        "v2-api/tests/test_v3_1_release.py",
        "v2-web/index.html",
        "v2-web/package.json",
        "v2-web/src/api/services.ts",
        "v2-web/src/api/types.ts",
        "v2-web/src/components/AppLayout.vue",
        "v2-web/src/constants/releaseNotes.ts",
        "v2-web/src/version.json",
        "v2-web/src/views/CollectorInventoryView.vue",
        "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts",
    }
)

V3210_CONTRACT_INPUTS = frozenset(
    {
        "AGENTS.md",
        "RELEASE_MANIFEST.md",
        "docs/AGENT_REQUIRED_READING.md",
        "docs/sop/README.md",
        "docs/superpowers/specs/2026-08-26-unified-terminal-review-rephoto-workbench-design.md",
        "ops/releases/V3.2.9.md",
        "ops/releases/V3.2.10.md",
        "scripts/build-client-release.ps1",
        "scripts/verify-client-release.py",
        "scripts/verify_release_sop.py",
        "scripts/verify_v3_2_10_release.py",
        "scripts/test_verify_v3_2_10_release.py",
        "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py",
        "v2-api/app/api/routes/collector_transfer.py",
        "v2-api/app/api/routes/groups.py",
        "v2-api/app/domain/terminal_review.py",
        "v2-api/app/main.py",
        "v2-api/app/services/collector_transfer.py",
        "v2-api/app/services/ops_status.py",
        "v2-api/pyproject.toml",
        "v2-api/scripts/verify_v3_1_release.py",
        "v2-api/tests/test_collector_transfer_api.py",
        "v2-api/tests/test_collector_transfer_postgres_integration.py",
        "v2-api/tests/test_collector_transfer_scale.py",
        "v2-api/tests/test_collector_transfer_service.py",
        "v2-api/tests/test_data_center_review.py",
        "v2-api/tests/test_terminal_review_domain.py",
        "v2-api/tests/test_v3_1_release.py",
        "v2-web/index.html",
        "v2-web/package.json",
        "v2-web/src/api/services.ts",
        "v2-web/src/api/types.ts",
        "v2-web/src/components/AppLayout.vue",
        "v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue",
        "v2-web/src/constants/releaseNotes.ts",
        "v2-web/src/features/collectorTransfer/state.ts",
        "v2-web/src/router/index.ts",
        "v2-web/src/router/staticPages.ts",
        "v2-web/src/version.json",
        "v2-web/src/views/CollectorInventoryView.vue",
        "v2-web/src/views/ReviewRephotoWorkbenchView.vue",
        "v2-web/src/views/__tests__/CollectorInventoryRouting.spec.ts",
        "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts",
        "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
    }
)

V3211_ANDROID_SCANNER_INPUTS = frozenset(
    {
        "v2-web/src/views/ConstructionView.vue",
        "v2-web/src/views/__tests__/ConstructionScannerAndroid.spec.ts",
    }
)

V3211_CONTRACT_INPUTS = frozenset(
    set(V3210_CONTRACT_INPUTS)
    | {
        "docs/sop/06-production-deploy-runbook.md",
        "ops/releases/V3.2.11.md",
        "scripts/production_health_check.py",
        "scripts/verify_v3_2_11_release.py",
        "scripts/test_verify_v3_2_11_release.py",
    }
    | V3211_ANDROID_SCANNER_INPUTS
)

V3212_CONTRACT_INPUTS = frozenset(
    set(V3211_CONTRACT_INPUTS)
    | {
        "ops/releases/V3.2.12.md",
        "scripts/verify_v3_2_12_release.py",
        "scripts/test_verify_v3_2_12_release.py",
        "v2-api/app/schemas/data_center.py",
        "v2-api/app/services/data_center.py",
        "v2-api/app/services/local_simulation.py",
        "v2-api/app/services/state_repository.py",
        "v2-api/tests/test_api.py",
        "v2-api/tests/test_state_repository.py",
        "v2-web/src/components/__tests__/DataCenterGroupReviewPanel.spec.ts",
    }
)

V3213_CONTRACT_INPUTS = frozenset(
    set(V3212_CONTRACT_INPUTS)
    | {
        "ops/releases/V3.2.13.md",
        "scripts/verify_v3_2_13_release.py",
        "scripts/test_verify_v3_2_13_release.py",
        "v2-api/app/static/vue/version.json",
        "v2-web/src/components/PhotoLightbox.vue",
        "v2-web/src/components/__tests__/PhotoLightbox.spec.ts",
    }
)

V3214_CONTRACT_INPUTS = frozenset(
    set(V3213_CONTRACT_INPUTS)
    | {
        "docs/superpowers/plans/2026-08-28-v3-2-14-review-rephoto-archive-manual-demand.md",
        "ops/releases/V3.2.14.md",
        "scripts/verify_v3_2_14_release.py",
        "scripts/test_verify_v3_2_14_release.py",
        "v2-api/alembic/versions/0001_initial_schema.py",
        "v2-api/alembic/versions/0002_local_state_postgres_bridge.py",
        "v2-api/alembic/versions/0003_photo_import_dedup_fields.py",
        "v2-api/alembic/versions/0004_allow_five_construction_tasks.py",
        "v2-api/alembic/versions/0005_add_construction_priority.py",
        "v2-api/alembic/versions/0006_group_barcode_verification.py",
        "v2-api/alembic/versions/0007_group_barcode_verification_lease_token.py",
        "v2-api/alembic/versions/0008_delivery_cache_jobs.py",
        "v2-api/alembic/versions/0009_delivery_cache_fix3.py",
        "v2-api/alembic/versions/0010_auto_archive_queue_state.py",
        "v2-api/alembic/versions/0011_delivery_package_jobs.py",
        "v2-api/alembic/versions/0012_delivery_package_group_ids_gin.py",
        "v2-api/alembic/versions/0013_data_center_query_indexes.py",
        "v2-api/alembic/versions/0014_export_center_jobs.py",
        "v2-api/alembic/versions/0015_collector_transfer_workbench.py",
        "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py",
        "v2-api/app/api/schemas/collector_transfer.py",
    }
)

V3215_CONTRACT_INPUTS = frozenset(
    set(V3214_CONTRACT_INPUTS)
    | {
        "docs/superpowers/plans/2026-08-28-v3-2-15-dashboard-rephoto-async.md",
        "ops/releases/V3.2.15.md",
        "scripts/verify_v3_2_15_release.py",
        "scripts/test_verify_v3_2_15_release.py",
        "v2-api/tests/test_v21_data_rules.py",
    }
)

V3216_CONTRACT_INPUTS = frozenset(
    set(V3215_CONTRACT_INPUTS)
    | {
        "docs/superpowers/plans/2026-08-29-v3-2-16-review-claim-hotfix.md",
        "ops/releases/V3.2.16.md",
        "scripts/verify_v3_2_16_release.py",
        "scripts/test_verify_v3_2_16_release.py",
        "scripts/production_backup.sh",
        "v2-api/tests/test_data_center.py",
        "v2-api/tests/test_local_simulation.py",
        "v2-web/src/views/__tests__/AppLayout.spec.ts",
        "v2-web/src/views/__tests__/LoginView.spec.ts",
    }
)

V3217_CONTRACT_INPUTS = frozenset(
    set(V3216_CONTRACT_INPUTS)
    | {
        "docs/superpowers/plans/2026-08-29-v3-2-17-anomaly-export-release.md",
        "ops/releases/V3.2.17.md",
        "scripts/verify_v3_2_17_release.py",
        "scripts/test_verify_v3_2_17_release.py",
        "v2-web/src/components/__tests__/ProjectBoardView.spec.ts",
        "v2-web/src/views/ProjectBoardView.vue",
    }
)

V3218_CONTRACT_INPUTS = frozenset(
    set(V3217_CONTRACT_INPUTS)
    | {
        "docs/superpowers/plans/2026-08-29-v3-2-18-approved-exception-hotfix.md",
        "ops/releases/V3.2.18.md",
        "scripts/verify_v3_2_18_release.py",
        "scripts/test_verify_v3_2_18_release.py",
    }
)

V3219_CONTRACT_INPUTS = frozenset(
    set(V3218_CONTRACT_INPUTS)
    | {
        "docs/superpowers/plans/2026-08-30-v3-2-19-meter-dedup-release.md",
        "ops/releases/V3.2.19.md",
        "scripts/verify_v3_2_19_release.py",
        "scripts/test_verify_v3_2_19_release.py",
        "v2-api/app/domain/collector_transfer.py",
        "v2-api/tests/test_collector_transfer_domain.py",
    }
)

V3220_CONTRACT_INPUTS = frozenset(
    set(V3219_CONTRACT_INPUTS)
    | {
        "docs/superpowers/plans/2026-08-30-v3-2-20-device-display-hotfix.md",
        "ops/releases/V3.2.20.md",
        "scripts/verify_v3_2_20_release.py",
        "scripts/test_verify_v3_2_20_release.py",
        "v2-web/src/components/__tests__/DataCenterGroupReviewPanel.spec.ts",
        "v2-web/src/views/GlobalSearchView.vue",
        "v2-web/src/views/__tests__/GlobalSearchView.spec.ts",
    }
)

V3221_CONTRACT_INPUTS = frozenset(
    set(V3220_CONTRACT_INPUTS)
    | {
        "docs/superpowers/specs/2026-08-30-bulk-anomaly-approval.md",
        "docs/superpowers/plans/2026-08-30-bulk-anomaly-approval.md",
        "ops/releases/V3.2.21.md",
        "scripts/verify_v3_2_21_release.py",
        "scripts/test_verify_v3_2_21_release.py",
        "v2-api/app/api/routes/groups.py",
        "v2-api/app/services/data_center.py",
        "v2-api/app/services/local_simulation.py",
        "v2-api/app/services/state_repository.py",
        "v2-api/tests/test_data_center_review.py",
        "v2-api/tests/test_state_repository.py",
        "v2-web/src/api/services.ts",
        "v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue",
        "v2-web/src/components/__tests__/DataCenterGroupReviewPanel.spec.ts",
    }
)

V3222_CONTRACT_INPUTS = frozenset(
    set(V3221_CONTRACT_INPUTS)
    | {
        "ops/releases/V3.2.22.md",
        "scripts/verify_v3_2_22_release.py",
        "scripts/test_verify_v3_2_22_release.py",
        "v2-api/app/services/data_center.py",
        "v2-api/app/services/state_repository.py",
        "v2-api/tests/test_data_center.py",
    }
)

V3223_CONTRACT_INPUTS = frozenset(
    set(V3222_CONTRACT_INPUTS)
    | {
        "ops/releases/V3.2.23.md",
        "scripts/verify_v3_2_23_release.py",
        "scripts/test_verify_v3_2_23_release.py",
        "v2-api/app/api/routes/groups.py",
        "v2-api/app/services/local_simulation.py",
        "v2-api/app/services/state_repository.py",
        "v2-web/src/api/services.ts",
        "v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue",
    }
)

V3224_CONTRACT_INPUTS = frozenset(
    set(V3223_CONTRACT_INPUTS)
    | {
        "ops/releases/V3.2.24.md",
        "scripts/verify_v3_2_24_release.py",
        "scripts/test_verify_v3_2_24_release.py",
        "v2-api/app/services/state_repository.py",
        "v2-api/tests/test_data_center_review.py",
        "v2-api/tests/test_state_repository.py",
    }
)

V3225_CONTRACT_INPUTS = frozenset(
    set(V3224_CONTRACT_INPUTS)
    | {
        "ops/releases/V3.2.25.md",
        "scripts/verify_v3_2_25_release.py",
        "scripts/test_verify_v3_2_25_release.py",
        "v2-api/app/services/barcode_maintenance_worker.py",
        "v2-api/app/services/collector_transfer.py",
        "v2-api/app/services/data_center.py",
        "v2-api/app/services/local_simulation.py",
        "v2-api/app/services/state_repository.py",
        "v2-api/scripts/repair_missing_collector_photo_exceptions.py",
        "v2-api/tests/test_api.py",
        "v2-api/tests/test_barcode_maintenance_worker.py",
        "v2-api/tests/test_collector_transfer_service.py",
        "v2-api/tests/test_data_center_review.py",
        "v2-api/tests/test_local_simulation.py",
        "v2-api/tests/test_miniprogram_api.py",
        "v2-api/tests/test_repair_missing_collector_photo_exceptions.py",
        "v2-api/tests/test_state_repository.py",
    }
)

V3226_CONTRACT_INPUTS = frozenset(
    set(V3225_CONTRACT_INPUTS)
    | {
        "ops/releases/V3.2.26.md",
        "scripts/verify_v3_2_26_release.py",
        "scripts/test_verify_v3_2_26_release.py",
        "v2-api/app/api/router.py",
        "v2-api/tests/test_v21_data_rules.py",
        "docs/sop/07-rollback-and-incident-review.md",
    }
)

V3227_CONTRACT_INPUTS = frozenset(
    set(V3226_CONTRACT_INPUTS)
    | {
        "AGENTS.md",
        "README.md",
        "RELEASE_MANIFEST.md",
        "ops/releases/V3.2.27.md",
        "scripts/build-client-release.ps1",
        "scripts/verify-client-release.py",
        "scripts/verify_release_sop.py",
        "scripts/verify_material_export_gate.py",
        "scripts/verify_v3_2_27_release.py",
        "scripts/test_verify_v3_2_27_release.py",
        "v2-api/alembic/versions/0017_material_exports.py",
        "v2-api/app/main.py",
        "v2-api/app/models.py",
        "v2-api/app/api/router.py",
        "v2-api/app/api/routes/material_exports.py",
        "v2-api/app/api/schemas/material_export.py",
        "v2-api/app/domain/material_export.py",
        "v2-api/app/services/material_export.py",
        "v2-api/app/services/material_export_stream.py",
        "v2-api/app/services/ops_status.py",
        "v2-api/pyproject.toml",
        "v2-api/scripts/verify_v3_1_release.py",
        "v2-api/tests/test_v3_1_release.py",
        "v2-api/tests/test_material_export_domain.py",
        "v2-api/tests/test_material_export_models.py",
        "v2-api/tests/test_material_export_service.py",
        "v2-api/tests/test_material_export_api.py",
        "v2-api/tests/test_material_export_stream.py",
        "v2-web/index.html",
        "v2-web/package.json",
        "v2-web/src/version.json",
        "v2-web/src/router/index.ts",
        "v2-web/src/components/AppLayout.vue",
        "v2-web/src/components/material-export/MaterialExportToolbar.vue",
        "v2-web/src/components/material-export/MaterialExportCardControls.vue",
        "v2-web/src/constants/releaseNotes.ts",
        "v2-web/src/features/materialExport/state.ts",
        "v2-web/src/features/materialExport/checkpoint.ts",
        "v2-web/src/features/materialExport/fileSystem.ts",
        "v2-web/src/features/materialExport/workbooks.ts",
        "v2-web/src/features/materialExport/runner.ts",
        "v2-web/src/features/materialExport/useMaterialExport.ts",
        "v2-web/src/views/ClaimTasksView.vue",
        "v2-web/src/views/__tests__/ClaimTasksMaterialExport.spec.ts",
    }
)

V3228_CONTRACT_INPUTS = frozenset(
    set(V3227_CONTRACT_INPUTS)
    | {
        "ops/releases/V3.2.28.md",
        "scripts/verify_v3_2_28_release.py",
        "scripts/test_verify_v3_2_28_release.py",
    }
)

V3226_RETIRED_BACKGROUND_BARCODE_FILES = frozenset(
    {
        "infra/module-manager-v2-photo-barcode-maintenance.service",
        "infra/module-manager-v2-photo-barcode-maintenance-enqueue.service",
        "infra/module-manager-v2-photo-barcode-maintenance.timer",
        "scripts/run_photo_barcode_maintenance.sh",
        "scripts/run_photo_barcode_maintenance_slice.sh",
        "scripts/run_photo_barcode_not_matched_rescan.sh",
    }
)

REQUIRED_FILES = {
    "SOURCE_COMMIT",
    "README.md",
    "AGENTS.md",
    ".gitattributes",
    "RELEASE_MANIFEST.md",
    "docs/CLIENT_ACCEPTANCE_REPORT.md",
    "docs/CLIENT_FINAL_AUDIT.md",
    "docs/CLIENT_DEMO_READINESS.md",
    "docs/CLIENT_DEMO_SCRIPT.md",
    "docs/CLIENT_SIGNOFF_CHECKLIST.md",
    "docs/CLIENT_VISUAL_QA.md",
    "docs/SERVER_DEPLOYMENT_PREP.md",
    "docs/PROJECT_DECISIONS.md",
    "docs/STATIC_TO_VUE_MIGRATION.md",
    "docs/sop/README.md",
    "docs/sop/01-demand-intake-and-priority.md",
    "docs/sop/02-production-branch-versioning.md",
    "docs/sop/03-change-analysis-and-tdd.md",
    "docs/sop/04-subagent-review-template.md",
    "docs/sop/05-release-package-and-hash.md",
    "docs/sop/06-production-deploy-runbook.md",
    "docs/sop/07-rollback-and-incident-review.md",
    "docs/sop/08-business-acceptance-templates.md",
    "docs/sop/09-export-retirement-and-oss-local-export.md",
    "docs/database/postgresql-schema.md",
    "infra/nginx/module-manager-v2.conf",
    "infra/module-manager-v2.service",
    "infra/module-manager-v2-photo-barcode-maintenance.service",
    "infra/module-manager-v2-photo-barcode-maintenance-enqueue.service",
    "infra/module-manager-v2-photo-barcode-maintenance.timer",
    "scripts/build-client-release.ps1",
    "scripts/run_photo_barcode_maintenance.sh",
    "scripts/run_photo_barcode_maintenance_slice.sh",
    "scripts/run_photo_barcode_not_matched_rescan.sh",
    "scripts/run-client-acceptance-gate.ps1",
    "scripts/run-client-demo.ps1",
    "scripts/smoke-client-demo.py",
    "scripts/seed-client-demo-data.py",
    "scripts/verify_vue_migration_gate.py",
    "scripts/verify_postgres_cutover_gate.py",
    "scripts/verify-production-readiness.py",
    "scripts/verify-client-release.py",
    "scripts/verify_admin_release_notes.js",
    "scripts/audit_production_security.py",
    "scripts/verify_security_hardening.py",
    "scripts/verify_frontend_auth_expiry.js",
    "scripts/verify_claim_tasks_completion_status.js",
    "scripts/verify_claim_tasks_construction_priority.js",
    "scripts/verify_construction_one_click_upload.js",
    "scripts/verify_construction_draft_photo_cache.js",
    "scripts/verify_construction_priority_import_dialog.js",
    "scripts/verify_installer_workload_completion_visibility.js",
    "scripts/verify_release_sop.py",
    "scripts/verify_release_retention_policy.py",
    "scripts/verify_project_board_photo_dialog.js",
    "scripts/verify_project_board_data_center_photos.js",
    "scripts/verify_project_board_unmatched_review.js",
    "scripts/verify_review_image_inspector.js",
    "scripts/verify_dialog_information_integration.js",
    "scripts/verify_v3_2_0_role_routes.py",
    "scripts/verify_v3_2_0_data_center_ui.py",
    "scripts/verify_v3_2_0_dashboard_drilldown.py",
    "scripts/verify_v3_2_0_export_center_ui.py",
    "scripts/verify_v3_2_0_single_export_entry.py",
    "scripts/verify_v3_2_0_release.py",
    "scripts/verify_v3_2_1_installer_kpi_restore.py",
    "scripts/verify_v3_2_2_release.py",
    "scripts/verify_v3_2_3_release.py",
    "scripts/test_verify_v3_2_3_release.py",
    "scripts/verify_v3_2_4_release.py",
    "scripts/test_verify_v3_2_4_release.py",
    "scripts/verify_v3_2_5_release.py",
    "scripts/test_verify_v3_2_5_release.py",
    "scripts/verify_v3_2_6_release.py",
    "scripts/test_verify_v3_2_6_release.py",
    "scripts/verify_v3_2_7_release.py",
    "scripts/test_verify_v3_2_7_release.py",
    "scripts/verify_v3_2_8_release.py",
    "scripts/test_verify_v3_2_8_release.py",
    "scripts/patch_export_retirement_nginx.py",
    "scripts/test_patch_export_retirement_nginx.py",
    "scripts/oss_local_export.py",
    "scripts/test_oss_local_export.py",
    "v2-api/scripts/preview_v3_1_backfill.py",
    "v2-api/scripts/verify_v3_1_release.py",
    "v2-api/app/services/photo_storage.py",
    "v2-api/tests/test_photo_storage.py",
    "v2-api/alembic/versions/0006_group_barcode_verification.py",
    "v2-api/alembic/versions/0007_group_barcode_verification_lease_token.py",
    "v2-api/alembic/versions/0008_delivery_cache_jobs.py",
    "v2-api/alembic/versions/0009_delivery_cache_fix3.py",
    "v2-api/alembic/versions/0010_auto_archive_queue_state.py",
    "v2-api/alembic/versions/0011_delivery_package_jobs.py",
    "v2-api/alembic/versions/0012_delivery_package_group_ids_gin.py",
    "v2-api/alembic/versions/0013_data_center_query_indexes.py",
    "v2-api/alembic/versions/0014_export_center_jobs.py",
    "v2-api/alembic/versions/0015_collector_transfer_workbench.py",
    "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py",
    "v2-api/app/api/routes/collector_transfer.py",
    "v2-api/app/domain/collector_transfer.py",
    "v2-api/app/services/collector_transfer.py",
    "v2-api/tests/test_collector_transfer_api.py",
    "v2-api/tests/test_collector_transfer_domain.py",
    "v2-api/tests/test_collector_transfer_postgres_integration.py",
    "v2-api/tests/test_collector_transfer_service.py",
    "v2-api/tests/test_collector_transfer_scale.py",
    "v2-web/src/components/Code128Barcode.vue",
    "v2-web/src/features/collectorTransfer/state.ts",
    "v2-web/src/layouts/AppLayout.vue",
    "v2-web/src/router/index.ts",
    "v2-web/src/router/staticPages.ts",
    "v2-web/src/views/CollectorInventoryView.vue",
    "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts",
    "v2-web/src/views/ReviewRephotoWorkbenchView.vue",
    "v2-web/src/views/__tests__/CollectorInventoryRouting.spec.ts",
    "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
    "v2-web/tests/collector-transfer-state.test.ts",
    "scripts/production_backup.sh",
    "scripts/cleanup_old_releases.sh",
    "scripts/production_health_check.py",
    "ops/releases/README.md",
    "ops/releases/V3.0.81.md",
    "ops/releases/V3.0.84.md",
    "ops/releases/V3.1.1.md",
    "ops/releases/V3.1.0.md",
    "ops/releases/V3.2.0.md",
    "ops/releases/V3.2.1.md",
    "ops/releases/V3.2.2.md",
    "ops/releases/V3.2.3.md",
    "ops/releases/V3.2.4.md",
    "ops/releases/V3.2.5.md",
    "ops/releases/V3.2.6.md",
    "ops/releases/V3.2.7.md",
    "ops/releases/V3.2.8.md",
    "ops/releases/V3.0.83.md",
    "ops/releases/V3.0.82.md",
    "ops/releases/V3.0.80.md",
    "ops/releases/V3.0.79.md",
    "ops/releases/V3.0.78.md",
    "ops/releases/V3.0.77.md",
    "ops/releases/V3.0.76.md",
    "ops/releases/V3.0.75.md",
    "ops/releases/V3.0.74.md",
    "ops/releases/V3.0.73.md",
    "ops/releases/V3.0.72.md",
    "ops/releases/V3.0.71.md",
    "ops/releases/V3.0.70.md",
    "ops/releases/V3.0.69.md",
    "ops/releases/V3.0.68.md",
    "ops/releases/V3.0.67.md",
    "ops/releases/V3.0.66.md",
    "ops/releases/V3.0.65.md",
    "ops/releases/V3.0.64.md",
    "ops/releases/V3.0.63.md",
    "ops/releases/V3.0.62.md",
    "ops/releases/V3.0.61.md",
    "ops/releases/V3.0.60.md",
    "ops/releases/V3.0.59.md",
    "ops/releases/V3.0.58.md",
    "ops/releases/V3.0.56.md",
    "ops/releases/V3.0.55.md",
    "ops/releases/V3.0.54.md",
    "ops/releases/V3.0.53.md",
    "ops/releases/V3.0.52.md",
    "ops/releases/V3.0.51.md",
    "ops/releases/V3.0.50.md",
    "ops/releases/V3.0.49.md",
    "ops/releases/V3.0.48.md",
    "ops/releases/V3.0.47.md",
    "ops/releases/V3.0.46.md",
    "ops/releases/V3.0.45.md",
    "ops/releases/V3.0.44.md",
    "ops/releases/V3.0.43.md",
    "ops/releases/V3.0.42.md",
    "ops/releases/V3.0.41.md",
    "ops/releases/V3.0.40.md",
    "ops/releases/V3.0.39.md",
    "ops/releases/V3.0.38.md",
    "ops/releases/V3.0.37.md",
    "ops/incidents/P0-template.md",
    "v2-api/app/main.py",
    "v2-api/app/api/routes/groups.py",
    "v2-api/app/api/routes/exports.py",
    "v2-api/app/schemas/data_center.py",
    "v2-api/app/schemas/export_center.py",
    "v2-api/app/services/construction_task_rules.py",
    "v2-api/app/services/data_center.py",
    "v2-api/app/services/export_center.py",
    "v2-api/app/services/export_retirement.py",
    "v2-api/app/services/external_photo_oss_migration.py",
    "v2-api/app/static/favicon.svg",
    "v2-api/app/static/vendor/quagga.min.js",
    "v2-api/app/static/vue/index.html",
    "v2-api/app/static/vue/version.json",
    "v2-api/app/static/demo-assets/review-photo-1.svg",
    "v2-api/app/static/demo-assets/review-photo-2.svg",
    "v2-api/app/static/demo-assets/review-photo-3.svg",
    "v2-api/app/static/demo-assets/review-photo-4.svg",
    "v2-api/requirements.txt",
    "v2-api/requirements-dev.txt",
    "v2-api/tests/test_api.py",
    "v2-api/tests/test_recompute_photo_barcode_checks.py",
    "v2-api/tests/test_export_retirement.py",
    "v2-api/tests/test_external_photo_oss_migration.py",
    "v2-api/tests/test_migrate_external_photos_to_oss.py",
    "v2-api/tests/test_oss_export_manifest.py",
    "v2-api/scripts/recompute_photo_barcode_checks.py",
    "v2-api/scripts/migrate_json_to_postgres.py",
    "v2-api/scripts/migrate_photos_to_oss.py",
    "v2-api/scripts/migrate_external_photos_to_oss.py",
    "v2-api/scripts/build_oss_export_manifest.py",
    "v2-api/scripts/verify_task_review_performance.py",
    "v2-web/Dockerfile",
    "v2-web/package.json",
    "v2-web/src/version.json",
    "v2-web/src/main.ts",
    "v2-web/src/components/data-center/DataCenterFilters.vue",
    "v2-web/src/components/data-center/DataCenterReviewDialog.vue",
    "v2-web/src/views/GlobalSearchView.vue",
    "v2-web/src/composables/useDataCenterQuery.ts",
    "v2-web/src/utils/dataCenterDrilldown.ts",
    "v2-web/src/components/InstallerKpiDialog.vue",
    "v2-web/src/utils/installerKpi.ts",
} | V328_CONTRACT_INPUTS | V3210_CONTRACT_INPUTS | V3211_CONTRACT_INPUTS | V3212_CONTRACT_INPUTS | V3213_CONTRACT_INPUTS | V3214_CONTRACT_INPUTS | V3215_CONTRACT_INPUTS | V3216_CONTRACT_INPUTS | V3217_CONTRACT_INPUTS | V3218_CONTRACT_INPUTS | V3219_CONTRACT_INPUTS | V3220_CONTRACT_INPUTS

V3210_ONLY_REQUIRED_FILES = frozenset(
    {
        "docs/AGENT_REQUIRED_READING.md",
        "docs/superpowers/specs/2026-08-26-unified-terminal-review-rephoto-workbench-design.md",
        "ops/releases/V3.2.9.md",
        "ops/releases/V3.2.10.md",
        "scripts/verify_v3_2_10_release.py",
        "scripts/test_verify_v3_2_10_release.py",
        "v2-api/app/domain/terminal_review.py",
        "v2-api/tests/test_data_center_review.py",
        "v2-api/tests/test_terminal_review_domain.py",
        "v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue",
        "v2-web/src/views/ReviewRephotoWorkbenchView.vue",
        "v2-web/src/views/__tests__/CollectorInventoryRouting.spec.ts",
        "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
    }
)
V328_WORKBENCH_REQUIRED_FILES = frozenset(
    {
        "v2-web/src/views/CollectorWorkbenchView.vue",
        "v2-web/src/views/__tests__/CollectorWorkbenchView.spec.ts",
    }
)
V328_REQUIRED_FILES = frozenset(
    (
        REQUIRED_FILES
        - V3210_ONLY_REQUIRED_FILES
        - (V3212_CONTRACT_INPUTS - V3211_CONTRACT_INPUTS)
        - (V3213_CONTRACT_INPUTS - V3212_CONTRACT_INPUTS)
        - (V3214_CONTRACT_INPUTS - V3213_CONTRACT_INPUTS)
        - (V3215_CONTRACT_INPUTS - V3214_CONTRACT_INPUTS)
        - (V3216_CONTRACT_INPUTS - V3215_CONTRACT_INPUTS)
        - (V3217_CONTRACT_INPUTS - V3216_CONTRACT_INPUTS)
        - (V3218_CONTRACT_INPUTS - V3217_CONTRACT_INPUTS)
        - (V3219_CONTRACT_INPUTS - V3218_CONTRACT_INPUTS)
        - (V3220_CONTRACT_INPUTS - V3219_CONTRACT_INPUTS)
    )
    | V328_WORKBENCH_REQUIRED_FILES
)


def required_files_for_version(version: str) -> frozenset[str]:
    if version == "3.2.8":
        return V328_REQUIRED_FILES
    if version == "3.2.10":
        return frozenset(
            REQUIRED_FILES
            - (V3211_CONTRACT_INPUTS - V3210_CONTRACT_INPUTS)
            - (V3212_CONTRACT_INPUTS - V3211_CONTRACT_INPUTS)
            - (V3213_CONTRACT_INPUTS - V3212_CONTRACT_INPUTS)
            - (V3214_CONTRACT_INPUTS - V3213_CONTRACT_INPUTS)
            - (V3215_CONTRACT_INPUTS - V3214_CONTRACT_INPUTS)
            - (V3216_CONTRACT_INPUTS - V3215_CONTRACT_INPUTS)
            - (V3217_CONTRACT_INPUTS - V3216_CONTRACT_INPUTS)
            - (V3218_CONTRACT_INPUTS - V3217_CONTRACT_INPUTS)
            - (V3219_CONTRACT_INPUTS - V3218_CONTRACT_INPUTS)
            - (V3220_CONTRACT_INPUTS - V3219_CONTRACT_INPUTS)
        )
    if version == "3.2.11":
        return frozenset(
            (
                REQUIRED_FILES
                - (V3212_CONTRACT_INPUTS - V3211_CONTRACT_INPUTS)
                - (V3213_CONTRACT_INPUTS - V3212_CONTRACT_INPUTS)
                - (V3214_CONTRACT_INPUTS - V3213_CONTRACT_INPUTS)
                - (V3215_CONTRACT_INPUTS - V3214_CONTRACT_INPUTS)
                - (V3216_CONTRACT_INPUTS - V3215_CONTRACT_INPUTS)
                - (V3217_CONTRACT_INPUTS - V3216_CONTRACT_INPUTS)
                - (V3218_CONTRACT_INPUTS - V3217_CONTRACT_INPUTS)
                - (V3219_CONTRACT_INPUTS - V3218_CONTRACT_INPUTS)
                - (V3220_CONTRACT_INPUTS - V3219_CONTRACT_INPUTS)
            )
            | V3211_ANDROID_SCANNER_INPUTS
        )
    if version == "3.2.12":
        return frozenset(
            REQUIRED_FILES
            - (V3213_CONTRACT_INPUTS - V3212_CONTRACT_INPUTS)
            - (V3214_CONTRACT_INPUTS - V3213_CONTRACT_INPUTS)
            - (V3215_CONTRACT_INPUTS - V3214_CONTRACT_INPUTS)
            - (V3216_CONTRACT_INPUTS - V3215_CONTRACT_INPUTS)
            - (V3217_CONTRACT_INPUTS - V3216_CONTRACT_INPUTS)
            - (V3218_CONTRACT_INPUTS - V3217_CONTRACT_INPUTS)
            - (V3219_CONTRACT_INPUTS - V3218_CONTRACT_INPUTS)
            - (V3220_CONTRACT_INPUTS - V3219_CONTRACT_INPUTS)
        )
    if version == "3.2.13":
        return frozenset(
            REQUIRED_FILES
            - (V3214_CONTRACT_INPUTS - V3213_CONTRACT_INPUTS)
            - (V3215_CONTRACT_INPUTS - V3214_CONTRACT_INPUTS)
            - (V3216_CONTRACT_INPUTS - V3215_CONTRACT_INPUTS)
            - (V3217_CONTRACT_INPUTS - V3216_CONTRACT_INPUTS)
            - (V3218_CONTRACT_INPUTS - V3217_CONTRACT_INPUTS)
            - (V3219_CONTRACT_INPUTS - V3218_CONTRACT_INPUTS)
            - (V3220_CONTRACT_INPUTS - V3219_CONTRACT_INPUTS)
        )
    if version == "3.2.14":
        return frozenset(
            REQUIRED_FILES
            - (V3215_CONTRACT_INPUTS - V3214_CONTRACT_INPUTS)
            - (V3216_CONTRACT_INPUTS - V3215_CONTRACT_INPUTS)
            - (V3217_CONTRACT_INPUTS - V3216_CONTRACT_INPUTS)
            - (V3218_CONTRACT_INPUTS - V3217_CONTRACT_INPUTS)
            - (V3219_CONTRACT_INPUTS - V3218_CONTRACT_INPUTS)
            - (V3220_CONTRACT_INPUTS - V3219_CONTRACT_INPUTS)
        )
    if version == "3.2.15":
        return frozenset(
            REQUIRED_FILES
            - (V3216_CONTRACT_INPUTS - V3215_CONTRACT_INPUTS)
            - (V3217_CONTRACT_INPUTS - V3216_CONTRACT_INPUTS)
            - (V3218_CONTRACT_INPUTS - V3217_CONTRACT_INPUTS)
            - (V3219_CONTRACT_INPUTS - V3218_CONTRACT_INPUTS)
            - (V3220_CONTRACT_INPUTS - V3219_CONTRACT_INPUTS)
        )
    if version == "3.2.16":
        return frozenset(
            REQUIRED_FILES
            - (V3217_CONTRACT_INPUTS - V3216_CONTRACT_INPUTS)
            - (V3218_CONTRACT_INPUTS - V3217_CONTRACT_INPUTS)
            - (V3219_CONTRACT_INPUTS - V3218_CONTRACT_INPUTS)
            - (V3220_CONTRACT_INPUTS - V3219_CONTRACT_INPUTS)
        )
    if version == "3.2.17":
        return frozenset(
            REQUIRED_FILES
            - (V3218_CONTRACT_INPUTS - V3217_CONTRACT_INPUTS)
            - (V3219_CONTRACT_INPUTS - V3218_CONTRACT_INPUTS)
            - (V3220_CONTRACT_INPUTS - V3219_CONTRACT_INPUTS)
        )
    if version == "3.2.18":
        return frozenset(
            REQUIRED_FILES
            - (V3219_CONTRACT_INPUTS - V3218_CONTRACT_INPUTS)
            - (V3220_CONTRACT_INPUTS - V3219_CONTRACT_INPUTS)
        )
    if version == "3.2.19":
        return frozenset(REQUIRED_FILES - (V3220_CONTRACT_INPUTS - V3219_CONTRACT_INPUTS))
    if version == "3.2.20":
        return frozenset(REQUIRED_FILES)
    if version == "3.2.21":
        return frozenset(REQUIRED_FILES | V3221_CONTRACT_INPUTS)
    if version == "3.2.22":
        return frozenset(REQUIRED_FILES | V3221_CONTRACT_INPUTS | V3222_CONTRACT_INPUTS)
    if version == "3.2.23":
        return frozenset(REQUIRED_FILES | V3221_CONTRACT_INPUTS | V3222_CONTRACT_INPUTS | V3223_CONTRACT_INPUTS)
    if version == "3.2.24":
        return frozenset(
            REQUIRED_FILES
            | V3221_CONTRACT_INPUTS
            | V3222_CONTRACT_INPUTS
            | V3223_CONTRACT_INPUTS
            | V3224_CONTRACT_INPUTS
        )
    if version == "3.2.25":
        return frozenset(
            REQUIRED_FILES
            | V3221_CONTRACT_INPUTS
            | V3222_CONTRACT_INPUTS
            | V3223_CONTRACT_INPUTS
            | V3224_CONTRACT_INPUTS
            | V3225_CONTRACT_INPUTS
        )
    if version == "3.2.26":
        return frozenset(
            (
                REQUIRED_FILES
                | V3221_CONTRACT_INPUTS
                | V3222_CONTRACT_INPUTS
                | V3223_CONTRACT_INPUTS
                | V3224_CONTRACT_INPUTS
                | V3225_CONTRACT_INPUTS
                | V3226_CONTRACT_INPUTS
            )
            - V3226_RETIRED_BACKGROUND_BARCODE_FILES
        )
    if version == "3.2.27":
        return frozenset(
            (
                REQUIRED_FILES
                | V3221_CONTRACT_INPUTS
                | V3222_CONTRACT_INPUTS
                | V3223_CONTRACT_INPUTS
                | V3224_CONTRACT_INPUTS
                | V3225_CONTRACT_INPUTS
                | V3226_CONTRACT_INPUTS
                | V3227_CONTRACT_INPUTS
            )
            - V3226_RETIRED_BACKGROUND_BARCODE_FILES
        )
    if version == "3.2.28":
        return frozenset(
            (
                REQUIRED_FILES
                | V3221_CONTRACT_INPUTS
                | V3222_CONTRACT_INPUTS
                | V3223_CONTRACT_INPUTS
                | V3224_CONTRACT_INPUTS
                | V3225_CONTRACT_INPUTS
                | V3226_CONTRACT_INPUTS
                | V3227_CONTRACT_INPUTS
                | V3228_CONTRACT_INPUTS
            )
            - V3226_RETIRED_BACKGROUND_BARCODE_FILES
        )
    fail(f"Release manifest Version must match a supported archived source contract: {version}")


def forbidden_files_for_version(version: str) -> frozenset[str]:
    if version in {"3.2.26", "3.2.27", "3.2.28"}:
        return V3226_RETIRED_BACKGROUND_BARCODE_FILES
    return frozenset()

RUNTIME_VERSION_ARTIFACT = "v2-api/app/static/vue/version.json"
SOURCE_VERSION_ARTIFACT = "v2-web/src/version.json"
MANIFEST_VERSION_LINE_PATTERN = re.compile(r"^- Version:\s*(?P<version>.*?)\s*$", re.MULTILINE)
SEMANTIC_VERSION_PATTERN = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")
STATIC_TITLE_PATTERN = re.compile(
    r"<title>\s*Module Manager V(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))\s*</title>",
    re.IGNORECASE,
)
ENTRY_ATTESTATION_PATTERN = re.compile(
    rb'\AglobalThis\.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__=\{"version":"'
    rb"(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))"
    rb'"\};\n'
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
SOURCE_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
RELEASE_MARKDOWN_STALE_PATTERNS = (
    ("legacy final-delivery-ready release name", re.compile(r"final-delivery-ready", re.IGNORECASE)),
    ("legacy client-release package path", re.compile(r"build[\\/]client-release", re.IGNORECASE)),
    ("obsolete 91 passed evidence", re.compile(r"\b91 passed\b", re.IGNORECASE)),
    (
        "retired unmatched direct-group workflow",
        re.compile(
            r"(?:空白组(?:可先)?创建为未关联终端|创建为关联终端的资料组|新建空资料组|直接关联终端)",
            re.IGNORECASE,
        ),
    ),
    ("retired upload-images endpoint", re.compile(r"(?:`|/)upload-images(?:`|\b)", re.IGNORECASE)),
    ("retired unmatched page route", re.compile(r"(?<!local-test)/unmatched(?:\b|`)", re.IGNORECASE)),
)
OPERATIONAL_RELEASE_VERSION_PATTERNS = (
    re.compile(
        r"(?:build-client-release|run-client-acceptance-gate)\.ps1\s+-Version\s+"
        r"(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))",
        re.IGNORECASE,
    ),
    re.compile(
        r"module-manager-v2-server-(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))\.zip",
        re.IGNORECASE,
    ),
)
HISTORICAL_RELEASE_RECORD_PATTERN = re.compile(r"^ops/releases/V\d+\.\d+\.\d+\.md$")
VERSION_LOCKED_HISTORICAL_DOCUMENTS = {
    "docs/CLIENT_ACCEPTANCE_REPORT.md": "3.2.2",
    "docs/CLIENT_FINAL_AUDIT.md": "3.2.0",
    "docs/superpowers/plans/2026-08-29-v3-2-16-review-claim-hotfix.md": "3.2.16",
    "docs/superpowers/plans/2026-08-29-v3-2-17-anomaly-export-release.md": "3.2.17",
    "docs/superpowers/plans/2026-08-29-v3-2-18-approved-exception-hotfix.md": "3.2.18",
    "docs/superpowers/plans/2026-08-30-v3-2-19-meter-dedup-release.md": "3.2.19",
    "docs/superpowers/plans/2026-08-30-v3-2-20-device-display-hotfix.md": "3.2.20",
    "docs/superpowers/specs/2026-08-30-bulk-anomaly-approval.md": "3.2.21",
    "docs/superpowers/plans/2026-08-30-bulk-anomaly-approval.md": "3.2.21",
}
VERSION_LOCKED_HISTORICAL_DOCUMENT_IDENTITIES = {
    "docs/CLIENT_FINAL_AUDIT.md": (
        "# V3.2.0 生产发布审计",
        "V3.2.0 是当前公网生产基线",
    ),
}

FORBIDDEN_PARTS = {
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    ".vite",
    "data",
    "uploads",
    "node_modules",
    "dist",
    "coverage",
    "htmlcov",
    "test-results",
    "playwright-report",
    ".nyc_output",
    "build",
    "backups",
    "secrets",
    "delivery-cache",
    "delivery_cache",
    "migration-reports",
    "migration_reports",
    "allowlists",
    "module-manager-exports",
}

FORBIDDEN_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".sql",
    ".dump",
    ".db",
    ".log",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
}

FORBIDDEN_NAMES = {
    ".coverage",
    "coverage.xml",
    "junit.xml",
    "uv.lock",
}
FORBIDDEN_OPERATIONAL_STEMS = {
    "allowed-hosts",
    "allowed_hosts",
    "migration-report",
    "migration_report",
}
FORBIDDEN_OPERATIONAL_ARCHIVE_PREFIXES = (
    "oss-local-export-",
    "oss_local_export_",
)


def is_forbidden_release_path(name: str) -> bool:
    normalized_name = name.replace("\\", "/").casefold()
    components = tuple(
        component
        for component in normalized_name.split("/")
        if component
    )
    if not components:
        return False
    if any(
        component in FORBIDDEN_PARTS
        or component == ".env"
        or component.startswith(".env.")
        for component in components
    ):
        return True

    leaf_name = components[-1]
    leaf_path = PurePosixPath(leaf_name)
    return (
        leaf_name in FORBIDDEN_NAMES
        or leaf_path.suffix in FORBIDDEN_SUFFIXES
        or leaf_path.stem in FORBIDDEN_OPERATIONAL_STEMS
        or leaf_path.suffix == ".zip"
    )


def load_release_truth_parser():
    path = Path(__file__).with_name("verify_release_sop.py")
    spec = importlib.util.spec_from_file_location("package_release_truth", path)
    if spec is None or spec.loader is None:
        fail("Unable to load shared release truth parser")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_v328_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v328-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        for relative_path in V328_CONTRACT_INPUTS:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))

        verifier_path = extracted_root / "scripts" / "verify_v3_2_8_release.py"
        spec = importlib.util.spec_from_file_location("archive_v328_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.8 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.8 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3210_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3210-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        for relative_path in V3210_CONTRACT_INPUTS:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))

        verifier_path = extracted_root / "scripts" / "verify_v3_2_10_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3210_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.10 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.10 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3211_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3211-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        for relative_path in V3211_CONTRACT_INPUTS:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))

        verifier_path = extracted_root / "scripts" / "verify_v3_2_11_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3211_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.11 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.11 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3212_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3212-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3212_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))

        verifier_path = extracted_root / "scripts" / "verify_v3_2_12_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3212_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.12 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.12 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3213_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3213-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3213_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))

        verifier_path = extracted_root / "scripts" / "verify_v3_2_13_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3213_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.13 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.13 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3214_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3214-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3214_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))

        verifier_path = extracted_root / "scripts" / "verify_v3_2_14_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3214_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.14 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.14 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3215_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3215-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3215_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))

        verifier_path = extracted_root / "scripts" / "verify_v3_2_15_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3215_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.15 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.15 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3216_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3216-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3216_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))

        verifier_path = extracted_root / "scripts" / "verify_v3_2_16_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3216_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.16 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.16 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3217_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3217-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3217_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))

        verifier_path = extracted_root / "scripts" / "verify_v3_2_17_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3217_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.17 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.17 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3218_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3218-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3218_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))

        verifier_path = extracted_root / "scripts" / "verify_v3_2_18_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3218_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.18 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.18 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3219_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3219-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3219_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))

        verifier_path = extracted_root / "scripts" / "verify_v3_2_19_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3219_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.19 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.19 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3220_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3220-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3220_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))

        verifier_path = extracted_root / "scripts" / "verify_v3_2_20_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3220_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.20 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.20 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3221_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3221-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3221_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))

        verifier_path = extracted_root / "scripts" / "verify_v3_2_21_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3221_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.21 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.21 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3222_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3222-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3222_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))

        verifier_path = extracted_root / "scripts" / "verify_v3_2_22_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3222_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.22 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.22 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3223_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3223-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3223_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))
        verifier_path = extracted_root / "scripts" / "verify_v3_2_23_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3223_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.23 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.23 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3224_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3224-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3224_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))
        verifier_path = extracted_root / "scripts" / "verify_v3_2_24_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3224_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.24 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.24 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3225_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3225-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3225_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))
        verifier_path = extracted_root / "scripts" / "verify_v3_2_25_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3225_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.25 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.25 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3226_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3226-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3226_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))
        verifier_path = extracted_root / "scripts" / "verify_v3_2_26_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3226_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.26 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.26 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3227_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3227-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3227_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))
        verifier_path = extracted_root / "scripts" / "verify_v3_2_27_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3227_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.27 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.27 archive source contract failed: " + " | ".join(failures))
        return module


def verify_v3228_archive_source_contract(archive: zipfile.ZipFile):
    with tempfile.TemporaryDirectory(prefix="module-manager-v3228-contract-") as temporary_root:
        extracted_root = Path(temporary_root)
        migration_members = {
            name
            for name in archive.namelist()
            if PurePosixPath(name).parent.as_posix() == "v2-api/alembic/versions"
            and PurePosixPath(name).suffix == ".py"
        }
        for relative_path in V3228_CONTRACT_INPUTS | migration_members:
            target = extracted_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative_path))
        verifier_path = extracted_root / "scripts" / "verify_v3_2_28_release.py"
        spec = importlib.util.spec_from_file_location("archive_v3228_release_contract", verifier_path)
        if spec is None or spec.loader is None:
            fail("Unable to load archived V3.2.28 release verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        failures = module.collect_failures(extracted_root, "source")
        if failures:
            fail("V3.2.28 archive source contract failed: " + " | ".join(failures))
        return module


def fail(message: str) -> None:
    raise AssertionError(message)


GENERATED_SOURCE_MEMBERS = frozenset(("SOURCE_COMMIT",))
SOURCE_BOUND_LF_SUFFIXES = frozenset(
    (
        ".conf",
        ".css",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".md",
        ".mjs",
        ".mts",
        ".ps1",
        ".py",
        ".service",
        ".sh",
        ".svg",
        ".timer",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".vue",
        ".yaml",
        ".yml",
    )
)
SOURCE_BOUND_LF_NAMES = frozenset((".gitattributes", "Dockerfile"))


def tracked_names_at_commit(source_commit: str) -> set[str]:
    repository_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", source_commit],
        cwd=repository_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        fail(f"Unable to inspect SOURCE_COMMIT {source_commit}: {result.stderr.strip()}")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def verify_archive_members_are_tracked(names: set[str], source_commit: str) -> None:
    tracked_names = tracked_names_at_commit(source_commit)
    unexpected = sorted(
        name
        for name in names - tracked_names - GENERATED_SOURCE_MEMBERS
    )
    if unexpected:
        fail("Release archive members not tracked by SOURCE_COMMIT: " + ", ".join(unexpected[:20]))


def canonical_source_bound_bytes(name: str, content: bytes) -> bytes:
    path = PurePosixPath(name)
    if path.name in SOURCE_BOUND_LF_NAMES or path.suffix.casefold() in SOURCE_BOUND_LF_SUFFIXES:
        return content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if path.name.endswith(".conf.example"):
        return content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return content


def verify_archive_members_match_source_commit(
    archive: zipfile.ZipFile,
    names: set[str],
    source_commit: str,
) -> None:
    verify_archive_members_are_tracked(names, source_commit)
    repository_root = Path(__file__).resolve().parents[1]
    tracked_names = tracked_names_at_commit(source_commit)
    mismatches: list[str] = []
    for name in sorted(names & tracked_names):
        if name in GENERATED_SOURCE_MEMBERS:
            continue
        result = subprocess.run(
            ["git", "show", f"{source_commit}:{name}"],
            cwd=repository_root,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            fail(f"Unable to read SOURCE_COMMIT blob {name}")
        if canonical_source_bound_bytes(name, archive.read(name)) != result.stdout:
            mismatches.append(name)
    if mismatches:
        fail(
            "Release archive member bytes do not match SOURCE_COMMIT: "
            + ", ".join(mismatches[:20])
        )


def canonical_zip_member_name(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if stat.S_ISLNK(info.external_attr >> 16):
        fail("Release zip must not contain symbolic links")
    if info.is_dir() and name.endswith("/"):
        name = name[:-1]
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or ":" in name
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
    ):
        fail("Release zip members must use canonical relative POSIX paths")
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        fail("Release zip members must use canonical relative POSIX paths")
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name:
        fail("Release zip members must use canonical relative POSIX paths")
    return name


def validated_zip_file_names(archive: zipfile.ZipFile) -> list[str]:
    canonical_members: list[tuple[zipfile.ZipInfo, str]] = []
    casefold_names: dict[str, str] = {}
    exact_names: set[str] = set()
    for info in archive.infolist():
        name = canonical_zip_member_name(info)
        if name in exact_names:
            fail(f"Release zip contains duplicate file names: {name}")
        exact_names.add(name)
        folded = name.casefold()
        previous = casefold_names.get(folded)
        if previous is not None and previous != name:
            fail(f"Release zip contains case-insensitive file names: {previous}, {name}")
        casefold_names[folded] = name
        canonical_members.append((info, name))
    return [name for info, name in canonical_members if not info.is_dir()]


def verify_release_markdown_text(path: str, content: str, package_version: str) -> None:
    for marker_name, marker in RELEASE_MARKDOWN_STALE_PATTERNS:
        if marker.search(content):
            fail(f"{path} contains stale release-document marker: {marker_name}")
    if (
        HISTORICAL_RELEASE_RECORD_PATTERN.fullmatch(path)
        and path != f"ops/releases/V{package_version}.md"
    ):
        return
    for marker in VERSION_LOCKED_HISTORICAL_DOCUMENT_IDENTITIES.get(path, ()):
        if marker not in content:
            fail(f"{path} missing version-locked historical identity marker: {marker}")
    expected_version = VERSION_LOCKED_HISTORICAL_DOCUMENTS.get(path, package_version)
    for version_pattern in OPERATIONAL_RELEASE_VERSION_PATTERNS:
        for match in version_pattern.finditer(content):
            if match.group("version") != expected_version:
                fail(
                    f"{path} contains non-current release version "
                    f"{match.group('version')}; expected {expected_version}"
                )
    if path == "README.md":
        expected_build_command = f".\\scripts\\build-client-release.ps1 -Version {package_version}"
        if expected_build_command not in content:
            fail("README.md build command must use the current package version")


def verify_release_markdown_documents(
    archive: zipfile.ZipFile,
    names: set[str],
    package_version: str,
) -> None:
    for path in sorted(name for name in names if name.endswith(".md")):
        try:
            content = archive.read(path).decode("utf-8")
        except UnicodeDecodeError as exc:
            fail(f"{path} must be valid UTF-8 Markdown: {exc}")
        verify_release_markdown_text(path, content, package_version)


class VueModuleEntryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.module_sources: list[str] = []
        self.script_count = 0
        self.has_duplicate_attributes = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "script":
            return
        self.script_count += 1
        attributes: dict[str, str | None] = {}
        for name, value in attrs:
            normalized_name = name.casefold()
            if normalized_name in attributes:
                self.has_duplicate_attributes = True
            attributes[normalized_name] = value
        if (attributes.get("type") or "").casefold() != "module":
            return
        source = (attributes.get("src") or "").strip()
        if source:
            self.module_sources.append(source)


def vue_entry_bundle_path(static_index: str) -> str:
    parser = VueModuleEntryParser()
    parser.feed(static_index)
    if parser.has_duplicate_attributes or parser.script_count != 1 or len(parser.module_sources) != 1:
        fail("Vue static index must contain exactly one executable module entry")
    source = urlsplit(parser.module_sources[0])
    if source.scheme or source.netloc or source.query or source.fragment:
        fail("Vue module entry bundle must be an unambiguous local path")
    if not source.path.startswith("/vue/"):
        fail("Vue module entry bundle must be rooted under /vue/")
    relative_path = PurePosixPath(source.path.removeprefix("/vue/"))
    if (
        relative_path.is_absolute()
        or not relative_path.parts
        or ".." in relative_path.parts
        or relative_path.suffix != ".js"
    ):
        fail("Vue module entry bundle must be a JavaScript file under /vue/")
    return f"v2-api/app/static/vue/{relative_path.as_posix()}"


def entry_bundle_version(entry_bundle: bytes) -> str:
    match = ENTRY_ATTESTATION_PATTERN.match(entry_bundle)
    if match is None:
        fail("Vue entry bundle must start with the executable build attestation")
    return match.group("version").decode("ascii")


def runtime_entry_attestation(value: str) -> dict[str, object]:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                fail("Vue runtime attestation must contain unambiguous fields")
            result[key] = item
        return result

    try:
        payload = json.loads(value, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AssertionError("Vue runtime attestation must be valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"version", "entry", "entrySha256", "assets"}:
        fail("Vue runtime attestation must bind version, entry, entry SHA-256, and Vue assets")
    version = payload.get("version")
    entry = payload.get("entry")
    entry_sha256 = payload.get("entrySha256")
    assets = payload.get("assets")
    if not isinstance(version, str) or SEMANTIC_VERSION_PATTERN.fullmatch(version) is None:
        fail("Vue runtime attestation version must be semantic")
    if not isinstance(entry, str):
        fail("Vue runtime attestation entry must be a path")
    entry_path = PurePosixPath(entry)
    if entry_path.is_absolute() or ".." in entry_path.parts or not entry.startswith("assets/"):
        fail("Vue runtime attestation entry must be under assets/")
    if not isinstance(entry_sha256, str) or SHA256_PATTERN.fullmatch(entry_sha256) is None:
        fail("Vue runtime attestation entry SHA-256 must be exact")
    if not isinstance(assets, list) or not assets:
        fail("Vue asset manifest must contain at least one asset")
    normalized_assets: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict) or set(asset) != {"path", "size", "sha256"}:
            fail("Vue asset manifest entries must bind path, size, and SHA-256")
        path = asset.get("path")
        size = asset.get("size")
        sha256 = asset.get("sha256")
        if not isinstance(path, str) or not path or path == "version.json":
            fail("Vue asset manifest paths must identify files other than version.json")
        asset_path = PurePosixPath(path)
        if asset_path.is_absolute() or "." in asset_path.parts or ".." in asset_path.parts or "\\" in path:
            fail("Vue asset manifest paths must be canonical relative POSIX paths")
        if path in seen_paths:
            fail("Vue asset manifest paths must be unique")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            fail("Vue asset manifest sizes must be non-negative integers")
        if not isinstance(sha256, str) or SHA256_PATTERN.fullmatch(sha256) is None:
            fail("Vue asset manifest SHA-256 values must be exact")
        seen_paths.add(path)
        normalized_assets.append({"path": path, "size": size, "sha256": sha256})
    if [asset["path"] for asset in normalized_assets] != sorted(seen_paths):
        fail("Vue asset manifest must be sorted by path")
    return {"version": version, "entry": entry, "entrySha256": entry_sha256, "assets": normalized_assets}


def verify_vue_asset_manifest(
    archive: zipfile.ZipFile,
    names: set[str],
    runtime_attestation: dict[str, object],
) -> None:
    vue_prefix = "v2-api/app/static/vue/"
    archive_paths = {
        name.removeprefix(vue_prefix)
        for name in names
        if name.startswith(vue_prefix) and name != RUNTIME_VERSION_ARTIFACT
    }
    manifest_assets = runtime_attestation["assets"]
    if not isinstance(manifest_assets, list):
        fail("Vue asset manifest must be a list")
    manifest_by_path = {str(asset["path"]): asset for asset in manifest_assets}
    if set(manifest_by_path) != archive_paths:
        fail("Vue asset manifest file set must exactly match the release archive")
    for path, expected in manifest_by_path.items():
        content = archive.read(f"{vue_prefix}{path}")
        if len(content) != expected["size"]:
            fail(f"Vue asset manifest size mismatch: {path}")
        if hashlib.sha256(content).hexdigest() != expected["sha256"]:
            fail(f"Vue asset manifest SHA-256 mismatch: {path}")


def verify_package(zip_path: Path, *, expected_source_commit: str | None = None) -> None:
    if not zip_path.exists():
        fail(f"Release zip not found: {zip_path}")
    if zip_path.stat().st_size <= 0:
        fail(f"Release zip is empty: {zip_path}")

    with zipfile.ZipFile(zip_path) as archive:
        names = set(validated_zip_file_names(archive))
        bootstrap_missing = sorted({"SOURCE_COMMIT", "RELEASE_MANIFEST.md"} - names)
        if bootstrap_missing:
            fail("Missing required release files: " + ", ".join(bootstrap_missing))
        manifest = archive.read("RELEASE_MANIFEST.md").decode("utf-8")
        manifest_versions = [
            match.group("version")
            for match in MANIFEST_VERSION_LINE_PATTERN.finditer(manifest)
        ]
        if (
            len(manifest_versions) != 1
            or SEMANTIC_VERSION_PATTERN.fullmatch(manifest_versions[0]) is None
        ):
            fail("Release manifest must define exactly one semantic Version")
        package_version = manifest_versions[0]
        if package_version not in {"3.2.8", "3.2.10", "3.2.11", "3.2.12", "3.2.13", "3.2.14", "3.2.15", "3.2.16", "3.2.17", "3.2.18", "3.2.19", "3.2.20", "3.2.21", "3.2.22", "3.2.23", "3.2.24", "3.2.25", "3.2.26", "3.2.27", "3.2.28"}:
            fail(
                "Release manifest Version must match a supported archived source contract: "
                "3.2.8, 3.2.10, 3.2.11, 3.2.12, 3.2.13, 3.2.14, 3.2.15, 3.2.16, 3.2.17, 3.2.18, 3.2.19, 3.2.20, 3.2.21, 3.2.22, 3.2.23, 3.2.24, 3.2.25, 3.2.26, 3.2.27, or 3.2.28"
            )
        required_files = required_files_for_version(package_version)
        missing = sorted(required_files - names)
        if missing:
            fail("Missing required release files: " + ", ".join(missing))
        retired_background_files = sorted(forbidden_files_for_version(package_version) & names)
        if retired_background_files:
            fail(
                "Release contains retired background barcode entrypoints: "
                + ", ".join(retired_background_files)
            )
        source_commit = archive.read("SOURCE_COMMIT").decode("ascii").strip().lower()
        if SOURCE_COMMIT_PATTERN.fullmatch(source_commit) is None:
            fail("SOURCE_COMMIT must contain exactly one lowercase 40-character Git commit")
        if expected_source_commit is not None:
            normalized_expected_commit = expected_source_commit.strip().lower()
            if SOURCE_COMMIT_PATTERN.fullmatch(normalized_expected_commit) is None:
                fail("Expected source commit must be a 40-character Git commit")
            if source_commit != normalized_expected_commit:
                fail(
                    f"Packaged SOURCE_COMMIT {source_commit} does not match expected commit "
                    f"{normalized_expected_commit}"
                )
            verify_archive_members_match_source_commit(
                archive,
                names,
                normalized_expected_commit,
            )
        verify_release_markdown_documents(archive, names, package_version)
        static_index = (
            archive.read("v2-api/app/static/vue/index.html").decode("utf-8")
            if "v2-api/app/static/vue/index.html" in names
            else ""
        )
        entry_bundle_name = vue_entry_bundle_path(static_index)
        if entry_bundle_name not in names:
            fail(f"Vue module entry bundle is missing from release: {entry_bundle_name}")
        entry_bundle = archive.read(entry_bundle_name)
        vue_entry_version = entry_bundle_version(entry_bundle)
        release_truth = load_release_truth_parser()
        runtime_attestation = runtime_entry_attestation(
            archive.read(RUNTIME_VERSION_ARTIFACT).decode("utf-8")
        )
        verify_vue_asset_manifest(archive, names, runtime_attestation)
        compiled_vue_assets = b"\n".join(
            archive.read(name)
            for name in sorted(names)
            if name.startswith("v2-api/app/static/vue/assets/") and name.endswith(".js")
        )
        if b"/static/vendor/quagga.min.js?v=20260615-quagga2" not in compiled_vue_assets:
            fail("Vue production assets must retain the pinned collector QuaggaJS fallback")
        runtime_version = runtime_attestation["version"]
        source_version = release_truth.runtime_version_from_artifact(
            archive.read(SOURCE_VERSION_ARTIFACT).decode("utf-8")
        )
        agents = archive.read("AGENTS.md").decode("utf-8")
        release_records = {
            name: archive.read(name).decode("utf-8")
            for name in names
            if HISTORICAL_RELEASE_RECORD_PATTERN.fullmatch(name)
        }
        crlf_shell_scripts = sorted(
            name
            for name in names
            if name.endswith(".sh") and b"\r\n" in archive.read(name)
        )
        if crlf_shell_scripts:
            fail("Shell scripts must use LF line endings: " + ", ".join(crlf_shell_scripts[:20]))

    forbidden_hits: list[str] = []
    for name in names:
        if is_forbidden_release_path(name):
            forbidden_hits.append(name)
    if forbidden_hits:
        fail("Forbidden local/cache files found in release: " + ", ".join(sorted(forbidden_hits)[:20]))
    legacy_static_pages = sorted(
        name
        for name in names
        if name.startswith("v2-api/app/static/")
        and name.endswith(".html")
        and not name.startswith("v2-api/app/static/vue/")
    )
    if legacy_static_pages:
        fail("Legacy static HTML pages found in release: " + ", ".join(legacy_static_pages[:20]))
    for text in [
        "Production mode disables demo accounts by default",
        "Production mode disables /docs, /redoc, and /openapi.json by default",
        "Confirm /docs, /redoc, and /openapi.json return 404 in production",
        "Vue strict-native production pages are required",
        "PostgreSQL cutover audit must be reviewed before production deployment",
        "Production SOP files and release record templates are present",
    ]:
        if text not in manifest:
            fail(f"Release manifest missing production safety note: {text}")
    title_versions = [match.group("version") for match in STATIC_TITLE_PATTERN.finditer(static_index)]
    if title_versions != [package_version]:
        fail(f"Vue static index title must be V{package_version}")
    if runtime_version != package_version:
        fail("Vue built runtime version must match the release manifest Version")
    if source_version != runtime_version:
        fail("Vue source and built runtime versions must agree")
    if vue_entry_version != runtime_version:
        fail("Vue entry bundle version must match source and built runtime versions")
    expected_entry = entry_bundle_name.removeprefix("v2-api/app/static/vue/")
    if runtime_attestation["entry"] != expected_entry:
        fail("Vue runtime attestation must identify the index-referenced entry bundle")
    if hashlib.sha256(entry_bundle).hexdigest() != runtime_attestation["entrySha256"]:
        fail("Vue runtime attestation entry SHA-256 must match the referenced entry bundle")

    deployed_version = release_truth.deployed_production_baseline(agents)
    candidate_version = release_truth.release_candidate(agents)
    if candidate_version != f"V{package_version}":
        fail("Release manifest Version must match packaged AGENTS.md release candidate")
    release_truth.validate_release_lifecycle_records(
        lambda version: release_records[f"ops/releases/{version}.md"],
        deployed_version,
        candidate_version,
    )
    with zipfile.ZipFile(zip_path) as archive:
        if package_version == "3.2.28":
            archived_release = verify_v3228_archive_source_contract(archive)
        elif package_version == "3.2.27":
            archived_release = verify_v3227_archive_source_contract(archive)
        elif package_version == "3.2.26":
            archived_release = verify_v3226_archive_source_contract(archive)
        elif package_version == "3.2.25":
            archived_release = verify_v3225_archive_source_contract(archive)
        elif package_version == "3.2.24":
            archived_release = verify_v3224_archive_source_contract(archive)
        elif package_version == "3.2.23":
            archived_release = verify_v3223_archive_source_contract(archive)
        elif package_version == "3.2.22":
            archived_release = verify_v3222_archive_source_contract(archive)
        elif package_version == "3.2.21":
            archived_release = verify_v3221_archive_source_contract(archive)
        elif package_version == "3.2.20":
            archived_release = verify_v3220_archive_source_contract(archive)
        elif package_version == "3.2.19":
            archived_release = verify_v3219_archive_source_contract(archive)
        elif package_version == "3.2.18":
            archived_release = verify_v3218_archive_source_contract(archive)
        elif package_version == "3.2.17":
            archived_release = verify_v3217_archive_source_contract(archive)
        elif package_version == "3.2.16":
            archived_release = verify_v3216_archive_source_contract(archive)
        elif package_version == "3.2.15":
            archived_release = verify_v3215_archive_source_contract(archive)
        elif package_version == "3.2.14":
            archived_release = verify_v3214_archive_source_contract(archive)
        elif package_version == "3.2.13":
            archived_release = verify_v3213_archive_source_contract(archive)
        elif package_version == "3.2.12":
            archived_release = verify_v3212_archive_source_contract(archive)
        elif package_version == "3.2.11":
            archived_release = verify_v3211_archive_source_contract(archive)
        elif package_version == "3.2.10":
            archived_release = verify_v3210_archive_source_contract(archive)
        else:
            archived_release = verify_v328_archive_source_contract(archive)
    if archived_release.VERSION != package_version:
        fail("Archived release verifier version must match the release manifest Version")

    print(f"[OK] release zip exists: {zip_path}")
    print(f"[OK] release zip size: {zip_path.stat().st_size} bytes")
    print(f"[OK] required files: {len(required_files)}")
    print(f"[OK] source commit: {source_commit}")
    print("[OK] release manifest contains production safety notes")
    print("[OK] no forbidden local/cache files")


def default_latest_zip() -> Path:
    root = Path(__file__).resolve().parents[1]
    candidates = sorted(
        [
            *root.glob("build/server-release/module-manager-v2-server-*.zip"),
        ],
        key=lambda item: item.stat().st_mtime,
    )
    if not candidates:
        fail(f"No release zip found under {root / 'build'}")
    return candidates[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Module Manager V2 client release zip.")
    parser.add_argument("zip", nargs="?", type=Path, help="Release zip path. Defaults to the newest client release zip.")
    parser.add_argument(
        "--expected-source-commit",
        help="Require SOURCE_COMMIT in the archive to match this full Git commit.",
    )
    args = parser.parse_args()
    expected_source_commit = args.expected_source_commit
    if expected_source_commit is None:
        repository_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode != 0:
            fail("Official release verification requires the source Git repository or --expected-source-commit")
        expected_source_commit = result.stdout.strip()
    verify_package(
        args.zip or default_latest_zip(),
        expected_source_commit=expected_source_commit,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
