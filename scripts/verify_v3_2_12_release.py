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
VERSION = "3.2.12"
DISPLAY_VERSION = "V3.2.12"
DEPLOYED_BASELINE = "V3.2.11"
MAINTENANCE_BRANCH = "production/V3/3.2.12"
MIGRATION_REVISION = "20260824_0016"
RELEASE_PATH = "ops/releases/V3.2.12.md"
BASELINE_RELEASE_PATH = "ops/releases/V3.2.11.md"
ARCHIVE_PATH = "build/server-release/module-manager-v2-server-3.2.12.zip"
PRODUCTION_RECORD_SHA256 = "75276c03c18ba4b66cfca62b25b85afa2022ab4aa7a975a46d46b7ad975bda15"
APPROVED_ALEMBIC_REVISIONS = frozenset(
    {
        "20260609_0001",
        "20260618_0002",
        "20260619_0003",
        "20260622_0004",
        "20260721_0005",
        "20260722_0006",
        "20260722_0007",
        "20260722_0008",
        "20260722_0009",
        "20260723_0010",
        "20260723_0011",
        "20260723_0012",
        "20260723_0013",
        "20260724_0014",
        "20260823_0015",
        MIGRATION_REVISION,
    }
)
OPERATOR_PRODUCTION_MARKERS = (
    "当前生产 release：`/opt/module-manager-v2/releases/v3.2.11-20260827T030718Z`",
    "当前回滚 release：`/opt/module-manager-v2/releases/v3.2.10-20260826T195524Z`",
    "当前生产提交：`2fd8c2cbe377d1316e3f97f6d7f83a53b4e08a3d`",
)
VERIFICATION_PHASES = frozenset(("source", "package", "attestation"))

REQUIRED_FILES = (
    "AGENTS.md",
    "RELEASE_MANIFEST.md",
    "docs/AGENT_REQUIRED_READING.md",
    "docs/sop/README.md",
    "docs/sop/06-production-deploy-runbook.md",
    BASELINE_RELEASE_PATH,
    RELEASE_PATH,
    "scripts/build-client-release.ps1",
    "scripts/production_health_check.py",
    "scripts/verify-client-release.py",
    "scripts/verify_release_sop.py",
    "scripts/verify_v3_2_11_release.py",
    "scripts/test_verify_v3_2_11_release.py",
    "scripts/verify_v3_2_12_release.py",
    "scripts/test_verify_v3_2_12_release.py",
    "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py",
    "v2-api/app/api/routes/groups.py",
    "v2-api/app/domain/terminal_review.py",
    "v2-api/app/main.py",
    "v2-api/app/schemas/data_center.py",
    "v2-api/app/services/data_center.py",
    "v2-api/app/services/local_simulation.py",
    "v2-api/app/services/ops_status.py",
    "v2-api/app/services/state_repository.py",
    "v2-api/pyproject.toml",
    "v2-api/scripts/verify_v3_1_release.py",
    "v2-api/tests/test_api.py",
    "v2-api/tests/test_data_center_review.py",
    "v2-api/tests/test_state_repository.py",
    "v2-api/tests/test_terminal_review_domain.py",
    "v2-api/tests/test_v3_1_release.py",
    "v2-web/index.html",
    "v2-web/package.json",
    "v2-web/src/api/services.ts",
    "v2-web/src/api/types.ts",
    "v2-web/src/components/AppLayout.vue",
    "v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue",
    "v2-web/src/components/__tests__/DataCenterGroupReviewPanel.spec.ts",
    "v2-web/src/constants/releaseNotes.ts",
    "v2-web/src/version.json",
    "v2-web/src/views/ReviewRephotoWorkbenchView.vue",
    "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
)

VERSION_SURFACES = {
    "v2-api/app/main.py": 'version="3.2.12"',
    "v2-api/app/services/ops_status.py": 'return "3.2.12"',
    "v2-api/pyproject.toml": 'version = "3.2.12"',
    "v2-api/scripts/verify_v3_1_release.py": 'EXPECTED_VERSION = "3.2.12"',
    "v2-api/tests/test_v3_1_release.py": 'EXPECTED_VERSION = "3.2.12"',
    "v2-web/index.html": "Module Manager V3.2.12",
    "v2-web/package.json": '"version": "3.2.12"',
    "v2-web/src/components/AppLayout.vue": "V3.2.12",
    "v2-web/src/constants/releaseNotes.ts": "version: 'V3.2.12'",
    "v2-web/src/version.json": '"version":"3.2.12"',
    "RELEASE_MANIFEST.md": "- Version: 3.2.12",
}

