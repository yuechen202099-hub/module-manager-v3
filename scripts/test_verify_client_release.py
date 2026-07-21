from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import re
import subprocess
import stat
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
V3079_RELEASE_RECORD = "ops/releases/V3.0.79.md"
V3080_RELEASE_RECORD = "ops/releases/V3.0.80.md"
V3081_RELEASE_RECORD = "ops/releases/V3.0.81.md"
RUNTIME_VERSION_ARTIFACT = "v2-api/app/static/vue/version.json"
SOURCE_VERSION_ARTIFACT = "v2-web/src/version.json"
VALID_SHA256 = "a" * 64
SAFETY_NOTES = (
    "Production mode disables demo accounts by default",
    "Production mode disables /docs, /redoc, and /openapi.json by default",
    "Confirm /docs, /redoc, and /openapi.json return 404 in production",
    "Vue strict-native production pages are required",
    "PostgreSQL cutover audit must be reviewed before production deployment",
    "Production SOP files and release record templates are present",
)

VALID_AGENTS = """# Package fixture

- Deployed production baseline: `V3.0.80`.
- Release candidate: `V3.0.81`.
- Release-candidate maintenance branch: `production/V3/3.0.81`.
- 当前已部署生产版本：`V3.0.80`。
- 当前发布候选版本：`V3.0.81`。
- 当前候选维护分支：`production/V3/3.0.81`。
"""
PENDING_RELEASE_RECORD = """# V3.0.81 Production Release Record

## Summary

- Status: pending
- Local Verification: not run
- Package: pending
- Production Deployment: pending
- Production Reconciliation: pending
- Rollback target: V3.0.80
- V3.0.81 has not been deployed to production.

## Package

| Evidence | Value |
| --- | --- |
| SHA256 | |

## Production Deployment

| Evidence | Value |
| --- | --- |
| Backup directory | |
| Release directory | |
| Public health check | |
"""


def deployed_release_record(version: str, status: str) -> str:
    return f"""# V{version} Production Release Record

## Summary

- {status}

## Package

| Evidence | Value |
| --- | --- |
| SHA256 | {VALID_SHA256} |

## Production Deployment

| Evidence | Value |
| --- | --- |
| Backup directory | /opt/module-manager-v2/backups/V{version}-pre-20260719_120000 |
| Release directory | /opt/module-manager-v2/releases/v{version}-20260719_120000 |
| Public health check | https://www.sgcc.online/health passed |
"""


