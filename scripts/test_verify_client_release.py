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


def load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_client_release", ROOT / "scripts" / "verify-client-release.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load verify-client-release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archive_missing_v3080_release_record_fails_verification(tmp_path: Path) -> None:
    verifier = load_verifier()
    archive_path = tmp_path / "module-manager-v2-server-v3.0.80.zip"
    archive_names = set(verifier.REQUIRED_FILES)
    archive_names.discard(V3080_RELEASE_RECORD)

    with zipfile.ZipFile(archive_path, "w") as archive:
        for name in sorted(archive_names):
            content = "\n".join(SAFETY_NOTES) if name == "RELEASE_MANIFEST.md" else "fixture\n"
            archive.writestr(name, content)

    with pytest.raises(AssertionError, match=r"ops/releases/V3\.0\.80\.md"):
        verifier.verify_package(archive_path)