FEATURE_MARKERS = {
    "v2-api/app/api/routes/groups.py": (
        '@router.post("/data-center/groups/{group_id}/classification-manual-confirm")',
        "class DataCenterManualClassificationConfirmRequest(BaseModel):",
        "except ClassificationConfirmationConflict as exc:",
        "raise HTTPException(status_code=409, detail=str(exc)) from exc",
    ),
    "v2-api/app/schemas/data_center.py": (
        "classification_manual_confirmation: dict[str, Any] | None = None",
        'classification_confirmation_fingerprint: str = ""',
    ),
    "v2-api/app/services/data_center.py": (
        "def manual_classification_snapshot(",
        "def manual_classification_fingerprint(",
        'anomalies.append("unclassified_photos")',
        'anomalies.append("barcode_verification_required")',
    ),
    "v2-api/app/services/state_repository.py": (
        "class ClassificationConfirmationConflict(ValueError):",
        "def _revoke_json_manual_classification_confirmation(",
        "def _revoke_postgres_manual_classification_confirmation(",
        'action="classification_manual_confirmation_revoked"',
        '"classification_manual_confirmed"',
        "def manual_confirm_group_classification(",
        "def _reject_uncoordinated_dual_write(operation: str) -> NoReturn:",
        "was rejected before either backend mutated",
    ),
    "v2-api/app/domain/terminal_review.py": (
        "classification_manually_confirmed: bool = False",
        "classification_confirmation_anomalies: tuple[str, ...] = ()",
    ),
    "v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue": (
        "confirmDataCenterGroupClassification",
        "classificationConfirmationFingerprint",
        "人工确认分类完成",
        "getApiErrorStatus(error) === 409",
    ),
    "v2-web/src/components/__tests__/DataCenterGroupReviewPanel.spec.ts": (
        "allows an administrator to manually confirm classification and warns when anomalies remain",
        "reloads latest anomalies after a confirmation fingerprint conflict",
    ),
    "v2-web/src/views/ReviewRephotoWorkbenchView.vue": (
        "classification_manually_confirmed",
        "分类已确认，资料异常",
    ),
    "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts": (
        "distinguishes manual classification acceptance from remaining material anomalies",
    ),
}

LABELED_TEST_MARKERS = (
    ("v2-api/tests/test_data_center_review.py", "def test_manual_classification_confirmation_requires_anomaly_acknowledgement_and_audits_snapshot(", "V3.2.12 anomaly acknowledgement regression"),
    ("v2-api/tests/test_data_center_review.py", "def test_json_confirmation_rejects_concurrent_photo_evidence_change_without_audit(", "V3.2.12 409 conflict regression"),
    ("v2-api/tests/test_data_center_review.py", "def test_legacy_barcode_rescan_category_context_preserves_classification_and_confirmation(", "V3.2.12 legacy rescan preservation regression"),
    ("v2-api/tests/test_data_center_review.py", "def test_data_center_category_carrying_rescan_revokes_marker_only_for_real_evidence_change(", "V3.2.12 JSON data-center revocation regression"),
    ("v2-api/tests/test_state_repository.py", "def test_postgres_legacy_rescan_preserves_classification_while_data_center_rescan_revokes_on_change(", "V3.2.12 PostgreSQL rescan boundary regression"),
    ("v2-api/tests/test_state_repository.py", "def test_postgres_data_center_rescan_rejects_unsupported_category_before_transaction(", "V3.2.12 PostgreSQL rescan category validation regression"),
    ("v2-api/tests/test_state_repository.py", "def test_postgres_manual_classification_confirmation_is_transactional_and_audited(", "V3.2.12 PostgreSQL confirmation audit regression"),
    ("v2-api/tests/test_data_center_review.py", "def test_dual_classification_evidence_writes_fail_before_json_or_postgres_mutates(", "V3.2.12 dual-write fail-closed regression"),
    ("v2-api/tests/test_terminal_review_domain.py", "def test_automatic_approval_without_explicit_marker_stays_pending_manual_confirmation(", "V3.2.12 explicit confirmation projection regression"),
    ("v2-api/tests/test_terminal_review_domain.py", "def test_stale_manual_confirmation_snapshot_cannot_unlock_rephoto(", "V3.2.12 stale confirmation projection regression"),
)

