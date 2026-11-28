"""Unit 200 Digital Twin FastAPI service (Phase 3 plant graph foundation)."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from twin.graph_store import MemoryPlantStore
from twin.plant_loader import build_plant_graph


def create_app(
    *,
    scenario_dir: Path | None = None,
    shapes_path: Path | None = None,
    neo4j_uri: str | None = None,
    neo4j_user: str | None = None,
    neo4j_password: str | None = None,
    frontend_dist_dir: Path | None = None,
) -> FastAPI:
    repo_root = Path(__file__).resolve().parents[4]
    scen_dir = scenario_dir or Path(os.environ.get("SCENARIO_DIR", str(repo_root / "data" / "scenario")))
    sh_path = shapes_path or Path(os.environ.get("SHAPES_PATH", str(repo_root / "specs" / "shapes.ttl")))
    n_uri = neo4j_uri or os.environ.get("NEO4J_URI", "")
    n_user = neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
    n_pass = neo4j_password or os.environ.get("NEO4J_PASSWORD", "")
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

    app = FastAPI(title="Unit 200 Turnaround Digital Twin API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = store
    app.state.scenario_dir = scen_dir

    api = APIRouter()

    @api.get("/api/v1/utils/health-check/")
    def health_check() -> bool:
        return True

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
