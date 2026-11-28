"""Fail-closed synthetic-data filter (docs/interactive-planning.md section 4)."""

from __future__ import annotations

import re

BLOCKED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "real company name",
        re.compile(
            r"\b(exxon\s*mobil|chevron|royal\s+dutch\s+shell|shell\s+(?:oil|energy|chemical\w*|refin\w*|deer\s+park|pernis)|bp\b|valero|marathon\s+petroleum|phillips\s*66|citgo|lyondellbasell|motiva|aramco|totalenergies|conocophillips|slb|schlumberger|halliburton|fluor|bechtel|wood\s+group|kbr|mckinsey|bcg|bain|deloitte|accenture|pwc|ey\b|kpmg)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "real refinery site",
        re.compile(
            r"\b(baytown|beaumont|baton\s+rouge|port\s+arthur|galveston\s+bay|texas\s+city|el\s+segundo|richmond\s+refinery|deer\s+park|lake\s+charles|garyville|whiting\s+refinery|pern[ií]s)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "personal identifier",
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    ),
]


def assert_synthetic_text(*texts: str | None) -> None:
    """Raise ValueError if any supplied text violates synthetic-only rules. Fails closed on error."""
    try:
        for raw in texts:
            if not raw:
                continue
            for label, pat in BLOCKED_PATTERNS:
                if pat.search(raw):
                    raise ValueError(
                        f"Synthetic-data filter blocked input matching {label}. "
                        "Use only synthetic Unit 200 names and tags."
                    )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Synthetic-data filter failed closed: {exc}") from exc
