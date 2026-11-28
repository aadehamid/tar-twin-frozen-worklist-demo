"""Pydantic v2 Layer-1 schemas for Unit 200 scenario artifacts (docs/verification.md section 1)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Provenance = Literal["SYNTHETIC"]


class FeedBasis(BaseModel):
    rate_bbl_day: float = Field(gt=0)
    api_gravity: float = Field(gt=10, lt=60)
    sg_60_60: float = Field(gt=0.5, lt=1.2)
    rho_ref_kg_m3: float = Field(gt=500, lt=1200)
    mass_rate_t_day: float = Field(gt=0)
    sr_wt_fraction: float = Field(ge=0.0, le=1.0)
    lco_wt_fraction: float = Field(ge=0.0, le=0.20)
    sulfur_wt_fraction: float = Field(gt=0.0, lt=0.05)


class HydrogenBasis(BaseModel):
    c_h2_sr_wt_fraction: float = Field(gt=0)
    c_h2_lco_wt_fraction: float = Field(gt=0)
    chemical_h2_t_day: float = Field(gt=0)
    purge_and_dissolved_h2_t_day: float = Field(gt=0)
    makeup_h2_t_day: float = Field(gt=0)
    recycle_gas_h2_mol_fraction: float = Field(gt=0.5, lt=1.0)


class UlsdProduct(BaseModel):
    mass_rate_t_day: float = Field(gt=0)
    api_gravity: float = Field(gt=10, lt=60)
    sg_60_60: float = Field(gt=0.5, lt=1.2)
    sulfur_ppmw: float = Field(gt=0, le=15.0)
    flash_point_c: float = Field(ge=52.0)
    cetane_number: float = Field(ge=40.0)


class LightProduct(BaseModel):
    mass_rate_t_day: float = Field(gt=0)


class SourOffgasProduct(BaseModel):
    mass_rate_t_day: float = Field(gt=0)
    h2s_t_day: float = Field(gt=0)


class ProductsBasis(BaseModel):
    ulsd: UlsdProduct
    wild_naphtha: LightProduct
    sour_offgas: SourOffgasProduct


class ExchangerThermalBasis(BaseModel):
    tag: str
    tube_mass_kg_s: float = Field(gt=0)
    tube_cp_kj_kg_k: float = Field(gt=0)
    tube_in_c: float
    tube_out_c: float
    shell_mass_kg_s: float = Field(gt=0)
    shell_cp_kj_kg_k: float = Field(gt=0)
    shell_in_c: float
    shell_out_c: float
    duty_mw: float = Field(gt=0)


class ReactorThermalBasis(BaseModel):
    r201_in_c: float
    r201_out_c: float
    r202_bed1_in_c: float
    r202_bed1_out_c: float
    r202_bed2_in_c: float
    r202_bed2_out_c: float
    bed1_out_mass_kg_s: float = Field(gt=0)
    process_cp_kj_kg_k: float = Field(gt=0)
    quench_mass_kg_s: float = Field(gt=0)
    quench_cp_kj_kg_k: float = Field(gt=0)
    quench_temp_c: float


class ChargePumpBasis(BaseModel):
    tags: list[str]
    suction_barg: float
    discharge_barg: float
    vol_flow_m3_s: float = Field(gt=0)
    hydraulic_efficiency: float = Field(gt=0.4, lt=0.95)
    shaft_power_kw: float = Field(gt=0)


class RecycleCompressorBasis(BaseModel):
    tag: str
    suction_barg: float
    discharge_barg: float
    suction_temp_c: float
    gas_mw_g_mol: float = Field(gt=2.0, lt=30.0)
    gamma_k: float = Field(gt=1.05, lt=1.67)
    z_avg: float = Field(gt=0.7, lt=1.2)
    polytropic_efficiency: float = Field(gt=0.5, lt=0.95)
    mechanical_efficiency: float = Field(gt=0.8, lt=1.0)
    mass_flow_kg_s: float = Field(gt=0)
    polytropic_head_kj_kg: float = Field(gt=0)
    shaft_power_kw: float = Field(gt=0)


class ProcessBasis(BaseModel):
    event_id: str
    unit: str
    provenance: Provenance = "SYNTHETIC"
    feed: FeedBasis
    hydrogen: HydrogenBasis
    products: ProductsBasis
    feed_effluent_exchangers: list[ExchangerThermalBasis]
    reactors: ReactorThermalBasis
    charge_pump: ChargePumpBasis
    recycle_compressor: RecycleCompressorBasis


class MajorEquipment(BaseModel):
    tag: str
    description: str
    equipment_class: Literal[
        "filter",
        "vessel",
        "pump",
        "reactor",
        "exchanger",
        "heater",
        "air_cooler",
        "column",
        "compressor",
        "turbine",
    ]
    shacl_class: str
    area: str
    sheet: str
    functional_location: str
    operating_pressure_barg: float = Field(ge=0.0)
    design_pressure_barg: float = Field(gt=0.0)
    operating_temp_c: float
    design_temp_c: float
    suction_block_valve: str | None = None
    discharge_block_valve: str | None = None
    status: Literal["active"] = "active"
    provenance: Provenance = "SYNTHETIC"


class PsvRecord(BaseModel):
    tag: str
    description: str
    protects_tag: str
    area: str
    sheet: str
    functional_location: str
    set_pressure_barg: float = Field(gt=0)
    orifice_letter: str
    side_note: str = ""
    status: Literal["active"] = "active"
    provenance: Provenance = "SYNTHETIC"


class ValveRecord(BaseModel):
    tag: str
    description: str
    valve_type: Literal["gate", "globe", "ball", "check"]
    role: Literal["block", "control", "check", "relief"]
    area: str
    sheet: str
    parent_equipment: str
    functional_location: str
    status: Literal["active"] = "active"
    provenance: Provenance = "SYNTHETIC"


class InstrumentRecord(BaseModel):
    tag: str
    description: str
    instrument_type: Literal["PT", "TT", "FT", "LT", "AT"]
    measures_tag: str
    area: str
    sheet: str
    functional_location: str
    status: Literal["active"] = "active"
    provenance: Provenance = "SYNTHETIC"


class PipingSegmentRecord(BaseModel):
    line_number: str
    description: str
    fluid_code: str
    piping_class: str
    size_in: int = Field(gt=0)
    area: str
    sheet: str
    parent_equipment: str
    status: Literal["active"] = "active"
    provenance: Provenance = "SYNTHETIC"


class InactiveTagRecord(BaseModel):
    tag: str
    unit: str
    status: Literal["retired", "other_unit"]
    description: str
    intended_unit200_tag: str
    provenance: Provenance = "SYNTHETIC"


class EquipmentMaster(BaseModel):
    unit: str
    site: str
    provenance: Provenance = "SYNTHETIC"
    major_equipment: list[MajorEquipment]
    psvs: list[PsvRecord]
    valves: list[ValveRecord]
    instruments: list[InstrumentRecord]
    piping_segments: list[PipingSegmentRecord]
    inactive_or_external_tags: list[InactiveTagRecord]


class PlotArea(BaseModel):
    code: str
    name: str
    x_min_m: float
    x_max_m: float
    y_min_m: float
    y_max_m: float


class PlotEquipmentPosition(BaseModel):
    tag: str
    area: str
    x_m: float
    y_m: float
    elevation_m: float
    width_m: float = Field(gt=0)
    depth_m: float = Field(gt=0)


class PlotPlan(BaseModel):
    unit: str
    width_m: float
    height_m: float
    pipe_rack_y_range_m: list[float]
    reactor_structure_elevations_m: list[float]
    provenance: Provenance = "SYNTHETIC"
    areas: list[PlotArea]
    equipment: list[PlotEquipmentPosition]


class IsolationEnvelopeRecord(BaseModel):
    id: str
    name: str
    equipment_tags: list[str]
    boundary_sides: dict[str, str]
    boundary_valves: list[str]
    blind_estimate: int = Field(gt=0)
    closed: bool = True


class IsolationEnvelopesDoc(BaseModel):
    unit: str
    provenance: Provenance = "SYNTHETIC"
    envelopes: list[IsolationEnvelopeRecord]


class WorkRequestRecord(BaseModel):
    request_id: str = Field(pattern=r"^WR-200-[0-9]{4}$")
    event_id: str
    title: str
    description: str
    equipment_text: str
    category: str
    work_type_label: str
    driver: Literal["inspection", "reliability", "regulatory", "capital", "operations"]
    source_group: Literal[
        "fixed_equipment", "rotating", "inspection", "operations", "projects", "instrumentation"
    ]
    area: str
    ript_score: int = Field(ge=1, le=25)
    mandatory: bool
    estimate_hours: int = Field(gt=0)
    estimate_hours_by_craft: dict[str, int]
    estimate_cost_usd: int = Field(gt=0)
    status: Literal["candidate", "screened_out", "accepted", "rejected", "deferred", "deleted"] = "candidate"
    version: int = 1
    work_package_id: None = None
    schedule_activity_id: None = None
    provenance: Provenance = "SYNTHETIC"

    @model_validator(mode="after")
    def _hours_match(self) -> WorkRequestRecord:
        if sum(self.estimate_hours_by_craft.values()) != self.estimate_hours:
            raise ValueError(f"{self.request_id}: craft hours do not sum to estimate_hours")
        return self


class WorkRequestsDoc(BaseModel):
    event_id: str
    site: str
    unit: str
    planned_duration_days: int
    budget_target_usd: int
    provenance: Provenance = "SYNTHETIC"
    craft_rates_usd_per_hr: dict[str, int]
    work_requests: list[WorkRequestRecord]


class AnswerKeyRow(BaseModel):
    request_id: str
    difficulty_class: str
    true_tag: str
    equipment_pattern: Literal["clean_tag", "tag_variant", "description_only", "vague_or_wrong"]
    notes: str = ""


class AnswerKeyDoc(BaseModel):
    event_id: str
    provenance: Provenance = "SYNTHETIC"
    rows: list[AnswerKeyRow]


class DuplicatePair(BaseModel):
    id: str
    request_ids: list[str]
    equipment_tag: str
    reason: str


class ClusterRecord(BaseModel):
    id: str
    type: Literal["scaffold", "isolation", "access"]
    name: str
    area: str
    equipment_tags: list[str]
    request_ids: list[str]
    shared_hours: int = Field(gt=0)
    shared_cost_usd: int = Field(gt=0)


class ClustersAndDuplicatesDoc(BaseModel):
    event_id: str
    provenance: Provenance = "SYNTHETIC"
    duplicate_pairs: list[DuplicatePair]
    scaffold_clusters: list[ClusterRecord]
    isolation_clusters: list[ClusterRecord]
    access_clusters: list[ClusterRecord]


class LateChangeRecord(BaseModel):
    change_id: str
    checkpoint: Literal["T-9", "T-6", "T-3", "T-1"]
    type: Literal["add", "delete", "change"]
    decision: Literal["approved", "rejected"]
    mandatory: bool
    equipment_tag: str
    target_request_id: str | None = None
    source_group: Literal[
        "fixed_equipment", "rotating", "inspection", "operations", "projects", "instrumentation"
    ]
    title: str
    reason: str
    hours_delta: int
    cost_delta_usd: int
    schedule_impact_days: float = 0.0


class LiveWalkthroughAdd(BaseModel):
    change_id: str
    equipment_tag: str
    envelope_id: str
    source_group: Literal["operations"] = "operations"
    mandatory: bool = False
    title: str
    reason: str
    hours_delta: int = Field(gt=0)
    cost_delta_usd: int = Field(gt=0)
    shared_setup_hours_saved: int = Field(gt=0)
    in_late_scope_simulation: Literal[False] = False


class LateScopeDoc(BaseModel):
    event_id: str
    provenance: Provenance = "SYNTHETIC"
    scripted_changes: list[LateChangeRecord]
    live_walkthrough_add: LiveWalkthroughAdd


class ManifestDoc(BaseModel):
    seed: int
    event_id: str
    unit: str
    provenance: Provenance = "SYNTHETIC"
    files: dict[str, str]
