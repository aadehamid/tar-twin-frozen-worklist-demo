"""Phase 1 scenario validation suite, written before the generator (CONTRIBUTING.md Rule 1).

Reads only the generated artifacts under data/scenario/ and verifies:
- Manifest integrity and deterministic byte-for-byte regeneration from seed
- Closed refinery physics (mass, sulfur, H2, heat exchangers, reactor quench, pump/compressor power,
  ASME VIII design margins, API 520/521 PSV set pressures, ASTM D975 ULSD specs)
- Exact Unit 200 scenario counts, plot geometry, isolation envelopes, work list, matching classes,
  and planted problems from docs/scenario-spec.md and docs/matching-showcase.md
- All 5 DEXPI 2.0.1 XML sheets (XSD, pyDEXPI validate, structural wiring, round-trip, SVG)
- SHACL validation against specs/shapes.ttl (plus negative mutants)
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
import warnings
from itertools import combinations
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_DIR = REPO_ROOT / "data" / "scenario"
GENERATOR = REPO_ROOT / "jobs" / "generate_scenario.py"
SHAPES_PATH = REPO_ROOT / "specs" / "shapes.ttl"
XSD_PATH = REPO_ROOT / "spikes" / "dexpi-sheet" / "vendor" / "DEXPI_XML_Schema.xsd"

RHO_W_60F = 999.016
C_BBL_M3 = 0.158987294928
MW_S = 32.065
MW_H2S = 34.0809
R_UNIVERSAL = 8.314462618

EXPECTED_MAJOR_BY_SHEET: dict[str, set[str]] = {
    "200-PID-001": {"FL-201A", "FL-201B", "D-201", "P-201A", "P-201B"},
    "200-PID-002": {"E-201A", "E-201B", "E-201C", "H-201", "R-201", "R-202"},
    "200-PID-003": {"A-201", "E-202", "D-202", "D-203", "P-204A", "P-204B"},
    "200-PID-004": {"D-204", "C-202", "K-201", "KT-201", "D-206", "K-202A", "K-202B"},
    "200-PID-005": {"C-201", "E-203", "D-205", "P-202A", "P-202B", "P-203A", "P-203B", "E-204"},
}

EXPECTED_MAJOR_TAGS: set[str] = set().union(*EXPECTED_MAJOR_BY_SHEET.values())

EXPECTED_ENVELOPE_VALVE_COUNTS: dict[str, int] = {
    "ENV-200-01": 14,
    "ENV-200-02": 38,
    "ENV-200-03": 16,
    "ENV-200-04": 12,
    "ENV-200-05": 10,
    "ENV-200-06": 22,
}

EXPECTED_CATEGORY_COUNTS: dict[str, int] = {
    "Catalyst change-out and reactor internals": 14,
    "Exchanger bundle work": 22,
    "Air cooler": 8,
    "Heater": 12,
    "Columns and vessels": 24,
    "Rotating equipment": 20,
    "Relief valves": 28,
    "Valve overhauls": 30,
    "Thickness, CUI and piping inspection": 26,
    "Instruments and analyzers": 10,
    "Capital tie-in": 4,
    "General prep": 2,
}

EXPECTED_DIFFICULTY_COUNTS: dict[str, int] = {
    "Clean tag": 80,
    "Tag variant": 60,
    "Known alias": 6,
    "Misspelled or shorthand description": 12,
    "Sibling names": 14,
    "Process context": 8,
    "Wrong unit or retired": 4,
    "Area or unit general": 14,
    "Text with instructions in it": 2,
}


def _load_json(name: str) -> dict:
    path = SCENARIO_DIR / name
    assert path.exists(), f"missing generated file {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifest_lists_every_artifact_with_valid_sha256():
    manifest = _load_json("manifest.json")
    assert manifest["seed"] == 20280200
    assert manifest["event_id"] == "TAR-200-2028"
    assert manifest["provenance"] == "SYNTHETIC"
    files = manifest["files"]
    expected_rel = {
        "process-basis.json",
        "equipment-master.json",
        "plot-plan.json",
        "isolation-envelopes.json",
        "work-requests.json",
        "answer-key.json",
        "clusters-and-duplicates.json",
        "late-scope.json",
        *(f"dexpi/{sheet}.xml" for sheet in EXPECTED_MAJOR_BY_SHEET),
        *(f"dexpi/{sheet}.svg" for sheet in EXPECTED_MAJOR_BY_SHEET),
    }
    assert expected_rel.issubset(set(files))
    for rel, expected_hash in files.items():
        actual = SCENARIO_DIR / rel
        assert actual.exists(), f"manifest lists missing file {rel}"
        assert _sha256(actual) == expected_hash, f"hash mismatch for {rel}"


def test_generator_is_byte_deterministic(tmp_path: Path):
    assert GENERATOR.exists(), f"missing generator {GENERATOR}"
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"
    for out in (out_a, out_b):
        res = subprocess.run(
            [sys.executable, str(GENERATOR), "--seed", "20280200", "--out", str(out)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, res.stderr

    files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*") if p.is_file())
    assert files_a == files_b and files_a
    for rel in files_a:
        assert (out_a / rel).read_bytes() == (out_b / rel).read_bytes(), f"nondeterministic {rel}"
        committed = SCENARIO_DIR / rel
        assert committed.exists(), f"missing committed artifact {rel}"
        assert committed.read_bytes() == (out_a / rel).read_bytes(), f"committed {rel} out of date"


class TestProcessPhysics:
    def test_mass_sulfur_and_hydrogen_conservation(self):
        basis = _load_json("process-basis.json")
        feed = basis["feed"]
        h2 = basis["hydrogen"]
        products = basis["products"]

        # EQ-01 API gravity and reference density
        sg_calc = 141.5 / (feed["api_gravity"] + 131.5)
        assert math.isclose(feed["sg_60_60"], sg_calc, rel_tol=1e-5)
        rho_calc = sg_calc * RHO_W_60F
        assert math.isclose(feed["rho_ref_kg_m3"], rho_calc, rel_tol=1e-5)
        m_feed_calc = feed["rate_bbl_day"] * C_BBL_M3 * rho_calc / 1000.0
        assert math.isclose(feed["mass_rate_t_day"], m_feed_calc, rel_tol=1e-5)

        # Feed LCO fraction bound (<= 20 wt% per PPC DHT interface)
        assert 0.0 <= feed["lco_wt_fraction"] <= 0.20
        assert math.isclose(feed["sr_wt_fraction"] + feed["lco_wt_fraction"], 1.0, abs_tol=1e-9)

        # Hydrogen uptake and makeup closure
        c_h2_expected = (
            feed["sr_wt_fraction"] * h2["c_h2_sr_wt_fraction"]
            + feed["lco_wt_fraction"] * h2["c_h2_lco_wt_fraction"]
        )
        assert math.isclose(h2["chemical_h2_t_day"], feed["mass_rate_t_day"] * c_h2_expected, rel_tol=1e-4)
        assert math.isclose(
            h2["makeup_h2_t_day"],
            h2["chemical_h2_t_day"] + h2["purge_and_dissolved_h2_t_day"],
            rel_tol=1e-6,
        )

        # Exact SI mass balance across hydrocarbon + H2 boundary (EQ-02)
        total_in = feed["mass_rate_t_day"] + h2["makeup_h2_t_day"]
        total_out = (
            products["ulsd"]["mass_rate_t_day"]
            + products["wild_naphtha"]["mass_rate_t_day"]
            + products["sour_offgas"]["mass_rate_t_day"]
        )
        assert abs(total_in - total_out) <= 1e-6 * total_in

        # Exact elemental sulfur closure (feed S == ULSD S + H2S S)
        s_in = feed["mass_rate_t_day"] * feed["sulfur_wt_fraction"]
        s_ulsd = products["ulsd"]["mass_rate_t_day"] * (products["ulsd"]["sulfur_ppmw"] * 1e-6)
        s_h2s = products["sour_offgas"]["h2s_t_day"] * (MW_S / MW_H2S)
        assert abs(s_in - (s_ulsd + s_h2s)) <= 1e-4 * s_in

        # Recycle-gas loop mass closure across K-201, E-201A/B/C, and R-202 quench
        comp = basis["recycle_compressor"]
        ex_a = basis["feed_effluent_exchangers"][0]
        rx = basis["reactors"]
        assert math.isclose(
            comp["mass_flow_kg_s"],
            h2["recycle_to_feed_kg_s"] + h2["recycle_to_quench_kg_s"],
            rel_tol=1e-5,
        )
        assert math.isclose(
            ex_a["tube_mass_kg_s"],
            feed["mass_rate_kg_s"] + h2["recycle_to_feed_kg_s"],
            rel_tol=1e-5,
        )
        assert math.isclose(
            ex_a["shell_mass_kg_s"],
            ex_a["tube_mass_kg_s"] + rx["quench_mass_kg_s"],
            rel_tol=1e-5,
        )

        # ASTM D975 S15 ULSD specs
        ulsd = products["ulsd"]
        assert ulsd["sulfur_ppmw"] <= 15.0
        assert ulsd["flash_point_c"] >= 52.0
        assert ulsd["cetane_number"] >= 40.0
        assert ulsd["sg_60_60"] < feed["sg_60_60"]

    def test_exchanger_energy_balance_and_no_temperature_cross(self):
        basis = _load_json("process-basis.json")
        exchangers = basis["feed_effluent_exchangers"]
        assert [e["tag"] for e in exchangers] == ["E-201A", "E-201B", "E-201C"]
        for ex in exchangers:
            q_tube = ex["tube_mass_kg_s"] * ex["tube_cp_kj_kg_k"] * (ex["tube_out_c"] - ex["tube_in_c"]) / 1000.0
            q_shell = ex["shell_mass_kg_s"] * ex["shell_cp_kj_kg_k"] * (ex["shell_in_c"] - ex["shell_out_c"]) / 1000.0
            assert q_tube > 0 and q_shell > 0
            assert math.isclose(q_tube, q_shell, rel_tol=0.02), (ex["tag"], q_tube, q_shell)
            assert math.isclose(ex["duty_mw"], q_tube, rel_tol=0.02)
            # Counter-current no temperature cross with >= 4 C approach
            assert ex["shell_in_c"] - ex["tube_out_c"] >= 4.0, ex["tag"]
            assert ex["shell_out_c"] - ex["tube_in_c"] >= 4.0, ex["tag"]

        # Series continuity: A->B->C on tube side, C->B->A on shell side
        a, b, c = exchangers
        assert math.isclose(a["tube_out_c"], b["tube_in_c"], abs_tol=0.5)
        assert math.isclose(b["tube_out_c"], c["tube_in_c"], abs_tol=0.5)
        assert math.isclose(c["shell_out_c"], b["shell_in_c"], abs_tol=0.5)
        assert math.isclose(b["shell_out_c"], a["shell_in_c"], abs_tol=0.5)

    def test_reactor_exotherm_and_interbed_quench_balance(self):
        basis = _load_json("process-basis.json")
        rx = basis["reactors"]
        assert rx["r201_out_c"] > rx["r201_in_c"]
        assert rx["r202_bed1_out_c"] > rx["r202_bed1_in_c"]
        assert rx["r202_bed2_in_c"] < rx["r202_bed1_out_c"]
        assert rx["r202_bed2_out_c"] > rx["r202_bed2_in_c"]

        # Quench mixing enthalpy balance between R-202 bed 1 and bed 2
        q_removed = rx["bed1_out_mass_kg_s"] * rx["process_cp_kj_kg_k"] * (rx["r202_bed1_out_c"] - rx["r202_bed2_in_c"])
        q_absorbed_by_quench = rx["quench_mass_kg_s"] * rx["quench_cp_kj_kg_k"] * (rx["r202_bed2_in_c"] - rx["quench_temp_c"])
        assert math.isclose(q_removed, q_absorbed_by_quench, rel_tol=0.02)

    def test_charge_pump_and_recycle_compressor_power(self):
        basis = _load_json("process-basis.json")
        pump = basis["charge_pump"]
        delta_p_pa = (pump["discharge_barg"] - pump["suction_barg"]) * 1e5
        q_m3_s = pump["vol_flow_m3_s"]
        w_shaft_kw = (q_m3_s * delta_p_pa) / (pump["hydraulic_efficiency"] * 1000.0)
        assert math.isclose(pump["shaft_power_kw"], w_shaft_kw, rel_tol=0.02)

        # GPSA polytropic compressor head & shaft power (EQ-05)
        comp = basis["recycle_compressor"]
        k = comp["gamma_k"]
        eta_p = comp["polytropic_efficiency"]
        n_over_n_minus_1 = (k / (k - 1.0)) * eta_p
        p1_abs = comp["suction_barg"] + 1.01325
        p2_abs = comp["discharge_barg"] + 1.01325
        t1_k = comp["suction_temp_c"] + 273.15
        mw_kg_mol = comp["gas_mw_g_mol"] / 1000.0
        hp_j_kg = (
            (comp["z_avg"] * R_UNIVERSAL * t1_k / mw_kg_mol)
            * n_over_n_minus_1
            * ((p2_abs / p1_abs) ** (1.0 / n_over_n_minus_1) - 1.0)
        )
        assert math.isclose(comp["polytropic_head_kj_kg"], hp_j_kg / 1000.0, rel_tol=0.02)
        w_comp_kw = (comp["mass_flow_kg_s"] * hp_j_kg) / (eta_p * comp["mechanical_efficiency"] * 1000.0)
        assert math.isclose(comp["shaft_power_kw"], w_comp_kw, rel_tol=0.02)

    def test_asme_design_margins_and_api_520_psv_set_pressures(self):
        master = _load_json("equipment-master.json")
        major = {e["tag"]: e for e in master["major_equipment"]}
        assert set(major) == EXPECTED_MAJOR_TAGS

        for tag, eq in major.items():
            p_op = eq["operating_pressure_barg"]
            p_des = eq["design_pressure_barg"]
            t_op = eq["operating_temp_c"]
            t_des = eq["design_temp_c"]
            assert p_des >= max(1.10 * p_op, p_op + 2.0) - 1e-6, (tag, p_op, p_des)
            assert t_des >= t_op + 25.0 - 1e-6, (tag, t_op, t_des)

        psvs = master["psvs"]
        assert len(psvs) == 30
        protected_set = set()
        for psv in psvs:
            prot = psv["protects_tag"]
            assert prot in major, psv["tag"]
            protected_set.add(prot)
            eq = major[prot]
            assert eq["operating_pressure_barg"] * 1.05 - 1e-6 <= psv["set_pressure_barg"] <= eq["design_pressure_barg"] + 1e-6, (
                psv["tag"],
                psv["set_pressure_barg"],
                eq["operating_pressure_barg"],
                eq["design_pressure_barg"],
            )

        # Every vessel, column, reactor, and exchanger shell must have at least one PSV
        must_protect = {
            tag
            for tag, eq in major.items()
            if eq["equipment_class"] in {"vessel", "column", "reactor", "exchanger"}
        }
        assert must_protect.issubset(protected_set), must_protect - protected_set


class TestScenarioCountsAndGeometry:
    def test_equipment_master_inventory_counts(self):
        master = _load_json("equipment-master.json")
        assert len(master["major_equipment"]) == 32
        assert len(master["psvs"]) == 30
        assert len(master["valves"]) == 120
        assert len(master["instruments"]) == 140
        assert len(master["piping_segments"]) >= 58

        total_unit200 = (
            len(master["major_equipment"])
            + len(master["psvs"])
            + len(master["valves"])
            + len(master["instruments"])
            + len(master["piping_segments"])
        )
        assert 380 <= total_unit200 <= 450

        valve_prefixes = {v["tag"].split("-", 1)[0] for v in master["valves"]}
        assert {"HV", "XV", "FV", "LV", "PV"}.issubset(valve_prefixes)

        # Every pump and compressor has suction and discharge block valves
        valves_by_tag = {v["tag"]: v for v in master["valves"]}
        for eq in master["major_equipment"]:
            if eq["equipment_class"] in {"pump", "compressor"}:
                assert eq["suction_block_valve"] in valves_by_tag, eq["tag"]
                assert eq["discharge_block_valve"] in valves_by_tag, eq["tag"]
                assert valves_by_tag[eq["suction_block_valve"]]["role"] == "block"
                assert valves_by_tag[eq["discharge_block_valve"]]["role"] == "block"

        # Non-Unit-200 / retired tags for planted matching problems
        inactive = master["inactive_or_external_tags"]
        assert len(inactive) == 4
        assert any(t["tag"] == "E-301B" and t["unit"] == "300" for t in inactive)

    def test_isolation_envelopes_match_spec(self):
        env_doc = _load_json("isolation-envelopes.json")
        master = _load_json("equipment-master.json")
        block_valves = {v["tag"] for v in master["valves"] if v["role"] == "block"}
        envelopes = env_doc["envelopes"]
        assert len(envelopes) == 6
        got_counts = {e["id"]: len(e["boundary_valves"]) for e in envelopes}
        assert got_counts == EXPECTED_ENVELOPE_VALVE_COUNTS

        all_eq = set()
        for env in envelopes:
            assert env["equipment_tags"]
            all_eq.update(env["equipment_tags"])
            assert len(env["boundary_valves"]) == len(set(env["boundary_valves"]))
            assert set(env["boundary_valves"]).issubset(block_valves)
            assert env["closed"] is True
        # Every major process item (all except steam turbine KT-201 if non-process, or all 32) is covered
        assert (EXPECTED_MAJOR_TAGS - {"KT-201"}).issubset(all_eq)

    def test_plot_plan_geometry_and_spacing(self):
        plot = _load_json("plot-plan.json")
        assert plot["width_m"] == 120.0
        assert plot["height_m"] == 80.0
        areas = {a["code"]: a for a in plot["areas"]}
        assert set(areas) == {"200-A", "200-B", "200-C", "200-D", "200-E", "200-F", "200-G"}

        positions = {p["tag"]: p for p in plot["equipment"]}
        assert set(positions) == EXPECTED_MAJOR_TAGS

        # Every item inside its area bounds
        for tag, pos in positions.items():
            area = areas[pos["area"]]
            x0 = pos["x_m"] - pos["width_m"] / 2.0
            x1 = pos["x_m"] + pos["width_m"] / 2.0
            y0 = pos["y_m"] - pos["depth_m"] / 2.0
            y1 = pos["y_m"] + pos["depth_m"] / 2.0
            assert area["x_min_m"] <= x0 and x1 <= area["x_max_m"], (tag, pos["area"])
            assert area["y_min_m"] <= y0 and y1 <= area["y_max_m"], (tag, pos["area"])

        # No overlapping footprints at same elevation
        for (ta, a), (tb, b) in combinations(positions.items(), 2):
            if abs(a["elevation_m"] - b["elevation_m"]) >= 3.0:
                continue
            overlap_x = min(a["x_m"] + a["width_m"] / 2.0, b["x_m"] + b["width_m"] / 2.0) > max(
                a["x_m"] - a["width_m"] / 2.0, b["x_m"] - b["width_m"] / 2.0
            )
            overlap_y = min(a["y_m"] + a["depth_m"] / 2.0, b["y_m"] + b["depth_m"] / 2.0) > max(
                a["y_m"] - a["depth_m"] / 2.0, b["y_m"] - b["depth_m"] / 2.0
            )
            assert not (overlap_x and overlap_y), (ta, tb)

        # Heater H-201 sits at the west end with >= 15m separation from hydrocarbon drums/pumps
        h201 = positions["H-201"]
        assert h201["x_m"] <= 25.0
        for tag in ("D-201", "D-202", "D-203", "P-201A", "P-201B"):
            other = positions[tag]
            dist = math.hypot(h201["x_m"] - other["x_m"], h201["y_m"] - other["y_m"])
            assert dist >= 15.0, (tag, dist)

        # Reactor structure has 3 levels (0, 12, 24 m)
        assert plot["reactor_structure_elevations_m"] == [0.0, 12.0, 24.0]


class TestWorkListAndPlantedProblems:
    def test_work_requests_counts_rates_and_schema_slots(self):
        wl = _load_json("work-requests.json")
        rates = wl["craft_rates_usd_per_hr"]
        requests = wl["work_requests"]
        assert len(requests) == 200
        assert [r["request_id"] for r in requests] == [f"WR-200-{i:04d}" for i in range(1, 201)]

        cat_counts: dict[str, int] = {}
        total_hours = 0
        total_cost = 0
        for req in requests:
            cat_counts[req["category"]] = cat_counts.get(req["category"], 0) + 1
            assert 1 <= req["ript_score"] <= 25
            assert req["work_package_id"] is None  # 4.1 schema slot only
            assert req["schedule_activity_id"] is None  # 4.2 schema slot only
            assert req["provenance"] == "SYNTHETIC"

            craft_sum = sum(req["estimate_hours_by_craft"].values())
            assert craft_sum == req["estimate_hours"] and craft_sum > 0, req["request_id"]
            expected_cost = round(sum(hrs * rates[craft] for craft, hrs in req["estimate_hours_by_craft"].items()))
            assert req["estimate_cost_usd"] == expected_cost, req["request_id"]
            total_hours += craft_sum
            total_cost += expected_cost

        assert cat_counts == EXPECTED_CATEGORY_COUNTS
        assert 115_000 <= total_hours <= 125_000, total_hours
        # Candidate list is about 27% over the $22M DRB target (~$27.94M, ~21% reduction needed)
        assert 27_400_000 <= total_cost <= 28_200_000, total_cost
        for req in requests:
            assert "T-010" not in req["title"]

    def test_answer_key_difficulty_classes_and_match_targets(self):
        ak = _load_json("answer-key.json")
        wl = _load_json("work-requests.json")
        master = _load_json("equipment-master.json")
        active_tags = (
            {e["tag"] for e in master["major_equipment"]}
            | {e["tag"] for e in master["psvs"]}
            | {e["tag"] for e in master["valves"]}
            | {e["tag"] for e in master["instruments"]}
            | {e["line_number"] for e in master["piping_segments"]}
        )

        rows = ak["rows"]
        assert len(rows) == 200
        assert {r["request_id"] for r in rows} == {r["request_id"] for r in wl["work_requests"]}

        class_counts: dict[str, int] = {}
        code_auto = 0
        true_tag_count = 0
        none_count = 0
        for row in rows:
            cls = row["difficulty_class"]
            class_counts[cls] = class_counts.get(cls, 0) + 1
            if cls in {"Clean tag", "Tag variant", "Known alias"}:
                code_auto += 1
            if row["true_tag"] == "none":
                none_count += 1
                assert cls == "Area or unit general"
            else:
                true_tag_count += 1
                assert row["true_tag"] in active_tags, (row["request_id"], row["true_tag"])

        assert class_counts == EXPECTED_DIFFICULTY_COUNTS
        assert code_auto == 146
        assert true_tag_count == 193
        assert none_count == 7

    def test_clusters_duplicates_and_late_scope(self):
        cd = _load_json("clusters-and-duplicates.json")
        wl = _load_json("work-requests.json")
        ak = _load_json("answer-key.json")
        req_by_id = {r["request_id"]: r for r in wl["work_requests"]}
        truth_by_id = {r["request_id"]: r["true_tag"] for r in ak["rows"]}

        assert len(cd["duplicate_pairs"]) == 9
        for pair in cd["duplicate_pairs"]:
            a, b = pair["request_ids"]
            assert a != b and a in req_by_id and b in req_by_id
            assert req_by_id[a]["source_group"] != req_by_id[b]["source_group"]
            assert req_by_id[a]["category"] == req_by_id[b]["category"], (pair["id"], a, b)
            assert req_by_id[a]["work_type_label"] == req_by_id[b]["work_type_label"], (pair["id"], a, b)
            assert req_by_id[a]["category"] != "Capital tie-in", pair["id"]
            if truth_by_id[a] == "A-201":
                assert "BAY 1" in req_by_id[a]["title"] and "BAY 1" in req_by_id[b]["title"], pair["id"]
            assert truth_by_id[a] == truth_by_id[b] and truth_by_id[a] != "none"

        assert len(cd["scaffold_clusters"]) == 7
        assert len(cd["isolation_clusters"]) == 6
        assert len(cd["access_clusters"]) == 3
        assert any({"E-201A", "E-201B", "E-201C"}.issubset(set(c["equipment_tags"])) for c in cd["access_clusters"])

        ls = _load_json("late-scope.json")
        scripted = ls["scripted_changes"]
        approved_adds = [c for c in scripted if c["type"] == "add" and c["decision"] == "approved"]
        approved_dels = [c for c in scripted if c["type"] == "delete" and c["decision"] == "approved"]
        rejected = [c for c in scripted if c["decision"] == "rejected"]
        assert len(approved_adds) == 18
        assert len(approved_dels) == 6
        assert len(rejected) == 5
        net_hours = sum(c["hours_delta"] for c in approved_adds + approved_dels)
        assert 3_500 <= net_hours <= 4_500, net_hours

        # Separate live walkthrough step 7 nozzle N3 add on C-201
        live = ls["live_walkthrough_add"]
        assert live["equipment_tag"] == "C-201"
        assert live["envelope_id"] == "ENV-200-06"
        assert "N3" in live["title"] or "N3" in live["reason"]
        assert live["in_late_scope_simulation"] is False


class TestDexpiSheets:
    def test_all_five_sheets_validate_roundtrip_and_render(self, tmp_path: Path):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        from lxml import etree
        from pydexpi.loaders import DexpiXmlSerializer
        from pydexpi.validation import validate

        sys.path.insert(0, str(REPO_ROOT / "spikes" / "dexpi-sheet"))
        import sheet_graph as sg  # noqa: E402

        parser = etree.XMLParser(load_dtd=True, resolve_entities=True)
        schema = etree.XMLSchema(etree.parse(str(XSD_PATH), parser))

        dexpi_dir = SCENARIO_DIR / "dexpi"
        all_found_major: set[str] = set()

        for sheet_no, expected_major in EXPECTED_MAJOR_BY_SHEET.items():
            xml_path = dexpi_dir / f"{sheet_no}.xml"
            svg_path = dexpi_dir / f"{sheet_no}.svg"
            assert xml_path.exists(), f"missing {xml_path}"
            assert svg_path.exists(), f"missing {svg_path}"

            tree = etree.parse(str(xml_path))
            assert schema.validate(tree), f"{sheet_no} XSD failed: {schema.error_log}"

            reloaded = DexpiXmlSerializer().load(dexpi_dir, sheet_no)
            issues = validate(reloaded)
            assert issues == [], (sheet_no, [(i.level_of_recommendation, i.short_description) for i in issues])
            assert sg.structural_problems(reloaded) == [], sheet_no

            # Round-trip byte equality
            rt_dir = tmp_path / sheet_no
            rt_dir.mkdir()
            DexpiXmlSerializer().save(reloaded, rt_dir, sheet_no)
            assert (rt_dir / f"{sheet_no}.xml").read_bytes() == xml_path.read_bytes(), sheet_no

            # Equipment coverage on this sheet
            eq_tags = {
                obj.tagName
                for obj in sg.objects(reloaded)
                if hasattr(obj, "tagName") and obj.tagName
            }
            assert expected_major.issubset(eq_tags), (sheet_no, expected_major - eq_tags)
            all_found_major.update(expected_major)

            # SVG parses with finite viewBox and labels each major equipment tag
            svg_tree = etree.parse(str(svg_path))
            vb = [float(v) for v in svg_tree.getroot().get("viewBox").split()]
            assert len(vb) == 4 and all(math.isfinite(v) for v in vb) and vb[2] > 0 and vb[3] > 0
            svg_texts = ["".join(t.itertext()).strip() for t in svg_tree.iter("{*}text")]
            for tag in expected_major:
                assert svg_texts.count(tag) == 1, (sheet_no, tag, svg_texts.count(tag))

        assert all_found_major == EXPECTED_MAJOR_TAGS

    def test_sheet_200_pid_002_preserves_spike_flow_edges_and_matcher_facts(self):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        from pydexpi.loaders import DexpiXmlSerializer

        sys.path.insert(0, str(REPO_ROOT / "spikes" / "dexpi-sheet"))
        import expected as X  # noqa: E402
        import sheet_graph as sg  # noqa: E402

        dexpi_dir = SCENARIO_DIR / "dexpi"
        assert (dexpi_dir / "200-PID-002.xml").exists()
        reloaded = DexpiXmlSerializer().load(dexpi_dir, "200-PID-002")
        edges = sg.flow_edges(reloaded)
        assert X.FLOW_EDGES.issubset(edges), X.FLOW_EDGES - edges


def test_twin_graph_full_mode_passes_cleanly():
    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "twin_graph.py"), "--repo", str(REPO_ROOT), "--mode", "full", "check", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    data = json.loads(res.stdout)
    assert data["mode"] == "full"
    assert data["errors"] == []
    assert data["clashes"] == []


class TestShaclValidation:
    def test_generated_scenario_conforms_and_mutants_fail(self):
        import pyshacl
        import rdflib

        sys.path.insert(0, str(REPO_ROOT / "jobs"))
        from scenario.shacl_export import build_scenario_graph, graph_to_turtle

        shapes_ttl = SHAPES_PATH.read_text(encoding="utf-8")
        shapes_g = rdflib.Graph().parse(data=shapes_ttl, format="turtle")

        clean_graph = build_scenario_graph(SCENARIO_DIR)
        clean_ttl = graph_to_turtle(clean_graph)
        data_g = rdflib.Graph().parse(data=clean_ttl, format="turtle")
        conforms, _report_g, report_text = pyshacl.validate(
            data_g, shacl_graph=shapes_g, inference="none", allow_warnings=False
        )
        assert conforms, report_text

        # Mutant 1: invalid major equipment tag pattern
        m1 = json.loads(json.dumps(clean_graph))
        eq_node = next(n for n in m1["nodes"] if "Equipment" in n["labels"])
        eq_node["props"]["tag"] = "E201A"
        c1, _, _ = pyshacl.validate(
            rdflib.Graph().parse(data=graph_to_turtle(m1), format="turtle"),
            shacl_graph=shapes_g,
            inference="none",
        )
        assert not c1

        # Mutant 2: BundlePull resolved to a Reactor instead of Exchanger
        m2 = json.loads(json.dumps(clean_graph))
        reactor_key = next(n["key"] for n in m2["nodes"] if "Reactor" in n["labels"])
        bp_key = next(n["key"] for n in m2["nodes"] if "BundlePull" in n["labels"])
        for rel in m2["rels"]:
            if rel["type"] == "RESOLVES_TO" and rel["from"] == bp_key:
                rel["to"] = reactor_key
        c2, _, _ = pyshacl.validate(
            rdflib.Graph().parse(data=graph_to_turtle(m2), format="turtle"),
            shacl_graph=shapes_g,
            inference="none",
        )
        assert not c2

        # Mutant 3: PSV without PROTECTS link
        m3 = json.loads(json.dumps(clean_graph))
        psv_key = next(n["key"] for n in m3["nodes"] if "ReliefValve" in n["labels"])
        m3["rels"] = [r for r in m3["rels"] if not (r["type"] == "PROTECTS" and r["from"] == psv_key)]
        c3, _, _ = pyshacl.validate(
            rdflib.Graph().parse(data=graph_to_turtle(m3), format="turtle"),
            shacl_graph=shapes_g,
            inference="none",
        )
        assert not c3

        # Mutant 4: RIPT score out of range (26)
        m4 = json.loads(json.dumps(clean_graph))
        wr_node = next(n for n in m4["nodes"] if "ScopeItem" in n["labels"])
        wr_node["props"]["ript"] = 26
        c4, _, _ = pyshacl.validate(
            rdflib.Graph().parse(data=graph_to_turtle(m4), format="turtle"),
            shacl_graph=shapes_g,
            inference="none",
        )
        assert not c4

        # Mutant 5: Shell-and-tube exchanger missing a nozzle (fails minCount 4)
        m5 = json.loads(json.dumps(clean_graph))
        ex_key = "eq:E-202"
        ex_nozzle_rels = [r for r in m5["rels"] if r["type"] == "HAS_NOZZLE" and r["from"] == ex_key]
        assert len(ex_nozzle_rels) == 4
        m5["rels"].remove(ex_nozzle_rels[0])
        c5, _, _ = pyshacl.validate(
            rdflib.Graph().parse(data=graph_to_turtle(m5), format="turtle"),
            shacl_graph=shapes_g,
            inference="none",
        )
        assert not c5

        # Mutant 6: Pump missing discharge block valve (fails SUCTION_VALVE/DISCHARGE_VALVE shape)
        m6 = json.loads(json.dumps(clean_graph))
        m6["rels"] = [r for r in m6["rels"] if not (r["type"] == "DISCHARGE_VALVE" and r["from"] == "eq:P-201A")]
        c6, _, _ = pyshacl.validate(
            rdflib.Graph().parse(data=graph_to_turtle(m6), format="turtle"),
            shacl_graph=shapes_g,
            inference="none",
        )
        assert not c6

    def test_topology_engineering_rules_and_closure_mutants(self):
        sys.path.insert(0, str(REPO_ROOT / "jobs"))
        from scenario.shacl_export import build_scenario_graph, verify_engineering_rules

        clean_graph = build_scenario_graph(SCENARIO_DIR)
        assert verify_engineering_rules(SCENARIO_DIR, clean_graph) == []

        # Mutant A: removing boundary valve HV-2043 from ENV-200-02 leaks HP reaction loop into C-202 (ENV-200-03)
        m_env = json.loads(json.dumps(clean_graph))
        m_env["rels"] = [
            r for r in m_env["rels"] if not (r["type"] == "BOUNDED_BY" and r["from"] == "env:ENV-200-02" and r["to"] == "valve:HV-2043")
        ]
        errs = verify_engineering_rules(SCENARIO_DIR, m_env)
        assert any("ENV-200-02" in e and "not closed" in e for e in errs), errs

        # Mutant B: removing a shell-side nozzle from E-204 fails exchanger nozzle rule
        m_nz = json.loads(json.dumps(clean_graph))
        m_nz["rels"] = [
            r for r in m_nz["rels"] if not (r["type"] == "HAS_NOZZLE" and r["from"] == "eq:E-204" and r["to"] == "nz:E-204:N3")
        ]
        errs_nz = verify_engineering_rules(SCENARIO_DIR, m_nz)
        assert any("E-204" in e and "nozzles" in e for e in errs_nz), errs_nz

        # Mutant C: duplicating an OPC on the same sheet fails duplicate-OPC check
        m_opc = json.loads(json.dumps(clean_graph))
        orig_opc = next(n for n in m_opc["nodes"] if "OffPageConnector" in n["labels"] and n["props"]["number"] == "OPC-21")
        dup_opc = json.loads(json.dumps(orig_opc))
        dup_opc["key"] = orig_opc["key"] + "_dup"
        m_opc["nodes"].append(dup_opc)
        errs_opc = verify_engineering_rules(SCENARIO_DIR, m_opc)
        assert any("duplicate off-page connector" in e and "OPC-21" in e for e in errs_opc), errs_opc
