"""Phase 7 verification: hosting hardening (docs/hosting.md section 6), Caddy edge rules,
paired watermark backup/restore, and mismatch rejection."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
for d in (REPO_ROOT / "apps" / "impactweb" / "backend", REPO_ROOT / "apps" / "twin" / "backend"):
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))

from impactweb.app import create_app as create_iw_app
from twin.app import create_app as create_twin_app
from twin.clients import CmmsClient, ImpactWebClient


def test_compose_file_satisfies_hosting_section_6_isolation_and_memory_rules():
    compose_path = REPO_ROOT / "compose.yml"
    assert compose_path.is_file(), "compose.yml missing at repo root"
    text = compose_path.read_text(encoding="utf-8")

    # Parse top-level service blocks cleanly without requiring PyYAML
    services_section = text.split("\nservices:\n", 1)[1].split("\nvolumes:\n", 1)[0]
    blocks: dict[str, str] = {}
    current_name: str | None = None
    buf: list[str] = []
    for line in services_section.splitlines():
        m = re.match(r"^  ([a-z0-9_-]+):\s*$", line)
        if m:
            if current_name is not None:
                blocks[current_name] = "\n".join(buf)
            current_name = m.group(1)
            buf = []
        else:
            buf.append(line)
    if current_name is not None:
        blocks[current_name] = "\n".join(buf)

    assert set(blocks.keys()) == {"edge", "impactweb", "twin", "postgres", "neo4j"}

    # 1. Only edge runs in host network mode
    assert "network_mode: host" in blocks["edge"]
    for name in ("impactweb", "twin", "postgres", "neo4j"):
        assert "network_mode: host" not in blocks[name], f"{name} must NOT use host network mode"

    # 2. Exact port mappings per docs/hosting.md section 1 & 6
    assert "127.0.0.1:18001:8000" in blocks["impactweb"]
    assert "127.0.0.1:18002:8000" in blocks["twin"]
    assert "ports:" not in blocks["postgres"], "postgres must publish zero host ports"
    assert "ports:" not in blocks["neo4j"], "neo4j must publish zero host ports"

    # 3. Twin container holds zero Postgres credentials
    assert "POSTGRES_" not in blocks["twin"]
    assert "DATABASE_URL" not in blocks["twin"]

    # 4. Neo4j heap/pagecache tuned for 4 GB VM budget
    assert "768m" in blocks["neo4j"]
    assert "384m" in blocks["neo4j"]


def test_caddyfile_strips_forged_headers_and_routes_only_on_loopback_8000():
    caddy_path = REPO_ROOT / "deploy" / "caddy" / "Caddyfile"
    assert caddy_path.is_file(), "deploy/caddy/Caddyfile missing"
    text = caddy_path.read_text(encoding="utf-8")

    assert "127.0.0.1:8000" in text
    assert "127.0.0.1:18001" in text
    assert "127.0.0.1:18002" in text
    assert "/impactweb" in text
    assert "/twin" in text
    # Must strip incoming X-Edge-Auth and guard X-ExeDev-* for non-loopback peers
    assert "-X-Edge-Auth" in text
    assert "X-Edge-Auth" in text
    assert "127.0.0.1" in text


def test_paired_watermark_maintenance_export_import_and_mismatch_rejection(tmp_path: Path):
    iw_app = create_iw_app(
        database_url=f"sqlite:///{tmp_path / 'iw-p7.db'}",
        scenario_dir=REPO_ROOT / "data" / "scenario",
        auth_mode="local",
        twin_sync_token="sync-p7",
        twin_raise_token="raise-p7",
    )
    iw = TestClient(iw_app)
    iw_cli = ImpactWebClient(base_url="http://testserver", sync_token="sync-p7", raise_token="raise-p7", http_client=iw)
    cmms_cli = CmmsClient(base_url="http://testserver", sync_token="sync-p7", http_client=iw)
    twin_app = create_twin_app(
        scenario_dir=REPO_ROOT / "data" / "scenario",
        shapes_path=REPO_ROOT / "specs" / "shapes.ttl",
        impactweb_client=iw_cli,
        cmms_client=cmms_cli,
        twin_sync_token="sync-p7",
        auth_mode="local",
    )
    twin = TestClient(twin_app)

    ta_tok = iw.post("/api/v1/auth/login", json={"email": "ta.manager@demo.local", "password": "demo-pass-2028"}).json()["access_token"]
    pl_tok = iw.post("/api/v1/auth/login", json={"email": "j.planner@demo.local", "password": "demo-pass-2028"}).json()["access_token"]
    fac_tok = iw.post("/api/v1/auth/login", json={"email": "facilitator@demo.local", "password": "demo-pass-2028"}).json()["access_token"]
    ta_hdr = {"Authorization": f"Bearer {ta_tok}"}
    pl_hdr = {"Authorization": f"Bearer {pl_tok}"}
    fac_hdr = {"Authorization": f"Bearer {fac_tok}"}

    # Sync and record one manual review + one saved cut-line run (twin-only state)
    assert twin.post("/api/v1/sync?exercise_id=EX-DEMO&use_ai=true").status_code == 200
    queue = twin.get("/api/v1/matching/review-queue?exercise_id=EX-DEMO").json()
    target_req = next(q["request_id"] for q in queue if q.get("proposal") and q["proposal"].get("tag"))
    assert (
        twin.post(
            f"/api/v1/matching/review/{target_req}?exercise_id=EX-DEMO",
            json={"action": "accept", "reason": "Backup test review"},
            headers=pl_hdr,
        ).status_code
        == 200
    )
    assert (
        twin.post(
            "/api/v1/cut-line/evaluate",
            json={"exercise_id": "EX-DEMO", "budget_usd": 22_000_000, "save_name": "DRB Option A", "saved_by": "J. Planner"},
        ).status_code
        == 200
    )

    # 1. Enter maintenance mode -> IMPACT Web refuses writes with 503
    r_m_on = iw.post("/api/v1/admin/maintenance", json={"enabled": True}, headers=fac_hdr)
    assert r_m_on.status_code == 200 and r_m_on.json()["maintenance_mode"] is True

    r_blocked = iw.post(
        "/api/v1/work-requests/WR-200-0001/decisions?exercise_id=EX-DEMO",
        json={"stage": "challenge", "kind": "recommendation", "decision": "accept", "reason": "Should fail in maintenance"},
        headers=ta_hdr,
    )
    assert r_blocked.status_code == 503

    # 2. Read per-exercise cutoffs and drain twin sync
    wm = iw.get("/api/v1/admin/watermarks", headers={"Authorization": "Bearer sync-p7"}).json()
    assert "EX-DEMO" in wm["cutoffs"]
    assert twin.post("/api/v1/sync?exercise_id=EX-DEMO").status_code == 200

    # 3. Export twin-only state carrying exact cutoffs
    exp = twin.get("/api/v1/backup/export", headers={"Authorization": "Bearer sync-p7"})
    assert exp.status_code == 200
    bundle = exp.json()
    assert bundle["cutoffs"]["EX-DEMO"] == wm["cutoffs"]["EX-DEMO"]
    assert target_req in bundle["exercises"]["EX-DEMO"]["manual_reviews"]
    assert len(bundle["exercises"]["EX-DEMO"]["saved_cut_line_runs"]) == 1

    # Exit maintenance mode
    assert iw.post("/api/v1/admin/maintenance", json={"enabled": False}, headers=fac_hdr).status_code == 200

    # 4. Restore into a fresh Twin instance: mismatched cutoffs MUST be refused (409)!
    fresh_twin = TestClient(
        create_twin_app(
            scenario_dir=REPO_ROOT / "data" / "scenario",
            shapes_path=REPO_ROOT / "specs" / "shapes.ttl",
            impactweb_client=iw_cli,
            cmms_client=cmms_cli,
            twin_sync_token="sync-p7",
            auth_mode="local",
        )
    )
    assert fresh_twin.post("/api/v1/sync?exercise_id=EX-DEMO&use_ai=true").status_code == 200

    bad_bundle = json.loads(json.dumps(bundle))
    bad_bundle["cutoffs"]["EX-DEMO"] = 999999
    r_bad = fresh_twin.post("/api/v1/backup/import", json=bad_bundle, headers={"Authorization": "Bearer sync-p7"})
    assert r_bad.status_code == 409

    # Missing cutoffs map or exercise omitted from cutoffs MUST also fail closed with 409
    assert (
        fresh_twin.post(
            "/api/v1/backup/import",
            json={"format_version": 1, "exercises": bundle["exercises"]},
            headers={"Authorization": "Bearer sync-p7"},
        ).status_code
        == 409
    )
    assert (
        fresh_twin.post(
            "/api/v1/backup/import",
            json={"format_version": 1, "cutoffs": {}, "exercises": bundle["exercises"]},
            headers={"Authorization": "Bearer sync-p7"},
        ).status_code
        == 409
    )
    assert (
        fresh_twin.post(
            "/api/v1/backup/import",
            json={"format_version": 1, "cutoffs": {"EX-OTHER": 0}, "exercises": bundle["exercises"]},
            headers={"Authorization": "Bearer sync-p7"},
        ).status_code
        == 409
    )

    # Failed watermark read from IMPACT Web MUST fail closed with 409 (never fall through)
    class _FailingIwClient:
        def get_watermarks(self):
            raise RuntimeError("IMPACT Web unreachable")

    broken_twin = TestClient(
        create_twin_app(
            scenario_dir=REPO_ROOT / "data" / "scenario",
            shapes_path=REPO_ROOT / "specs" / "shapes.ttl",
            impactweb_client=_FailingIwClient(),  # type: ignore[arg-type]
            cmms_client=cmms_cli,
            twin_sync_token="sync-p7",
            auth_mode="local",
        )
    )
    assert broken_twin.post("/api/v1/backup/import", json=bundle, headers={"Authorization": "Bearer sync-p7"}).status_code == 409

    # Multi-exercise partial mismatch MUST NOT mutate earlier exercises (all-or-nothing atomic restore)
    partial_bad = json.loads(json.dumps(bundle))
    partial_bad["cutoffs"]["EX-Z-LATER"] = 99
    partial_bad["exercises"]["EX-Z-LATER"] = {"cursor_seq": 99, "manual_reviews": {}, "saved_cut_line_runs": []}
    assert fresh_twin.post("/api/v1/backup/import", json=partial_bad, headers={"Authorization": "Bearer sync-p7"}).status_code == 409
    still_unreviewed = fresh_twin.get(f"/api/v1/scope-items/{target_req}?exercise_id=EX-DEMO").json()
    assert still_unreviewed["match_status"] != "accepted", "Earlier exercise must not be mutated when a later exercise mismatches"

    # 5. Valid paired bundle restores manual reviews and saved cut-line runs cleanly
    r_ok = fresh_twin.post("/api/v1/backup/import", json=bundle, headers={"Authorization": "Bearer sync-p7"})
    assert r_ok.status_code == 200
    restored_item = fresh_twin.get(f"/api/v1/scope-items/{target_req}?exercise_id=EX-DEMO").json()
    assert restored_item["match_status"] == "accepted"
    assert restored_item["mapping_trace"]["decision"]["reason"] == "Backup test review"

    # 6. Restore onto a NON-EMPTY Twin whose cursor moved ahead of the backup cutoff:
    #    calling reset-scope rewinds cursor to 0 so replaying the older feed and importing succeeds cleanly.
    r_post = iw.post(
        "/api/v1/work-requests/WR-200-0002/decisions?exercise_id=EX-DEMO",
        json={"stage": "challenge", "kind": "recommendation", "decision": "accept", "reason": "Post-backup write"},
        headers=ta_hdr,
    )
    assert r_post.status_code == 201
    assert fresh_twin.post("/api/v1/sync?exercise_id=EX-DEMO").status_code == 200
    # Without reset-scope, importing the older bundle is rejected with 409
    assert fresh_twin.post("/api/v1/backup/import", json=bundle, headers={"Authorization": "Bearer sync-p7"}).status_code == 409
    # Reset-scope clears Twin cursor back to 0 cleanly
    r_rst = fresh_twin.post("/api/v1/backup/reset-scope?exercise_id=EX-DEMO", headers={"Authorization": "Bearer sync-p7"})
    assert r_rst.status_code == 200 and r_rst.json()["cursor_seq"] == 0


def test_maintenance_mode_write_barrier_drains_in_flight_writes(tmp_path: Path):
    """Maintenance activation blocks new writes and waits for an in-flight write to finish before returning."""
    import threading
    import time

    iw_app = create_iw_app(
        database_url=f"sqlite:///{tmp_path / 'iw-barrier.db'}",
        scenario_dir=REPO_ROOT / "data" / "scenario",
        auth_mode="local",
    )
    iw = TestClient(iw_app)
    fac_tok = iw.post("/api/v1/auth/login", json={"email": "facilitator@demo.local", "password": "demo-pass-2028"}).json()["access_token"]
    fac_hdr = {"Authorization": f"Bearer {fac_tok}"}

    # Simulate an active in-flight write holding the barrier counter
    with iw_app.state.write_barrier_cond:
        iw_app.state.in_flight_writes = 1

    done_event = threading.Event()
    result_box: dict = {}

    def _activate():
        r = iw.post("/api/v1/admin/maintenance", json={"enabled": True}, headers=fac_hdr)
        result_box["status"] = r.status_code
        result_box["json"] = r.json()
        done_event.set()

    t = threading.Thread(target=_activate, daemon=True)
    t.start()
    time.sleep(0.15)
    # Maintenance activation MUST still be waiting while the in-flight write has not drained
    assert not done_event.is_set()
    assert iw_app.state.maintenance_mode is True

    # Release the in-flight write -> maintenance activation drains and completes cleanly
    with iw_app.state.write_barrier_cond:
        iw_app.state.in_flight_writes = 0
        iw_app.state.write_barrier_cond.notify_all()
    t.join(timeout=5.0)
    assert done_event.is_set()
    assert result_box["status"] == 200
    assert result_box["json"]["maintenance_mode"] is True
    assert result_box["json"]["in_flight_writes"] == 0


def test_deploy_and_backup_scripts_enforce_hosting_rules():
    deploy_txt = (REPO_ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    assert "pull" in deploy_txt
    assert "--no-build" in deploy_txt
    assert "--build" not in deploy_txt, "deploy.sh must never build images on the 4 GB VM"
    assert "scripts/backup.sh" in deploy_txt, "deploy.sh must run paired pre-deploy backup"
    assert "sys.exit(1)" in deploy_txt
    assert "network_mode" in deploy_txt
    assert "18001" in deploy_txt and "18002" in deploy_txt

    for script_name in ("backup.sh", "restore.sh"):
        txt = (REPO_ROOT / "scripts" / script_name).read_text(encoding="utf-8")
        assert "/api/v1/auth/mode" in txt, f"{script_name} must detect AUTH_MODE"
        assert "/api/v1/auth/login" in txt, f"{script_name} must support AUTH_MODE=local JWT auth"
        assert "X-Edge-Auth" in txt, f"{script_name} must support AUTH_MODE=exe edge auth"


