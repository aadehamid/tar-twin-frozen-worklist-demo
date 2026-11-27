"""Unit tests for the output parsers in checks.py, written before checks.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks  # noqa: E402


def test_pytest_summary_pass():
    out = "....\n==== 61 passed, 2 warnings in 3.21s ====\n"
    assert checks.pytest_summary(out) == {"passed": 61, "failed": 0, "errors": 0, "skipped": 0}


def test_pytest_summary_mixed():
    out = "=== 2 failed, 58 passed, 1 skipped, 1 error in 9.0s ===\n"
    assert checks.pytest_summary(out) == {"passed": 58, "failed": 2, "errors": 1, "skipped": 1}


def test_pytest_summary_missing_is_an_error():
    with pytest.raises(ValueError):
        checks.pytest_summary("collected 0 items\nINTERNALERROR")


def test_pytest_summary_takes_the_last_line():
    out = "=== 1 failed in 1s ===\nrerun\n=== 3 passed in 1s ===\n"
    assert checks.pytest_summary(out)["passed"] == 3


def test_coverage_total():
    out = "Name  Stmts  Miss  Cover\n-----\napp/x.py  10  1  90%\nTOTAL   1290    37    97%\n"
    assert checks.coverage_total(out) == 97.0


def test_coverage_total_decimal():
    assert checks.coverage_total("TOTAL  10  1  89.5%\n") == 89.5


def test_coverage_total_missing():
    with pytest.raises(ValueError):
        checks.coverage_total("no report")


def test_playwright_summary_pass():
    out = "Running 54 tests using 1 worker\n...\n  54 passed (1.2m)\n"
    assert checks.playwright_summary(out) == {
        "passed": 54, "failed": 0, "flaky": 0, "skipped": 0, "did_not_run": 0}


def test_playwright_summary_failures():
    out = "  2 failed\n    [chromium] x\n  1 flaky\n  3 skipped\n  48 passed (2.0m)\n"
    s = checks.playwright_summary(out)
    assert (s["passed"], s["failed"], s["flaky"], s["skipped"]) == (48, 2, 1, 3)


def test_playwright_summary_did_not_run():
    s = checks.playwright_summary("  1 failed\n  5 did not run\n  10 passed (30s)\n")
    assert s["did_not_run"] == 5 and s["failed"] == 1


def test_playwright_summary_missing():
    with pytest.raises(ValueError):
        checks.playwright_summary("Error: browserType.launch: Executable doesn't exist")


def test_no_docker_commands():
    assert checks.docker_commands('run(["uv", "sync"])\n# docs mention Docker Compose\n') == []
    assert checks.docker_commands('on_path = shutil.which("docker") is not None\n') == []
    hits = checks.docker_commands('run(["docker", "compose", "up"])\n'
                                  'subprocess.run("docker ps", shell=True)\n'
                                  'run([ "docker-compose", "up"])\n')
    assert len(hits) == 3


def test_no_docker_in_run_script():
    # T1 itself: the run script never calls docker.
    text = (Path(__file__).resolve().parent / "run_spike.py").read_text()
    assert checks.docker_commands(text) == []
