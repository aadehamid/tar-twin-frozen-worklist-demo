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

# Non-synthetic plant equipment / unit / piping tag shapes (real refinery tags outside synthetic Unit 200)
NON_SYNTHETIC_TAG_PATTERN = re.compile(
    r"\b(?:(?:CDU|FCC|FCCU|VDU|HCU|CCR|SRU|ALK|NHT|DCU|HDS)-\d{2,5}[A-Z]?|"
    r"(?:[A-Z]{1,3})-\d{4,6}[A-Z]?|"
    r"\d{3,4}-[A-Z]{1,3}-\d{4,6})\b"
)

# Synthetic Unit 200 / scenario allowlist shapes (PSV-2101, FV-2101, 200-P-0412, WR-200-0001, CR-200-..., etc.)
SYNTHETIC_TAG_ALLOWLIST = re.compile(
    r"^(?:PSV-2\d{3}|PSV-1102|(?:BV|XV|FV|PV|TV|LV|HV|CV|FT|PT|TT|LT|PI|TI|FI|LI|AIT|PDT)-2\d{3}[A-Z]?|"
    r"200-P-\d{4}|200-PID-\d{3}|TAR-200-2028|ENV-200-\d{2}|WR-200-\d{4}|CR-200-[A-Z0-9]+|EX-[A-Z0-9-]+)$"
)


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
            for match in NON_SYNTHETIC_TAG_PATTERN.finditer(raw):
                token = match.group(0)
                if not SYNTHETIC_TAG_ALLOWLIST.match(token):
                    raise ValueError(
                        f"Synthetic-data filter blocked non-synthetic plant tag pattern '{token}'. "
                        "Use only synthetic Unit 200 tags."
                    )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Synthetic-data filter failed closed: {exc}") from exc
