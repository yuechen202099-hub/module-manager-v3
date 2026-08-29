from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.2.16"
DISPLAY_VERSION = "V3.2.16"
DEPLOYED_BASELINE = "V3.2.15"
MAINTENANCE_BRANCH = "production/V3/3.2.16"
MIGRATION_REVISION = "20260824_0016"
RELEASE_PATH = "ops/releases/V3.2.16.md"
BASELINE_RELEASE_PATH = "ops/releases/V3.2.15.md"
ARCHIVE_PATH = "build/server-release/module-manager-v2-server-3.2.16.zip"
PRODUCTION_RECORD_SHA256 = "2417960478d1598b8f836104d4a5d22eb30f95f163e914dbc105327e2f2e16b7"
OPERATOR_PRODUCTION_MARKERS = (
    "当前生产 release：`/opt/module-manager-v2/releases/v3.2.15-20260828T144635Z`",
    "当前回滚 release：`/opt/module-manager-v2/releases/v3.2.14-20260828T113306Z`",
    "当前生产提交：`7cf23bfca2748da45b4d425cef42a6ba1928d500`",
)
VERIFICATION_PHASES = frozenset(("source", "package", "attestation"))
APPROVED_ALEMBIC_CHAIN = {
    "0001_initial_schema.py": ("20260609_0001", None),
    "0002_local_state_postgres_bridge.py": ("20260618_0002", "20260609_0001"),
    "0003_photo_import_dedup_fields.py": ("20260619_0003", "20260618_0002"),
    "0004_allow_five_construction_tasks.py": ("20260622_0004", "20260619_0003"),
    "0005_add_construction_priority.py": ("20260721_0005", "20260622_0004"),
    "0006_group_barcode_verification.py": ("20260722_0006", "20260721_0005"),
    "0007_group_barcode_verification_lease_token.py": ("20260722_0007", "20260722_0006"),
    "0008_delivery_cache_jobs.py": ("20260722_0008", "20260722_0007"),
    "0009_delivery_cache_fix3.py": ("20260722_0009", "20260722_0008"),
    "0010_auto_archive_queue_state.py": ("20260723_0010", "20260722_0009"),
    "0011_delivery_package_jobs.py": ("20260723_0011", "20260723_0010"),
    "0012_delivery_package_group_ids_gin.py": ("20260723_0012", "20260723_0011"),
    "0013_data_center_query_indexes.py": ("20260723_0013", "20260723_0012"),
    "0014_export_center_jobs.py": ("20260724_0014", "20260723_0013"),
    "0015_collector_transfer_workbench.py": ("20260823_0015", "20260724_0014"),
    "0016_project_scoped_collector_inventory.py": (MIGRATION_REVISION, "20260823_0015"),
}

REQUIRED_FILES = (
    "AGENTS.md",
    "RELEASE_MANIFEST.md",
    "docs/AGENT_REQUIRED_READING.md",
    "docs/sop/README.md",
    "docs/sop/06-production-deploy-runbook.md",
    "docs/superpowers/plans/2026-08-29-v3-2-16-review-claim-hotfix.md",
    "docs/superpowers/plans/2026-08-28-v3-2-15-dashboard-rephoto-async.md",
    BASELINE_RELEASE_PATH,
    RELEASE_PATH,
    "scripts/build-client-release.ps1",
    "scripts/production_health_check.py",
    "scripts/verify-client-release.py",
    "scripts/verify_release_sop.py",
    "scripts/verify_v3_2_13_release.py",
    "scripts/test_verify_v3_2_13_release.py",
    "scripts/verify_v3_2_14_release.py",
    "scripts/test_verify_v3_2_14_release.py",
    "scripts/verify_v3_2_16_release.py",
    "scripts/test_verify_v3_2_16_release.py",
    "scripts/production_backup.sh",
    "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py",
    "v2-api/app/api/routes/collector_transfer.py",
    "v2-api/app/api/schemas/collector_transfer.py",
    "v2-api/app/domain/terminal_review.py",
    "v2-api/app/main.py",
    "v2-api/app/services/collector_transfer.py",
    "v2-api/app/services/data_center.py",
    "v2-api/app/services/local_simulation.py",
    "v2-api/app/services/ops_status.py",
    "v2-api/app/services/state_repository.py",
    "v2-api/app/static/vue/version.json",
    "v2-api/pyproject.toml",
    "v2-api/scripts/verify_v3_1_release.py",
    "v2-api/tests/test_api.py",
    "v2-api/tests/test_collector_transfer_api.py",
    "v2-api/tests/test_collector_transfer_service.py",
    "v2-api/tests/test_data_center.py",
    "v2-api/tests/test_data_center_review.py",
    "v2-api/tests/test_local_simulation.py",
    "v2-api/tests/test_state_repository.py",
    "v2-api/tests/test_terminal_review_domain.py",
    "v2-api/tests/test_v21_data_rules.py",
    "v2-api/tests/test_v3_1_release.py",
    "v2-web/index.html",
    "v2-web/package.json",
    "v2-web/src/api/services.ts",
    "v2-web/src/components/AppLayout.vue",
    "v2-web/src/components/PhotoLightbox.vue",
    "v2-web/src/components/__tests__/PhotoLightbox.spec.ts",
    "v2-web/src/components/__tests__/DataCenterGroupReviewPanel.spec.ts",
    "v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue",
    "v2-web/src/constants/releaseNotes.ts",
    "v2-web/src/version.json",
    "v2-web/src/views/CollectorInventoryView.vue",
    "v2-web/src/views/ConstructionView.vue",
    "v2-web/src/views/ReviewRephotoWorkbenchView.vue",
    "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts",
    "v2-web/src/views/__tests__/ConstructionScannerAndroid.spec.ts",
    "v2-web/src/views/__tests__/AppLayout.spec.ts",
    "v2-web/src/views/__tests__/LoginView.spec.ts",
    "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
)

