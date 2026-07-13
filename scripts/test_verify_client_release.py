from __future__ import annotations

import importlib.util
from pathlib import Path
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
V3080_RELEASE_RECORD = "ops/releases/V3.0.80.md"
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
    static_version: str = "3.0.80",
    agents: str = VALID_AGENTS,
    release_record: str = PENDING_RELEASE_RECORD,
    omitted: set[str] | None = None,
) -> None:
    names = set(verifier.REQUIRED_FILES) - set(omitted or set())
    version_line = f"- Version: {manifest_version}\n" if manifest_version is not None else ""
    manifest = "\n".join(("# Release manifest", version_line.rstrip(), *SAFETY_NOTES))
    contents = {
        "RELEASE_MANIFEST.md": manifest,
        "AGENTS.md": agents,
        V3080_RELEASE_RECORD: release_record,
        "v2-api/app/static/vue/index.html": (
            f"<!doctype html><title>Module Manager V{static_version}</title>"
        ),
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name in sorted(names):
            archive.writestr(name, contents.get(name, "fixture\n"))
        archive.writestr(
            "v2-api/app/static/vue/assets/app.js",
            f"const APP_VERSION = '{static_version}';\n",
        )


def test_archive_missing_v3080_release_record_fails_verification(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "module-manager-v2-server-v3.0.80.zip"
    write_release_archive(verifier, archive_path, omitted={V3080_RELEASE_RECORD})

    with pytest.raises(AssertionError, match=r"ops/releases/V3\.0\.80\.md"):
        verifier.verify_package(archive_path)


def test_archive_missing_manifest_version_fails_verification(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "missing-version.zip"
    write_release_archive(verifier, archive_path, manifest_version=None)

    with pytest.raises(AssertionError, match="manifest must define Version"):
        verifier.verify_package(archive_path)


def test_archive_manifest_version_must_match_static_version(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "static-version-mismatch.zip"
    write_release_archive(verifier, archive_path, static_version="3.0.79")

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
