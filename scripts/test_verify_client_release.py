from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
V3080_RELEASE_RECORD = "ops/releases/V3.0.80.md"
RUNTIME_VERSION_ARTIFACT = "v2-api/app/static/vue/version.json"
SOURCE_VERSION_ARTIFACT = "v2-web/public/version.json"
SAFETY_NOTES = (
    "Production mode disables demo accounts by default",
    "Production mode disables /docs, /redoc, and /openapi.json by default",
    "Confirm /docs, /redoc, and /openapi.json return 404 in production",
    "Vue strict-native production pages are required",
    "PostgreSQL cutover audit must be reviewed before production deployment",
    "Production SOP files and release record templates are present",
)

VALID_AGENTS = """# Package fixture

- Deployed production baseline: `V3.0.79`.
- Release candidate: `V3.0.80`.
- 当前已部署生产版本：`V3.0.79`。
- 当前发布候选版本：`V3.0.80`。
"""
PENDING_RELEASE_RECORD = """# V3.0.80 Production Release Record

## Summary

- Status: pending
- V3.0.80 has not been deployed to production.

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
    manifest_version: str | None = "3.0.80",
    manifest_versions: list[str] | None = None,
    static_version: str = "3.0.80",
    title_version: str | None = None,
    runtime_version: str | None = None,
    source_version: str | None = None,
    unrelated_static_version: str = "",
    unrelated_index_text: str = "",
    agents: str = VALID_AGENTS,
    release_record: str = PENDING_RELEASE_RECORD,
    omitted: set[str] | None = None,
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
    resolved_title_version = title_version or static_version
    contents = {
        "RELEASE_MANIFEST.md": manifest,
        "AGENTS.md": agents,
        V3080_RELEASE_RECORD: release_record,
        RUNTIME_VERSION_ARTIFACT: json.dumps({"version": resolved_runtime_version}),
        SOURCE_VERSION_ARTIFACT: json.dumps({"version": resolved_source_version}),
        "v2-api/app/static/vue/index.html": (
            f"<!doctype html><title>Module Manager V{resolved_title_version}</title>{unrelated_index_text}"
        ),
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name in sorted(names):
            archive.writestr(name, contents.get(name, "fixture\n"))
        archive.writestr(
            "v2-api/app/static/vue/assets/app.js",
            f"const APP_VERSION = '{resolved_runtime_version}';\n"
            f"const unrelatedReleaseNote = '{unrelated_static_version}';\n",
        )


def test_archive_missing_v3080_release_record_fails_verification(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "module-manager-v2-server-v3.0.80.zip"
    write_release_archive(verifier, archive_path, omitted={V3080_RELEASE_RECORD})

    with pytest.raises(AssertionError, match=r"ops/releases/V3\.0\.80\.md"):
        verifier.verify_package(archive_path)


def test_release_builder_default_version_is_candidate_semantic_version() -> None:
    build_script = (ROOT / "scripts" / "build-client-release.ps1").read_text(encoding="utf-8")

    assert '[string]$Version = "3.0.80"' in build_script


def test_archive_missing_manifest_version_fails_verification(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "missing-version.zip"
    write_release_archive(verifier, archive_path, manifest_version=None)

    with pytest.raises(AssertionError, match="exactly one semantic Version"):
        verifier.verify_package(archive_path)


def test_archive_manifest_version_must_match_static_version(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "static-version-mismatch.zip"
    write_release_archive(verifier, archive_path, static_version="3.0.79")

    with pytest.raises(AssertionError, match="static index title"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "manifest_versions",
    [
        ["3.0.80", "3.0.80"],
        ["3.0.80", "3.0.79"],
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
    write_release_archive(verifier, archive_path, manifest_version="release-3.0.80")

    with pytest.raises(AssertionError, match="exactly one semantic Version"):
        verifier.verify_package(archive_path)


def test_archive_runtime_version_cannot_be_satisfied_by_unrelated_candidate_string(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "forged-runtime-version.zip"
    write_release_archive(
        verifier,
        archive_path,
        runtime_version="3.0.79",
        unrelated_static_version="3.0.80",
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
    write_release_archive(verifier, archive_path, source_version="3.0.79")

    with pytest.raises(AssertionError, match="source and built runtime versions"):
        verifier.verify_package(archive_path)


def test_archive_title_version_cannot_be_satisfied_by_unrelated_index_text(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "forged-title-version.zip"
    write_release_archive(
        verifier,
        archive_path,
        title_version="3.0.79",
        unrelated_index_text="<!-- Module Manager V3.0.80 -->",
    )

    with pytest.raises(AssertionError, match="static index title"):
        verifier.verify_package(archive_path)


def test_archive_rejects_contradictory_agents_deployed_markers(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "contradictory-agents.zip"
    agents = VALID_AGENTS.replace(
        "Deployed production baseline: `V3.0.79`",
        "Deployed production baseline: `V3.0.80`",
    )
    write_release_archive(verifier, archive_path, agents=agents)

    with pytest.raises(AssertionError, match="English and Chinese deployed production baseline"):
        verifier.verify_package(archive_path)


def test_archive_rejects_deployed_record_without_live_evidence(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "unsupported-deployed-record.zip"
    record = PENDING_RELEASE_RECORD.replace("Status: pending", "Status: deployed")
    write_release_archive(verifier, archive_path, release_record=record)

    with pytest.raises(AssertionError, match="claims deployed without complete live evidence"):
        verifier.verify_package(archive_path)


@pytest.mark.parametrize(
    "affirmative_prose",
    [
        "V3.0.80 was not deployed yesterday and was deployed today.",
        "V3.0.80\n\nhas been deployed to production.",
        "V3.0.80 生产部署已完成。",
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


def test_valid_pending_candidate_archive_passes_truthfulness_checks(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "valid-pending.zip"
    write_release_archive(verifier, archive_path)

    verifier.verify_package(archive_path)


ROUND4_CONDITIONAL_OR_NEGATED_CLAIMS = [
    "V3.0.80 can't be deployed to production.",
    "V3.0.80 cannot be deployed to production.",
    "V3.0.80 can be deployed to production.",
    "V3.0.80 could be deployed to production.",
    "V3.0.80 may be deployed to production.",
    "V3.0.80 might be deployed to production.",
    "V3.0.80 is deployed to production if approval is granted.",
    "V3.0.80 is deployed to production unless rollback is required.",
    "V3.0.80 可能已上线生产环境。",
    "V3.0.80 若通过验收则已上线生产环境。",
    "如果验证通过，V3.0.80 生产部署已完成。",
    "除非回归测试失败，否则 V3.0.80 已部署到生产环境。",
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
        "V3.0.80 has gone live in production.",
        "V3.0.80 and its assets have gone live in production.",
        "V3.0.80 could be deployed after approval, but V3.0.80 was deployed today.",
        "V3.0.80 已在生产环境上线。",
        "V3.0.80 已完成生产上线。",
        "V3.0.80 现已在生产环境正式生效。",
        "V3.0.80 可能在审批后上线，但 V3.0.80 今日已上线生产环境。",
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
        "V3.0.80 has not gone live in production.",
        "V3.0.80 cannot go live in production.",
        "V3.0.80 may go live in production.",
        "V3.0.80 will go live in production after approval.",
        "V3.0.80 尚未在生产环境上线。",
        "V3.0.80 可能在生产环境上线。",
        "V3.0.80 将在生产环境上线。",
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