VERSION_SURFACES = {
    "v2-api/app/main.py": 'version="3.2.16"',
    "v2-api/app/services/ops_status.py": 'return "3.2.16"',
    "v2-api/pyproject.toml": 'version = "3.2.16"',
    "v2-api/scripts/verify_v3_1_release.py": 'EXPECTED_VERSION = "3.2.16"',
    "v2-api/tests/test_v3_1_release.py": 'EXPECTED_VERSION = "3.2.16"',
    "v2-web/index.html": "Module Manager V3.2.16",
    "v2-web/package.json": '"version": "3.2.16"',
    "v2-web/src/components/AppLayout.vue": "V3.2.16",
    "v2-web/src/constants/releaseNotes.ts": "version: 'V3.2.16'",
    "v2-web/src/version.json": '"version":"3.2.16"',
    "RELEASE_MANIFEST.md": "- Version: 3.2.16",
}

FEATURE_MARKERS = {
    "v2-api/app/domain/terminal_review.py": (
        "rephoto_sources = tuple(",
        "and all(code in _SOFT_REVIEW_BLOCKERS for code in item.blockers)",
        "rephoto_sources=rephoto_sources",
    ),
    "v2-api/app/services/collector_transfer.py": (
        "def _require_terminal_rephoto_ready(",
        'if locked_state in {"no_construction", "blocked"}:',
    ),
    "v2-web/src/components/PhotoLightbox.vue": (
        'data-testid="photo-lightbox"',
        "window.addEventListener('keydown', handleKeydown)",
        "event.key !== 'Tab'",
        "if (previousFocus?.isConnected) previousFocus.focus()",
        '@click.self="emit(\'close\')"',
    ),
    "v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue": (
        "import PhotoLightbox from '@/components/PhotoLightbox.vue'",
        "fetchGroupPhotoObjectUrl(groupId, photo.id, 'original'",
        'data-testid="`preview-classification-${photo.id}`"',
    ),
    "v2-web/src/views/ReviewRephotoWorkbenchView.vue": (
        "const rephotoUnlocked = computed(",
        "分类不影响翻拍",
        'data-testid="`preview-meter-${slot.slot}`"',
        'data-testid="`preview-collector-${row.key}`"',
    ),
}

LABELED_TEST_MARKERS = (
    (
        "v2-web/src/components/__tests__/PhotoLightbox.spec.ts",
        "keeps keyboard focus inside the dialog and restores the opener after closing",
        "lightbox keyboard focus regression",
    ),
    (
        "v2-api/tests/test_terminal_review_domain.py",
        "def test_pending_manual_confirmation_remains_visible_but_keeps_rephoto_source()",
        "classification-independent rephoto domain regression",
    ),
    (
        "v2-api/tests/test_terminal_review_domain.py",
        "def test_source_revision_ignores_review_confirmation_and_barcode_status()",
        "review-only source revision regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_service.py",
        "def test_every_collector_mutation_allows_pending_review_when_source_is_unchanged(",
        "classification-independent rephoto mutation regression",
    ),
    (
        "v2-web/src/components/__tests__/DataCenterGroupReviewPanel.spec.ts",
        "fetchGroupPhotoObjectUrl).toHaveBeenCalledWith(",
        "protected original-photo preview regression",
    ),
    (
        "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
        "keeps pending review visible without locking complete rephoto material",
        "classification-independent rephoto UI regression",
    ),
    (
        "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
        "opens every rephoto image in a large read-only preview",
        "rephoto large-image preview regression",
    ),
)

TASK_FEATURE_MARKERS = {
    "v2-api/app/api/schemas/collector_transfer.py": (
        "class ManualCollectorDemandRequest(BaseModel):",
        "quantity: int = Field(gt=0, le=100, strict=True)",
        'original_collector_no: Literal["人工需求"]',
    ),
    "v2-api/app/api/routes/collector_transfer.py": (
        '"/review-workbench/terminals/{terminal_id}/manual-demand"',
        "lambda service: service.create_manual_demand(",
    ),
    "v2-api/app/services/collector_transfer.py": (
        '_MANUAL_DEMAND_INTERNAL_PREFIX = "manual-demand:"',
        '_MANUAL_DEMAND_LABEL = "人工需求"',
        "_MAX_MANUAL_DEMAND_QUANTITY = 100",
        "def create_manual_demand(",
        'action="collector_workbench.manual_demand_added"',
        "source_collector_photo_by_requirement.setdefault(",
        '"source_group_id": public_group_id_by_id.get(',
    ),
    "v2-web/src/api/services.ts": (
        "export async function createReviewWorkbenchManualDemand(",
        "/manual-demand`, {",
    ),
    "v2-web/src/views/ReviewRephotoWorkbenchView.vue": (
        "const completedGroupIds = new Set(",
        "item.source_group_id === selectedMeter.value?.group_id",
        "quantity <= maxManualDemandQuantity",
        "`requirement:${row.requirement_id}`",
        ".filter((row) => row.status !== 'completed')",
        'data-testid="submit-manual-demand"',
        "增加并随机匹配",
    ),
}

