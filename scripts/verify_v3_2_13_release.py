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
VERSION = "3.2.13"
DISPLAY_VERSION = "V3.2.13"
DEPLOYED_BASELINE = "V3.2.12"
MAINTENANCE_BRANCH = "production/V3/3.2.13"
MIGRATION_REVISION = "20260824_0016"
RELEASE_PATH = "ops/releases/V3.2.13.md"
BASELINE_RELEASE_PATH = "ops/releases/V3.2.12.md"
ARCHIVE_PATH = "build/server-release/module-manager-v2-server-3.2.13.zip"
PRODUCTION_RECORD_SHA256 = "7354aa5be62423111f4e4136cc56d88da76dd426965b7c1c10705eca83d598aa"
OPERATOR_PRODUCTION_MARKERS = (
    "当前生产 release：`/opt/module-manager-v2/releases/v3.2.12-20260827T160539Z`",
    "当前回滚 release：`/opt/module-manager-v2/releases/v3.2.11-20260827T030718Z`",
    "当前生产提交：`b57e322b45b57143edd673893c04c3f00109188b`",
)
VERIFICATION_PHASES = frozenset(("source", "package", "attestation"))
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
    "scripts/verify_v3_2_12_release.py",
    "scripts/test_verify_v3_2_12_release.py",
    "scripts/verify_v3_2_13_release.py",
    "scripts/test_verify_v3_2_13_release.py",
    "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py",
    "v2-api/app/domain/terminal_review.py",
    "v2-api/app/main.py",
    "v2-api/app/services/collector_transfer.py",
    "v2-api/app/services/ops_status.py",
    "v2-api/app/static/vue/version.json",
    "v2-api/pyproject.toml",
    "v2-api/scripts/verify_v3_1_release.py",
    "v2-api/tests/test_api.py",
    "v2-api/tests/test_collector_transfer_service.py",
    "v2-api/tests/test_terminal_review_domain.py",
    "v2-api/tests/test_v3_1_release.py",
    "v2-web/index.html",
    "v2-web/package.json",
    "v2-web/src/components/AppLayout.vue",
    "v2-web/src/components/PhotoLightbox.vue",
    "v2-web/src/components/__tests__/PhotoLightbox.spec.ts",
    "v2-web/src/components/__tests__/DataCenterGroupReviewPanel.spec.ts",
    "v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue",
    "v2-web/src/constants/releaseNotes.ts",
    "v2-web/src/version.json",
    "v2-web/src/views/ReviewRephotoWorkbenchView.vue",
    "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
)

