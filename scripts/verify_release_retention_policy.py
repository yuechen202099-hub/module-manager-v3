from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise AssertionError(message)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> int:
    cleanup_path = ROOT / "scripts" / "cleanup_old_releases.sh"
    if not cleanup_path.exists():
        fail("scripts/cleanup_old_releases.sh is required for production release retention")

    gitattributes = ROOT / ".gitattributes"
    if not gitattributes.exists() or "*.sh text eol=lf" not in gitattributes.read_text(encoding="utf-8"):
        fail(".gitattributes must force shell scripts to LF line endings")

    cleanup = cleanup_path.read_text(encoding="utf-8")
    required_snippets = {
        'KEEP_RELEASES="${2:-5}"': "default retention must keep the latest 5 releases",
        'readlink -f "$APP_ROOT/current"': "cleanup must resolve and protect the current symlink target",
        'DRY_RUN=1': "cleanup must support dry-run mode before deleting old releases",
        'rm -rf -- "$release_path"': "cleanup must delete only explicit release directory paths",
        'module-manager-v2-server-*.zip': "cleanup must remove loose release package archives from releases root",
        'rm -f -- "$package_path"': "cleanup must delete only explicit release package archive paths",
        'Refusing to delete current release': "cleanup must refuse to delete current release",
    }
    for snippet, message in required_snippets.items():
        if snippet not in cleanup:
            fail(message)

    runbook = read("docs/sop/06-production-deploy-runbook.md")
    for text in [
        "cleanup_old_releases.sh",
        "keep 5",
        "--dry-run",
        "Production Release Retention",
    ]:
        if text not in runbook:
            fail(f"deploy runbook must document release retention: {text}")

    package_builder = read("scripts/build-client-release.ps1")
    if 'scripts\\cleanup_old_releases.sh' not in package_builder:
        fail("release builder must include cleanup_old_releases.sh in server packages")
    if "Normalize server shell scripts to LF" not in package_builder:
        fail("release builder must normalize shell scripts to LF before zipping")

    release_verifier = read("scripts/verify-client-release.py")
    if "scripts/cleanup_old_releases.sh" not in release_verifier:
        fail("release package verifier must require cleanup_old_releases.sh")
    if "Shell scripts must use LF line endings" not in release_verifier:
        fail("release package verifier must reject CRLF shell scripts")

    sop_verifier = read("scripts/verify_release_sop.py")
    if "scripts/cleanup_old_releases.sh" not in sop_verifier:
        fail("release SOP verifier must require cleanup_old_releases.sh")
    if "verify_release_retention_policy.py" not in sop_verifier:
        fail("release SOP verifier must require the retention policy verifier")

    print("[OK] production release retention policy is enforced")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