V3213_SCANNER_MARKERS = (
    (
        "v2-web/src/views/CollectorInventoryView.vue",
        "if (await startQuaggaScanner(session))",
        "V3.2.13 inventory scanner regression",
    ),
    (
        "v2-web/src/views/CollectorInventoryView.vue",
        "const stream = await requestCameraStream(session)",
        "V3.2.13 inventory scanner regression",
    ),
    (
        "v2-web/src/views/CollectorInventoryView.vue",
        "offDetected",
        "V3.2.13 inventory scanner regression",
    ),
    (
        "v2-web/src/views/CollectorInventoryView.vue",
        'data-testid="inventory-scanner-dialog"',
        "V3.2.13 inventory scanner regression",
    ),
    (
        "v2-web/src/views/CollectorInventoryView.vue",
        "function closeScanner()",
        "V3.2.13 inventory scanner regression",
    ),
    (
        "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts",
        "reuses the construction Quagga scanner before opening a competing native camera stream",
        "V3.2.13 inventory scanner test regression",
    ),
    (
        "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts",
        "stops a partially started construction scanner before native fallback opens the camera",
        "V3.2.13 inventory scanner test regression",
    ),
    (
        "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts",
        "keeps the live barcode camera inside a closable scanner dialog",
        "V3.2.13 inventory scanner test regression",
    ),
    (
        "v2-web/src/views/ConstructionView.vue",
        "new BrowserMultiFormatReader()",
        "V3.2.13 Android scanner regression",
    ),
    (
        "v2-web/src/views/ConstructionView.vue",
        "decodeFromConstraints",
        "V3.2.13 Android scanner regression",
    ),
    (
        "v2-web/src/views/ConstructionView.vue",
        "beginScannerSession()",
        "V3.2.13 Android scanner regression",
    ),
    (
        "v2-web/src/views/ConstructionView.vue",
        "scannerSessionIsCurrent(session)",
        "V3.2.13 Android scanner regression",
    ),
    (
        "v2-web/src/views/ConstructionView.vue",
        "controls.stop()",
        "V3.2.13 Android scanner regression",
    ),
    (
        "v2-web/src/views/__tests__/ConstructionScannerAndroid.spec.ts",
        "stops controls from a closed ZXing session instead of letting an old promise replace the reopened scanner",
        "V3.2.13 Android scanner test regression",
    ),
    (
        "scripts/production_health_check.py",
        '("/static/vendor/quagga.min.js", 200)',
        "V3.2.13 scanner health regression",
    ),
    (
        "docs/sop/06-production-deploy-runbook.md",
        'chmod 0751 "$REL"',
        "V3.2.13 static runtime traversal regression",
    ),
    (
        "v2-api/tests/test_terminal_review_domain.py",
        "def test_pending_manual_confirmation_remains_visible_but_keeps_rephoto_source()",
        "V3.2.13 classification-independent rephoto regression",
    ),
)

TASK_TEST_MARKERS = (
    (
        "v2-api/tests/test_terminal_review_domain.py",
        "def test_safe_constructed_sources_survive_unconstructed_and_incomplete_rows()",
        "Task 1 safe constructed source regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_service.py",
        "def test_open_global_terminal_keeps_only_safe_constructed_sources(",
        "Task 1 terminal open regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_service.py",
        "def test_manual_demand_matches_unique_current_project_collectors_and_audits(",
        "Task 2 manual demand allocation regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_service.py",
        "def test_manual_demand_pool_shortage_ignores_foreign_project_and_writes_nothing(",
        "Task 2 pool shortage zero-write regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_service.py",
        "def test_manual_demand_rejects_non_positive_quantity_without_writes(",
        "Task 2 positive quantity regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_service.py",
        "def test_manual_demand_assignment_uses_existing_rollback_and_keeps_neutral_label(",
        "Task 2 rollback compatibility regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_service.py",
        "def test_manual_demand_internal_key_is_independent_from_returned_requirement_id(",
        "Task 2 internal key isolation regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_service.py",
        "def test_manual_namespace_is_rejected_by_every_collector_number_input(",
        "Task 2 reserved namespace regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_service.py",
        "def test_manual_internal_inventory_never_reconciles_or_surfaces_in_mappings(",
        "Task 2 synthetic inventory isolation regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_service.py",
        "def test_manual_demand_reopens_completed_terminal_with_pending_work(",
        "Task 2 terminal reopen regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_service.py",
        "def test_terminal_workbench_redacts_legacy_manual_namespace_assignment(",
        "Task 2 legacy namespace redaction regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_api.py",
        "def test_project_inventory_photo_rejects_manual_namespace_before_storage(",
        "Task 2 API namespace rejection regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_api.py",
        "def test_manual_collector_demand_requires_positive_quantity_and_administrator(",
        "Task 2 manual demand API regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_api.py",
        "def test_manual_collector_demand_enforces_the_operational_quantity_limit(",
        "Task 2 manual demand API quantity-limit regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_service.py",
        "def test_manual_demand_rejects_oversized_quantity_before_terminal_locking(",
        "Task 2 manual demand service quantity-limit regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_service.py",
        "def test_global_terminal_detail_reuses_authorized_source_photo_for_present_collector(",
        "Task 3 present collector source-photo regression",
    ),
    (
        "v2-api/tests/test_collector_transfer_service.py",
        'row["source_group_id"]',
        "Task 4 stable meter group identity regression",
    ),
    (
        "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
        "posts a positive manual demand to the active terminal through the API boundary",
        "Task 4 manual demand API boundary regression",
    ),
    (
        "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
        "omits persisted completed meter and collector items after reopening",
        "Task 4 completed row visibility regression",
    ),
    (
        "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
        "keeps every incomplete manual-demand collector visible by requirement identity",
        "Task 4 manual demand identity regression",
    ),
    (
        "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
        "hides only the completed group when sibling meters share a display number",
        "Task 4 stable meter group UI regression",
    ),
    (
        "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
        "submits a positive manual demand, disables invalid quantities, and reopens the terminal",
        "Task 4 manual demand control regression",
    ),
    (
        "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
        "shows manual-demand shortage feedback from the existing error surface",
        "Task 4 shortage feedback regression",
    ),
    (
        "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
        "does not clear or reopen terminal B when a manual demand for terminal A resolves late",
        "Task 4 stale success isolation regression",
    ),
    (
        "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
        "does not render a manual-demand error from terminal A after terminal B is current",
        "Task 4 stale error isolation regression",
    ),
)