VERSION_SURFACES = {
    "v2-api/app/main.py": 'version="3.2.13"',
    "v2-api/app/services/ops_status.py": 'return "3.2.13"',
    "v2-api/pyproject.toml": 'version = "3.2.13"',
    "v2-api/scripts/verify_v3_1_release.py": 'EXPECTED_VERSION = "3.2.13"',
    "v2-api/tests/test_v3_1_release.py": 'EXPECTED_VERSION = "3.2.13"',
    "v2-web/index.html": "Module Manager V3.2.13",
    "v2-web/package.json": '"version": "3.2.13"',
    "v2-web/src/components/AppLayout.vue": "V3.2.13",
    "v2-web/src/constants/releaseNotes.ts": "version: 'V3.2.13'",
    "v2-web/src/version.json": '"version":"3.2.13"',
    "RELEASE_MANIFEST.md": "- Version: 3.2.13",
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

PENDING_FIELDS = {
    "Status": {"pending"},
    "Local Verification": {"passed"},
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
    "Archive file": ARCHIVE_PATH,
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
    revisions: dict[str, str | None] = {}
    for path in sorted((root / "v2-api/alembic/versions").glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            failures.append(f"{path.relative_to(root).as_posix()}: cannot parse migration: {exc}")
            continue
        values: dict[str, str | None] = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id not in {"revision", "down_revision"}:
                continue
            if isinstance(node.value, ast.Constant) and (
                isinstance(node.value.value, str) or node.value.value is None
            ):
                values[target.id] = node.value.value
        revision = values.get("revision")
        if isinstance(revision, str):
            revisions[revision] = values.get("down_revision")
    unexpected = sorted(set(revisions) - APPROVED_ALEMBIC_REVISIONS)
    if unexpected:
        failures.append(
            "v2-api/alembic/versions: no new Alembic migration is permitted for V3.2.13; "
            f"unapproved revisions: {', '.join(unexpected)}"
        )
    down_revisions = {parent for parent in revisions.values() if isinstance(parent, str)}
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
            failures.append(f"{relative_path}: required V3.2.13 file is missing")

    for path, marker in VERSION_SURFACES.items():
        _require_once(_read(root, path, failures), marker, path, failures)

    runtime_version_path = "v2-api/app/static/vue/version.json"
    try:
        runtime_version = json.loads(_read(root, runtime_version_path, failures))
    except json.JSONDecodeError as exc:
        failures.append(f"{runtime_version_path}: invalid JSON: {exc}")
    else:
        if runtime_version.get("version") != VERSION:
            failures.append(f"{runtime_version_path}: version must equal {VERSION}")

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
            "classification",
            "rephoto",
            "hard source anomalies",
            "source revision",
            "large-image",
            "No database migration",
            "has not been deployed to production",
        ):
            if marker.casefold() not in candidate.casefold():
                failures.append(f"{RELEASE_PATH}: candidate scope is missing: {marker}")

    for path, markers in FEATURE_MARKERS.items():
        label = "V3.2.13 rephoto and preview contract"
        if "collector_transfer.py" in path:
            label = "classification-independent rephoto"
        if "PhotoLightbox.vue" in path:
            label = "lightbox keyboard focus"
        if "DataCenterGroupReviewPanel.vue" in path:
            label = "protected original-photo preview"
        _require_markers(root, path, markers, label, failures)
    for path, marker, label in LABELED_TEST_MARKERS:
        _require_markers(root, path, (marker,), label, failures)

    release_tool_markers = {
        "scripts/build-client-release.ps1": (
            '[string]$Version = "3.2.13"',
            MAINTENANCE_BRANCH,
            "scripts\\verify_v3_2_13_release.py",
            "scripts\\test_verify_v3_2_13_release.py",
            "scripts\\verify_v3_2_12_release.py",
            "scripts\\test_verify_v3_2_12_release.py",
            "ops\\releases\\V3.2.12.md",
            "ops\\releases\\V3.2.13.md",
        ),
        "scripts/verify-client-release.py": (
            '"scripts/verify_v3_2_13_release.py"',
            '"scripts/test_verify_v3_2_13_release.py"',
            '"scripts/verify_v3_2_12_release.py"',
            '"scripts/test_verify_v3_2_12_release.py"',
            '"ops/releases/V3.2.12.md"',
            '"ops/releases/V3.2.13.md"',
            "verify_v3213_archive_source_contract",
            "verify_v3212_archive_source_contract",
        ),
        "scripts/verify_release_sop.py": (
            'with_name("verify_v3_2_13_release.py")',
            'candidate == "V3.2.13"',
            '"scripts/verify_v3_2_12_release.py"',
        ),
    }
    for path, markers in release_tool_markers.items():
        _require_markers(root, path, markers, "V3.2.13 release gate", failures)

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
        "uploads",
    }
    parts = tuple(part.casefold() for part in PurePosixPath(name).parts)
    if any(part in forbidden_components or part == ".env" or part.startswith(".env.") for part in parts):
        return True
    leaf = parts[-1] if parts else ""
    return leaf == "uv.lock" or leaf.endswith((".pem", ".key", ".p12", ".pfx", ".dump", ".sqlite", ".sqlite3"))


def _load_generic_package_verifier(root: Path):
    path = root / "scripts/verify-client-release.py"
    spec = importlib.util.spec_from_file_location("v3213_generic_package_verifier", path)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load generic package verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_package(root: Path, package_path: Path | None, failures: list[str]) -> None:
    if package_path is None:
        failures.append("package phase requires --package for V3.2.13")
        return
    package = Path(package_path)
    if not package.is_file() or package.stat().st_size <= 0:
        failures.append(f"V3.2.13 package is missing or empty: {package}")
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
                failures.append("V3.2.13 package requires SOURCE_COMMIT")
            else:
                source_commit = archive.read("SOURCE_COMMIT").decode("ascii", errors="replace").strip()
                if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
                    failures.append("V3.2.13 SOURCE_COMMIT must be one lowercase 40-character Git commit")
            if "RELEASE_MANIFEST.md" not in name_set:
                failures.append("V3.2.13 package requires RELEASE_MANIFEST.md")
            else:
                manifest_bytes = archive.read("RELEASE_MANIFEST.md")
                if b"\r" in manifest_bytes:
                    failures.append("V3.2.13 RELEASE_MANIFEST.md must use LF line endings")
                manifest = manifest_bytes.decode("utf-8", errors="replace")
                versions = re.findall(r"(?m)^- Version:\s*(\S+)\s*$", manifest)
                if versions != [VERSION]:
                    failures.append(f"V3.2.13 package manifest must contain exactly Version {VERSION}")
    except (BadZipFile, OSError) as exc:
        failures.append(f"V3.2.13 package cannot be opened: {exc}")
        return

    try:
        _load_generic_package_verifier(root).verify_package(package)
    except (AssertionError, KeyError, OSError, BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
        failures.append(f"V3.2.13 package verification failed: {exc}")


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
    source_commits = _field_values(record, "Source commit")
    if len(source_commits) == 1 and re.fullmatch(r"[0-9a-f]{40}", source_commits[0]) is None:
        failures.append(f"{RELEASE_PATH}: Source commit must be one lowercase 40-character Git commit")
    hashes = {field: _field_values(record, field) for field in ("SHA256", "Server SHA256")}
    if all(len(values) == 1 for values in hashes.values()):
        local_hash = hashes["SHA256"][0]
        server_hash = hashes["Server SHA256"][0]
        if (
            re.fullmatch(r"[0-9a-f]{64}", local_hash) is None
            or re.fullmatch(r"[0-9a-f]{64}", server_hash) is None
            or local_hash != server_hash
        ):
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
    parser = argparse.ArgumentParser(description="Verify the V3.2.13 source, package, or attestation contract.")
    parser.add_argument("--phase", required=True, choices=sorted(VERIFICATION_PHASES))
    parser.add_argument("--package", type=Path)
    args = parser.parse_args(argv)
    failures = collect_failures(ROOT, args.phase, package_path=args.package)
    if failures:
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"[OK] V3.2.13 {args.phase} release contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
