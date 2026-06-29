from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRODUCTION_REF = "origin/production/v3.0.35"
DEFAULT_REMOTE = "origin"
DEFAULT_REMOTE_BRANCH = "production/v3.0.35"
DEFAULT_BASELINE_TAG = "v3.0.68"
DEFAULT_EXPECTED_COMMIT = "6b78a329c515240d11f76442d03f25479436eb05"


@dataclass
class BaselineResult:
    ok: bool
    production_ref: str
    production_commit: str = ""
    baseline_tag: str = ""
    tag_commit: str = ""
    current_ref: str = ""
    current_commit: str = ""
    issues: list[str] = field(default_factory=list)


def git_executable() -> str:
    windows_git = Path("C:/Program Files/Git/cmd/git.exe")
    return str(windows_git) if windows_git.exists() else "git"


def run_git(repo: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [git_executable(), *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def git_output(repo: Path, args: list[str]) -> str:
    return run_git(repo, args).stdout.strip()


def resolve_commit(repo: Path, ref: str) -> str:
    return git_output(repo, ["rev-parse", "--verify", f"{ref}^{{commit}}"])


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = run_git(repo, ["merge-base", "--is-ancestor", ancestor, descendant], check=False)
    return result.returncode == 0


def fetch_production_refs(repo: Path, remote: str, branch: str) -> None:
    run_git(repo, ["fetch", remote, branch, "--tags"])


def verify_baseline(
    *,
    repo: Path = ROOT,
    production_ref: str = DEFAULT_PRODUCTION_REF,
    baseline_tag: str = DEFAULT_BASELINE_TAG,
    expected_commit: str = DEFAULT_EXPECTED_COMMIT,
    current_ref: str = "HEAD",
    fetch: bool = False,
    remote: str = DEFAULT_REMOTE,
    remote_branch: str = DEFAULT_REMOTE_BRANCH,
) -> BaselineResult:
    issues: list[str] = []
    if fetch:
        try:
            fetch_production_refs(repo, remote, remote_branch)
        except subprocess.CalledProcessError as exc:
            issues.append(f"Failed to fetch {remote}/{remote_branch}: {exc.stderr.strip() or exc.stdout.strip()}")

    def resolve_or_issue(ref: str, label: str) -> str:
        try:
            return resolve_commit(repo, ref)
        except subprocess.CalledProcessError as exc:
            issues.append(f"{label} {ref} is not available locally: {exc.stderr.strip() or exc.stdout.strip()}")
            return ""

    production_commit = resolve_or_issue(production_ref, "Production ref")
    tag_commit = resolve_or_issue(baseline_tag, "Baseline tag")
    current_commit = resolve_or_issue(current_ref, "Current ref")

    if expected_commit and production_commit and not production_commit.startswith(expected_commit):
        issues.append(
            f"Production ref {production_ref} is {production_commit[:12]}, expected {expected_commit}"
        )
    if expected_commit and tag_commit and not tag_commit.startswith(expected_commit):
        issues.append(f"Baseline tag {baseline_tag} is {tag_commit[:12]}, expected {expected_commit}")
    if production_commit and current_commit and not is_ancestor(repo, production_commit, current_commit):
        issues.append(
            f"Current ref {current_ref} does not contain production ref {production_ref} "
            f"({production_commit[:12]})"
        )

    return BaselineResult(
        ok=not issues,
        production_ref=production_ref,
        production_commit=production_commit,
        baseline_tag=baseline_tag,
        tag_commit=tag_commit,
        current_ref=current_ref,
        current_commit=current_commit,
        issues=issues,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the current platform branch contains the configured production baseline."
    )
    parser.add_argument("--repo", type=Path, default=ROOT, help="Repository path.")
    parser.add_argument("--production-ref", default=DEFAULT_PRODUCTION_REF, help="Production branch/ref to require.")
    parser.add_argument("--baseline-tag", default=DEFAULT_BASELINE_TAG, help="Production baseline tag to require.")
    parser.add_argument("--expected-commit", default=DEFAULT_EXPECTED_COMMIT, help="Expected production commit prefix.")
    parser.add_argument("--current-ref", default="HEAD", help="Current branch/ref to verify.")
    parser.add_argument("--fetch", action="store_true", help="Fetch production branch and tags before checking.")
    parser.add_argument("--remote", default=DEFAULT_REMOTE, help="Remote name used with --fetch.")
    parser.add_argument("--remote-branch", default=DEFAULT_REMOTE_BRANCH, help="Remote branch used with --fetch.")
    args = parser.parse_args()

    result = verify_baseline(
        repo=args.repo,
        production_ref=args.production_ref,
        baseline_tag=args.baseline_tag,
        expected_commit=args.expected_commit,
        current_ref=args.current_ref,
        fetch=args.fetch,
        remote=args.remote,
        remote_branch=args.remote_branch,
    )
    if result.ok:
        print(f"[OK] production ref: {result.production_ref} @ {result.production_commit[:12]}")
        print(f"[OK] baseline tag: {result.baseline_tag} @ {result.tag_commit[:12]}")
        print(f"[OK] current ref contains production baseline: {result.current_ref} @ {result.current_commit[:12]}")
        return 0
    for issue in result.issues:
        print(f"[FAIL] {issue}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
