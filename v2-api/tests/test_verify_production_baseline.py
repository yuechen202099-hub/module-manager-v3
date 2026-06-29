from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "verify_production_baseline.py"
GIT = "C:/Program Files/Git/cmd/git.exe" if Path("C:/Program Files/Git/cmd/git.exe").exists() else "git"


def load_script():
    spec = importlib.util.spec_from_file_location("verify_production_baseline", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [GIT, *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def commit_file(repo: Path, path: str, content: str, message: str) -> str:
    file_path = repo / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    git(repo, "add", path)
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "codex@example.invalid")
    git(repo, "config", "user.name", "Codex")
    return repo


def test_verify_production_baseline_accepts_platform_branch_containing_production(tmp_path):
    script = load_script()
    repo = init_repo(tmp_path)
    production_commit = commit_file(repo, "app.txt", "production\n", "production")
    git(repo, "tag", "v3.0.68")
    git(repo, "branch", "production/v3.0.35")
    commit_file(repo, "platform.txt", "platform\n", "platform")

    result = script.verify_baseline(
        repo=repo,
        production_ref="production/v3.0.35",
        baseline_tag="v3.0.68",
        expected_commit=production_commit[:7],
        current_ref="HEAD",
    )

    assert result.ok is True
    assert result.production_commit == production_commit


def test_verify_production_baseline_rejects_platform_branch_missing_production_commit(tmp_path):
    script = load_script()
    repo = init_repo(tmp_path)
    commit_file(repo, "base.txt", "base\n", "base")
    git(repo, "checkout", "-b", "production/v3.0.35")
    production_commit = commit_file(repo, "production.txt", "production\n", "production")
    git(repo, "tag", "v3.0.68")
    git(repo, "checkout", "main")
    commit_file(repo, "platform.txt", "platform\n", "platform")

    result = script.verify_baseline(
        repo=repo,
        production_ref="production/v3.0.35",
        baseline_tag="v3.0.68",
        expected_commit=production_commit[:7],
        current_ref="HEAD",
    )

    assert result.ok is False
    assert any("does not contain" in issue for issue in result.issues)


def test_verify_production_baseline_requires_tag_to_resolve_to_expected_commit(tmp_path):
    script = load_script()
    repo = init_repo(tmp_path)
    production_commit = commit_file(repo, "production.txt", "production\n", "production")
    git(repo, "branch", "production/v3.0.35")
    commit_file(repo, "platform.txt", "platform\n", "platform")

    result = script.verify_baseline(
        repo=repo,
        production_ref="production/v3.0.35",
        baseline_tag="v3.0.68",
        expected_commit=production_commit[:7],
        current_ref="HEAD",
    )

    assert result.ok is False
    assert any("v3.0.68" in issue for issue in result.issues)


def test_verify_production_baseline_rejects_unexpected_production_commit(tmp_path):
    script = load_script()
    repo = init_repo(tmp_path)
    expected_commit = commit_file(repo, "expected.txt", "expected\n", "expected")
    git(repo, "tag", "v3.0.68")
    git(repo, "branch", "production/v3.0.35")
    git(repo, "checkout", "production/v3.0.35")
    commit_file(repo, "production.txt", "new production\n", "new production")
    git(repo, "checkout", "main")
    commit_file(repo, "platform.txt", "platform\n", "platform")

    result = script.verify_baseline(
        repo=repo,
        production_ref="production/v3.0.35",
        baseline_tag="v3.0.68",
        expected_commit=expected_commit,
        current_ref="HEAD",
    )

    assert result.ok is False
    assert any("Production ref" in issue for issue in result.issues)


def test_verify_production_baseline_resolves_annotated_tag_to_commit(tmp_path):
    script = load_script()
    repo = init_repo(tmp_path)
    production_commit = commit_file(repo, "production.txt", "production\n", "production")
    git(repo, "tag", "-a", "v3.0.68", "-m", "V3.0.68")
    git(repo, "branch", "production/v3.0.35")
    commit_file(repo, "platform.txt", "platform\n", "platform")

    result = script.verify_baseline(
        repo=repo,
        production_ref="production/v3.0.35",
        baseline_tag="v3.0.68",
        expected_commit=production_commit,
        current_ref="HEAD",
    )

    assert result.ok is True
    assert result.tag_commit == production_commit