V3215_FEATURE_MARKERS = {
    "v2-api/app/services/collector_transfer.py": (
        "resolve_photos: bool = True",
        "resolve_photos=False",
        "resolve_urls=resolve_photos",
    ),
    "v2-api/app/services/data_center.py": (
        'DASHBOARD_IGNORED_EXCEPTION_REASON = "missing_collector_photo"',
        "def is_only_missing_collector_photo_exception(",
        "reasons == {DASHBOARD_IGNORED_EXCEPTION_REASON}",
    ),
    "v2-api/app/services/local_simulation.py": (
        "if is_dashboard_exception_group(item)",
        "def is_dashboard_exception_group(",
    ),
    "v2-api/app/services/state_repository.py": (
        "def _only_missing_collector_photo_exception_clause()",
        "def _dashboard_exception_clause()",
        "(_dashboard_exception_clause(), 1)",
    ),
    "v2-web/src/views/ReviewRephotoWorkbenchView.vue": (
        "void hydrateRephotoPhotos(next, serial)",
        "async function hydrateRephotoPhotos(",
        "serial !== photoLoadSerial",
        'loading="lazy" decoding="async"',
        "图片加载失败，文字资料仍可继续审阅",
    ),
}

V3215_TEST_MARKERS = (
    (
        "v2-api/tests/test_collector_transfer_service.py",
        "def test_review_workbench_open_defers_photo_urls_until_detail_request(",
        "deferred image service regression",
    ),
    (
        "v2-api/tests/test_data_center_review.py",
        "def test_data_center_exception_drilldown_ignores_only_missing_collector_photo(",
        "data-center exception semantics regression",
    ),
    (
        "v2-api/tests/test_state_repository.py",
        "def test_postgres_dashboard_exception_clause_excludes_only_missing_collector_photo(",
        "PostgreSQL exception semantics regression",
    ),
    (
        "v2-api/tests/test_v21_data_rules.py",
        "def test_project_progress_ignores_only_missing_collector_photo_but_keeps_mixed_exceptions(",
        "JSON exception semantics regression",
    ),
    (
        "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
        "renders terminal rows before asynchronously hydrating lazy images",
        "deferred image UI regression",
    ),
    (
        "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
        "does not let a late image response overwrite the newly opened terminal",
        "deferred image stale-response regression",
    ),
    (
        "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
        "keeps rows visible when asynchronous image loading fails",
        "deferred image failure regression",
    ),
)

V3216_TEST_MARKERS = (
    (
        "scripts/test_verify_v3_2_16_release.py",
        "def test_production_backup_checksum_manifest_is_relocatable(",
        "relocatable production-backup checksum regression",
    ),
    (
        "scripts/test_verify_v3_2_16_release.py",
        "def test_production_backup_checksum_manifest_covers_env(",
        "production-backup env checksum regression",
    ),
    (
        "v2-api/tests/test_data_center.py",
        "def test_postgres_data_center_unmatched_list_only_returns_open_records(",
        "open unmatched list regression",
    ),
    (
        "v2-api/tests/test_data_center_review.py",
        "def test_admin_data_center_review_ignores_removed_reviewer_claim(",
        "admin review claim-removal regression",
    ),
    (
        "v2-api/tests/test_local_simulation.py",
        "def test_review_group_does_not_require_removed_reviewer_claim(",
        "JSON review claim-removal regression",
    ),
    (
        "v2-api/tests/test_state_repository.py",
        "def test_postgres_review_does_not_consult_removed_reviewer_claim(",
        "PostgreSQL review claim-removal regression",
    ),
    (
        "v2-web/src/views/__tests__/LoginView.spec.ts",
        "presents only the current administrator and constructor roles",
        "login reviewer-role removal regression",
    ),
    (
        "v2-web/src/views/__tests__/AppLayout.spec.ts",
        "does not present a removed reviewer role from a stale session",
        "stale-session reviewer-role regression",
    ),
)