PENDING_FIELDS = {
    "Status": ("pending",),
    "Local Verification": ("not run", "passed"),
    "Package": ("pending",),
    "Production Deployment": ("pending",),
    "Production Reconciliation": ("pending",),
    "Rollback target": (DEPLOYED_BASELINE,),
    "Candidate branch": (f"`{MAINTENANCE_BRANCH}`",),
    "Deployed production baseline": (f"`{DEPLOYED_BASELINE}`",),
    "Candidate version": (f"`{DISPLAY_VERSION}`",),
    "Database head": (f"`{MIGRATION_REVISION} (head)`",),
}

ATTESTATION_EXACT_FIELDS = {
    "Status": "attested",
    "Local Verification": "passed",
    "Package": "passed",
    "Production Deployment": "passed",
    "Production Reconciliation": "passed",
    "Rollback target": DEPLOYED_BASELINE,
    "Candidate branch": f"`{MAINTENANCE_BRANCH}`",
    "Deployed production baseline": f"`{DEPLOYED_BASELINE}`",
    "Candidate version": f"`{DISPLAY_VERSION}`",
    "Database head": f"`{MIGRATION_REVISION} (head)`",
    "Archive file": f"`{ARCHIVE_PATH}`",
    "Backup verification": "passed",
    "Uvicorn readiness": "`127.0.0.1:8000 ready`",
    "Authorization acceptance": "passed",
    "Zero-write acceptance": "passed",
    "Camera requests": "`0`",
    "Client-platform requests": "`0`",
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

FORBIDDEN_COMPONENTS = frozenset(
    {
        ".git",
        ".cache",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "backups",
        "cache",
        "node_modules",
        "uploads",
    }
)


def _read(root: Path, relative_path: str, failures: list[str]) -> str:
    path = root / relative_path
    if not path.is_file():
        failures.append(f"{relative_path}: required V3.2.12 file is missing")
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        failures.append(f"{relative_path}: cannot be read as UTF-8: {exc}")
        return ""


def _require_once(text: str, marker: str, path: str, failures: list[str]) -> None:
    if text.count(marker) != 1:
        failures.append(f"{path}: required marker must appear exactly once: {marker}")


def _require_markers(
    root: Path,
    path: str,
    markers: tuple[str, ...],
    label: str,
    failures: list[str],
) -> None:
    text = _read(root, path, failures)
    for marker in markers:
        if marker not in text:
            failures.append(f"{path}: {label} is missing: {marker}")


def _field_values(record: str, field: str) -> list[str]:
    return re.findall(rf"(?m)^\s*[-*+]\s*{re.escape(field)}\s*[:：]\s*(.*?)\s*$", record)


def _alembic_assignment(tree: ast.Module, name: str):
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            return ast.literal_eval(statement.value)
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
            and statement.value is not None
        ):
            return ast.literal_eval(statement.value)
    raise ValueError(f"missing {name} assignment")


