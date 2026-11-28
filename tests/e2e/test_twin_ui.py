"""End-to-end Playwright interaction and visual audit tests for the Unit 200 Digital Twin UI."""

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
TWIN_FRONTEND_DIST = TWIN_BACKEND_DIR / "twin" / "frontend"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


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
        database_url=f"sqlite:///{tmp_path / 'impactweb-twin-e2e.db'}",
        scenario_dir=REPO_ROOT / "data" / "scenario",
        auth_mode="local",
        twin_sync_token="e2e-sync-tok",
        twin_raise_token="e2e-raise-tok",
    )
    twin_app = create_twin_app(
        scenario_dir=REPO_ROOT / "data" / "scenario",
        shapes_path=REPO_ROOT / "specs" / "shapes.ttl",
        impactweb_url=iw_url,
        twin_sync_token="e2e-sync-tok",
        twin_raise_token="e2e-raise-tok",
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

    # Initial sync with AI proposals enabled (using recorded fixtures, zero network calls)
    r = httpx.post(f"{twin_url}/api/v1/sync", params={"exercise_id": "EX-DEMO", "use_ai": "true"}, timeout=20.0)
    assert r.status_code == 200, f"Initial sync failed: {r.text}"

    return (iw_srv, twin_srv), (t_iw, t_tw), iw_url, twin_url


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


@pytest.mark.skipif(not (TWIN_FRONTEND_DIST / "index.html").exists(), reason="Built Twin frontend not present")
def test_twin_all_frontend_interactions(tmp_path: Path):
    from playwright.sync_api import sync_playwright

    screenshot_dir_env = os.environ.get("SCREENSHOT_DIR", "")
    screenshot_dir = Path(screenshot_dir_env) if screenshot_dir_env else tmp_path / "shots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    servers, threads, _iw_url, twin_url = _start_servers(tmp_path)
    console_errors: list[str] = []
    page_errors: list[str] = []

    try:
        with sync_playwright() as p:
            browser = _launch_chromium(p)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: page_errors.append(str(err)))

            # 1. Open directly into live Plot Plan workspace (no marketing hero!)
            page.goto(twin_url, wait_until="networkidle")
            page.get_by_role("heading", name="Unit 200 plot plan").wait_for(timeout=12_000)
            assert page.get_by_label("Explore Unit 200 in plain English").is_visible()
            assert page.locator("svg[aria-label='Unit 200 2D plot plan'] g[data-tag='E-201B']").is_visible()
            page.screenshot(path=str(screenshot_dir / "twin-desktop-open.png"))

            # Switch plot plan layers and click equipment E-201B
            page.get_by_role("radio", name="Clusters").click()
            page.get_by_role("radio", name="Cut line").click()
            page.get_by_role("radio", name="Match status").click()
            page.locator("svg[aria-label='Unit 200 2D plot plan'] g[data-tag='E-201B']").click()
            page.get_by_role("heading", name="E-201B").wait_for()
            page.screenshot(path=str(screenshot_dir / "twin-desktop-scrolled.png"))

            # 2. Native Natural-Language Explore bar (NOT a chatbot: drives live workspace!)
            explore_input = page.get_by_label("Explore Unit 200 in plain English")
            explore_input.fill("What shares isolation envelope ENV-200-02 with E-201B?")
            page.get_by_role("button", name="Explore", exact=True).click()
            page.locator(".explore-cypher").wait_for(timeout=10_000)
            assert page.get_by_text("ENV-200-02", exact=False).first.is_visible()
            assert page.locator(".explore-cypher").is_visible()
            page.screenshot(path=str(screenshot_dir / "twin-explore-active.png"))

            # Click follow-up pivot to open P&ID sheet 200-PID-002
            page.locator(".explore-followups button", has_text="200-PID-002").first.click()
            page.get_by_role("heading", name="P&ID sheet viewer").wait_for(timeout=10_000)
            page.locator(".pid-svg-host svg g#E_201B").wait_for(timeout=10_000)
            page.screenshot(path=str(screenshot_dir / "twin-pid-viewer.png"))

            # Switch to another P&ID sheet
            page.get_by_role("tab", name="200-PID-005").click()
            page.locator(".pid-svg-host svg g#C_201").wait_for(timeout=10_000)

            # 3. Graph panel (real Relate WASM worker + Cytoscape.js + Cypher text!)
            page.get_by_role("tab", name="Graph").click()
            page.get_by_role("heading", name="In-browser plant graph").wait_for(timeout=10_000)
            # Wait for Relate WASM worker to seed and render
            page.get_by_text("Relate WASM ready", exact=False).wait_for(timeout=20_000)
            assert page.locator(".cypher-code").is_visible()
            assert "MATCH" in (page.locator(".cypher-code").text_content() or "")
            assert page.locator(".cytoscape-canvas canvas").count() >= 1
            page.screenshot(path=str(screenshot_dir / "twin-graph-relate.png"))

            # Switch graph query mode to Work request chain
            page.get_by_label("Graph query mode").select_option("work_request_chain")
            page.get_by_text("RESOLVES_TO", exact=False).first.wait_for(timeout=10_000)

            # 4. Mapping trace + deep link + Side-by-side IMPACT Web vs Twin view
            page.goto(f"{twin_url}/twin/?request=WR-200-0147", wait_until="networkidle")
            page.get_by_role("heading", name="Mapping trace").wait_for(timeout=10_000)
            page.get_by_role("heading", name="WR-200-0147", exact=False).wait_for(timeout=10_000)
            page.get_by_role("checkbox", name="Side-by-side IMPACT Web vs Twin").check()
            assert page.get_by_text("IMPACT Web record", exact=False).is_visible()
            assert page.get_by_text("Twin equipment context", exact=False).is_visible()

            # 5. Match review queue: sign in as planner, accept a proposal, verify match rate rises
            page.get_by_role("tab", name="Review").click()
            page.get_by_role("heading", name="Match review queue").wait_for(timeout=10_000)
            before_rate = page.locator("[data-testid='match-rate-value']").text_content()
            page.get_by_role("button", name="Sign in as J. Planner").click()
            page.get_by_text("Signed in as J. Planner", exact=False).wait_for(timeout=10_000)
            page.get_by_role("button", name="Accept proposed tag").first.click()
            page.get_by_text("Accepted match for ", exact=False).wait_for(timeout=10_000)
            after_rate = page.locator("[data-testid='match-rate-value']").text_content()
            assert after_rate != before_rate, f"Expected match rate to change after accept: {before_rate} -> {after_rate}"

            # 6. Matching lab: step-through (Code vs AI colors) + 3-mode comparison table
            page.get_by_role("tab", name="Matching lab").click()
            page.get_by_role("heading", name="Matching lab").wait_for(timeout=10_000)
            page.get_by_text("Code then AI").first.wait_for(timeout=15_000)
            assert page.get_by_text("Code only").first.is_visible()
            assert page.get_by_text("AI on everything").first.is_visible()
            assert page.get_by_text("100.0%").first.is_visible()

            # 7. Clusters & cut line: test natural-language $20M cut line + slider + duplicate pairs
            page.get_by_label("Explore Unit 200 in plain English").fill("What drops below a $20M cut line?")
            page.get_by_role("button", name="Explore", exact=True).click()
            page.get_by_role("heading", name="Clusters and cut line").wait_for(timeout=10_000)
            page.get_by_text("Shared cost saved", exact=False).wait_for(timeout=10_000)
            # Test infeasible budget preset ($10M)
            page.get_by_role("button", name="$10M", exact=True).click()
            page.get_by_text("Shortfall", exact=False).wait_for(timeout=10_000)
            # Test feasible budget preset ($22M)
            page.get_by_role("button", name="$22M", exact=True).click()
            page.get_by_text("Feasible", exact=True).wait_for(timeout=10_000)
            page.screenshot(path=str(screenshot_dir / "twin-clusters-cutline.png"))

            # Switch to Duplicate pairs tab inside Clusters view
            page.get_by_role("tab", name="Duplicate pairs (9)").click()
            page.get_by_text("DUP-01", exact=False).wait_for(timeout=10_000)

            # 8. Mobile viewport check (390x844, zero horizontal overflow)
            mobile_ctx = browser.new_context(viewport={"width": 390, "height": 844})
            m_page = mobile_ctx.new_page()
            m_page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            m_page.on("pageerror", lambda err: page_errors.append(str(err)))
            m_page.goto(twin_url, wait_until="networkidle")
            m_page.get_by_role("heading", name="Unit 200 plot plan").wait_for(timeout=12_000)
            overflow = m_page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            assert overflow <= 1, f"Mobile horizontal overflow detected: {overflow}px"
            m_page.screenshot(path=str(screenshot_dir / "twin-mobile-390.png"))
            mobile_ctx.close()

            browser.close()

        assert not console_errors, f"Browser console errors: {console_errors}"
        assert not page_errors, f"Browser page errors: {page_errors}"
    finally:
        for srv in servers:
            srv.should_exit = True
        for t in threads:
            t.join(timeout=5)