PENDING_FIELDS = {
    "Status": {"pending"},
    "Local Verification": {"pending"},
    "Package": {"pending"},
    "Production Deployment": {"pending"},
    "Production Reconciliation": {"pending"},
    "Rollback target": {DEPLOYED_BASELINE},
    "Candidate branch": {MAINTENANCE_BRANCH},
    "Deployed production baseline": {DEPLOYED_BASELINE},
    "Candidate version": {DISPLAY_VERSION},
    "Database head": {f"{MIGRATION_REVISION} (head)"},
}
ATTESTATION_EXACT_FIELDS = {
    "Status": "attested",
    "Local Verification": "passed",
    "Package": "passed",
    "Production Deployment": "passed",
    "Production Reconciliation": "passed",
    "Rollback target": DEPLOYED_BASELINE,
    "Candidate branch": MAINTENANCE_BRANCH,
    "Deployed production baseline": DEPLOYED_BASELINE,
    "Candidate version": DISPLAY_VERSION,
    "Database head": f"{MIGRATION_REVISION} (head)",
    "Source verifier tests": "passed",
    "Generic client-package verifier tests": "passed",
    "SOP verifier tests": "passed",
    "Source phase": "passed",
    "SOP source phase": "passed",
    "Git diff check": "passed",
    "Archive file": ARCHIVE_PATH,
    "Build command": "passed",
    "Archive verification result": "passed",
    "Backup verification": "passed",
    "Uvicorn readiness": "127.0.0.1:8000 ready",
    "Authorization acceptance": "passed",
    "Zero-write acceptance": "passed",
    "Camera requests": "0",
    "Client-platform requests": "0",
    "Maintenance restoration": "passed",
    "Soak health checks": "passed",
    "Attestation": "passed",
}
ATTESTATION_DYNAMIC_FIELDS = (
    "Source commit",
    "SHA256",
    "Server SHA256",
    "Backup directory",
    "Release directory",
    "Rollback directory",
    "Local health",
    "Public health",
    "Browser viewport",
)
FIELD_PATTERN = re.compile(
    r"(?mi)^\s*[-*+]\s*(?P<field>[A-Za-z][A-Za-z0-9 -]*?)\s*[:：]\s*(?P<value>.*?)\s*$"
)


def _read(root: Path, relative_path: str, failures: list[str]) -> str:
    path = root / relative_path
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        failures.append(f"{relative_path}: cannot be read as UTF-8: {exc}")
        return ""


def _require_once(text: str, marker: str, path: str, failures: list[str]) -> None:
    count = text.count(marker)
    if count != 1:
        failures.append(f"{path}: expected {marker!r} exactly once; found {count}")


def _require_markers(
    root: Path,
    relative_path: str,
    markers: tuple[str, ...],
    label: str,
    failures: list[str],
) -> None:
    text = _read(root, relative_path, failures)
    missing = [marker for marker in markers if marker not in text]
    if missing:
        failures.append(f"{relative_path}: missing {label}: {', '.join(missing)}")


def _field_values(record: str, field: str) -> list[str]:
    return [
        match.group("value").strip().strip("`")
        for match in FIELD_PATTERN.finditer(record)
        if match.group("field").strip().casefold() == field.casefold()
    ]


def _check_alembic_revisions(root: Path, failures: list[str]) -> None:
    revision_files: dict[str, list[str]] = {}
    migration_paths = sorted((root / "v2-api/alembic/versions").glob("*.py"))
    actual_files = {path.name for path in migration_paths}
    expected_files = set(APPROVED_ALEMBIC_CHAIN)
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        unexpected = sorted(actual_files - expected_files)
        failures.append(
            "v2-api/alembic/versions: no new Alembic migration is permitted; "
            "approved Alembic file chain mismatch; "
            f"missing={missing}, unexpected={unexpected}"
        )

    for path in migration_paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            failures.append(f"{path.relative_to(root).as_posix()}: cannot parse migration: {exc}")
            continue
        assignments: dict[str, list[str | None]] = {"revision": [], "down_revision": []}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id not in {"revision", "down_revision"}:
                continue
            if isinstance(node.value, ast.Constant) and (
                isinstance(node.value.value, str) or node.value.value is None
            ):
                assignments[target.id].append(node.value.value)
        if len(assignments["revision"]) != 1 or len(assignments["down_revision"]) != 1:
            failures.append(
                f"{path.relative_to(root).as_posix()}: migration must define exactly one valid "
                "revision and down_revision metadata assignment"
            )
            continue
        revision = assignments["revision"][0]
        down_revision = assignments["down_revision"][0]
        if not isinstance(revision, str) or not revision or (
            down_revision is not None and not isinstance(down_revision, str)
        ):
            failures.append(
                f"{path.relative_to(root).as_posix()}: migration must define valid revision "
                "and down_revision metadata"
            )
            continue
        revision_files.setdefault(revision, []).append(path.name)
        expected_metadata = APPROVED_ALEMBIC_CHAIN.get(path.name)
        if expected_metadata is None or (revision, down_revision) != expected_metadata:
            failures.append(
                f"{path.relative_to(root).as_posix()}: approved Alembic file chain requires "
                f"{expected_metadata!r}; found {(revision, down_revision)!r}"
            )

    for revision, filenames in sorted(revision_files.items()):
        if len(filenames) > 1:
            failures.append(
                f"v2-api/alembic/versions: duplicate Alembic revision {revision}: "
                + ", ".join(sorted(filenames))
            )


