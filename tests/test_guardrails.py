"""Tests for scripts/tree_guard.py, scripts/check_docs.py, scripts/hooks/pre-push, and scripts/check.sh."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
PRE_PUSH = SCRIPTS_DIR / "hooks" / "pre-push"
CHECK_SH = SCRIPTS_DIR / "check.sh"


def clean_git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of os.environ with all GIT_* variables removed."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    if extra:
        env.update(extra)
    return env


def run_git(repo: Path, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        env=clean_git_env(extra_env),
        check=True,
        capture_output=True,
        text=True,
    )


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    run_git(path, "init", "-b", "main")
    run_git(path, "config", "user.name", "Test User")
    run_git(path, "config", "user.email", "test@example.com")
    (path / "README.md").write_text("# Demo\n\nSee [doc](docs/info.md).\n", encoding="utf-8")
    (path / "docs").mkdir()
    (path / "docs" / "info.md").write_text("# Info\n\nPlain text.\n", encoding="utf-8")
    run_git(path, "add", "README.md", "docs/info.md")
    run_git(path, "commit", "-m", "Initial commit")
    return path


def _load_module(name: str):
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import importlib

    return importlib.import_module(name)


def test_clean_git_env_leaves_decoy_git_dir_untouched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Per guardrails: git helpers inside tests must drop inherited GIT_* vars."""
    decoy = init_repo(tmp_path / "decoy")
    decoy_head_before = run_git(decoy, "rev-parse", "HEAD").stdout.strip()
    decoy_status_before = run_git(decoy, "status", "--porcelain=v1").stdout

    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))

    other = init_repo(tmp_path / "other")
    (other / "extra.txt").write_text("hello\n", encoding="utf-8")
    run_git(other, "add", "extra.txt")
    run_git(other, "commit", "-m", "Add extra")

    assert run_git(decoy, "rev-parse", "HEAD").stdout.strip() == decoy_head_before
    assert run_git(decoy, "status", "--porcelain=v1").stdout == decoy_status_before
    assert not (decoy / "extra.txt").exists()