def _check_alembic_revisions(root: Path, failures: list[str]) -> None:
    versions_dir = root / "v2-api/alembic/versions"
    revisions: dict[str, str] = {}
    down_revisions: set[str] = set()
    for path in sorted(versions_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        relative_path = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
            revision = _alembic_assignment(tree, "revision")
            down_revision = _alembic_assignment(tree, "down_revision")
        except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
            failures.append(f"{relative_path}: cannot identify Alembic revision metadata: {exc}")
            continue
        if not isinstance(revision, str) or not revision:
            failures.append(f"{relative_path}: Alembic revision must be one non-empty string")
            continue
        if revision in revisions:
            failures.append(
                f"{relative_path}: duplicate Alembic revision {revision}; first defined by {revisions[revision]}"
            )
            continue
        revisions[revision] = relative_path
        if down_revision is None:
            continue
        parents = (down_revision,) if isinstance(down_revision, str) else down_revision
        if not isinstance(parents, (tuple, list)) or not all(
            isinstance(parent, str) and parent for parent in parents
        ):
            failures.append(f"{relative_path}: invalid Alembic down_revision metadata")
            continue
        down_revisions.update(parents)

    unexpected = sorted(set(revisions) - APPROVED_ALEMBIC_REVISIONS)
    if unexpected:
        failures.append(
            "v2-api/alembic/versions: no new Alembic migration is permitted for V3.2.12; "
            f"unapproved revisions: {', '.join(unexpected)}"
        )
    heads = sorted(set(revisions) - down_revisions)
    if heads != [MIGRATION_REVISION]:
        failures.append(
            "v2-api/alembic/versions: Alembic head must remain "
            f"{MIGRATION_REVISION}; found {heads or ['none']}"
        )


def _check_source(
    root: Path,
    failures: list[str],
    *,
    require_pending_lifecycle: bool = True,
) -> None:
    for relative_path in REQUIRED_FILES:
        if not (root / relative_path).is_file():
            failures.append(f"{relative_path}: required V3.2.12 file is missing")

    for path, marker in VERSION_SURFACES.items():
        _require_once(_read(root, path, failures), marker, path, failures)

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
            "manual classification confirmation",
            "anomaly acknowledgement",
            "evidence fingerprint",
            "409",
            "JSON",
            "PostgreSQL",
            "revocation",
            "dual-write",
            "fail closed",
            "No database migration",
            "has not been deployed to production",
        ):
            if marker.casefold() not in candidate.casefold():
                failures.append(f"{RELEASE_PATH}: candidate scope is missing: {marker}")

    migration_path = "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py"
    migration = _read(root, migration_path, failures)
    _require_once(migration, f'revision = "{MIGRATION_REVISION}"', migration_path, failures)
    _check_alembic_revisions(root, failures)

    for path, markers in FEATURE_MARKERS.items():
        label = "V3.2.12 manual classification confirmation"
        if "fingerprint" in " ".join(markers).casefold():
            label = "V3.2.12 evidence fingerprint"
        if "409" in " ".join(markers):
            label = "V3.2.12 409 conflict regression"
        if "category_carrying_rescan" in " ".join(markers) and "state_repository" not in path:
            label = "V3.2.12 JSON revocation regression"
        if "postgres_category_carrying_rescan" in " ".join(markers):
            label = "V3.2.12 PostgreSQL revocation regression"
        if "dual_classification" in " ".join(markers):
            label = "V3.2.12 dual-write fail-closed regression"
        _require_markers(root, path, markers, label, failures)
    for path, marker, label in LABELED_TEST_MARKERS:
        _require_markers(root, path, (marker,), label, failures)

    release_tool_markers = {
        "scripts/build-client-release.ps1": (
            '[string]$Version = "3.2.12"',
            MAINTENANCE_BRANCH,
            "scripts\\verify_v3_2_12_release.py",
            "scripts\\test_verify_v3_2_12_release.py",
            "scripts\\verify_v3_2_11_release.py",
            "scripts\\test_verify_v3_2_11_release.py",
            "ops\\releases\\V3.2.11.md",
            "ops\\releases\\V3.2.12.md",
        ),
        "scripts/verify-client-release.py": (
            '"scripts/verify_v3_2_12_release.py"',
            '"scripts/test_verify_v3_2_12_release.py"',
            '"scripts/verify_v3_2_11_release.py"',
            '"scripts/test_verify_v3_2_11_release.py"',
            '"ops/releases/V3.2.11.md"',
            '"ops/releases/V3.2.12.md"',
            "verify_v3212_archive_source_contract",
            "verify_v3211_archive_source_contract",
        ),
        "scripts/verify_release_sop.py": (
            'with_name("verify_v3_2_12_release.py")',
            'candidate == "V3.2.12"',
            '"scripts/verify_v3_2_11_release.py"',
        ),
    }
    for path, markers in release_tool_markers.items():
        _require_markers(root, path, markers, "V3.2.12 release gate", failures)


def _canonical_member_name(name: str) -> str | None:
    if not name or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return None
    path = PurePosixPath(name)
    if any(part in ("", ".", "..") for part in path.parts):
        return None
    canonical = path.as_posix()
    return canonical if canonical == name else None


def _forbidden_package_path(name: str) -> bool:
    parts = tuple(part.casefold() for part in PurePosixPath(name).parts)
    if any(part in FORBIDDEN_COMPONENTS or part == ".env" or part.startswith(".env.") for part in parts):
        return True
    leaf = parts[-1] if parts else ""
    return leaf == "uv.lock" or leaf.endswith((".pem", ".key", ".p12", ".pfx", ".dump", ".sqlite", ".sqlite3"))