@pytest.mark.skipif(not (TWIN_FRONTEND_DIST / "index.html").exists(), reason="Built Twin frontend not present")
def test_twin_phase6_baseline_kpis_and_writethrough_step7(tmp_path: Path):
    """End-to-end walkthrough steps 6-8: freeze, late-scope sim, C-201 N3 write-through, and switch-off fallback."""
    from playwright.sync_api import sync_playwright

    jobs_dir = str(REPO_ROOT / "jobs")
    if jobs_dir not in sys.path:
        sys.path.insert(0, jobs_dir)
    from simulate_late_scope import run_late_scope_simulation

    screenshot_dir_env = os.environ.get("SCREENSHOT_DIR", "")
    screenshot_dir = Path(screenshot_dir_env) if screenshot_dir_env else tmp_path / "shots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    servers, threads, iw_url, twin_url = _start_servers(tmp_path)
    console_errors: list[str] = []
    page_errors: list[str] = []

    try:
        # Freeze in IMPACT Web and run scripted late-scope simulation (step 6)
        with httpx.Client(base_url=iw_url, timeout=20.0) as iw_cli, httpx.Client(
            base_url=twin_url, timeout=20.0
        ) as twin_cli:
            ta_tok = iw_cli.post(
                "/api/v1/auth/login", json={"email": "ta.manager@demo.local", "password": "demo-pass-2028"}
            ).json()["access_token"]
            ta_hdr = {"Authorization": f"Bearer {ta_tok}"}
            wrs = iw_cli.get("/api/v1/work-requests?exercise_id=EX-DEMO", headers=ta_hdr).json()
            assert (
                iw_cli.post(
                    "/api/v1/work-requests/bulk-decisions",
                    json={
                        "exercise_id": "EX-DEMO",
                        "request_ids": [w["id"] for w in wrs],
                        "stage": "drb",
                        "decision": "accept",
                        "reason": "DRB freeze batch",
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
            sim = run_late_scope_simulation(
                impactweb_client=iw_cli,
                twin_client=twin_cli,
                scenario_dir=REPO_ROOT / "data" / "scenario",
                exercise_id="EX-DEMO",
            )
            assert sim["adds_approved"] == 18 and sim["deletes_approved"] == 6 and sim["rejected"] == 5

        with sync_playwright() as p:
            browser = _launch_chromium(p)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: page_errors.append(str(err)))

            page.goto(twin_url, wait_until="networkidle")
            page.get_by_role("tab", name="Baseline & KPIs").click()
            page.get_by_role("heading", name="Baseline, KPIs, and value").wait_for(timeout=10_000)
            growth_before = page.locator("[data-testid='growth-hours-value']").text_content()
            assert growth_before and "+4," in growth_before
            assert page.get_by_text("Unvalidated assumption", exact=False).first.is_visible()
            assert page.get_by_text("$1.13M").is_visible()
            assert page.get_by_text("4.1 Work packages").is_visible()
            assert page.get_by_text("4.2 Execution plan and logistics").is_visible()
            page.screenshot(path=str(screenshot_dir / "twin-baseline-kpis.png"))

            # Walkthrough step 7: Click C-201 on Plot Plan -> Raise change request -> submit N3 from Twin
            page.get_by_role("tab", name="Plot plan").click()
            page.locator("svg[aria-label='Unit 200 2D plot plan'] g[data-tag='C-201']").click()
            page.get_by_role("button", name="Raise change request").click()
            dlg = page.get_by_role("dialog", name="Raise change request for C-201")
            dlg.wait_for(timeout=10_000)
            dlg.get_by_text("ENV-200-06", exact=False).first.wait_for(timeout=10_000)
            dlg.get_by_role("button", name="Sign in as J. Planner").click()
            page.screenshot(path=str(screenshot_dir / "twin-raise-cr-modal.png"))
            dlg.get_by_role("button", name="Submit to IMPACT Web").click()
            dlg.get_by_text("raised_via = twin", exact=False).wait_for(timeout=10_000)
            dlg.get_by_role("button", name="Done").click()

            # Approve the twin-raised CR in IMPACT Web as TA manager, then Sync now in Twin UI
            with httpx.Client(base_url=iw_url, timeout=20.0) as iw_cli:
                ta_tok = iw_cli.post(
                    "/api/v1/auth/login", json={"email": "ta.manager@demo.local", "password": "demo-pass-2028"}
                ).json()["access_token"]
                ta_hdr = {"Authorization": f"Bearer {ta_tok}"}
                crs = iw_cli.get("/api/v1/change-requests?exercise_id=EX-DEMO", headers=ta_hdr).json()
                twin_crs = [c for c in crs if c["raised_via"] == "twin" and c["status"] == "pending"]
                assert len(twin_crs) == 1
                assert twin_crs[0]["raised_by_name"] == "J. Planner"
                assert (
                    iw_cli.post(
                        f"/api/v1/change-requests/{twin_crs[0]['id']}/decide?exercise_id=EX-DEMO",
                        json={"decision": "approved", "reason": "Shared column window approved"},
                        headers=ta_hdr,
                    ).status_code
                    == 200
                )

            page.get_by_role("tab", name="Baseline & KPIs").click()
            page.get_by_role("button", name="Sync now").click()
            page.locator("[data-testid='growth-hours-value']", has_text="+4,160 hrs").wait_for(timeout=10_000)
            assert page.get_by_text("Raised from twin", exact=False).first.is_visible()

            # Turn write-through OFF and verify read-only copyable fallback in Twin modal
            with httpx.Client(base_url=iw_url, timeout=20.0) as iw_cli:
                ta_tok = iw_cli.post(
                    "/api/v1/auth/login", json={"email": "ta.manager@demo.local", "password": "demo-pass-2028"}
                ).json()["access_token"]
                assert (
                    iw_cli.patch(
                        "/api/v1/exercises/EX-DEMO/write-through",
                        json={"twin_write_through": False},
                        headers={"Authorization": f"Bearer {ta_tok}"},
                    ).status_code
                    == 200
                )

            page.get_by_role("button", name="Raise change request (C-201 N3)").click()
            dlg_off = page.get_by_role("dialog", name="Raise change request for C-201")
            dlg_off.get_by_text("Write-through is off for this exercise", exact=False).wait_for(timeout=10_000)
            assert dlg_off.get_by_role("button", name="Copy prefilled text").is_visible()
            dlg_off.get_by_role("button", name="Close").click()

            browser.close()

        assert not console_errors, f"Browser console errors: {console_errors}"
        assert not page_errors, f"Browser page errors: {page_errors}"
    finally:
        for srv in servers:
            srv.should_exit = True
        for t in threads:
            t.join(timeout=5)

