#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BANNED_DASHES: dict[str, str] = {"\u2014": "em dash", "\u2013": "en dash"}
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def _iter_doc_files(repo: Path) -> list[Path]:
    files: list[Path] = []
    files.extend(sorted(repo.glob("*.md")))
    for folder in ("docs", ".github"):
        sub = repo / folder
        if sub.is_dir():
            files.extend(sorted(sub.rglob("*.md")))
    return files


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

                cleaned = INLINE_CODE_RE.sub("", line)
                for raw_target in LINK_RE.findall(cleaned):
                    target = raw_target.strip()
                    if not target:
                        continue
                    if target.startswith("<") and ">" in target:
                        target = target[1 : target.index(">")]
                    else:
                        target = target.split()[0]

                    if target.startswith(("http://", "https://", "mailto:", "#")):
                        continue

                    path_part = target.split("#", 1)[0]
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
