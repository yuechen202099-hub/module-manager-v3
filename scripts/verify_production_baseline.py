from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRODUCTION_REF = "latest"
DEFAULT_REMOTE = "origin"
DEFAULT_REMOTE_BRANCH = "production/*"
DEFAULT_BASELINE_TAG = "latest"
DEFAULT_EXPECTED_COMMIT = ""


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


def command_error_text(exc: subprocess.CalledProcessError) -> str:
    return (exc.stderr or exc.stdout or "").strip()


def git_output(repo: Path, args: list[str]) -> str:
    return run_git(repo, args).stdout.strip()


def resolve_commit(repo: Path, ref: str) -> str:
    return git_output(repo, ["rev-parse", "--verify", f"{ref}^{{commit}}"])


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = run_git(repo, ["merge-base", "--is-ancestor", ancestor, descendant], check=False)
    return result.returncode == 0


def latest_production_tag(repo: Path, production_ref: str) -> str:
    output = git_output(repo, ["tag", "--merged", production_ref, "--sort=-v:refname", "--list", "v[0-9]*"])
    tags = [tag.strip() for tag in output.splitlines() if tag.strip()]
    if not tags:
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["git", "tag", "--merged", production_ref, "--sort=-v:refname", "--list", "v[0-9]*"],
            stderr=f"No production version tags found on {production_ref}",
        )
    return tags[0]


def latest_version_tag(repo: Path) -> str:
    output = git_output(repo, ["tag", "--sort=-v:refname", "--list", "v[0-9]*"])
    tags = [tag.strip() for tag in output.splitlines() if tag.strip()]
    if not tags:
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["git", "tag", "--sort=-v:refname", "--list", "v[0-9]*"],
            stderr="No version tags found",
        )
    return tags[0]


def production_refs_containing(repo: Path, commit: str, remote: str) -> list[str]:
    output = git_output(repo, ["branch", "-a", "--contains", commit, "--format=%(refname:short)"])
    refs = [ref.strip() for ref in output.splitlines() if ref.strip()]
    prefixes = (f"{remote}/production/", "production/")
    return sorted(
        [ref for ref in refs if ref.startswith(prefixes)],
        key=lambda ref: [int(part) for part in re.findall(r"\d+", ref)],
        reverse=True,
    )


def latest_production_ref(repo: Path, tag_commit: str, remote: str) -> str:
    refs = production_refs_containing(repo, tag_commit, remote)
    if not refs:
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["git", "branch", "-a", "--contains", tag_commit],
            stderr=f"No production branch contains {tag_commit[:12]}",
        )
    return refs[0]


def fetch_production_refs(repo: Path, remote: str, branch: str) -> None:
    if branch in {"", "latest", "production/*"}:
        run_git(repo, ["fetch", remote, f"+refs/heads/production/*:refs/remotes/{remote}/production/*", "--tags"])
        return
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
            issues.append(f"Failed to fetch {remote}/{remote_branch}: {command_error_text(exc)}")

    def resolve_or_issue(ref: str, label: str) -> str:
        try:
            return resolve_commit(repo, ref)
        except subprocess.CalledProcessError as exc:
            issues.append(f"{label} {ref} is not available locally: {command_error_text(exc)}")
            return ""

    effective_baseline_tag = baseline_tag
    if baseline_tag in {"", "latest"}:
        try:
            effective_baseline_tag = latest_version_tag(repo)
        except subprocess.CalledProcessError as exc:
            issues.append(f"Latest production tag is not available: {command_error_text(exc)}")
            effective_baseline_tag = ""
    tag_commit = resolve_or_issue(effective_baseline_tag, "Baseline tag") if effective_baseline_tag else ""
    effective_production_ref = production_ref
    if production_ref in {"", "latest"} and tag_commit:
        try:
            effective_production_ref = latest_production_ref(repo, tag_commit, remote)
        except subprocess.CalledProcessError as exc:
            issues.append(f"Latest production ref is not available: {command_error_text(exc)}")
            effective_production_ref = ""
    production_commit = resolve_or_issue(effective_production_ref, "Production ref") if effective_production_ref else ""
    current_commit = resolve_or_issue(current_ref, "Current ref")

    if expected_commit and production_commit and not production_commit.startswith(expected_commit):
        issues.append(
            f"Production ref {effective_production_ref} is {production_commit[:12]}, expected {expected_commit}"
        )
    if expected_commit and tag_commit and not tag_commit.startswith(expected_commit):
        issues.append(f"Baseline tag {effective_baseline_tag} is {tag_commit[:12]}, expected {expected_commit}")
    if tag_commit and production_commit and not is_ancestor(repo, tag_commit, production_commit):
        issues.append(
            f"Baseline tag {effective_baseline_tag} ({tag_commit[:12]}) is not contained in "
            f"production ref {effective_production_ref} ({production_commit[:12]})"
        )
    if production_commit and current_commit and not is_ancestor(repo, production_commit, current_commit):
        issues.append(
            f"Current ref {current_ref} does not contain production ref {effective_production_ref} "
            f"({production_commit[:12]})"
        )

    return BaselineResult(
        ok=not issues,
        production_ref=effective_production_ref,
        production_commit=production_commit,
        baseline_tag=effective_baseline_tag,
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
    parser.add_argument(
        "--baseline-tag",
        default=DEFAULT_BASELINE_TAG,
        help="Production baseline tag to require, or 'latest' for the newest production tag.",
    )
    parser.add_argument(
        "--expected-commit",
        default=DEFAULT_EXPECTED_COMMIT,
        help="Optional expected production commit prefix for locked release checks.",
    )
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
