"""End-to-end Playwright interaction & visual layout tests for IMPACT Web UI."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "apps" / "impactweb" / "backend"
FRONTEND_DIST = BACKEND_DIR / "impactweb" / "frontend"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _start_server(tmp_path: Path):
    import uvicorn

    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    from impactweb.app import create_app

    port = _free_port()
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'impactweb-e2e.db'}",
        scenario_dir=REPO_ROOT / "data" / "scenario",
        auth_mode="local",
        frontend_dist_dir=FRONTEND_DIST,
    )
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 15.0
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "IMPACT Web server failed to start"
    return server, thread, f"http://127.0.0.1:{port}"


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


@pytest.mark.skipif(not (FRONTEND_DIST / "index.html").exists(), reason="Built IMPACT Web frontend not present")
def test_impactweb_all_frontend_interactions(tmp_path: Path):
    from playwright.sync_api import sync_playwright

    screenshot_dir_env = os.environ.get("SCREENSHOT_DIR", "")
    screenshot_dir = Path(screenshot_dir_env) if screenshot_dir_env else tmp_path / "shots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    server, thread, base_url = _start_server(tmp_path)
    console_errors: list[str] = []
    page_errors: list[str] = []

    try:
        with sync_playwright() as p:
            browser = _launch_chromium(p)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: page_errors.append(str(err)))

            # 1. Open directly into Dashboard
            page.goto(base_url, wait_until="networkidle")
            page.get_by_text("Work requests (200)").wait_for(timeout=10_000)
            assert page.get_by_text("System of record for TAR-200-2028").is_visible()
            assert page.get_by_text("Open for review").is_visible()
            page.screenshot(path=str(screenshot_dir / "impactweb-desktop-open.png"))

            # Scroll and capture scrolled view
            page.evaluate("window.scrollTo(0, 420)")
            page.wait_for_timeout(150)
            page.screenshot(path=str(screenshot_dir / "impactweb-desktop-scrolled.png"))
            page.evaluate("window.scrollTo(0, 0)")

            # 2. Click Area 200-C on Dashboard -> jumps to filtered Work requests
            page.locator("table.data-table tbody tr").filter(has_text="200-C").first.click()
            page.get_by_role("heading", name="Work requests").wait_for()
            assert page.get_by_label("Filter by area").input_value() == "200-C"
            page.get_by_role("button", name="Clear filters").click()
            assert page.get_by_text("Showing 200 of 200").is_visible()

            # 3. Search WR-200-0147, open drawer, inspect "View in twin", edit free-text equipment + craft hours
            page.get_by_label("Search work requests").fill("WR-200-0147")
            page.locator("table.data-table tbody tr").filter(has_text="WR-200-0147").first.click()
            drawer = page.get_by_role("dialog", name="Work request WR-200-0147")
            drawer.wait_for()
            twin_href = drawer.get_by_role("link", name="View in twin").get_attribute("href")
            assert twin_href == "/twin/?request=WR-200-0147"
            page.screenshot(path=str(screenshot_dir / "impactweb-drawer.png"))

            drawer.get_by_label("Equipment text (free text, no catalog lookup)").fill(
                "feed effluent exchanger middle shell revised"
            )
            drawer.get_by_role("button", name="Save changes").click()
            page.get_by_text("Saved WR-200-0147 (now v2).").wait_for()
            drawer.get_by_role("button", name="Close").click()

            # 4. New work request -> test synthetic-data filter block, then create valid synthetic request
            page.get_by_role("button", name="New work request").click()
            new_dlg = page.get_by_role("dialog", name="New work request")
            new_dlg.wait_for()
            new_dlg.get_by_label("Title").fill("ExxonMobil Baytown valve tie-in")
            new_dlg.get_by_label("Equipment text (free text)").fill("HV-2001")
            new_dlg.get_by_label("Scope description").fill("Blocked real company test")
            new_dlg.get_by_role("button", name="Create work request").click()
            page.get_by_text("Synthetic-data filter blocked").wait_for()

            new_dlg.get_by_label("Title").fill("Inspect E-201B channel head stud bolts")
            new_dlg.get_by_label("Equipment text (free text)").fill("E-201B channel head")
            new_dlg.get_by_label("Scope description").fill("Ultrasonic check on channel stud bolts during turnaround")
            new_dlg.get_by_role("button", name="Create work request").click()
            page.get_by_text("Created work request WR-200-0201.").wait_for()
            page.get_by_role("dialog", name="Work request WR-200-0201").get_by_role("button", name="Close").click()
            page.get_by_label("Search work requests").fill("")

            # 5. Switch persona to DRB Member -> recommend accept on WR-200-0147
            page.get_by_label("Active persona").select_option("drb.member@demo.local")
            page.get_by_text("Signed in as drb.member@demo.local.").wait_for()
            page.get_by_role("button", name="Review queue").click()
            page.get_by_label("Search review queue").fill("WR-200-0147")
            row_147 = page.locator("table.data-table tbody tr").filter(has_text="WR-200-0147").first
            row_147.get_by_role("button", name="Recommend accept").click()
            page.get_by_text("Recommendation: Accept (v2)").wait_for()

            # 6. Switch back to TA Manager -> final accept -> edit -> verify Needs re-review
            page.get_by_label("Active persona").select_option("ta.manager@demo.local")
            page.get_by_text("Signed in as ta.manager@demo.local.").wait_for()
            row_147.get_by_role("button", name="Final accept").click()
            page.get_by_text("Final: Accept (v2)").wait_for()

            page.get_by_role("button", name="Work requests (201)").click()
            page.get_by_label("Search work requests").fill("WR-200-0147")
            page.locator("table.data-table tbody tr").filter(has_text="WR-200-0147").first.click()
            d2 = page.get_by_role("dialog", name="Work request WR-200-0147")
            d2.get_by_label("Title").fill("Pull E-201B middle bundle and hydrotest revised")
            d2.get_by_role("button", name="Save changes").click()
            page.get_by_text("Saved WR-200-0147 (now v3).").wait_for()
            assert d2.get_by_text("Prior review decision is stale").is_visible()
            d2.get_by_role("button", name="Close").click()

            # 7. Dashboard -> bulk DRB accept & Freeze work list
            page.get_by_role("button", name="Dashboard").click()
            page.get_by_role("button", name="Accept all unreviewed at DRB").click()
            page.get_by_text("Recorded final DRB accept").wait_for()
            page.get_by_role("button", name="Freeze work list").click()
            page.get_by_text("Work list frozen as FRZ-EX-DEMO-V1").wait_for()

            # 8. Change requests -> raise post-freeze CR -> approve it
            page.get_by_role("button", name="Change requests (0)").click()
            page.get_by_role("button", name="Raise change request").click()
            page.get_by_label("Target work request").select_option("WR-200-0152")
            page.get_by_label("Title").fill("Add nozzle N3 inspection on C-201")
            page.get_by_label("Equipment text (free text)").fill("C-201 nozzle N3")
            page.get_by_label("Justification").fill("Shares entry, scaffold, and isolation envelope ENV-200-06")
            page.get_by_role("button", name="Submit change request").click()
            page.get_by_text("Raised pending change request CR-200-").wait_for()
            assert page.locator("table.data-table tbody tr").filter(has_text="IMPACT Web").first.is_visible()

            page.locator("table.data-table tbody tr").first.get_by_role("button", name="Approve").click()
            page.get_by_text("marked approved.").wait_for()
            page.screenshot(path=str(screenshot_dir / "impactweb-changes.png"))

            # 9. Toggle twin write-through off and back on
            page.get_by_role("button", name="Turn off").click()
            page.get_by_text("Twin write-through switch is now off.").wait_for()
            page.get_by_role("button", name="Turn on").click()
            page.get_by_text("Twin write-through switch is now on.").wait_for()

            # 10. Mobile viewport check (390x844) -> zero horizontal overflow
            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("button", name="Dashboard").click()
            page.wait_for_timeout(150)
            overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            assert overflow <= 1, f"Mobile horizontal overflow detected: {overflow}px"
            page.screenshot(path=str(screenshot_dir / "impactweb-mobile.png"))

            # 11. Prefixed /impactweb/ mount loads and communicates with /impactweb/api/v1/...
            page.set_viewport_size({"width": 1440, "height": 900})
            page.goto(f"{base_url}/impactweb/", wait_until="networkidle")
            page.get_by_text("Work requests (201)").wait_for(timeout=10_000)

            browser.close()

        unexpected_console = [e for e in console_errors if "422 (Unprocessable Entity)" not in e]
        assert unexpected_console == [], f"Unexpected browser console errors: {unexpected_console}"
        assert page_errors == [], f"Uncaught page errors: {page_errors}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