def _load_generic_package_verifier(root: Path):
    path = root / "scripts/verify-client-release.py"
    spec = importlib.util.spec_from_file_location("v3212_generic_package_verifier", path)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load generic package verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_package(root: Path, package_path: Path | None, failures: list[str]) -> None:
    if package_path is None:
        failures.append("package phase requires --package for V3.2.12")
        return
    package = Path(package_path)
    if not package.is_file() or package.stat().st_size <= 0:
        failures.append(f"V3.2.12 package is missing or empty: {package}")
        return
    try:
        with ZipFile(package) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            canonical = [_canonical_member_name(name) for name in names]
            for name, normalized in zip(names, canonical, strict=True):
                if normalized is None:
                    failures.append(f"non-canonical archive member: {name}")
            if len(names) != len(set(names)):
                failures.append("duplicate archive member names are forbidden")
            folded = [name.casefold() for name in names]
            if len(folded) != len(set(folded)):
                failures.append("case-colliding archive member names are forbidden")
            for info in infos:
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    failures.append(f"symlink archive member is forbidden: {info.filename}")
                if _forbidden_package_path(info.filename):
                    failures.append(f"forbidden archive member: {info.filename}")
            bad_member = archive.testzip()
            if bad_member is not None:
                failures.append(f"archive CRC failed: {bad_member}")
            name_set = set(names)
            if "SOURCE_COMMIT" not in name_set:
                failures.append("V3.2.12 package requires SOURCE_COMMIT")
            else:
                source_commit = archive.read("SOURCE_COMMIT").decode("ascii", errors="replace").strip()
                if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
                    failures.append("V3.2.12 SOURCE_COMMIT must be one lowercase 40-character Git commit")
            if "RELEASE_MANIFEST.md" not in name_set:
                failures.append("V3.2.12 package requires RELEASE_MANIFEST.md")
            else:
                manifest_bytes = archive.read("RELEASE_MANIFEST.md")
                if b"\r" in manifest_bytes:
                    failures.append("V3.2.12 RELEASE_MANIFEST.md must use LF line endings")
                manifest = manifest_bytes.decode("utf-8", errors="replace")
                versions = re.findall(r"(?m)^- Version:\s*(\S+)\s*$", manifest)
                if versions != [VERSION]:
                    failures.append(f"V3.2.12 package manifest must contain exactly Version {VERSION}")
    except (BadZipFile, OSError) as exc:
        failures.append(f"V3.2.12 package cannot be opened: {exc}")
        return

    try:
        _load_generic_package_verifier(root).verify_package(package)
    except (AssertionError, KeyError, OSError, BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
        failures.append(f"V3.2.12 package verification failed: {exc}")


def _check_attestation(root: Path, failures: list[str]) -> None:
    record = _read(root, RELEASE_PATH, failures)
    for field, expected in ATTESTATION_EXACT_FIELDS.items():
        values = _field_values(record, field)
        if values != [expected]:
            failures.append(f"{RELEASE_PATH}: attestation requires {field}: {expected} exactly once")
    for field in ATTESTATION_DYNAMIC_FIELDS:
        values = _field_values(record, field)
        if len(values) != 1 or values[0].strip().casefold() in {"", "pending", "not run"}:
            failures.append(f"{RELEASE_PATH}: attestation requires one non-pending {field} value")
    hashes = {field: _field_values(record, field) for field in ("SHA256", "Server SHA256")}
    if all(len(values) == 1 for values in hashes.values()):
        local_hash = hashes["SHA256"][0].strip("`").casefold()
        server_hash = hashes["Server SHA256"][0].strip("`").casefold()
        if re.fullmatch(r"[0-9a-f]{64}", local_hash) is None or local_hash != server_hash:
            failures.append(f"{RELEASE_PATH}: Server SHA256 must equal one valid SHA256")


def collect_failures(
    root: Path,
    phase: str,
    *,
    package_path: Path | None = None,
) -> list[str]:
    root = Path(root)
    if phase not in VERIFICATION_PHASES:
        return [f"verification phase must be one of {sorted(VERIFICATION_PHASES)}"]
    failures: list[str] = []
    if phase == "source":
        _check_source(root, failures)
    elif phase == "package":
        _check_package(root, package_path, failures)
    else:
        _check_source(root, failures, require_pending_lifecycle=False)
        _check_attestation(root, failures)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the V3.2.12 source, package, or attestation contract.")
    parser.add_argument("--phase", required=True, choices=sorted(VERIFICATION_PHASES))
    parser.add_argument("--package", type=Path)
    args = parser.parse_args(argv)
    failures = collect_failures(ROOT, args.phase, package_path=args.package)
    if failures:
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"[OK] V3.2.12 {args.phase} release contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