def _check_source(
    root: Path,
    failures: list[str],
    *,
    require_pending_lifecycle: bool = True,
) -> None:
    for relative_path in REQUIRED_FILES:
        if not (root / relative_path).is_file():
            failures.append(f"{relative_path}: required V3.2.16 file is missing")

    for path, marker in VERSION_SURFACES.items():
        _require_once(_read(root, path, failures), marker, path, failures)

    runtime_version_path = "v2-api/app/static/vue/version.json"
    try:
        runtime_version = json.loads(_read(root, runtime_version_path, failures))
    except json.JSONDecodeError as exc:
        failures.append(f"{runtime_version_path}: invalid JSON: {exc}")
    else:
        allowed_runtime_versions = {VERSION, DEPLOYED_BASELINE.removeprefix("V")}
        if runtime_version.get("version") not in allowed_runtime_versions:
            failures.append(
                f"{runtime_version_path}: source phase runtime version must equal one of "
                f"{sorted(allowed_runtime_versions)}"
            )

    agents = _read(root, "AGENTS.md", failures)
    for marker in (
        f"- Deployed production baseline: `{DEPLOYED_BASELINE}`.",
        f"- Release candidate: `{DISPLAY_VERSION}`.",
        f"- Release-candidate maintenance branch: `{MAINTENANCE_BRANCH}`.",
        f"- 当前已部署生产版本：`{DEPLOYED_BASELINE}`。",
        f"- 当前发布候选版本：`{DISPLAY_VERSION}`。",
        f"- 当前候选维护分支：`{MAINTENANCE_BRANCH}`。",
    ):
        _require_once(agents, marker, "AGENTS.md", failures)

    _require_markers(
        root,
        "docs/AGENT_REQUIRED_READING.md",
        (
            f"生产维护分支：`{MAINTENANCE_BRANCH}`",
            f"当前生产应用基线：`{DEPLOYED_BASELINE}`",
            f"当前发布候选版本：`{DISPLAY_VERSION}`",
            *OPERATOR_PRODUCTION_MARKERS,
        ),
        "operator release identity",
        failures,
    )
    _require_markers(
        root,
        "docs/sop/README.md",
        (
            f"Current production baseline: `{DEPLOYED_BASELINE}`.",
            f"Current release candidate: `{DISPLAY_VERSION}`.",
            f"Current candidate branch: `{MAINTENANCE_BRANCH}`.",
        ),
        "SOP release identity",
        failures,
    )
    _require_markers(
        root,
        "docs/sop/06-production-deploy-runbook.md",
        (
            "20260721_0005 -> 20260824_0016 upgrade chain",
            '$APP/venv/bin/python -m alembic current | grep -q "20260824_0016"',
            "`0006` through `0016` migrations are forward-only",
            "database at `20260824_0016`",
        ),
        "production Alembic head gate",
        failures,
    )

    baseline_path = root / BASELINE_RELEASE_PATH
    if baseline_path.is_file():
        digest = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
        if digest != PRODUCTION_RECORD_SHA256:
            failures.append(
                f"{BASELINE_RELEASE_PATH}: SHA256 must remain {PRODUCTION_RECORD_SHA256}; got {digest}"
            )

    if require_pending_lifecycle:
        candidate = _read(root, RELEASE_PATH, failures)
        for field, allowed in PENDING_FIELDS.items():
            values = _field_values(candidate, field)
            if len(values) != 1 or values[0] not in allowed:
                failures.append(f"{RELEASE_PATH}: {field} must equal one of {allowed} exactly once")
        for marker in (
            "status is `open`",
            "legacy reviewer claim",
            "historical reviewer/audit",
            "No database migration",
            "has not been deployed to production",
        ):
            if marker.casefold() not in candidate.casefold():
                failures.append(f"{RELEASE_PATH}: candidate scope is missing: {marker}")

    for path, markers in FEATURE_MARKERS.items():
        label = "V3.2.16 rephoto and preview contract"
        if "collector_transfer.py" in path:
            label = "classification-independent rephoto"
        if "PhotoLightbox.vue" in path:
            label = "lightbox keyboard focus"
        if "DataCenterGroupReviewPanel.vue" in path:
            label = "protected original-photo preview"
        _require_markers(root, path, markers, label, failures)
    for path, marker, label in LABELED_TEST_MARKERS:
        _require_markers(root, path, (marker,), label, failures)
    for path, markers in TASK_FEATURE_MARKERS.items():
        _require_markers(root, path, markers, "V3.2.16 Task 1-4 feature contract", failures)
    for path, marker, label in V3213_SCANNER_MARKERS:
        _require_markers(root, path, (marker,), label, failures)
    for path, marker, label in TASK_TEST_MARKERS:
        _require_markers(root, path, (marker,), label, failures)
    for path, markers in V3215_FEATURE_MARKERS.items():
        _require_markers(root, path, markers, "V3.2.16 feature contract", failures)
    for path, marker, label in V3215_TEST_MARKERS:
        _require_markers(root, path, (marker,), label, failures)
    for path, marker, label in V3216_TEST_MARKERS:
        _require_markers(root, path, (marker,), label, failures)

    release_tool_markers = {
        "scripts/build-client-release.ps1": (
            '[string]$Version = "3.2.16"',
            MAINTENANCE_BRANCH,
            "scripts\\verify_v3_2_16_release.py",
            "scripts\\test_verify_v3_2_16_release.py",
            "scripts\\verify_v3_2_13_release.py",
            "scripts\\test_verify_v3_2_13_release.py",
            "scripts\\verify_v3_2_14_release.py",
            "scripts\\test_verify_v3_2_14_release.py",
            "ops\\releases\\V3.2.15.md",
            "ops\\releases\\V3.2.16.md",
            "verify_v3_2_16_release.py --phase package --package $zipPath --expected-source-commit $sourceCommit",
        ),
        "scripts/verify-client-release.py": (
            '"scripts/verify_v3_2_16_release.py"',
            '"scripts/test_verify_v3_2_16_release.py"',
            '"scripts/verify_v3_2_13_release.py"',
            '"scripts/test_verify_v3_2_13_release.py"',
            '"scripts/verify_v3_2_14_release.py"',
            '"scripts/test_verify_v3_2_14_release.py"',
            '"ops/releases/V3.2.15.md"',
            '"ops/releases/V3.2.16.md"',
            "verify_v3216_archive_source_contract",
            "verify_v3215_archive_source_contract",
            "verify_v3214_archive_source_contract",
        ),
        "scripts/verify_release_sop.py": (
            'with_name("verify_v3_2_16_release.py")',
            'candidate == "V3.2.16"',
            '"scripts/verify_v3_2_16_release.py"',
            '"scripts/verify_v3_2_14_release.py"',
        ),
    }
    for path, markers in release_tool_markers.items():
        _require_markers(root, path, markers, "V3.2.16 release gate", failures)

    _check_alembic_revisions(root, failures)


