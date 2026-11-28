"""Unit 200 Digital Twin FastAPI service (plant graph, sync, matching, clusters, cut line)."""

from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from twin.auth import resolve_authenticated_member
from twin.clients import CmmsClient, ImpactWebClient
from twin.explorer import STARTER_PROMPTS, run_explore_query
from twin.graph_store import MemoryPlantStore
from twin.matcher import AiClientConfig
from twin.plant_loader import build_plant_graph
from twin.sync import SyncEngine


class ExploreQueryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str = "EX-DEMO"
    query: str = Field(min_length=2, max_length=500)
    allow_external_ai: bool = False


class LocalLoginPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class ReviewDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "reject", "pick_another"]
    tag: str | None = None
    reason: str = Field(default="", max_length=1000)


class CutLineEvaluatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str = "EX-DEMO"
    budget_usd: int = Field(ge=0)
    save_name: str | None = None
    saved_by: str = ""


class RaiseFromTwinPayload(BaseModel):
    """Browser payload for delegated write-through (docs/design.md section 5.8).

    Extra fields such as on_behalf_of, raised_by, or raised_via are forbidden (422);
    caller identity comes strictly from the verified session.
    """

    model_config = ConfigDict(extra="forbid")

    exercise_id: str = "EX-DEMO"
    request_id: str | None = None
    change_type: Literal["add", "delete", "change"] = "add"
    mandatory: bool = False
    schedule_impact_days: float = 0.0
    risk_if_not_done: str = Field(default="", max_length=2000)
    hours_delta: int
    cost_delta_usd: int
    title: str = Field(min_length=3, max_length=240)
    equipment_text: str | None = None
    category: str | None = None
    driver: Literal["inspection", "reliability", "regulatory", "capital", "operations"] | None = "operations"
    source_group: Literal["fixed_equipment", "rotating", "inspection", "operations", "projects", "instrumentation"] | None = "operations"
    area: str | None = None
    evidence: str = Field(default="", max_length=2000)
    reason: str = Field(min_length=3, max_length=4000)


