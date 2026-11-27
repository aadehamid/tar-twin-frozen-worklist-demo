#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def _clean_git_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git_bytes(repo: Path, env: dict[str, str], *args: str) -> bytes:
    res = subprocess.run(
        ["git", "-C", str(repo), *args],
        env=env,
        check=True,
        capture_output=True,
    )
    return res.stdout


def _hash_regular_file(path: bytes) -> str:
    with open(path, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


@dataclass(frozen=True)
class TreeSnapshot:
    entries: dict[bytes, tuple[object, ...]]
    index_raw: bytes
    status_raw: bytes


def snapshot(repo: Path) -> TreeSnapshot:
    repo = repo.resolve()
    repo_b = os.fsencode(repo)
    git_env = _clean_git_env()

    raw_paths = _git_bytes(repo, git_env, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    unique_paths = {p for p in raw_paths.split(b"\x00") if p}

    entries: dict[bytes, tuple[object, ...]] = {}
    for rel in unique_paths:
        full = os.path.join(repo_b, rel)
        try:
            st = os.lstat(full)
        except FileNotFoundError:
            entries[rel] = ("missing",)
            continue

        fmt = stat.S_IFMT(st.st_mode)
        mode = stat.S_IMODE(st.st_mode)
        if stat.S_ISLNK(st.st_mode):
            target = os.readlink(full)
            entries[rel] = ("symlink", fmt, mode, target)
        elif stat.S_ISREG(st.st_mode):
            digest = _hash_regular_file(full)
            entries[rel] = ("file", fmt, mode, digest)
        else:
            entries[rel] = ("other", fmt, mode)

    index_raw = _git_bytes(repo, git_env, "ls-files", "-s", "-z")
    status_raw = _git_bytes(repo, git_env, "status", "--porcelain=v1", "-z", "-uall")
    return TreeSnapshot(entries=entries, index_raw=index_raw, status_raw=status_raw)


def _fmt_path(raw: bytes) -> str:
    return repr(raw.decode("utf-8", errors="surrogateescape"))


def diff_snapshots(before: TreeSnapshot, after: TreeSnapshot) -> list[str]:
    diffs: list[str] = []
    all_paths = sorted(set(before.entries) | set(after.entries))
    for rel in all_paths:
        b = before.entries.get(rel)
        a = after.entries.get(rel)
        if b != a:
            diffs.append(f"path changed: {_fmt_path(rel)} ({b!r} -> {a!r})")
    if before.index_raw != after.index_raw:
        diffs.append("git index changed (git ls-files -s differs)")
    if before.status_raw != after.status_raw:
        diffs.append("git status changed (git status --porcelain=v1 -z differs)")
    return diffs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a command and fail if it modifies the repo tree.")
    parser.add_argument("--repo", required=True, type=Path, help="Repository root path")
    parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to run (after --)")
    args = parser.parse_args(argv)

    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("tree_guard: no command provided", file=sys.stderr)
        return 2

    before = snapshot(args.repo)
    proc = subprocess.run(cmd, check=False)
    after = snapshot(args.repo)

    diffs = diff_snapshots(before, after)
    if diffs:
        print("tree_guard: checks modified the working tree:", file=sys.stderr)
        for line in diffs:
            print(f"  - {line}", file=sys.stderr)
        return proc.returncode if proc.returncode != 0 else 1

    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
