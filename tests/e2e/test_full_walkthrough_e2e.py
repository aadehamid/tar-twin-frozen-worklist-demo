"""Full 11-minute demo walkthrough E2E test against a live URL (Docker Compose at http://127.0.0.1:8000).

Run with:
    LIVE_BASE_URL=http://127.0.0.1:8000 uv run --no-project --with httpx --with playwright --with pytest \
      python -m pytest tests/e2e/test_full_walkthrough_e2e.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_BASE_URL = os.environ.get("LIVE_BASE_URL", "").rstrip("/")


def _launch_chromium(p):
    try:
        return p.chromium.launch(headless=True)
    except Exception:
        cache = Path.home() / "Library" / "Caches" / "ms-playwright"
        for pattern in (
            "chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell",
            "chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        ):
            matches = sorted(cache.glob(pattern))
            if matches:
                return p.chromium.launch(headless=True, executable_path=str(matches[-1]))
        raise


@pytest.mark.skipif(not LIVE_BASE_URL, reason="Set LIVE_BASE_URL (e.g. http://127.0.0.1:8000) to run full Compose walkthrough")
def test_full_11_minute_demo_walkthrough_against_compose(tmp_path: Path):
    """Walks all 8 steps of docs/scenario-spec.md section 7 through Caddy edge -> IMPACT Web + Twin + Neo4j + Postgres."""
    from playwright.sync_api import sync_playwright

    jobs_dir = str(REPO_ROOT / "jobs")
    if jobs_dir not in sys.path:
        sys.path.insert(0, jobs_dir)
    from simulate_late_scope import run_late_scope_simulation

    shot_dir = Path(os.environ.get("SCREENSHOT_DIR", str(tmp_path / "compose-shots")))
    shot_dir.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as p:
        browser = _launch_chromium(p)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))

        # Step 0: Landing page at /
        page.goto(f"{LIVE_BASE_URL}/", wait_until="networkidle")
        page.get_by_role("heading", name="Unit 200 Frozen Work List Demo").wait_for(timeout=10_000)
        page.screenshot(path=str(shot_dir / "compose-landing.png"))

        # Step 1: IMPACT Web at /impactweb/
        page.get_by_role("link", name="IMPACT Web", exact=False).click()
        page.get_by_text("Work requests (200)").wait_for(timeout=15_000)
        assert page.get_by_text("System of record for TAR-200-2028").is_visible()

        # Step 2: Digital Twin at /twin/ -> Sync, Match review, Trace, Matching lab
        page.goto(f"{LIVE_BASE_URL}/twin/", wait_until="networkidle")
        page.get_by_role("heading", name="Unit 200 plot plan").wait_for(timeout=15_000)

        # Step 3: Native Explore bar -> ENV-200-02 -> P&ID -> Relate WASM Graph
        page.get_by_label("Explore Unit 200 in plain English").fill("What shares isolation envelope ENV-200-02 with E-201B?")
        page.get_by_role("button", name="Explore", exact=True).click()
        page.locator(".explore-followups button", has_text="200-PID-002").first.click()
        page.locator(".pid-svg-host svg g#E_201B").wait_for(timeout=10_000)

        page.get_by_role("tab", name="Graph").click()
        page.get_by_text("Relate WASM ready", exact=False).wait_for(timeout=20_000)
        assert page.locator(".cytoscape-canvas canvas").count() >= 1

        # Step 4 & 5: Clusters, Duplicates, Cut Line
        page.get_by_role("tab", name="Clusters & cut line").click()
        page.get_by_role("tab", name="Duplicate pairs (9)").click()
        page.get_by_text("DUP-01", exact=False).wait_for(timeout=10_000)

        # Step 6: Freeze in IMPACT Web + scripted late-scope simulation + Sync
        with httpx.Client(base_url=f"{LIVE_BASE_URL}/impactweb", timeout=20.0) as iw_cli, httpx.Client(
            base_url=f"{LIVE_BASE_URL}/twin", timeout=20.0
        ) as twin_cli:
            ta_tok = iw_cli.post(
                "/api/v1/auth/login", json={"email": "ta.manager@demo.local", "password": "demo-pass-2028"}
            ).json()["access_token"]
            ta_hdr = {"Authorization": f"Bearer {ta_tok}"}
            ex = iw_cli.get("/api/v1/exercises/EX-DEMO", headers=ta_hdr).json()
            if not ex.get("frozen"):
                wrs = iw_cli.get("/api/v1/work-requests?exercise_id=EX-DEMO", headers=ta_hdr).json()
                assert (
                    iw_cli.post(
                        "/api/v1/work-requests/bulk-decisions",
                        json={
                            "exercise_id": "EX-DEMO",
                            "request_ids": [w["id"] for w in wrs],
                            "stage": "drb",
                            "decision": "accept",
                            "reason": "Compose E2E freeze batch",
                        },
                        headers=ta_hdr,
                    ).status_code
                    == 201
                )
                assert (
                    iw_cli.post(
                        "/api/v1/freezes",
                        json={"exercise_id": "EX-DEMO", "event_id": "TAR-200-2028"},
                        headers=ta_hdr,
                    ).status_code
                    == 201
                )
                assert twin_cli.post("/api/v1/sync?exercise_id=EX-DEMO&use_ai=true").status_code == 200

            run_late_scope_simulation(
                impactweb_client=iw_cli,
                twin_client=twin_cli,
                scenario_dir=REPO_ROOT / "data" / "scenario",
                exercise_id="EX-DEMO",
            )

        # Step 7 & 8: Baseline & KPIs, Value Panel, C-201 N3 Write-Through
        page.get_by_role("tab", name="Baseline & KPIs").click()
        page.get_by_role("button", name="Sync now").click()
        page.locator("[data-testid='growth-hours-value']", has_text="+4,").wait_for(timeout=15_000)
        page.get_by_text("Unvalidated assumption", exact=False).first.wait_for(timeout=10_000)
        assert page.get_by_text("$1.13M").is_visible()
        page.screenshot(path=str(shot_dir / "compose-twin-kpis.png"))

        browser.close()

    assert not console_errors, f"Console errors: {console_errors}"
    assert not page_errors, f"Page errors: {page_errors}"
