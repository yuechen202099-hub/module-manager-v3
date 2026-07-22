from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPOSITORY_ROOT / "v2-api"
EXPECTED_VERSION = "3.1.0"


def read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_v3_1_runtime_version_sources_and_release_notes_are_aligned() -> None:
    assert f'version="{EXPECTED_VERSION}"' in read("v2-api/app/main.py")
    assert f'return "{EXPECTED_VERSION}"' in read("v2-api/app/services/ops_status.py")
    assert f'version = "{EXPECTED_VERSION}"' in read("v2-api/pyproject.toml")
    assert json.loads(read("v2-web/package.json"))["version"] == EXPECTED_VERSION
    assert json.loads(read("v2-web/src/version.json"))["version"] == EXPECTED_VERSION
    assert f"Module Manager V{EXPECTED_VERSION}" in read("v2-web/index.html")

    release_notes = read("v2-web/src/constants/releaseNotes.ts")
    for required_text in (
        "双 Sheet",
        "四类照片",
        "条码/二维码",
        "OCR",
        "人工确认",
        "自动归档",
        "后台自动缓存",
    ):
        assert required_text in release_notes


def test_v3_1_preview_defaults_to_read_only_preview() -> None:
    preview = read("v2-api/scripts/preview_v3_1_backfill.py")
    assert "--preview" in preview
    assert "--apply" in preview
    assert "default=\"preview\"" in preview
    for field in ("backfilled", "conflicts", "skipped", "queueable", "unscannable", "export_errors"):
        assert field in preview


def test_v3_1_release_verifier_validates_candidate_contract() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/verify_v3_1_release.py", "--repo-root", str(REPOSITORY_ROOT)],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for expected in (
        "migration",
        "4-photo eligibility",
        "worker paused",
        "20 groups serial",
        "5 seconds",
        "placeholder zero",
        "export sample",
        "task claim",
        "review performance",
    ):
        assert expected in result.stdout


def test_v3_1_release_package_contains_new_release_guards() -> None:
    build_script = read("scripts/build-client-release.ps1")
    package_verifier = read("scripts/verify-client-release.py")
    for path in (
        "v2-api\\scripts\\preview_v3_1_backfill.py",
        "v2-api\\scripts\\verify_v3_1_release.py",
    ):
        assert path in build_script
    for path in (
        "v2-api/scripts/preview_v3_1_backfill.py",
        "v2-api/scripts/verify_v3_1_release.py",
    ):
        assert path in package_verifier