class TestTreeGuard:
    def test_clean_snapshot_matches(self, tmp_path: Path):
        tg = _load_module("tree_guard")
        repo = init_repo(tmp_path / "repo")
        before = tg.snapshot(repo)
        after = tg.snapshot(repo)
        assert tg.diff_snapshots(before, after) == []

    def test_detects_rewritten_untracked_file(self, tmp_path: Path):
        tg = _load_module("tree_guard")
        repo = init_repo(tmp_path / "repo")
        scratch = repo / "untracked.txt"
        scratch.write_text("v1\n", encoding="utf-8")
        before = tg.snapshot(repo)
        scratch.write_text("v2\n", encoding="utf-8")
        after = tg.snapshot(repo)
        diffs = tg.diff_snapshots(before, after)
        assert any("untracked.txt" in d for d in diffs)

    def test_detects_rewritten_file_named_dash(self, tmp_path: Path):
        tg = _load_module("tree_guard")
        repo = init_repo(tmp_path / "repo")
        dash = repo / "-"
        dash.write_text("first\n", encoding="utf-8")
        before = tg.snapshot(repo)
        dash.write_text("second\n", encoding="utf-8")
        after = tg.snapshot(repo)
        diffs = tg.diff_snapshots(before, after)
        assert any("'-'" in d or ": -" in d or "b'-'" in d for d in diffs)

    def test_detects_dropped_execute_bit_on_untracked_script(self, tmp_path: Path):
        tg = _load_module("tree_guard")
        repo = init_repo(tmp_path / "repo")
        script = repo / "tool.sh"
        script.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
        script.chmod(0o755)
        before = tg.snapshot(repo)
        script.chmod(0o644)
        after = tg.snapshot(repo)
        diffs = tg.diff_snapshots(before, after)
        assert any("tool.sh" in d for d in diffs)

    def test_detects_retargeted_symlink_with_identical_target_bytes(self, tmp_path: Path):
        tg = _load_module("tree_guard")
        repo = init_repo(tmp_path / "repo")
        (repo / "a.txt").write_text("same bytes\n", encoding="utf-8")
        (repo / "b.txt").write_text("same bytes\n", encoding="utf-8")
        link = repo / "ptr"
        os.symlink("a.txt", link)
        before = tg.snapshot(repo)
        link.unlink()
        os.symlink("b.txt", link)
        after = tg.snapshot(repo)
        diffs = tg.diff_snapshots(before, after)
        assert any("ptr" in d for d in diffs)

    def test_detects_symlink_target_differing_only_by_trailing_newline(self, tmp_path: Path):
        tg = _load_module("tree_guard")
        repo = init_repo(tmp_path / "repo")
        link = repo / "nl_ptr"
        os.symlink(b"target", link)
        before = tg.snapshot(repo)
        link.unlink()
        os.symlink(b"target\n", link)
        after = tg.snapshot(repo)
        diffs = tg.diff_snapshots(before, after)
        assert any("nl_ptr" in d for d in diffs)

    def test_detects_index_blob_change_while_status_stays_mm(self, tmp_path: Path):
        tg = _load_module("tree_guard")
        repo = init_repo(tmp_path / "repo")
        readme = repo / "README.md"
        readme.write_text("staged-v1\n", encoding="utf-8")
        run_git(repo, "add", "README.md")
        readme.write_text("worktree-v1\n", encoding="utf-8")
        assert run_git(repo, "status", "--porcelain=v1").stdout.strip() == "MM README.md"
        before = tg.snapshot(repo)

        # Replace staged blob with different bytes, then restore identical worktree bytes
        readme.write_text("staged-v2\n", encoding="utf-8")
        run_git(repo, "add", "README.md")
        readme.write_text("worktree-v1\n", encoding="utf-8")
        assert run_git(repo, "status", "--porcelain=v1").stdout.strip() == "MM README.md"
        after = tg.snapshot(repo)

        diffs = tg.diff_snapshots(before, after)
        assert any("index" in d.lower() for d in diffs)

    def test_unreadable_file_aborts_snapshot(self, tmp_path: Path):
        if os.geteuid() == 0:
            pytest.skip("root can read chmod 000 files")
        tg = _load_module("tree_guard")
        repo = init_repo(tmp_path / "repo")
        secret = repo / "unreadable.txt"
        secret.write_text("cannot read\n", encoding="utf-8")
        secret.chmod(0o000)
        try:
            with pytest.raises(OSError):
                tg.snapshot(repo)
        finally:
            secret.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_missing_tracked_file_aborts_snapshot_while_staged_delete_succeeds(self, tmp_path: Path):
        tg = _load_module("tree_guard")
        repo = init_repo(tmp_path / "repo")
        (repo / "docs" / "info.md").unlink()
        with pytest.raises(FileNotFoundError):
            tg.snapshot(repo)
        run_git(repo, "rm", "docs/info.md")
        before = tg.snapshot(repo)
        after = tg.snapshot(repo)
        assert tg.diff_snapshots(before, after) == []


class TestCheckDocs:
    def test_clean_docs_pass(self, tmp_path: Path):
        cd = _load_module("check_docs")
        repo = init_repo(tmp_path / "repo")
        assert cd.check_repo_docs(repo) == []

    def test_catches_em_dash_and_en_dash(self, tmp_path: Path):
        cd = _load_module("check_docs")
        repo = init_repo(tmp_path / "repo")
        (repo / "docs" / "info.md").write_text("Bad \u2014 em dash and \u2013 en dash.\n", encoding="utf-8")
        errors = cd.check_repo_docs(repo)
        assert any("dash" in e.lower() for e in errors)

    def test_catches_broken_relative_link_and_ignores_code_blocks_and_urls(self, tmp_path: Path):
        cd = _load_module("check_docs")
        repo = init_repo(tmp_path / "repo")
        (repo / "docs" / "info.md").write_text(
            "Valid [readme](../README.md#section), [web](https://example.com), "
            "`[inline](missing-inline.md)`, ``[double](missing-double.md)``.\n"
            "```md\n[fenced](missing-fenced.md)\n```\n"
            "Broken [missing](nope.md).\n",
            encoding="utf-8",
        )
        errors = cd.check_repo_docs(repo)
        assert len(errors) == 1
        assert "nope.md" in errors[0]

    def test_catches_link_escaping_repo_root(self, tmp_path: Path):
        cd = _load_module("check_docs")
        outside = tmp_path / "outside.md"
        outside.write_text("outside\n", encoding="utf-8")
        repo = init_repo(tmp_path / "repo")
        (repo / "README.md").write_text("Escape [out](../outside.md).\n", encoding="utf-8")
        errors = cd.check_repo_docs(repo)
        assert any("outside.md" in e or "outside repository" in e.lower() for e in errors)

    def test_handles_balanced_parens_and_reference_links(self, tmp_path: Path):
        cd = _load_module("check_docs")
        repo = init_repo(tmp_path / "repo")
        paren_dir = repo / "docs" / "v(1)"
        paren_dir.mkdir(parents=True)
        (paren_dir / "note(2).md").write_text("# Note\n", encoding="utf-8")
        (repo / "README.md").write_text(
            "Good [paren](docs/v(1)/note(2).md) and [ref][good] and [badref][bad].\n\n"
            "[good]: docs/v(1)/note(2).md\n"
            "[bad]: docs/v(1)/missing(3).md\n",
            encoding="utf-8",
        )
        errors = cd.check_repo_docs(repo)
        assert len(errors) == 1
        assert "missing(3).md" in errors[0]

    def test_scans_markdown_in_other_directories_and_excludes_vendor(self, tmp_path: Path):
        cd = _load_module("check_docs")
        repo = init_repo(tmp_path / "repo")
        (repo / "scripts").mkdir()
        (repo / "scripts" / "guide.md").write_text("See [broken](missing.md) \u2014 bad.\n", encoding="utf-8")
        (repo / "spikes" / "demo" / "vendor").mkdir(parents=True)
        (repo / "spikes" / "demo" / "vendor" / "README.md").write_text(
            "Vendored \u2014 [ignored](nope.md)\n", encoding="utf-8"
        )
        errors = cd.check_repo_docs(repo)
        assert len(errors) == 2
        assert all("scripts/guide.md" in e for e in errors)