def _canonical_member_name(name: str) -> str | None:
    if not name or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return None
    path = PurePosixPath(name)
    if any(part in ("", ".", "..") for part in path.parts):
        return None
    canonical = path.as_posix()
    return canonical if canonical == name else None


def _forbidden_package_path(name: str) -> bool:
    forbidden_components = {
        ".git",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "backups",
        "build",
        "data",
        "node_modules",
        "secrets",
        "uploads",
    }
    parts = tuple(part.casefold() for part in PurePosixPath(name).parts)
    if any(part in forbidden_components or part == ".env" or part.startswith(".env.") for part in parts):
        return True
    leaf = parts[-1] if parts else ""
    return leaf == "uv.lock" or leaf.endswith(
        (".zip", ".pem", ".key", ".p12", ".pfx", ".dump", ".sqlite", ".sqlite3")
    )


def _load_generic_package_verifier(root: Path):
    path = root / "scripts/verify-client-release.py"
    spec = importlib.util.spec_from_file_location("v3215_generic_package_verifier", path)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load generic package verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_package(
    root: Path,
    package_path: Path | None,
    expected_source_commit: str | None,
    failures: list[str],
) -> None:
    if expected_source_commit is None:
        failures.append("package phase requires --expected-source-commit for V3.2.16")
        return
    normalized_expected_commit = expected_source_commit.strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", normalized_expected_commit) is None:
        failures.append("V3.2.16 expected source commit must be one lowercase 40-character Git commit")
        return
    if package_path is None:
        failures.append("package phase requires --package for V3.2.16")
        return
    package = Path(package_path)
    if not package.is_file() or package.stat().st_size <= 0:
        failures.append(f"V3.2.16 package is missing or empty: {package}")
        return
    try:
        with ZipFile(package) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            for name in names:
                if _canonical_member_name(name) is None:
                    failures.append(f"non-canonical archive member: {name}")
            if len(names) != len(set(names)):
                failures.append("duplicate archive member names are forbidden")
            folded = [name.casefold() for name in names]
            if len(folded) != len(set(folded)):
                failures.append("case-colliding archive member names are forbidden")
            for info in infos:
                if stat.S_ISLNK(info.external_attr >> 16):
                    failures.append(f"symlink archive member is forbidden: {info.filename}")
                if _forbidden_package_path(info.filename):
                    failures.append(f"forbidden archive member: {info.filename}")
            bad_member = archive.testzip()
            if bad_member is not None:
                failures.append(f"archive CRC failed: {bad_member}")
            name_set = set(names)
            if "SOURCE_COMMIT" not in name_set:
                failures.append("V3.2.16 package requires SOURCE_COMMIT")
            else:
                source_commit = archive.read("SOURCE_COMMIT").decode("ascii", errors="replace").strip()
                if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
                    failures.append("V3.2.16 SOURCE_COMMIT must be one lowercase 40-character Git commit")
            if "RELEASE_MANIFEST.md" not in name_set:
                failures.append("V3.2.16 package requires RELEASE_MANIFEST.md")
            else:
                manifest_bytes = archive.read("RELEASE_MANIFEST.md")
                if b"\r" in manifest_bytes:
                    failures.append("V3.2.16 RELEASE_MANIFEST.md must use LF line endings")
                manifest = manifest_bytes.decode("utf-8", errors="replace")
                versions = re.findall(r"(?m)^- Version:\s*(\S+)\s*$", manifest)
                if versions != [VERSION]:
                    failures.append(f"V3.2.16 package manifest must contain exactly Version {VERSION}")
    except (BadZipFile, OSError) as exc:
        failures.append(f"V3.2.16 package cannot be opened: {exc}")
        return

    try:
        _load_generic_package_verifier(root).verify_package(
            package,
            expected_source_commit=normalized_expected_commit,
        )
    except (AssertionError, KeyError, OSError, BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
        failures.append(f"V3.2.16 package verification failed: {exc}")


def _check_attestation(
    root: Path,
    package_path: Path | None,
    expected_source_commit: str | None,
    failures: list[str],
) -> None:
    record = _read(root, RELEASE_PATH, failures)
    for field, expected in ATTESTATION_EXACT_FIELDS.items():
        values = _field_values(record, field)
        if values != [expected]:
            failures.append(f"{RELEASE_PATH}: attestation requires {field}: {expected} exactly once")
    for field in ATTESTATION_DYNAMIC_FIELDS:
        values = _field_values(record, field)
        if len(values) != 1 or values[0].strip().casefold() in {"", "pending", "not run"}:
            failures.append(f"{RELEASE_PATH}: attestation requires one non-pending {field} value")
    source_commits = _field_values(record, "Source commit")
    normalized_expected_commit = (expected_source_commit or "").strip().lower()
    if (
        len(source_commits) != 1
        or re.fullmatch(r"[0-9a-f]{40}", source_commits[0]) is None
        or source_commits[0] != normalized_expected_commit
    ):
        failures.append(
            f"{RELEASE_PATH}: Source commit must equal the verified expected source commit exactly once"
        )
    hashes = {field: _field_values(record, field) for field in ("SHA256", "Server SHA256")}
    if all(len(values) == 1 for values in hashes.values()):
        local_hash = hashes["SHA256"][0]
        server_hash = hashes["Server SHA256"][0]
        actual_hash = (
            hashlib.sha256(Path(package_path).read_bytes()).hexdigest()
            if package_path is not None and Path(package_path).is_file()
            else ""
        )
        if re.fullmatch(r"[0-9a-f]{64}", local_hash) is None or local_hash != actual_hash:
            failures.append(f"{RELEASE_PATH}: package SHA256 must equal the verified package bytes")
        if re.fullmatch(r"[0-9a-f]{64}", server_hash) is None or server_hash != actual_hash:
            failures.append(f"{RELEASE_PATH}: Server SHA256 must equal the verified package SHA256")

    path_patterns = {
        "Backup directory": r"/opt/module-manager-v2/backups/v3\.2\.16-\d{8}T\d{6}Z",
        "Release directory": r"/opt/module-manager-v2/releases/v3\.2\.16-\d{8}T\d{6}Z",
        "Rollback directory": r"/opt/module-manager-v2/releases/v3\.2\.15-\d{8}T\d{6}Z",
    }
    for field, pattern in path_patterns.items():
        values = _field_values(record, field)
        if len(values) != 1 or re.fullmatch(pattern, values[0]) is None:
            failures.append(f"{RELEASE_PATH}: {field} must be one canonical immutable release path")

    for field in ("Local health", "Public health"):
        values = _field_values(record, field)
        if (
            len(values) != 1
            or re.fullmatch(r"HTTP\s+200\s+version\s+3\.2\.16", values[0], re.IGNORECASE) is None
        ):
            failures.append(f"{RELEASE_PATH}: {field} must prove HTTP 200 for version 3.2.16")

    viewport_values = _field_values(record, "Browser viewport")
    if (
        len(viewport_values) != 1
        or re.fullmatch(r"[1-9]\d*x[1-9]\d*\s+passed", viewport_values[0], re.IGNORECASE) is None
    ):
        failures.append(f"{RELEASE_PATH}: Browser viewport must be WIDTHxHEIGHT passed")


def collect_failures(
    root: Path,
    phase: str,
    *,
    package_path: Path | None = None,
    expected_source_commit: str | None = None,
) -> list[str]:
    root = Path(root)
    if phase not in VERIFICATION_PHASES:
        return [f"verification phase must be one of {sorted(VERIFICATION_PHASES)}"]
    failures: list[str] = []
    if phase == "source":
        _check_source(root, failures)
    elif phase == "package":
        _check_package(root, package_path, expected_source_commit, failures)
    else:
        _check_source(root, failures, require_pending_lifecycle=False)
        _check_package(root, package_path, expected_source_commit, failures)
        _check_attestation(root, package_path, expected_source_commit, failures)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the V3.2.16 source, package, or attestation contract.")
    parser.add_argument("--phase", required=True, choices=sorted(VERIFICATION_PHASES))
    parser.add_argument("--package", type=Path)
    parser.add_argument("--expected-source-commit")
    args = parser.parse_args(argv)
    failures = collect_failures(
        ROOT,
        args.phase,
        package_path=args.package,
        expected_source_commit=args.expected_source_commit,
    )
    if failures:
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"[OK] V3.2.16 {args.phase} release contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
