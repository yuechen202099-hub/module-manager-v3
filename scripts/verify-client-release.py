from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


REQUIRED_FILES = {
    "README.md",
    "AGENTS.md",
    ".gitattributes",
    ".env.example",
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
    "docs/database/postgresql-schema.md",
    "infra/nginx/module-manager-v2.conf",
    "infra/module-manager-v2.service",
    "infra/module-manager-v2-photo-barcode-maintenance.service",
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
    "scripts/verify_construction_one_click_upload.js",
    "scripts/verify_construction_draft_photo_cache.js",
    "scripts/verify_installer_workload_completion_visibility.js",
    "scripts/verify_release_sop.py",
    "scripts/verify_release_retention_policy.py",
    "scripts/verify_project_board_photo_dialog.js",
    "scripts/verify_project_board_data_center_photos.js",
    "scripts/verify_project_board_unmatched_review.js",
    "scripts/verify_dialog_information_integration.js",
    "scripts/production_backup.sh",
    "scripts/cleanup_old_releases.sh",
    "scripts/production_health_check.py",
    "ops/releases/README.md",
    "ops/releases/V3.0.81.md",
    "ops/releases/V3.0.80.md",
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
    "v2-api/app/static/favicon.svg",
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
    "v2-api/scripts/recompute_photo_barcode_checks.py",
    "v2-api/scripts/migrate_json_to_postgres.py",
    "v2-api/scripts/migrate_photos_to_oss.py",
    "v2-web/Dockerfile",
    "v2-web/package.json",
    "v2-web/src/version.json",
    "v2-web/src/main.ts",
}

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

FORBIDDEN_PARTS = {
    ".env",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "build",
}

FORBIDDEN_SUFFIXES = {
    ".pyc",
    ".pyo",
}

FORBIDDEN_PREFIXES = {
    "v2-api/app/static/uploads/",
}


def load_release_truth_parser():
    path = Path(__file__).with_name("verify_release_sop.py")
    spec = importlib.util.spec_from_file_location("package_release_truth", path)
    if spec is None or spec.loader is None:
        fail("Unable to load shared release truth parser")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fail(message: str) -> None:
    raise AssertionError(message)


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
    for version_pattern in OPERATIONAL_RELEASE_VERSION_PATTERNS:
        for match in version_pattern.finditer(content):
            if match.group("version") != package_version:
                fail(
                    f"{path} contains non-current release version "
                    f"{match.group('version')}; expected {package_version}"
                )


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


def verify_package(zip_path: Path) -> None:
    if not zip_path.exists():
        fail(f"Release zip not found: {zip_path}")
    if zip_path.stat().st_size <= 0:
        fail(f"Release zip is empty: {zip_path}")

    with zipfile.ZipFile(zip_path) as archive:
        names = set(validated_zip_file_names(archive))
        missing = sorted(REQUIRED_FILES - names)
        if missing:
            fail("Missing required release files: " + ", ".join(missing))
        manifest = archive.read("RELEASE_MANIFEST.md").decode("utf-8") if "RELEASE_MANIFEST.md" in names else ""
        manifest_versions = [match.group("version") for match in MANIFEST_VERSION_LINE_PATTERN.finditer(manifest)]
        if len(manifest_versions) != 1 or SEMANTIC_VERSION_PATTERN.fullmatch(manifest_versions[0]) is None:
            fail("Release manifest must define exactly one semantic Version")
        package_version = manifest_versions[0]
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
        runtime_version = runtime_attestation["version"]
        source_version = release_truth.runtime_version_from_artifact(
            archive.read(SOURCE_VERSION_ARTIFACT).decode("utf-8")
        )
        agents = archive.read("AGENTS.md").decode("utf-8")
        release_record = archive.read("ops/releases/V3.0.81.md").decode("utf-8")
        crlf_shell_scripts = sorted(
            name
            for name in names
            if name.endswith(".sh") and b"\r\n" in archive.read(name)
        )
        if crlf_shell_scripts:
            fail("Shell scripts must use LF line endings: " + ", ".join(crlf_shell_scripts[:20]))

    forbidden_hits: list[str] = []
    for name in names:
        if any(name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
            forbidden_hits.append(name)
            continue
        parts = set(Path(name).parts)
        if parts & FORBIDDEN_PARTS:
            forbidden_hits.append(name)
            continue
        if Path(name).suffix in FORBIDDEN_SUFFIXES:
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
    if deployed_version != "V3.0.80":
        fail("Packaged AGENTS.md deployed production baseline must remain V3.0.80")
    if candidate_version != "V3.0.81":
        fail("Packaged AGENTS.md release candidate must be V3.0.81")
    if candidate_version != f"V{package_version}":
        fail("Release manifest Version must match packaged AGENTS.md release candidate")
    record_version = release_truth.RELEASE_RECORD_VERSION_PATTERN.search(release_record)
    if record_version is None or record_version.group("version") != candidate_version:
        fail("Packaged release record version must match the release candidate")
    if release_truth.release_record_claims_deployed_without_live_evidence(release_record):
        fail("Packaged V3.0.81 release record claims deployed without complete live evidence")
    if not release_truth.status_is_pending(release_truth.release_record_status(release_record)):
        fail("Packaged V3.0.81 release record must remain pending before deployment")

    print(f"[OK] release zip exists: {zip_path}")
    print(f"[OK] release zip size: {zip_path.stat().st_size} bytes")
    print(f"[OK] required files: {len(REQUIRED_FILES)}")
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
    args = parser.parse_args()
    verify_package(args.zip or default_latest_zip())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
