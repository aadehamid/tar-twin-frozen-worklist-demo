#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

BANNED_DASHES: dict[str, str] = {"\u2014": "em dash", "\u2013": "en dash"}
EXCLUDED_DIR_NAMES = frozenset({".git", ".venv", "node_modules", "vendor"})
EXTERNAL_SCHEMES = frozenset({"http", "https", "mailto"})
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
REF_DEF_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(?:<([^>]+)>|(\S+))")


def _clean_git_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _is_excluded(rel_path: Path) -> bool:
    return any(part in EXCLUDED_DIR_NAMES for part in rel_path.parts[:-1])


def _iter_doc_files(repo: Path) -> list[Path]:
    res = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        env=_clean_git_env(),
        capture_output=True,
        check=False,
    )
    if res.returncode == 0:
        paths: list[Path] = []
        seen: set[Path] = set()
        for raw in res.stdout.split(b"\x00"):
            if not raw:
                continue
            rel = Path(os.fsdecode(raw))
            if rel.suffix.lower() != ".md" or _is_excluded(rel):
                continue
            full = repo / rel
            if full.is_file() and full not in seen:
                seen.add(full)
                paths.append(full)
        return sorted(paths)

    return sorted(
        p
        for p in repo.rglob("*.md")
        if p.is_file() and not _is_excluded(p.relative_to(repo))
    )


def _strip_inline_code(line: str) -> str:
    out: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        if line[i] == "`":
            j = i
            while j < n and line[j] == "`":
                j += 1
            ticks = line[i:j]
            end = line.find(ticks, j)
            if end != -1:
                i = end + len(ticks)
                continue
            out.append(ticks)
            i = j
        else:
            out.append(line[i])
            i += 1
    return "".join(out)


def _extract_inline_destinations(line: str) -> list[str]:
    targets: list[str] = []
    i = 0
    n = len(line)
    while True:
        idx = line.find("](", i)
        if idx == -1:
            break
        pos = idx + 2
        while pos < n and line[pos] in " \t":
            pos += 1
        if pos >= n:
            break
        if line[pos] == "<":
            end = line.find(">", pos + 1)
            if end == -1:
                i = pos + 1
                continue
            targets.append(line[pos + 1 : end].strip())
            i = end + 1
            continue

        start = pos
        depth = 0
        while pos < n:
            ch = line[pos]
            if ch == "\\" and pos + 1 < n:
                pos += 2
                continue
            if ch in " \t":
                break
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    break
                depth -= 1
            pos += 1
        dest = line[start:pos].strip()
        if dest:
            targets.append(dest)
        i = pos + 1
    return targets


def _extract_targets(line: str) -> list[str]:
    cleaned = _strip_inline_code(line)
    targets = _extract_inline_destinations(cleaned)
    ref_match = REF_DEF_RE.match(cleaned)
    if ref_match:
        ref_target = (ref_match.group(1) or ref_match.group(2) or "").strip()
        if ref_target:
            targets.append(ref_target)
    return targets


def check_repo_docs(repo: Path) -> list[str]:
    repo_root = repo.resolve()
    errors: list[str] = []
    link_cache: dict[tuple[Path, str], str | None] = {}

    for md_path in _iter_doc_files(repo_root):
        rel_path = md_path.relative_to(repo_root)
        in_fence = False
        fence_char = ""
        fence_len = 0

        with md_path.open("r", encoding="utf-8") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                line = raw_line.rstrip("\r\n")
                for ch, label in BANNED_DASHES.items():
                    if ch in line:
                        errors.append(f"{rel_path}:{lineno}: banned {label} found")

                fence_match = FENCE_RE.match(line)
                if fence_match:
                    marker = fence_match.group(1)
                    if not in_fence:
                        in_fence = True
                        fence_char = marker[0]
                        fence_len = len(marker)
                    elif marker[0] == fence_char and len(marker) >= fence_len:
                        in_fence = False
                    continue

                if in_fence:
                    continue

                for target in _extract_targets(line):
                    if target.startswith("#"):
                        continue
                    scheme = urlsplit(target).scheme.lower()
                    if scheme in EXTERNAL_SCHEMES:
                        continue
                    if scheme:
                        errors.append(
                            f"{rel_path}:{lineno}: unsupported link scheme in {target!r}"
                        )
                        continue

                    path_part = unquote(target.split("#", 1)[0].split("?", 1)[0])
                    if not path_part:
                        continue

                    cache_key = (md_path.parent, path_part)
                    if cache_key not in link_cache:
                        resolved = (md_path.parent / path_part).resolve()
                        if not resolved.is_relative_to(repo_root):
                            link_cache[cache_key] = "outside"
                        elif not resolved.exists():
                            link_cache[cache_key] = "broken"
                        else:
                            link_cache[cache_key] = None

                    status = link_cache[cache_key]
                    if status == "outside":
                        errors.append(
                            f"{rel_path}:{lineno}: link {target!r} points outside repository root"
                        )
                    elif status == "broken":
                        errors.append(f"{rel_path}:{lineno}: broken relative link {target!r}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check markdown docs for banned dashes and broken links.")
    parser.add_argument("--repo", type=Path, default=Path("."), help="Repository root path")
    args = parser.parse_args(argv)

    errors = check_repo_docs(args.repo)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
