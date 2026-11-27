"""Parsers for the output of the template's test steps, and the T1 scan. Stdlib only."""

import re

_PYTEST_LINE = re.compile(r"^=+ (.*\b(?:passed|failed|error|errors|skipped)\b.*) in [\d.]+s", re.M)


def pytest_summary(out):
    """Counts from the last pytest summary line. Raises if there isn't one."""
    lines = _PYTEST_LINE.findall(out)
    if not lines:
        raise ValueError("no pytest summary line")
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for n, word in re.findall(r"(\d+) (passed|failed|errors?|skipped)", lines[-1]):
        counts["errors" if word.startswith("error") else word] = int(n)
    return counts


def coverage_total(out):
    """The TOTAL percentage from `coverage report`. Raises if there isn't one."""
    m = re.findall(r"^TOTAL\s+.*?([\d.]+)%\s*$", out, re.M)
    if not m:
        raise ValueError("no coverage TOTAL line")
    return float(m[-1])


def playwright_summary(out):
    """Counts from Playwright's list or line reporter footer. Raises if it has no passed or
    failed line, which is what a launch error looks like."""
    counts = {"passed": 0, "failed": 0, "flaky": 0, "skipped": 0, "did_not_run": 0}
    found = False
    for n, word in re.findall(r"^\s+(\d+) (passed|failed|flaky|skipped|did not run)\b", out, re.M):
        counts[word.replace(" ", "_")] = int(n)
        found = found or word in ("passed", "failed")
    if not found:
        raise ValueError("no Playwright summary")
    return counts


def docker_commands(text):
    """Lines that would run docker: "docker" as the first item of an argument list, or a
    shell string starting with docker. Prose, and asking which("docker"), don't count."""
    hits = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        if (re.search(r"""\[\s*["']docker(?:-compose)?["']\s*,""", line)
                or re.search(r"""["']docker(?:-compose)?\s+\w""", line)):
            hits.append(line.strip())
    return hits