def create_app(
    *,
    scenario_dir: Path | None = None,
    shapes_path: Path | None = None,
    neo4j_uri: str | None = None,
    neo4j_user: str | None = None,
    neo4j_password: str | None = None,
    impactweb_url: str | None = None,
    twin_sync_token: str | None = None,
    twin_raise_token: str | None = None,
    auth_mode: str | None = None,
    jwt_secret: str | None = None,
    edge_auth_secret: str | None = None,
    impactweb_client: ImpactWebClient | None = None,
    cmms_client: CmmsClient | None = None,
    frontend_dist_dir: Path | None = None,
) -> FastAPI:
    repo_root = Path(__file__).resolve().parents[4]
    scen_dir = scenario_dir or Path(os.environ.get("SCENARIO_DIR", str(repo_root / "data" / "scenario")))
    sh_path = shapes_path or Path(os.environ.get("SHAPES_PATH", str(repo_root / "specs" / "shapes.ttl")))
    n_uri = neo4j_uri or os.environ.get("NEO4J_URI", "")
    n_user = neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
    n_pass = neo4j_password or os.environ.get("NEO4J_PASSWORD", "")
    iw_url = impactweb_url or os.environ.get("IMPACTWEB_URL", "")
    sync_tok = twin_sync_token or os.environ.get("TWIN_SYNC_TOKEN", "demo-twin-sync-token")
    raise_tok = twin_raise_token or os.environ.get("TWIN_RAISE_TOKEN", "")
    mode = auth_mode or os.environ.get("AUTH_MODE", "local")
    j_secret = jwt_secret if jwt_secret is not None else os.environ.get("JWT_SECRET", "")
    e_secret = edge_auth_secret or os.environ.get("EDGE_AUTH_SECRET", "")
    dist_dir = frontend_dist_dir or (Path(__file__).resolve().parent / "frontend")

    if n_uri:
        from twin.neo4j_store import Neo4jPlantStore

        store = Neo4jPlantStore(uri=n_uri, user=n_user, password=n_pass, shapes_path=sh_path)
        store.ensure_constraints()
        if not store.guard_ready():
            store.install_shacl_guard()
        if store.summary()["equipment_count"] == 0 and (scen_dir / "dexpi").is_dir():
            store.load_plant_graph(build_plant_graph(scen_dir))
    else:
        store = MemoryPlantStore(shapes_path=sh_path)
        if (scen_dir / "dexpi").is_dir():
            store.load_plant_graph(build_plant_graph(scen_dir))

    iw_cli = impactweb_client
    cmms_cli = cmms_client
    if iw_cli is None and iw_url:
        iw_cli = ImpactWebClient(base_url=iw_url, sync_token=sync_tok, raise_token=raise_tok)
    if cmms_cli is None and iw_url:
        cmms_cli = CmmsClient(base_url=iw_url, sync_token=sync_tok)

    sync_engine = SyncEngine(
        plant_store=store,
        scenario_dir=scen_dir,
        impactweb_client=iw_cli,
        cmms_client=cmms_cli,
        ai_config=AiClientConfig.from_env(),
    )

    app = FastAPI(title="Unit 200 Turnaround Digital Twin API", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = store
    app.state.sync_engine = sync_engine
    app.state.scenario_dir = scen_dir

    api = APIRouter()

    @api.get("/api/v1/utils/health-check/")
    def health_check() -> bool:
        return True

    @api.get("/api/v1/auth/mode")
    def auth_mode_info() -> dict:
        return {
            "auth_mode": mode,
            "impactweb_connected": iw_cli is not None,
        }

    @api.get("/api/v1/auth/me")
    def auth_me(request: Request, exercise_id: str = Query(default="EX-DEMO")) -> dict:
        member = resolve_authenticated_member(
            request,
            exercise_id=exercise_id,
            auth_mode=mode,
            jwt_secret=j_secret,
            edge_auth_secret=e_secret,
            impactweb_client=iw_cli,
        )
        return {
            "user_id": member.user_id,
            "email": member.email,
            "full_name": member.full_name,
            "role": member.role,
            "exercise_id": member.exercise_id,
        }

    @api.post("/api/v1/auth/login")
    def auth_login(body: LocalLoginPayload) -> dict:
        if mode != "local":
            raise HTTPException(status_code=403, detail="Password login is disabled in exe auth mode")
        if iw_cli is None:
            raise HTTPException(status_code=503, detail="IMPACT Web identity authority is not connected")
        result = iw_cli.login_user(body.email, body.password)
        if result is None:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        return result

    # --- Plant Graph Endpoints (Phase 3) ---

    @api.get("/api/v1/plant/active-tags")
    def list_active_tags() -> list[dict]:
        pipeline = sync_engine._ensure_pipeline()
        out = []
        for tag in sorted(pipeline.active_u200_tags):
            row = pipeline.cmms_by_tag.get(tag, {})
            out.append(
                {
                    "tag": tag,
                    "description": row.get("description", ""),
                    "equipment_class": row.get("equipment_class", ""),
                    "area": row.get("area", ""),
                    "sheet": row.get("sheet", ""),
                }
            )
        return out

    @api.get("/api/v1/plant/summary")
    def plant_summary() -> dict:
        return store.summary()

    @api.get("/api/v1/plant/equipment")
    def list_equipment() -> list[dict]:
        return store.list_equipment()

    @api.get("/api/v1/plant/equipment/{tag}")
    def get_equipment(tag: str) -> dict:
        eq = store.get_equipment(tag)
        if eq is None:
            raise HTTPException(status_code=404, detail=f"Equipment {tag} not found")
        return eq

    @api.get("/api/v1/plant/plot-plan")
    def get_plot_plan() -> dict:
        return store.plot_plan()

    @api.get("/api/v1/plant/sheets")
    def list_sheets() -> list[dict]:
        return store.list_sheets()

    @api.get("/api/v1/plant/sheets/{sheet_no}.svg")
    def get_sheet_svg(sheet_no: str):
        safe = Path(sheet_no).name
        svg_path = scen_dir / "dexpi" / f"{safe}.svg"
        if not svg_path.is_file():
            raise HTTPException(status_code=404, detail=f"P&ID sheet {safe} SVG not found")
        return FileResponse(svg_path, media_type="image/svg+xml")

    @api.get("/api/v1/plant/envelopes")
    def list_envelopes() -> list[dict]:
        return store.list_envelopes()

    @api.get("/api/v1/plant/envelopes/{env_id}")
    def get_envelope(env_id: str) -> dict:
        env = store.get_envelope(env_id)
        if env is None:
            raise HTTPException(status_code=404, detail=f"Isolation envelope {env_id} not found")
        return env

    @api.get("/api/v1/plant/snapshot")
    def get_snapshot() -> dict:
        return store.export_snapshot()

    @api.get("/api/v1/graph/export.cypher", response_class=PlainTextResponse)
    def export_cypher(
        exercise_id: str = Query(default="EX-DEMO"),
        event_id: str | None = Query(default=None),
    ) -> str:
        if event_id is not None and event_id != "TAR-200-2028":
            raise HTTPException(status_code=404, detail=f"Unknown event_id {event_id}")
        if not store.has_exercise(exercise_id):
            raise HTTPException(status_code=404, detail=f"Unknown exercise_id {exercise_id}")
        return store.export_cypher(exercise_id=exercise_id)

    # --- Sync, Matching, Clusters, and Cut Line Endpoints (Phase 4 & Phase 8) ---

    @api.get("/api/v1/exercises")
    def list_exercises() -> list[dict]:
        if iw_cli is not None:
            try:
                return iw_cli.list_exercises()
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Failed to list exercises from IMPACT Web: {exc}") from exc
        return [
            {
                "id": "EX-DEMO",
                "name": "TAR-200-2028 Scripted Demo",
                "mode": "demo",
                "starting_fixture": "seeded",
                "clock_step": "candidate_list",
                "twin_write_through": True,
                "allow_external_ai": True,
                "epoch": 1,
                "frozen": False,
                "freeze_id": None,
            }
        ]

    @api.post("/api/v1/sync")
    def trigger_sync(
        request: Request,
        exercise_id: str = Query(default="EX-DEMO"),
        use_ai: bool = Query(default=False),
        live_ai: bool = Query(default=False),
        expected_epoch: int | None = Query(default=None),
    ) -> dict:
        if iw_cli is not None:
            try:
                live_ex = iw_cli.get_exercise(exercise_id)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Failed to verify exercise metadata before sync: {exc}") from exc
            if live_ex.get("mode") == "planning":
                hdr = request.headers.get("Authorization", "")
                is_sync_token = (
                    hdr.startswith("Bearer ")
                    and bool(sync_tok)
                    and hmac.compare_digest(hdr[len("Bearer ") :].strip(), sync_tok)
                )
                if not is_sync_token:
                    member = resolve_authenticated_member(
                        request,
                        exercise_id=exercise_id,
                        auth_mode=mode,
                        jwt_secret=j_secret,
                        edge_auth_secret=e_secret,
                        impactweb_client=iw_cli,
                    )
                    if member.role not in {"facilitator", "ta_manager", "planner"}:
                        raise HTTPException(
                            status_code=403,
                            detail="Only facilitator, TA manager, or planner roles may run sync now in planning mode",
                        )
        try:
            return sync_engine.sync_exercise(
                exercise_id=exercise_id,
                use_ai=use_ai,
                live_ai=live_ai,
                expected_epoch=expected_epoch,
            )
        except RuntimeError as exc:
            if "stale sync epoch" in str(exc).lower():
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=502, detail=f"Sync failed: {exc}") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Sync failed: {exc}") from exc

    @api.get("/api/v1/scope-items")
    def list_scope_items(exercise_id: str = Query(default="EX-DEMO")) -> list[dict]:
        return sync_engine.list_scope_items(exercise_id)

    @api.get("/api/v1/scope-items/{request_id}")
    def get_scope_item(request_id: str, exercise_id: str = Query(default="EX-DEMO")) -> dict:
        it = sync_engine.get_scope_item(exercise_id, request_id)
        if it is None:
            raise HTTPException(status_code=404, detail=f"Scope item {request_id} not found")
        return it

    @api.get("/api/v1/matching/summary")
    def matching_summary(exercise_id: str = Query(default="EX-DEMO")) -> dict:
        return sync_engine.matching_summary(exercise_id)

    @api.get("/api/v1/matching/review-queue")
    def matching_review_queue(exercise_id: str = Query(default="EX-DEMO")) -> list[dict]:
        return sync_engine.review_queue(exercise_id)

    @api.post("/api/v1/matching/review/{request_id}")
    def matching_review_decide(
        request_id: str,
        body: ReviewDecisionPayload,
        request: Request,
        exercise_id: str = Query(default="EX-DEMO"),
    ) -> dict:
        member = resolve_authenticated_member(
            request,
            exercise_id=exercise_id,
            auth_mode=mode,
            jwt_secret=j_secret,
            edge_auth_secret=e_secret,
            impactweb_client=iw_cli,
        )
        if member.role not in {"planner", "ta_manager"}:
            raise HTTPException(
                status_code=403,
                detail="Only planner or TA manager roles may accept or reject equipment matches",
            )
        epoch_hdr = request.headers.get("X-Exercise-Epoch")
        expected_epoch: int | None = None
        if epoch_hdr is not None and epoch_hdr.strip():
            try:
                expected_epoch = int(epoch_hdr.strip())
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="X-Exercise-Epoch must be an integer") from exc
        try:
            return sync_engine.decide_review(
                exercise_id=exercise_id,
                request_id=request_id,
                action=body.action,
                reviewer=member.full_name,
                reason=body.reason,
                tag=body.tag,
                expected_epoch=expected_epoch,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @api.get("/api/v1/matching/lab/step/{request_id}")
    def matching_lab_step(request_id: str, exercise_id: str = Query(default="EX-DEMO")) -> dict:
        try:
            return sync_engine.matching_lab_step(exercise_id, request_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @api.get("/api/v1/matching/lab/compare")
    def matching_lab_compare(
        exercise_id: str = Query(default="EX-DEMO"),
        live_ai: bool = Query(default=False),
    ) -> dict:
        return sync_engine.matching_lab_compare(exercise_id, live_ai=live_ai)

    @api.get("/api/v1/clusters")
    def get_clusters(exercise_id: str = Query(default="EX-DEMO")) -> dict:
        return sync_engine.clusters_and_duplicates(exercise_id)

    @api.get("/api/v1/cut-line/runs")
    def list_cut_line_runs(exercise_id: str = Query(default="EX-DEMO")) -> list[dict]:
        return sync_engine.list_cut_line_runs(exercise_id)

    @api.post("/api/v1/cut-line/evaluate")
    def post_cut_line(body: CutLineEvaluatePayload, request: Request) -> dict:
        saved_by = body.saved_by
        if body.save_name and iw_cli is not None:
            try:
                ex_meta = iw_cli.get_exercise(body.exercise_id)
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to verify exercise phase from IMPACT Web before saving cut-line option: {exc}",
                ) from exc
            if ex_meta.get("mode") == "planning":
                member = resolve_authenticated_member(
                    request,
                    exercise_id=body.exercise_id,
                    auth_mode=mode,
                    jwt_secret=j_secret,
                    edge_auth_secret=e_secret,
                    impactweb_client=iw_cli,
                )
                if member.role not in {"planner", "ta_manager"}:
                    raise HTTPException(
                        status_code=403,
                        detail="Only planner or TA manager may save cut-line options",
                    )
                if ex_meta.get("clock_step") not in {"candidate_list", "fit_to_frame", "challenge", "drb"}:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Saving cut-line options is closed in phase '{ex_meta.get('clock_step')}'",
                    )
                saved_by = member.full_name
        return sync_engine.evaluate_cut_line(
            exercise_id=body.exercise_id,
            budget_usd=body.budget_usd,
            save_name=body.save_name,
            saved_by=saved_by,
        )

    @api.get("/api/v1/debrief")
    def get_debrief(exercise_id: str = Query(default="EX-DEMO")) -> dict:
        return sync_engine.debrief_report(exercise_id)

    @api.get("/api/v1/explore/suggestions")
    def explore_suggestions() -> list[dict]:
        return STARTER_PROMPTS

    @api.post("/api/v1/explore/query")
    def post_explore_query(body: ExploreQueryPayload) -> dict:
        try:
            return run_explore_query(
                query=body.query,
                exercise_id=body.exercise_id,
                plant_store=store,
                sync_engine=sync_engine,
                allow_external_ai=body.allow_external_ai,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # --- Baseline, KPIs, Value Panel, and Delegated Write-Through (Phase 6) ---

    @api.get("/api/v1/baseline")
    def get_baseline(exercise_id: str = Query(default="EX-DEMO")) -> dict:
        return sync_engine.baseline_summary(exercise_id)

    @api.get("/api/v1/kpis")
    def get_kpis(exercise_id: str = Query(default="EX-DEMO")) -> dict:
        return sync_engine.kpis_summary(exercise_id)

    @api.get("/api/v1/value")
    def get_value_panel(exercise_id: str = Query(default="EX-DEMO")) -> dict:
        return sync_engine.value_panel(exercise_id)

    @api.get("/api/v1/change-requests/prefill")
    def get_change_request_prefill(
        tag: str = Query(min_length=2),
        exercise_id: str = Query(default="EX-DEMO"),
    ) -> dict:
        try:
            return sync_engine.change_request_prefill(exercise_id, tag)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @api.post("/api/v1/change-requests/raise-from-twin", status_code=201)
    def post_raise_from_twin(body: RaiseFromTwinPayload, request: Request) -> dict:
        """Delegated write-through proxy (docs/design.md section 5.8, D9).

        Resolves caller strictly from verified session and forwards to IMPACT Web
        POST /api/v1/twin/change-requests under TWIN_RAISE_TOKEN.
        """
        member = resolve_authenticated_member(
            request,
            exercise_id=body.exercise_id,
            auth_mode=mode,
            jwt_secret=j_secret,
            edge_auth_secret=e_secret,
            impactweb_client=iw_cli,
        )
        if member.role != "planner":
            raise HTTPException(
                status_code=403,
                detail="Delegated twin change requests require the planner role in the named exercise",
            )
        if iw_cli is None:
            raise HTTPException(status_code=503, detail="IMPACT Web client is not configured")

        delegate_payload = {
            **body.model_dump(),
            "on_behalf_of": member.user_id,
        }
        cur_epoch = sync_engine._get_state(body.exercise_id).epoch
        try:
            return iw_cli.raise_twin_change_request(delegate_payload, epoch=cur_epoch)
        except httpx.HTTPStatusError as exc:
            detail = f"IMPACT Web refused delegated change request ({exc.response.status_code})"
            try:
                err_json = exc.response.json()
                if isinstance(err_json, dict) and err_json.get("detail"):
                    detail = str(err_json["detail"])
            except Exception:
                pass
            raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    # --- Paired Backup Export / Import (docs/hosting.md section 5) ---

    def _require_backup_auth(request: Request) -> None:
        hdr = request.headers.get("Authorization", "")
        if hdr.startswith("Bearer "):
            tok = hdr[len("Bearer ") :].strip()
            if sync_tok and hmac.compare_digest(tok, sync_tok):
                return
        member = resolve_authenticated_member(
            request,
            exercise_id="EX-DEMO",
            auth_mode=mode,
            jwt_secret=j_secret,
            edge_auth_secret=e_secret,
            impactweb_client=iw_cli,
        )
        if member.role != "facilitator":
            raise HTTPException(status_code=403, detail="Backup endpoints require sync token or facilitator role")

    @api.post("/api/v1/backup/reset-scope")
    def backup_reset_scope(request: Request, exercise_id: str = Query(default="EX-DEMO")) -> dict:
        _require_backup_auth(request)
        return sync_engine.reset_exercise_scope(exercise_id)

    @api.get("/api/v1/backup/export")
    def backup_export(request: Request) -> dict:
        _require_backup_auth(request)
        return sync_engine.export_twin_only_backup()

    @api.post("/api/v1/backup/import")
    def backup_import(bundle: dict, request: Request) -> dict:
        _require_backup_auth(request)
        try:
            return sync_engine.import_twin_only_backup(bundle)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    app.include_router(api)
    app.include_router(api, prefix="/twin")

    if (dist_dir / "index.html").exists():
        assets_dir = dist_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="twin-assets")
            app.mount("/twin/assets", StaticFiles(directory=str(assets_dir)), name="twin-prefixed-assets")

        @app.get("/")
        @app.get("/twin")
        @app.get("/twin/")
        def serve_index():
            return FileResponse(dist_dir / "index.html")

    return app