class TestPrePushHook:
    def _run_hook(self, stdin_text: str, check_cmd: Path) -> subprocess.CompletedProcess[str]:
        env = clean_git_env({"TAR_TWIN_CHECK_SCRIPT": str(check_cmd)})
        return subprocess.run(
            [str(PRE_PUSH), "origin", "https://example.com/repo.git"],
            input=stdin_text,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_hook_is_executable(self):
        assert PRE_PUSH.exists()
        mode = PRE_PUSH.stat().st_mode
        assert bool(mode & stat.S_IXUSR)

    def test_skips_delete_only_push(self, tmp_path: Path):
        marker = tmp_path / "ran"
        fake_check = tmp_path / "fake_check.sh"
        fake_check.write_text(f"#!/usr/bin/env bash\ntouch '{marker}'\nexit 1\n", encoding="utf-8")
        fake_check.chmod(0o755)

        zero40 = "0" * 40
        stdin = (
            f"(delete) {zero40} refs/heads/old-a {'a' * 40}\n"
            f"(delete) {zero40} refs/heads/old-b {'b' * 40}\n"
        )
        res = self._run_hook(stdin, fake_check)
        assert res.returncode == 0
        assert not marker.exists()

    def test_runs_checks_on_empty_stdin_like_git_hook_run(self, tmp_path: Path):
        marker = tmp_path / "ran"
        fake_check = tmp_path / "fake_check.sh"
        fake_check.write_text(f"#!/usr/bin/env bash\ntouch '{marker}'\nexit 0\n", encoding="utf-8")
        fake_check.chmod(0o755)

        res = self._run_hook("", fake_check)
        assert res.returncode == 0
        assert marker.exists()

    def test_runs_checks_when_push_includes_non_delete_and_propagates_failure(self, tmp_path: Path):
        fake_check = tmp_path / "fake_check.sh"
        fake_check.write_text("#!/usr/bin/env bash\nexit 7\n", encoding="utf-8")
        fake_check.chmod(0o755)

        stdin = (
            f"(delete) {'0' * 40} refs/heads/old {'a' * 40}\n"
            f"refs/heads/feat {'b' * 40} refs/heads/feat {'0' * 40}\n"
        )
        res = self._run_hook(stdin, fake_check)
        assert res.returncode == 7


class TestCheckScript:
    def test_check_script_exists_and_is_executable(self):
        assert CHECK_SH.exists()
        assert bool(CHECK_SH.stat().st_mode & stat.S_IXUSR)

    def test_tree_guard_cli_fails_when_command_mutates_tree(self, tmp_path: Path):
        tg_py = SCRIPTS_DIR / "tree_guard.py"
        repo = init_repo(tmp_path / "repo")
        res = subprocess.run(
            [
                sys.executable,
                str(tg_py),
                "--repo",
                str(repo),
                "--",
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(repo / 'dirty.txt')!r}).write_text('x')",
            ],
            env=clean_git_env(),
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode != 0
        assert "dirty.txt" in (res.stdout + res.stderr)
