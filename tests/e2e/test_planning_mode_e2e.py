"""End-to-end Playwright test for Phase 8 Interactive Planning Mode (IMPACT Web + Digital Twin)."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
IW_BACKEND_DIR = REPO_ROOT / "apps" / "impactweb" / "backend"
TWIN_BACKEND_DIR = REPO_ROOT / "apps" / "twin" / "backend"
IW_FRONTEND_DIST = IW_BACKEND_DIR / "impactweb" / "frontend"
TWIN_FRONTEND_DIST = TWIN_BACKEND_DIR / "twin" / "frontend"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


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


def _start_servers(tmp_path: Path):
    import uvicorn

    for d in (str(IW_BACKEND_DIR), str(TWIN_BACKEND_DIR)):
        if d not in sys.path:
            sys.path.insert(0, d)
    from impactweb.app import create_app as create_iw_app
    from twin.app import create_app as create_twin_app

    iw_port = _free_port()
    twin_port = _free_port()
    iw_url = f"http://127.0.0.1:{iw_port}"
    twin_url = f"http://127.0.0.1:{twin_port}"

    iw_app = create_iw_app(
        database_url=f"sqlite:///{tmp_path / 'impactweb-p8-e2e.db'}",
        scenario_dir=REPO_ROOT / "data" / "scenario",
        auth_mode="local",
        twin_sync_token="e2e-p8-sync",
        twin_raise_token="e2e-p8-raise",
        frontend_dist_dir=IW_FRONTEND_DIST,
    )
    twin_app = create_twin_app(
        scenario_dir=REPO_ROOT / "data" / "scenario",
        shapes_path=REPO_ROOT / "specs" / "shapes.ttl",
        impactweb_url=iw_url,
        twin_sync_token="e2e-p8-sync",
        twin_raise_token="e2e-p8-raise",
        auth_mode="local",
        frontend_dist_dir=TWIN_FRONTEND_DIST,
    )

    iw_srv = uvicorn.Server(uvicorn.Config(iw_app, host="127.0.0.1", port=iw_port, log_level="warning"))
    twin_srv = uvicorn.Server(uvicorn.Config(twin_app, host="127.0.0.1", port=twin_port, log_level="warning"))
    t_iw = threading.Thread(target=iw_srv.run, daemon=True)
    t_tw = threading.Thread(target=twin_srv.run, daemon=True)
    t_iw.start()
    t_tw.start()

    deadline = time.time() + 15.0
    while (not iw_srv.started or not twin_srv.started) and time.time() < deadline:
        time.sleep(0.05)
    assert iw_srv.started and twin_srv.started, "Servers failed to start"
    assert httpx.post(f"{twin_url}/api/v1/sync", params={"exercise_id": "EX-DEMO", "use_ai": "true"}, timeout=20.0).status_code == 200
    return (iw_srv, twin_srv), (t_iw, t_tw), iw_url, twin_url


@pytest.mark.skipif(
    not (IW_FRONTEND_DIST / "index.html").exists() or not (TWIN_FRONTEND_DIST / "index.html").exists(),
    reason="Built IMPACT Web and Twin frontends required",
)
def test_planning_mode_end_to_end_facilitator_switch_debrief_and_reset(tmp_path: Path):
    """Full browser rehearsal: create planning exercise, membership, inject, clock, freeze, twin switch + Relate reload, debrief, reset."""
    from playwright.sync_api import sync_playwright

    shot_env = os.environ.get("SCREENSHOT_DIR", "")
    shot_dir = Path(shot_env) if shot_env else tmp_path / "shots"
    shot_dir.mkdir(parents=True, exist_ok=True)

    servers, threads, iw_url, twin_url = _start_servers(tmp_path)
    console_errors: list[str] = []
    page_errors: list[str] = []

    try:
        with sync_playwright() as p:
            browser = _launch_chromium(p)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: page_errors.append(str(err)))

            # 1. IMPACT Web: switch to Facilitator and open Facilitator console
            page.goto(iw_url, wait_until="networkidle")
            page.get_by_label("Active persona").select_option("facilitator@demo.local")
            page.get_by_role("button", name="Facilitator", exact=True).click()
            page.get_by_role("heading", name="Create exercise").wait_for(timeout=10_000)

            # Create a partial planning exercise
            page.get_by_label("Exercise name").fill("Unit 200 Live Rehearsal")
            page.get_by_label("Mode", exact=True).select_option("planning")
            page.get_by_label("Starting fixture", exact=True).select_option("partial")
            page.get_by_role("button", name="Create exercise").click()
            page.get_by_text("Created exercise EX-PLAN-", exact=False).wait_for(timeout=10_000)

            # Read newly created exercise ID from selector
            new_ex_id = page.get_by_label("Active exercise").input_value()
            assert new_ex_id.startswith("EX-PLAN-")

            # Add TA manager and planner memberships
            page.get_by_label("Email").fill("ta.manager@demo.local")
            page.get_by_label("Role").select_option("ta_manager")
            page.get_by_role("button", name="Add or update member").click()
            page.get_by_text("Saved membership for ta.manager@demo.local", exact=False).wait_for(timeout=10_000)

            page.get_by_label("Email").fill("j.planner@demo.local")
            page.get_by_label("Role").select_option("planner")
            page.get_by_role("button", name="Add or update member").click()
            page.get_by_text("Saved membership for j.planner@demo.local", exact=False).wait_for(timeout=10_000)

            # Apply library inject INJ-RETIRED-TAG in candidate_list (100 -> 101 work requests)
            retired_row = page.locator("tr", has_text="INJ-RETIRED-TAG")
            retired_row.get_by_role("button", name="Apply inject").click()
            page.get_by_text("Applied inject INJ-RETIRED-TAG", exact=False).wait_for(timeout=10_000)
            assert "Work requests (101)" in (page.locator(".nav-tabs").text_content() or "")
            page.screenshot(path=str(shot_dir / "phase8-iw-facilitator.png"))

            # Advance clock to DRB
            page.get_by_label("Target clock step").select_option("drb")
            page.get_by_role("button", name="Advance clock").click()
            page.get_by_text("Clock moved to DRB", exact=False).wait_for(timeout=10_000)

            # Switch to TA manager on the planning exercise, accept all at DRB, then facilitator moves to freeze, TA freezes
            page.get_by_label("Active persona").select_option("ta.manager@demo.local")
            page.get_by_label("Active exercise").select_option(new_ex_id)
            page.get_by_role("button", name="Dashboard").click()
            page.get_by_role("button", name="Accept all unreviewed at DRB").click()
            page.get_by_text("Recorded final DRB accept on", exact=False).wait_for(timeout=15_000)

            page.get_by_label("Active persona").select_option("facilitator@demo.local")
            page.get_by_label("Active exercise").select_option(new_ex_id)
            page.get_by_role("button", name="Facilitator", exact=True).click()
            page.get_by_label("Target clock step").select_option("freeze")
            page.get_by_role("button", name="Advance clock").click()
            page.get_by_text("Clock moved to Freeze", exact=False).wait_for(timeout=10_000)

            page.get_by_label("Active persona").select_option("ta.manager@demo.local")
            page.get_by_label("Active exercise").select_option(new_ex_id)
            page.get_by_role("button", name="Dashboard").click()
            page.get_by_role("button", name="Freeze work list", exact=False).click()
            page.get_by_text("Work list frozen as FRZ-", exact=False).wait_for(timeout=10_000)

            # Facilitator advances to t_minus_9 and injects INJ-UT-THINNING (pending mandatory CR)
            page.get_by_label("Active persona").select_option("facilitator@demo.local")
            page.get_by_label("Active exercise").select_option(new_ex_id)
            page.get_by_role("button", name="Facilitator", exact=True).click()
            page.get_by_label("Target clock step").select_option("t_minus_9")
            page.get_by_role("button", name="Advance clock").click()
            page.get_by_text("Clock moved to T-9", exact=False).wait_for(timeout=10_000)
            ut_row = page.locator("tr", has_text="INJ-UT-THINNING")
            ut_row.get_by_role("button", name="Apply inject").click()
            page.get_by_text("Applied inject INJ-UT-THINNING", exact=False).wait_for(timeout=10_000)

            # 2. Digital Twin: sign in as planner, switch exercise selector -> verify isolation, Relate WASM reload, and Debrief view
            page.goto(twin_url, wait_until="networkidle")
            page.get_by_role("heading", name="Unit 200 plot plan").wait_for(timeout=12_000)
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.get_by_role("dialog").get_by_role("button", name="Sign in", exact=True).click()
            page.get_by_role("button", name="J. Planner", exact=True).wait_for(timeout=10_000)
            page.get_by_label("Active exercise").select_option(new_ex_id)
            page.get_by_role("button", name="Sync now").click()
            page.locator(".sync-stamp").wait_for(timeout=15_000)

            # Switch to Graph tab and confirm Relate WASM seeds cleanly for the planning exercise
            page.get_by_role("tab", name="Graph").click()
            page.get_by_text("Relate WASM ready", exact=False).wait_for(timeout=20_000)

            # Open Debrief tab and verify exact sections + unvalidated value notice
            page.get_by_role("tab", name="Debrief").click()
            page.get_by_role("heading", name="Exercise debrief").wait_for(timeout=10_000)
            assert page.get_by_text("Match rate over time").is_visible()
            assert page.get_by_text("Shared costs bundled vs missed").is_visible()
            assert page.get_by_text("Facilitator talking points").is_visible()
            assert page.get_by_text("unvalidated assumptions", exact=False).first.is_visible()
            page.screenshot(path=str(shot_dir / "phase8-twin-debrief.png"))

            # Mobile 390x844 check on Debrief view (zero horizontal overflow)
            mobile_ctx = browser.new_context(viewport={"width": 390, "height": 844})
            m_page = mobile_ctx.new_page()
            m_page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            m_page.on("pageerror", lambda err: page_errors.append(str(err)))
            m_page.goto(f"{twin_url}/?exercise={new_ex_id}", wait_until="networkidle")
            m_page.get_by_role("tab", name="Debrief").click()
            m_page.get_by_role("heading", name="Exercise debrief").wait_for(timeout=10_000)
            overflow = m_page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            assert overflow <= 1, f"Mobile Debrief overflow: {overflow}px"
            m_page.screenshot(path=str(shot_dir / "phase8-twin-debrief-mobile.png"))
            mobile_ctx.close()

            # 3. Return to IMPACT Web Facilitator Console and Reset the planning exercise (epoch 1 -> 2, archived log visible)
            page.goto(iw_url, wait_until="networkidle")
            page.get_by_label("Active persona").select_option("facilitator@demo.local")
            page.get_by_label("Active exercise").select_option(new_ex_id)
            page.get_by_role("button", name="Facilitator", exact=True).click()
            page.get_by_text(f"Active exercise {new_ex_id}", exact=False).wait_for(timeout=10_000)
            page.get_by_role("button", name="Reset exercise (bump epoch)").click()
            page.get_by_text("to epoch 2", exact=False).wait_for(timeout=10_000)
            page.get_by_text("Archived event logs from prior epochs").wait_for(timeout=10_000)
            page.get_by_text("Epoch 1", exact=True).wait_for(timeout=10_000)

            browser.close()

        assert not console_errors, f"Console errors: {console_errors}"
        assert not page_errors, f"Page errors: {page_errors}"
    finally:
        for srv in servers:
            srv.should_exit = True
        for t in threads:
            t.join(timeout=5)