def load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_client_release", ROOT / "scripts" / "verify-client-release.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load verify-client-release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_release_archive(
    verifier,
    archive_path: Path,
    *,
    manifest_version: str | None = "3.0.81",
    manifest_versions: list[str] | None = None,
    static_version: str = "3.0.81",
    title_version: str | None = None,
    runtime_version: str | None = None,
    source_version: str | None = None,
    entry_version: str | None = None,
    entry_source: str | None = None,
    duplicate_entry: bool = False,
    runtime_entry_sha256: str | None = None,
    unrelated_chunk_entry_version: str = "",
    unrelated_static_version: str = "",
    unrelated_index_text: str = "",
    agents: str = VALID_AGENTS,
    release_record: str = PENDING_RELEASE_RECORD,
    omitted: set[str] | None = None,
    content_overrides: dict[str, str] | None = None,
) -> None:
    omitted_names = set(omitted or set())
    names = (set(verifier.REQUIRED_FILES) | {RUNTIME_VERSION_ARTIFACT, SOURCE_VERSION_ARTIFACT}) - omitted_names
    versions = manifest_versions
    if versions is None:
        versions = [] if manifest_version is None else [manifest_version]
    version_lines = [f"- Version: {version}" for version in versions]
    manifest = "\n".join(("# Release manifest", *version_lines, *SAFETY_NOTES))
    resolved_runtime_version = runtime_version or static_version
    resolved_source_version = source_version or resolved_runtime_version
    resolved_entry_version = entry_version or resolved_runtime_version
    resolved_title_version = title_version or static_version
    resolved_entry_source = entry_source or (
        "globalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__="
        f'{{"version":"{resolved_entry_version}"}};\n'
        f"const unrelatedReleaseNote = '{unrelated_static_version}';\n"
    )
    contents = {
        "RELEASE_MANIFEST.md": manifest,
        "AGENTS.md": agents,
        V3080_RELEASE_RECORD: deployed_release_record(
            "3.0.80",
            "Status: reviewed, packaged, deployed, and verified in production",
        ),
        V3081_RELEASE_RECORD: release_record,
        SOURCE_VERSION_ARTIFACT: json.dumps({"version": resolved_source_version}),
        "v2-api/app/static/vue/index.html": (
            f"<!doctype html><title>Module Manager V{resolved_title_version}</title>"
            f'<script type="module" src="/vue/assets/app.js"></script>{unrelated_index_text}'
        ),
        "v2-api/app/static/vue/assets/app.js": resolved_entry_source,
    }
    if unrelated_chunk_entry_version:
        contents["v2-api/app/static/vue/assets/unrelated.js"] = (
            "globalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__="
            f'{{"version":"{unrelated_chunk_entry_version}"}};\n'
        )
    archive_contents = {
        name: contents.get(name, "fixture\n")
        for name in names
        if name != RUNTIME_VERSION_ARTIFACT
    }
    archive_contents.update(content_overrides or {})
    archive_contents["v2-api/app/static/vue/assets/app.js"] = resolved_entry_source
    if unrelated_chunk_entry_version:
        archive_contents["v2-api/app/static/vue/assets/unrelated.js"] = contents[
            "v2-api/app/static/vue/assets/unrelated.js"
        ]
    vue_prefix = "v2-api/app/static/vue/"
    assets = []
    for name, content in sorted(archive_contents.items()):
        if not name.startswith(vue_prefix):
            continue
        encoded = content.encode("utf-8") if isinstance(content, str) else content
        assets.append(
            {
                "path": name.removeprefix(vue_prefix),
                "size": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        )
    resolved_entry_sha256 = runtime_entry_sha256 or hashlib.sha256(
        resolved_entry_source.encode("utf-8")
    ).hexdigest()
    if RUNTIME_VERSION_ARTIFACT in names:
        archive_contents[RUNTIME_VERSION_ARTIFACT] = json.dumps(
            {
                "version": resolved_runtime_version,
                "entry": "assets/app.js",
                "entrySha256": resolved_entry_sha256,
                "assets": assets,
            }
        )
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, content in sorted(archive_contents.items()):
            archive.writestr(name, content)
        if duplicate_entry:
            archive.writestr("v2-api/app/static/vue/assets/app.js", resolved_entry_source)


def test_archive_missing_v3081_release_record_fails_verification(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "module-manager-v2-server-v3.0.81.zip"
    write_release_archive(verifier, archive_path, omitted={V3081_RELEASE_RECORD})

    with pytest.raises(AssertionError, match=r"ops/releases/V3\.0\.81\.md"):
        verifier.verify_package(archive_path)


def test_archive_missing_v3079_historical_release_record_fails_verification(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "module-manager-v2-server-v3.0.81.zip"
    write_release_archive(verifier, archive_path, omitted={V3079_RELEASE_RECORD})

    with pytest.raises(AssertionError, match=r"ops/releases/V3\.0\.79\.md"):
        verifier.verify_package(archive_path)


def test_release_builder_default_version_is_candidate_semantic_version() -> None:
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")

    assert '[string]$Version = "3.0.84"' in build_script


def test_v3083_feature_verifiers_are_packaged_and_required() -> None:
    verifier = load_verifier()
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")
    feature_verifiers = {
        "scripts/verify_claim_tasks_construction_priority.js",
        "scripts/verify_construction_priority_import_dialog.js",
        "scripts/verify_review_image_inspector.js",
        "scripts/verify_task_hall_region_scan.js",
    }

    assert feature_verifiers <= verifier.REQUIRED_FILES
    for verifier_path in feature_verifiers:
        windows_path = verifier_path.replace("/", "\\")
        assert f'Copy-ReleaseItem "{windows_path}" "{windows_path}"' in build_script


def test_v3084_performance_verifiers_are_packaged_and_required() -> None:
    verifier = load_verifier()
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")
    acceptance_script = (ROOT / "scripts" / "run-client-acceptance-gate.ps1").read_text(encoding="utf-8")

    assert "scripts/verify_task_hall_pagination.js" in verifier.REQUIRED_FILES
    assert "v2-api/scripts/verify_task_review_performance.py" in verifier.REQUIRED_FILES
    assert (
        'Copy-ReleaseItem "scripts\\verify_task_hall_pagination.js" '
        '"scripts\\verify_task_hall_pagination.js"'
    ) in build_script
    assert "node .\\scripts\\verify_task_hall_pagination.js" in acceptance_script
    assert "v2-api\\scripts\\verify_task_review_performance.py" in acceptance_script


def test_release_builder_stops_when_smoke_check_fails() -> None:
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")
    smoke_block = build_script.split("Running release smoke check before packaging...", maxsplit=1)[1]
    smoke_block = smoke_block.split("$releaseRoot", maxsplit=1)[0]

    assert "$LASTEXITCODE -ne 0" in smoke_block
    assert 'throw "Release smoke check failed."' in smoke_block


def test_admin_release_notes_gate_executes_against_machine_version_source() -> None:
    result = subprocess.run(
        ["node", "scripts/verify_admin_release_notes.js"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "admin release notes checks passed" in result.stdout


def test_package_and_acceptance_chains_execute_admin_release_notes_gate() -> None:
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")
    acceptance_script = (ROOT / "scripts" / "run-client-acceptance-gate.ps1").read_text(encoding="utf-8")

    command = "node .\\scripts\\verify_admin_release_notes.js"
    assert command in build_script
    assert command in acceptance_script


def test_acceptance_gate_derives_and_validates_machine_version_contract() -> None:
    acceptance_script = (ROOT / "scripts" / "run-client-acceptance-gate.ps1").read_text(encoding="utf-8")
    documents = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ["README.md", "RELEASE_MANIFEST.md", "docs/CLIENT_SIGNOFF_CHECKLIST.md"]
    )

    assert '[string]$Version = ""' in acceptance_script
    assert "v2-web\\src\\version.json" in acceptance_script
    assert "ConvertFrom-Json" in acceptance_script
    assert "must match the machine version source" in acceptance_script
    assert "final-delivery-ready" not in acceptance_script
    assert "final-delivery-ready" not in documents


def test_all_copied_operational_documents_reject_round8_stale_markers() -> None:
    verifier = load_verifier()
    document_paths = sorted(
        path
        for path in verifier.REQUIRED_FILES
        if path.endswith(".md")
    )

    assert document_paths
    for document_path in document_paths:
        content = (ROOT / document_path).read_text(encoding="utf-8")
        verifier.verify_release_markdown_text(document_path, content, "3.0.84")


@pytest.mark.parametrize(
    "document_path",
    sorted(path for path in load_verifier().REQUIRED_FILES if path.endswith(".md")),
)
def test_archive_rejects_stale_marker_in_every_required_markdown(
    tmp_path: Path,
    document_path: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / f"stale-markdown-{hashlib.sha256(document_path.encode()).hexdigest()[:8]}.zip"
    stale_content = "final-delivery-ready\n"
    if document_path == "RELEASE_MANIFEST.md":
        stale_content = "\n".join(("# Release manifest", "- Version: 3.0.81", *SAFETY_NOTES, stale_content))
    write_release_archive(
        verifier,
        archive_path,
        content_overrides={document_path: stale_content},
    )

    with pytest.raises(AssertionError, match=re.escape(document_path)):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "stale_text",
    [
        ".\\scripts\\build-client-release.ps1 -Version 3.0.39",
        "build/server-release/module-manager-v2-server-3.0.39.zip",
    ],
)
def test_archive_rejects_non_current_version_in_operational_document(
    tmp_path: Path,
    stale_text: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "stale-operational-version.zip"
    write_release_archive(
        verifier,
        archive_path,
        content_overrides={"README.md": stale_text},
    )

    with pytest.raises(AssertionError, match="non-current release version"):
        verifier.verify_package(archive_path)


def test_smoke_check_validates_current_server_release_signoff_package() -> None:
    smoke_check = (ROOT / "scripts" / "smoke-client-demo.py").read_text(encoding="utf-8")

    assert 'ROOT / "v2-web" / "src" / "version.json"' in smoke_check
    assert 'f"module-manager-v2-server-{release_version}.zip"' in smoke_check
    assert "module-manager-v2-client-demo-final-delivery-ready.zip" not in smoke_check


def test_archive_missing_manifest_version_fails_verification(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "missing-version.zip"
    write_release_archive(verifier, archive_path, manifest_version=None)

    with pytest.raises(AssertionError, match="exactly one semantic Version"):
        verifier.verify_package(archive_path)


def test_archive_manifest_version_must_match_static_version(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "static-version-mismatch.zip"
    write_release_archive(verifier, archive_path, static_version="3.0.80")

    with pytest.raises(AssertionError, match="static index title"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "manifest_versions",
    [
        ["3.0.81", "3.0.81"],
        ["3.0.81", "3.0.80"],
    ],
)
def test_archive_manifest_must_have_exactly_one_version(
    tmp_path: Path,
    manifest_versions: list[str],
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "duplicate-manifest-version.zip"
    write_release_archive(verifier, archive_path, manifest_versions=manifest_versions)

    with pytest.raises(AssertionError, match="exactly one semantic Version"):
        verifier.verify_package(archive_path)


def test_archive_manifest_version_must_be_semantic(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "non-semantic-manifest-version.zip"
    write_release_archive(verifier, archive_path, manifest_version="release-3.0.81")

    with pytest.raises(AssertionError, match="exactly one semantic Version"):
        verifier.verify_package(archive_path)


def test_archive_runtime_version_cannot_be_satisfied_by_unrelated_candidate_string(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "forged-runtime-version.zip"
    write_release_archive(
        verifier,
        archive_path,
        runtime_version="3.0.80",
        unrelated_static_version="3.0.81",
    )

    with pytest.raises(AssertionError, match="runtime version"):
        verifier.verify_package(archive_path)


def test_archive_requires_machine_readable_runtime_version_artifact(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "missing-runtime-version-artifact.zip"
    write_release_archive(verifier, archive_path, omitted={RUNTIME_VERSION_ARTIFACT})

    with pytest.raises(AssertionError, match="version.json"):
        verifier.verify_package(archive_path)


def test_archive_source_and_runtime_version_artifacts_must_match(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "source-runtime-version-mismatch.zip"
    write_release_archive(verifier, archive_path, source_version="3.0.80")

    with pytest.raises(AssertionError, match="source and built runtime versions"):
        verifier.verify_package(archive_path)


def test_archive_rejects_stale_entry_bundle_despite_current_sidecars(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "stale-entry-bundle.zip"
    write_release_archive(
        verifier,
        archive_path,
        runtime_version="3.0.81",
        source_version="3.0.81",
        entry_version="3.0.80",
        unrelated_static_version="3.0.81",
        unrelated_chunk_entry_version="3.0.81",
    )

    with pytest.raises(AssertionError, match="entry bundle version"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "entry_source",
    [
        "/* globalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__={\"version\":\"3.0.81\"}; */\n",
        "const unused = 'globalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__={\"version\":\"3.0.81\"};';\n",
        "if (false) { globalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__={\"version\":\"3.0.81\"}; }\n",
        "/* stale V3.0.80 entry */\nglobalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__={\"version\":\"3.0.81\"};\n",
    ],
)
def test_archive_rejects_non_executable_or_stale_entry_markers(
    tmp_path: Path,
    entry_source: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "non-executable-entry-marker.zip"
    write_release_archive(verifier, archive_path, entry_source=entry_source)

    with pytest.raises(AssertionError, match="entry bundle"):
        verifier.verify_package(archive_path)


def test_archive_rejects_duplicate_entry_bundle_members(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "duplicate-entry-member.zip"
    write_release_archive(verifier, archive_path, duplicate_entry=True)

    with pytest.raises(AssertionError, match="duplicate"):
        verifier.verify_package(archive_path)


def test_archive_rejects_entry_marker_found_only_in_unrelated_chunk(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "unrelated-chunk-marker.zip"
    write_release_archive(
        verifier,
        archive_path,
        entry_source="console.log('entry without attestation');\n",
        unrelated_chunk_entry_version="3.0.81",
    )

    with pytest.raises(AssertionError, match="entry bundle"):
        verifier.verify_package(archive_path)


def test_archive_rejects_runtime_attestation_with_wrong_entry_digest(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "wrong-entry-digest.zip"
    write_release_archive(verifier, archive_path, runtime_entry_sha256="0" * 64)

    with pytest.raises(AssertionError, match="SHA-256"):
        verifier.verify_package(archive_path)


def test_archive_title_version_cannot_be_satisfied_by_unrelated_index_text(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "forged-title-version.zip"
    write_release_archive(
        verifier,
        archive_path,
        title_version="3.0.80",
        unrelated_index_text="<!-- Module Manager V3.0.81 -->",
    )

    with pytest.raises(AssertionError, match="static index title"):
        verifier.verify_package(archive_path)


def test_archive_rejects_contradictory_agents_deployed_markers(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "contradictory-agents.zip"
    agents = VALID_AGENTS.replace(
        "Deployed production baseline: `V3.0.80`",
        "Deployed production baseline: `V3.0.81`",
    )
    write_release_archive(verifier, archive_path, agents=agents)

    with pytest.raises(AssertionError, match="English and Chinese deployed production baseline"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    ("case_name", "field", "conflicting_line"),
    [
        (
            "star-package",
            "Package",
            "* Package: module-manager-v2-server-3.0.81.zip",
        ),
        ("plus-local-verification", "Local Verification", "+ Local Verification: passed"),
        (
            "unbulleted-reconciliation",
            "Production Reconciliation",
            "Production Reconciliation: completed",
        ),
        (
            "fullwidth-colon-reconciliation",
            "Production Reconciliation",
            "- Production Reconciliation\uff1a completed",
        ),
    ],
)
def test_archive_rejects_normalized_duplicate_candidate_lifecycle_field(
    tmp_path: Path,
    case_name: str,
    field: str,
    conflicting_line: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / f"{case_name}.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{conflicting_line}\n",
    )

    with pytest.raises(AssertionError, match=rf"{field}: .* exactly once"):
        verifier.verify_package(archive_path)


def test_archive_rejects_deployed_record_without_live_evidence(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "unsupported-deployed-record.zip"
    agents = VALID_AGENTS.replace("V3.0.80", "V3.0.81")
    record = deployed_release_record(
        "3.0.81",
        "Status: reviewed, packaged, deployed, and verified in production",
    ).replace(f"| SHA256 | {VALID_SHA256} |", "| SHA256 | |")
    write_release_archive(
        verifier,
        archive_path,
        agents=agents,
        release_record=record,
    )

    with pytest.raises(AssertionError, match="claims deployment without complete live evidence"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "affirmative_prose",
    [
        "V3.0.81 was not deployed yesterday and was deployed today.",
        "V3.0.81\n\nhas been deployed to production.",
        "V3.0.81 生产部署已完成。",
    ],
)
def test_archive_rejects_pending_record_with_affirmative_deployment_prose(
    tmp_path: Path,
    affirmative_prose: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "affirmative-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{affirmative_prose}\n",
    )

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


def test_archive_rejects_pending_candidate_with_unversioned_claim_and_complete_evidence(
    tmp_path: Path,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "forged-complete-pending.zip"
    record = (
        PENDING_RELEASE_RECORD.replace("- V3.0.81 has not been deployed to production.\n", "")
        .replace(f"| SHA256 | |", f"| SHA256 | {VALID_SHA256} |")
        .replace(
            "| Backup directory | |",
            "| Backup directory | /opt/module-manager-v2/backups/forged-complete |",
        )
        .replace(
            "| Release directory | |",
            "| Release directory | /opt/module-manager-v2/releases/forged-complete |",
        )
        .replace(
            "| Public health check | |",
            "| Public health check | https://www.sgcc.online/health passed |",
        )
    )
    record += "\nProduction was deployed successfully.\n"
    write_release_archive(verifier, archive_path, release_record=record)

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


def test_archive_rejects_bare_deployed_baseline_status(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "bare-deployed-baseline.zip"
    write_release_archive(
        verifier,
        archive_path,
        content_overrides={
            V3080_RELEASE_RECORD: deployed_release_record("3.0.80", "Status: deployed")
        },
    )

    with pytest.raises(AssertionError, match="reviewed, packaged, deployed, and verified"):
        verifier.verify_package(archive_path)


def test_archive_accepts_complete_deployed_baseline_status(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "complete-deployed-baseline.zip"
    write_release_archive(verifier, archive_path)

    verifier.verify_package(archive_path)


def test_archive_accepts_equal_post_deploy_markers_as_one_deployed_record(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "post-deploy-equal-markers.zip"
    agents = VALID_AGENTS.replace("V3.0.80", "V3.0.81")
    write_release_archive(
        verifier,
        archive_path,
        agents=agents,
        release_record=deployed_release_record(
            "3.0.81",
            "Status: reviewed, packaged, deployed, and verified in production",
        ),
    )

    verifier.verify_package(archive_path)


def test_valid_pending_candidate_archive_passes_truthfulness_checks(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "valid-pending.zip"
    write_release_archive(verifier, archive_path)

    verifier.verify_package(archive_path)


ROUND4_CONDITIONAL_OR_NEGATED_CLAIMS = [
    "V3.0.81 can't be deployed to production.",
    "V3.0.81 cannot be deployed to production.",
    "V3.0.81 can be deployed to production.",
    "V3.0.81 could be deployed to production.",
    "V3.0.81 may be deployed to production.",
    "V3.0.81 might be deployed to production.",
    "V3.0.81 is deployed to production if approval is granted.",
    "V3.0.81 is deployed to production unless rollback is required.",
    "V3.0.81 可能已上线生产环境。",
    "V3.0.81 若通过验收则已上线生产环境。",
    "如果验证通过，V3.0.81 生产部署已完成。",
    "除非回归测试失败，否则 V3.0.81 已部署到生产环境。",
]


@pytest.mark.parametrize("prose", ROUND4_CONDITIONAL_OR_NEGATED_CLAIMS)
def test_archive_accepts_conditional_or_negated_deployment_prose(
    tmp_path: Path,
    prose: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "conditional-deployment-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "prose",
    [
        "V3.0.81 has gone live in production.",
        "V3.0.81 and its assets have gone live in production.",
        "V3.0.81 could be deployed after approval, but V3.0.81 was deployed today.",
        "V3.0.81 已在生产环境上线。",
        "V3.0.81 已完成生产上线。",
        "V3.0.81 现已在生产环境正式生效。",
        "V3.0.81 可能在审批后上线，但 V3.0.81 今日已上线生产环境。",
    ],
)
def test_archive_rejects_round4_live_and_completion_synonyms(
    tmp_path: Path,
    prose: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "live-synonym-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "prose",
    [
        "V3.0.81 has not gone live in production.",
        "V3.0.81 cannot go live in production.",
        "V3.0.81 may go live in production.",
        "V3.0.81 will go live in production after approval.",
        "V3.0.81 尚未在生产环境上线。",
        "V3.0.81 可能在生产环境上线。",
        "V3.0.81 将在生产环境上线。",
    ],
)
def test_archive_accepts_negative_pending_and_future_live_controls(
    tmp_path: Path,
    prose: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "live-control-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    verifier.verify_package(archive_path)


ROUND5_AFFIRMATIVE_CLAIMS = [
    "Operators can log in, and V3.0.81 was deployed to production.",
    "Operators can log in if authorized, and V3.0.81 was deployed to production.",
    "V3.0.81 has already gone live in production.",
]


ROUND5_NORMATIVE_OR_FUTURE_CLAIMS = [
    "V3.0.81 should be deployed tomorrow.",
    "V3.0.81 must be deployed after approval.",
    "V3.0.81 ought to be deployed tomorrow.",
    "V3.0.81 应于明日部署至生产环境。",
    "V3.0.81 必须在验收后部署至生产环境。",
]


ROUND6_AFFIRMATIVE_CLAIMS = [
    "V3.0.81 was deployed to production because operators can verify it.",
    "V3.0.81 was deployed to production because operators can verify it if authorized.",
    "V3.0.81 was deployed to production after admins could approve it.",
    "V3.0.81 已部署到生产环境且响应正常。",
]


ROUND6_NEGATIVE_CONDITIONAL_OR_FUTURE_CLAIMS = [
    "V3.0.81 did not get deployed to production.",
    "V3.0.81 should be deployed tomorrow because operators can verify it.",
    "V3.0.81 应于明日部署至生产环境且响应需验证。",
    "V3.0.81 仅当验收通过才可部署到生产环境。",
]


ROUND7_AFFIRMATIVE_CLAIMS = [
    "V3.0.81 has gone live.",
    "V3.0.81 已经部署到生产环境。",
]


ROUND7_NONAFFIRMATIVE_CLAIMS = [
    "V3.0.81 could have been deployed to production.",
    "V3.0.81 will have been deployed to production by Friday.",
    "V3.0.81 was not even deployed to production.",
    "V3.0.81 may eventually be deployed to production.",
]


ROUND8_AFFIRMATIVE_LIVE_CLAIMS = [
    "V3.0.81 is currently live in production.",
    "V3.0.81 is presently live in production.",
]


ROUND9_AFFIRMATIVE_PERFECT_PRODUCTION_STATE_CLAIMS = [
    "V3.0.81 has been running in production since Monday.",
    "V3.0.81 has been in production since Monday.",
    "V3.0.81 and its assets have been running in production since Monday.",
    "V3.0.81 had been in production before the rollback.",
    "V3.0.81 has been continuously running in production since Monday.",
    "V3.0.81 has been running successfully in production since Monday.",
    "V3.0.81 has recently been running in production since Monday.",
    "V3.0.81 has long been running steadily in production.",
    "V3.0.81 has been running reliably in production.",
]


ROUND9_NONAFFIRMATIVE_PERFECT_PRODUCTION_STATE_CLAIMS = [
    "V3.0.81 has not been continuously running in production.",
    "V3.0.81 will have been continuously running in production by Friday.",
    "V3.0.81 may have been running successfully in production.",
    "V3.0.81 has possibly been running in production.",
    "V3.0.81 may recently have been running steadily in production.",
    "V3.0.81 may well have been running in production.",
    "V3.0.81 could recently have been running in production.",
]

ROUND10_NONCLAIM_CONTEXTS = [
    '> Example: "V3.0.81 was deployed to production."',
    '`V3.0.81 was deployed to production.`',
    '示例：“V3.0.81 已在生产环境上线。”',
    'There is no evidence that V3.0.81 was deployed to production.',
    'We cannot claim that V3.0.81 has been released to production.',
    '目前没有证据表明 V3.0.81 已在生产环境上线。',
    '我们不能声称 V3.0.81 已部署到生产环境。',
]


@pytest.mark.parametrize("prose", ROUND5_AFFIRMATIVE_CLAIMS)
def test_archive_rejects_round5_atomic_affirmative_claims(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round5-affirmative-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND5_NORMATIVE_OR_FUTURE_CLAIMS)
def test_archive_accepts_round5_normative_or_future_claims(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round5-normative-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND6_AFFIRMATIVE_CLAIMS)
def test_archive_rejects_round6_modal_tokens_outside_deployment_predicate(
    tmp_path: Path,
    prose: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round6-affirmative-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND6_NEGATIVE_CONDITIONAL_OR_FUTURE_CLAIMS)
def test_archive_accepts_round6_nonaffirmative_deployment_predicate_controls(
    tmp_path: Path,
    prose: str,
) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round6-nonaffirmative-prose.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND7_AFFIRMATIVE_CLAIMS)
def test_archive_rejects_round7_common_affirmative_claims(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round7-affirmative-prose.zip"
    write_release_archive(verifier, archive_path, release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n")

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND7_NONAFFIRMATIVE_CLAIMS)
def test_archive_accepts_round7_complete_auxiliary_controls(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round7-nonaffirmative-prose.zip"
    write_release_archive(verifier, archive_path, release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n")

    verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND8_AFFIRMATIVE_LIVE_CLAIMS)
def test_archive_rejects_round8_current_live_adverbs(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round8-current-live-prose.zip"
    write_release_archive(verifier, archive_path, release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n")

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND9_AFFIRMATIVE_PERFECT_PRODUCTION_STATE_CLAIMS)
def test_archive_rejects_round9_perfect_production_states(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round9-perfect-production-state.zip"
    write_release_archive(verifier, archive_path, release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n")

    with pytest.raises(AssertionError, match="contradictory pending and deployment claims"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND9_NONAFFIRMATIVE_PERFECT_PRODUCTION_STATE_CLAIMS)
def test_archive_accepts_round9_nonaffirmative_perfect_states(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round9-nonaffirmative-perfect-production-state.zip"
    write_release_archive(verifier, archive_path, release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n")

    verifier.verify_package(archive_path)


@pytest.mark.parametrize("prose", ROUND10_NONCLAIM_CONTEXTS)
def test_archive_accepts_round10_nonclaim_contexts(tmp_path: Path, prose: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "round10-nonclaim-context.zip"
    write_release_archive(
        verifier,
        archive_path,
        release_record=f"{PENDING_RELEASE_RECORD}\n{prose}\n",
    )

    verifier.verify_package(archive_path)


def test_archive_rejects_substituted_imported_chunk(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "stale-imported-chunk.zip"
    entry = (
        'globalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__={"version":"3.0.81"};\n'
        'import "./stale.js";\n'
    )
    write_release_archive(verifier, archive_path, entry_source=entry)
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr("v2-api/app/static/vue/assets/stale.js", "const staleVersion = '3.0.80';\n")

    with pytest.raises(AssertionError, match="Vue asset manifest"):
        verifier.verify_package(archive_path)


def test_archive_rejects_extra_executable_script(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "extra-script.zip"
    write_release_archive(
        verifier,
        archive_path,
        unrelated_index_text='<script src="/vue/assets/stale-classic.js"></script>',
    )
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr("v2-api/app/static/vue/assets/stale-classic.js", "const stale = true;\n")

    with pytest.raises(AssertionError, match="exactly one executable module entry"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "member_name",
    [
        "../../outside-release.txt",
        "/absolute-release.txt",
        "C:/drive-release.txt",
        "v2-api/app/static/vue/./dot.js",
        "v2-api/app/static/vue//empty.js",
        "v2-api/app/static/vue/control\x01.js",
    ],
)
def test_archive_rejects_noncanonical_member_paths(tmp_path: Path, member_name: str) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "noncanonical-member.zip"
    write_release_archive(verifier, archive_path)
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr(member_name, "unsafe\n")

    with pytest.raises(AssertionError, match="canonical relative POSIX path"):
        verifier.verify_package(archive_path)


def test_archive_rejects_symlink_member(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "symlink-member.zip"
    write_release_archive(verifier, archive_path)
    link = zipfile.ZipInfo("v2-api/app/static/vue/assets/link.js")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr(link, "target.js")

    with pytest.raises(AssertionError, match="symbolic links"):
        verifier.verify_package(archive_path)


def test_archive_rejects_case_colliding_member(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "case-collision.zip"
    write_release_archive(verifier, archive_path)
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr("V2-API/app/static/vue/assets/app.js", "collision\n")

    with pytest.raises(AssertionError, match="case-insensitive file names"):
        verifier.verify_package(archive_path)
