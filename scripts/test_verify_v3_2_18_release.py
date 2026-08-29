from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_v3_2_18_release.py"
V3217_RECORD_SHA256 = "eb3007e5ec2b63d4a56ee80b76864d451faed55c511638be86007ca61bd6807d"


def load_verifier():
    assert VERIFIER_PATH.is_file(), "V3.2.18 release verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_v3_2_18_release", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v3218_release_contract_identity_and_immutable_baseline() -> None:
    verifier = load_verifier()

    assert verifier.VERSION == "3.2.18"
    assert verifier.DISPLAY_VERSION == "V3.2.18"
    assert verifier.DEPLOYED_BASELINE == "V3.2.17"
    assert verifier.MAINTENANCE_BRANCH == "production/V3/3.2.18"
    assert verifier.BASELINE_RELEASE_PATH == "ops/releases/V3.2.17.md"
    assert verifier.RELEASE_PATH == "ops/releases/V3.2.18.md"
    assert verifier.ARCHIVE_PATH == "build/server-release/module-manager-v2-server-3.2.18.zip"
    assert verifier.PRODUCTION_RECORD_SHA256 == V3217_RECORD_SHA256
    assert hashlib.sha256((ROOT / verifier.BASELINE_RELEASE_PATH).read_bytes()).hexdigest() == V3217_RECORD_SHA256


def test_v3218_release_contract_carries_historical_and_current_inputs() -> None:
    verifier = load_verifier()
    required = set(verifier.REQUIRED_FILES)

    assert "ops/releases/V3.2.17.md" in required
    assert "ops/releases/V3.2.18.md" in required
    assert "scripts/verify_v3_2_17_release.py" in required
    assert "scripts/test_verify_v3_2_17_release.py" in required
    assert "scripts/verify_v3_2_18_release.py" in required
    assert "scripts/test_verify_v3_2_18_release.py" in required
    assert "docs/superpowers/plans/2026-08-29-v3-2-18-approved-exception-hotfix.md" in required


def test_v3218_source_contract_accepts_the_pending_candidate() -> None:
    verifier = load_verifier()

    assert verifier.collect_failures(ROOT, "source") == []


def test_v3218_attestation_requires_current_release_and_v3217_rollback_paths(
    tmp_path: Path,
) -> None:
    verifier = load_verifier()
    package = tmp_path / "module-manager-v2-server-3.2.18.zip"
    package.write_bytes(b"v3.2.18-package")
    package_sha256 = hashlib.sha256(package.read_bytes()).hexdigest()
    source_commit = "a" * 40
    release_path = tmp_path / verifier.RELEASE_PATH
    release_path.parent.mkdir(parents=True)
    exact_fields = {
        **verifier.ATTESTATION_EXACT_FIELDS,
        "Source commit": source_commit,
        "SHA256": package_sha256,
        "Server SHA256": package_sha256,
        "Backup directory": "/opt/module-manager-v2/backups/v3.2.18-20260829T120000Z",
        "Release directory": "/opt/module-manager-v2/releases/v3.2.18-20260829T120100Z",
        "Rollback directory": "/opt/module-manager-v2/releases/v3.2.17-20260829T095416Z",
        "Local health": "HTTP 200 version 3.2.18",
        "Public health": "HTTP 200 version 3.2.18",
        "Browser viewport": "1280x720 passed",
    }
    release_path.write_text(
        "# V3.2.18 Production Release Record\n\n"
        + "\n".join(f"- {field}: `{value}`" for field, value in exact_fields.items())
        + "\n",
        encoding="utf-8",
    )

    failures: list[str] = []
    verifier._check_attestation(tmp_path, package, source_commit, failures)

    assert failures == []
