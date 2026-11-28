"""Unit 200 canonical equipment master, plot plan, and isolation envelopes."""

from __future__ import annotations

from scenario.schemas import (
    EquipmentMaster,
    InactiveTagRecord,
    InstrumentRecord,
    IsolationEnvelopeRecord,
    IsolationEnvelopesDoc,
    MajorEquipment,
    PipingSegmentRecord,
    PlotArea,
    PlotEquipmentPosition,
    PlotPlan,
    PsvRecord,
    ValveRecord,
)

SHACL_CLASS_MAP: dict[str, str] = {
    "filter": "Filter",
    "vessel": "Vessel",
    "pump": "RotatingEquipment",
    "reactor": "Reactor",
    "exchanger": "Exchanger",
    "heater": "FiredHeater",
    "air_cooler": "AirCooler",
    "column": "Column",
    "compressor": "RotatingEquipment",
    "turbine": "RotatingEquipment",
}

# (tag, description, equipment_class, area, sheet, p_op, p_des, t_op, t_des, suct_bv, disch_bv)
MAJOR_SPECS: list[tuple[str, str, str, str, str, float, float, float, float, str | None, str | None]] = [
    ("FL-201A", "Feed filter A", "filter", "200-A", "200-PID-001", 5.5, 10.0, 60.0, 120.0, None, None),
    ("FL-201B", "Feed filter B", "filter", "200-A", "200-PID-001", 5.5, 10.0, 60.0, 120.0, None, None),
    ("D-201", "Feed surge drum", "vessel", "200-A", "200-PID-001", 4.5, 9.0, 62.0, 120.0, None, None),
    ("P-201A", "Charge pump A (north)", "pump", "200-A", "200-PID-001", 98.5, 120.0, 62.0, 130.0, "HV-2017", "HV-2021"),
    ("P-201B", "Charge pump B (south)", "pump", "200-A", "200-PID-001", 98.5, 120.0, 62.0, 130.0, "HV-2018", "HV-2022"),
    ("R-201", "Guard reactor", "reactor", "200-B", "200-PID-002", 92.0, 118.0, 346.0, 440.0, None, None),
    ("R-202", "Main reactor, two beds with quench", "reactor", "200-B", "200-PID-002", 89.0, 118.0, 374.0, 440.0, None, None),
    ("E-201A", "Feed/effluent exchanger shell 1 of 3", "exchanger", "200-C", "200-PID-002", 95.0, 120.0, 237.0, 430.0, None, None),
    ("E-201B", "Feed/effluent exchanger shell 2 of 3", "exchanger", "200-C", "200-PID-002", 94.0, 120.0, 306.0, 430.0, None, None),
    ("E-201C", "Feed/effluent exchanger shell 3 of 3", "exchanger", "200-C", "200-PID-002", 93.0, 120.0, 374.0, 430.0, None, None),
    ("E-202", "Effluent trim cooler", "exchanger", "200-C", "200-PID-003", 82.0, 105.0, 110.0, 180.0, None, None),
    ("E-204", "Product cooler", "exchanger", "200-C", "200-PID-005", 12.0, 20.0, 185.0, 240.0, None, None),
    ("H-201", "Charge heater, two passes", "heater", "200-D", "200-PID-002", 94.0, 125.0, 332.0, 450.0, None, None),
    ("A-201", "Effluent air cooler, 4 bays", "air_cooler", "200-E", "200-PID-003", 84.0, 108.0, 169.0, 230.0, None, None),
    ("D-202", "Cold high-pressure separator", "vessel", "200-E", "200-PID-003", 80.0, 102.0, 50.0, 110.0, None, None),
    ("D-203", "Low-pressure separator", "vessel", "200-E", "200-PID-003", 14.0, 22.0, 52.0, 110.0, None, None),
    ("P-204A", "Wash water pump A", "pump", "200-E", "200-PID-003", 86.0, 108.0, 45.0, 100.0, "HV-2083", "HV-2084"),
    ("P-204B", "Wash water pump B", "pump", "200-E", "200-PID-003", 86.0, 108.0, 45.0, 100.0, "HV-2085", "HV-2086"),
    ("D-204", "Recycle gas knockout drum", "vessel", "200-F", "200-PID-004", 75.0, 96.0, 48.0, 100.0, None, None),
    ("C-202", "Recycle gas amine scrubber", "column", "200-F", "200-PID-004", 76.0, 98.0, 50.0, 110.0, None, None),
    ("K-201", "Recycle gas compressor, centrifugal", "compressor", "200-F", "200-PID-004", 96.0, 118.0, 72.0, 130.0, "HV-2055", "HV-2056"),
    ("KT-201", "Steam turbine driver for K-201", "turbine", "200-F", "200-PID-004", 42.0, 52.0, 385.0, 440.0, None, None),
    ("D-206", "Makeup gas knockout drum", "vessel", "200-F", "200-PID-004", 22.0, 32.0, 40.0, 100.0, None, None),
    ("K-202A", "Makeup hydrogen compressor A, reciprocating", "compressor", "200-F", "200-PID-004", 96.0, 118.0, 95.0, 160.0, "HV-2073", "HV-2074"),
    ("K-202B", "Makeup hydrogen compressor B, reciprocating", "compressor", "200-F", "200-PID-004", 96.0, 118.0, 95.0, 160.0, "HV-2075", "HV-2076"),
    ("C-201", "Product stripper, 30 trays", "column", "200-G", "200-PID-005", 8.5, 15.0, 235.0, 290.0, None, None),
    ("E-203", "Stripper overhead condenser", "exchanger", "200-G", "200-PID-005", 8.0, 15.0, 145.0, 200.0, None, None),
    ("D-205", "Stripper overhead drum", "vessel", "200-G", "200-PID-005", 7.5, 15.0, 48.0, 110.0, None, None),
    ("P-202A", "Stripper reflux pump A", "pump", "200-G", "200-PID-005", 14.0, 22.0, 48.0, 110.0, "HV-2095", "HV-2096"),
    ("P-202B", "Stripper reflux pump B", "pump", "200-G", "200-PID-005", 14.0, 22.0, 48.0, 110.0, "HV-2097", "HV-2098"),
    ("P-203A", "Stripper bottoms pump A", "pump", "200-G", "200-PID-005", 16.0, 24.0, 230.0, 285.0, "HV-2099", "HV-2100"),
    ("P-203B", "Stripper bottoms pump B", "pump", "200-G", "200-PID-005", 16.0, 24.0, 230.0, 285.0, "HV-2101", "HV-2102"),
]


def build_equipment_master_and_envelopes() -> tuple[EquipmentMaster, IsolationEnvelopesDoc]:
    major_equipment = [
        MajorEquipment(
            tag=tag,
            description=desc,
            equipment_class=cls,  # type: ignore[arg-type]
            shacl_class=SHACL_CLASS_MAP[cls],
            area=area,
            sheet=sheet,
            functional_location=f"DEMO-U200-{area}-{tag}",
            operating_pressure_barg=p_op,
            design_pressure_barg=p_des,
            operating_temp_c=t_op,
            design_temp_c=t_des,
            suction_block_valve=sbv,
            discharge_block_valve=dbv,
        )
        for tag, desc, cls, area, sheet, p_op, p_des, t_op, t_des, sbv, dbv in MAJOR_SPECS
    ]
    major_by_tag = {e.tag: e for e in major_equipment}

    # 30 PSVs (PSV-2101..PSV-2130); protects every vessel, column, reactor, exchanger plus key rotating/heater items
    psv_targets: list[tuple[str, str, str, str]] = [
        ("PSV-2101", "D-201", "F", "Feed surge drum primary relief"),
        ("PSV-2102", "R-201", "H", "Guard reactor inlet relief"),
        ("PSV-2103", "R-202", "J", "Main reactor primary relief"),
        ("PSV-2104", "D-202", "H", "HP separator relief valve A side (south) on nozzle N7"),
        ("PSV-2105", "D-202", "H", "HP separator relief valve B side (north) on nozzle N8"),
        ("PSV-2106", "E-201A", "F", "E-201A shell-side thermal/blocked outlet relief"),
        ("PSV-2107", "E-201B", "F", "E-201B shell-side thermal/blocked outlet relief"),
        ("PSV-2108", "E-201C", "F", "E-201C shell-side thermal/blocked outlet relief"),
        ("PSV-2109", "E-202", "E", "Effluent trim cooler shell relief"),
        ("PSV-2110", "E-204", "E", "Product cooler shell relief"),
        ("PSV-2111", "D-203", "G", "LP separator primary relief"),
        ("PSV-2112", "D-204", "H", "Recycle gas KO drum primary relief"),
        ("PSV-2113", "C-202", "J", "Amine scrubber overhead relief"),
        ("PSV-2114", "D-206", "G", "Makeup gas KO drum relief"),
        ("PSV-2115", "C-201", "K", "Product stripper overhead primary relief A"),
        ("PSV-2116", "C-201", "K", "Product stripper overhead spare relief B"),
        ("PSV-2117", "E-203", "F", "Stripper overhead condenser shell relief"),
        ("PSV-2118", "D-205", "G", "Stripper overhead drum primary relief"),
        ("PSV-2119", "H-201", "F", "Charge heater pass 1 thermal relief"),
        ("PSV-2120", "H-201", "F", "Charge heater pass 2 thermal relief"),
        ("PSV-2121", "A-201", "G", "Effluent air cooler inlet header relief"),
        ("PSV-2122", "K-201", "H", "Recycle gas compressor discharge relief"),
        ("PSV-2123", "K-202A", "F", "Makeup compressor A 2nd stage discharge relief"),
        ("PSV-2124", "K-202B", "F", "Makeup compressor B 2nd stage discharge relief"),
        ("PSV-2125", "FL-201A", "D", "Feed filter A thermal relief"),
        ("PSV-2126", "FL-201B", "D", "Feed filter B thermal relief"),
        ("PSV-2127", "P-201A", "D", "Charge pump A discharge thermal relief"),
        ("PSV-2128", "P-201B", "D", "Charge pump B discharge thermal relief"),
        ("PSV-2129", "R-202", "J", "Main reactor spare relief B"),
        ("PSV-2130", "E-201C", "E", "E-201C tube-side blocked-in relief"),
    ]
    psvs: list[PsvRecord] = []
    for ptag, eq_tag, orifice, note in psv_targets:
        eq = major_by_tag[eq_tag]
        p_set = round(min(eq.design_pressure_barg, max(eq.operating_pressure_barg * 1.06, eq.design_pressure_barg * 0.96)), 1)
        psvs.append(
            PsvRecord(
                tag=ptag,
                description=note,
                protects_tag=eq_tag,
                area=eq.area,
                sheet=eq.sheet,
                functional_location=f"DEMO-U200-{eq.area}-{ptag}",
                set_pressure_barg=p_set,
                orifice_letter=orifice,
                side_note=note,
            )
        )

    # 112 block valves partitioned across the 6 envelopes (exact counts 14, 38, 16, 12, 10, 22) + 8 control valves = 120
    env_specs: list[tuple[str, str, list[str], dict[str, str], list[tuple[str, str, str]]]] = [
        (
            "ENV-200-01",
            "Feed",
            ["FL-201A", "FL-201B", "D-201", "P-201A", "P-201B"],
            {"FL-201A": "full", "FL-201B": "full", "D-201": "full", "P-201A": "suction", "P-201B": "suction"},
            [
                ("HV-2011", "FL-201A", "Feed battery-limit inlet block valve"),
                ("HV-2012", "FL-201A", "Filter FL-201A inlet block valve"),
                ("HV-2013", "FL-201A", "Filter FL-201A outlet block valve"),
                ("HV-2014", "FL-201B", "Filter FL-201B inlet block valve"),
                ("HV-2016", "FL-201B", "Filter FL-201B outlet block valve"),
                ("HV-2017", "P-201A", "Charge pump P-201A suction block valve"),
                ("HV-2018", "P-201B", "Charge pump P-201B suction block valve"),
                ("HV-2019", "D-201", "Feed surge drum D-201 drain block valve"),
                ("HV-2020", "D-201", "Feed surge drum D-201 N2 blanket block valve"),
                ("HV-2010", "D-201", "Feed surge drum D-201 vent block valve"),
                ("XV-2011", "D-201", "Feed battery-limit emergency shutdown valve"),
                ("XV-2012", "D-201", "Feed surge drum outlet ESD valve"),
                ("XV-2013", "P-201A", "Charge pump A suction remote isolation valve"),
                ("XV-2014", "P-201B", "Charge pump B suction remote isolation valve"),
            ],
        ),
        (
            "ENV-200-02",
            "HP reaction loop",
            ["P-201A", "P-201B", "E-201A", "E-201B", "E-201C", "H-201", "R-201", "R-202", "A-201", "E-202", "D-202"],
            {
                "P-201A": "discharge",
                "P-201B": "discharge",
                "E-201A": "full",
                "E-201B": "full",
                "E-201C": "full",
                "H-201": "full",
                "R-201": "full",
                "R-202": "full",
                "A-201": "full",
                "E-202": "full",
                "D-202": "full",
            },
            [
                ("HV-2001", "E-201A", "Combined feed inlet block valve"),
                ("HV-2002", "E-201A", "Reactor effluent outlet block valve to A-201"),
                ("HV-2003", "E-201A", "Recycle gas to combined feed block valve"),
                ("HV-2015", "R-202", "Interbed quench gas block valve"),
                ("XV-2210", "R-201", "Reactor inlet emergency isolation valve"),
                ("HV-2021", "P-201A", "Charge pump P-201A discharge block valve"),
                ("HV-2022", "P-201B", "Charge pump P-201B discharge block valve"),
                ("HV-2023", "E-201A", "E-201A tube drain block valve"),
                ("HV-2024", "E-201A", "E-201A shell vent block valve"),
                ("HV-2025", "E-201B", "E-201B tube drain block valve"),
                ("HV-2026", "E-201B", "E-201B shell vent block valve"),
                ("HV-2027", "E-201C", "E-201C tube drain block valve"),
                ("HV-2028", "E-201C", "E-201C shell vent block valve"),
                ("HV-2029", "H-201", "Charge heater pass 1 inlet block valve"),
                ("HV-2030", "H-201", "Charge heater pass 2 inlet block valve"),
                ("HV-2031", "H-201", "Charge heater pass 1 outlet block valve"),
                ("HV-2032", "H-201", "Charge heater pass 2 outlet block valve"),
                ("HV-2033", "H-201", "Charge heater steam decoke tie-in block valve"),
                ("HV-2034", "R-201", "Guard reactor N2 purge inlet block valve"),
                ("HV-2035", "R-201", "Guard reactor catalyst dump isolation valve"),
                ("HV-2036", "R-202", "Main reactor N2 purge inlet block valve"),
                ("HV-2037", "R-202", "Main reactor flare depressuring block valve"),
                ("HV-2038", "A-201", "Wash water injection check/block valve at A-201"),
                ("HV-2039", "A-201", "Air cooler bay 1-2 header isolation valve"),
                ("HV-2040", "A-201", "Air cooler bay 3-4 header isolation valve"),
                ("HV-2041", "E-202", "Trim cooler process inlet block valve"),
                ("HV-2042", "E-202", "Trim cooler process outlet block valve"),
                ("HV-2043", "D-202", "HP separator overhead gas outlet block valve"),
                ("HV-2044", "D-202", "HP separator hydrocarbon liquid outlet block valve"),
                ("XV-2201", "D-202", "HP separator sour water boot ESD valve"),
                ("XV-2202", "D-202", "HP separator depressuring blowdown valve"),
                ("XV-2203", "R-202", "HP loop emergency depressuring valve A"),
                ("XV-2204", "R-202", "HP loop emergency depressuring valve B"),
                ("XV-2205", "H-201", "Charge heater fuel gas trip isolation valve"),
                ("XV-2206", "E-201C", "Reactor effluent high-pressure isolation valve"),
                ("XV-2207", "A-201", "Wash water injection shutdown block valve"),
                ("XV-2208", "D-202", "HP separator liquid letdown ESD valve"),
                ("XV-2209", "D-202", "HP separator vapor outlet ESD valve"),
            ],
        ),
        (
            "ENV-200-03",
            "Recycle gas",
            ["D-204", "C-202", "K-201"],
            {"D-204": "full", "C-202": "full", "K-201": "full"},
            [
                ("HV-2051", "C-202", "Amine scrubber sour gas inlet block valve"),
                ("HV-2052", "C-202", "Lean amine inlet block valve"),
                ("HV-2053", "C-202", "Rich amine outlet block valve"),
                ("HV-2054", "D-204", "Recycle gas KO drum inlet block valve"),
                ("HV-2055", "K-201", "Recycle gas compressor K-201 suction block valve"),
                ("HV-2056", "K-201", "Recycle gas compressor K-201 discharge block valve"),
                ("HV-2057", "K-201", "K-201 spillback bypass block valve"),
                ("HV-2058", "K-201", "K-201 dry gas seal N2 supply block valve"),
                ("HV-2059", "D-204", "Recycle gas KO drum liquid drain block valve"),
                ("HV-2060", "C-202", "Amine scrubber water wash inlet block valve"),
                ("HV-2061", "C-202", "Amine scrubber flare vent block valve"),
                ("HV-2062", "K-201", "K-201 casing vent to flare block valve"),
                ("XV-2221", "C-202", "Amine scrubber overhead ESD valve"),
                ("XV-2222", "K-201", "K-201 suction emergency shutdown valve"),
                ("XV-2223", "K-201", "K-201 discharge emergency shutdown valve"),
                ("XV-2224", "K-201", "K-201 blowdown to flare ESD valve"),
            ],
        ),
        (
            "ENV-200-04",
            "Makeup gas",
            ["D-206", "K-202A", "K-202B"],
            {"D-206": "full", "K-202A": "full", "K-202B": "full"},
            [
                ("HV-2071", "D-206", "Makeup H2 battery-limit inlet block valve"),
                ("HV-2072", "D-206", "Makeup gas KO drum drain block valve"),
                ("HV-2073", "K-202A", "Makeup compressor K-202A suction block valve"),
                ("HV-2074", "K-202A", "Makeup compressor K-202A discharge block valve"),
                ("HV-2075", "K-202B", "Makeup compressor K-202B suction block valve"),
                ("HV-2076", "K-202B", "Makeup compressor K-202B discharge block valve"),
                ("HV-2077", "K-202A", "K-202A interstage cooler vent block valve"),
                ("HV-2078", "K-202B", "K-202B interstage cooler vent block valve"),
                ("XV-2231", "D-206", "Makeup H2 header ESD isolation valve"),
                ("XV-2232", "K-202A", "K-202A discharge check/ESD block valve"),
                ("XV-2233", "K-202B", "K-202B discharge check/ESD block valve"),
                ("XV-2234", "D-206", "Makeup gas loop flare blowdown valve"),
            ],
        ),
        (
            "ENV-200-05",
            "LP separation",
            ["D-203", "P-204A", "P-204B"],
            {"D-203": "full", "P-204A": "full", "P-204B": "full"},
            [
                ("HV-2081", "D-203", "LP separator feed inlet block valve"),
                ("HV-2082", "D-203", "LP separator offgas outlet block valve"),
                ("HV-2083", "P-204A", "Wash water pump P-204A suction block valve"),
                ("HV-2084", "P-204A", "Wash water pump P-204A discharge block valve"),
                ("HV-2085", "P-204B", "Wash water pump P-204B suction block valve"),
                ("HV-2086", "P-204B", "Wash water pump P-204B discharge block valve"),
                ("HV-2087", "D-203", "LP separator hydrocarbon outlet block valve"),
                ("HV-2088", "D-203", "LP separator sour water drain block valve"),
                ("XV-2241", "D-203", "LP separator offgas to fuel gas ESD valve"),
                ("XV-2242", "D-203", "LP separator liquid to stripper ESD valve"),
            ],
        ),
        (
            "ENV-200-06",
            "Stripper",
            ["C-201", "E-203", "D-205", "P-202A", "P-202B", "P-203A", "P-203B", "E-204"],
            {
                "C-201": "full",
                "E-203": "full",
                "D-205": "full",
                "P-202A": "full",
                "P-202B": "full",
                "P-203A": "full",
                "P-203B": "full",
                "E-204": "full",
            },
            [
                ("HV-2091", "C-201", "Stripper C-201 feed inlet block valve"),
                ("HV-2092", "C-201", "Stripper C-201 stripping steam block valve"),
                ("HV-2093", "E-203", "Overhead condenser process inlet block valve"),
                ("HV-2094", "D-205", "Overhead drum offgas outlet block valve"),
                ("HV-2095", "P-202A", "Reflux pump P-202A suction block valve"),
                ("HV-2096", "P-202A", "Reflux pump P-202A discharge block valve"),
                ("HV-2097", "P-202B", "Reflux pump P-202B suction block valve"),
                ("HV-2098", "P-202B", "Reflux pump P-202B discharge block valve"),
                ("HV-2099", "P-203A", "Bottoms pump P-203A suction block valve"),
                ("HV-2100", "P-203A", "Bottoms pump P-203A discharge block valve"),
                ("HV-2101", "P-203B", "Bottoms pump P-203B suction block valve"),
                ("HV-2102", "P-203B", "Bottoms pump P-203B discharge block valve"),
                ("HV-2103", "E-204", "Product cooler ULSD inlet block valve"),
                ("HV-2104", "E-204", "Product cooler ULSD battery-limit outlet block valve"),
                ("HV-2105", "D-205", "Wild naphtha product outlet block valve"),
                ("HV-2106", "D-205", "Overhead drum sour water boot block valve"),
                ("XV-2251", "C-201", "Stripper feed ESD isolation valve"),
                ("XV-2252", "C-201", "Stripper steam inlet ESD valve"),
                ("XV-2253", "D-205", "Stripper overhead flare vent ESD valve"),
                ("XV-2254", "P-203A", "Bottoms pump A suction remote isolation valve"),
                ("XV-2255", "P-203B", "Bottoms pump B suction remote isolation valve"),
                ("XV-2256", "E-204", "ULSD product battery-limit ESD valve"),
            ],
        ),
    ]

    valves: list[ValveRecord] = []
    envelopes: list[IsolationEnvelopeRecord] = []
    for env_id, env_name, eq_tags, sides, bv_list in env_specs:
        bv_tags: list[str] = []
        for vtag, parent_tag, desc in bv_list:
            eq = major_by_tag[parent_tag]
            valves.append(
                ValveRecord(
                    tag=vtag,
                    description=desc,
                    valve_type="gate" if vtag.startswith("HV-") else "ball",
                    role="block",
                    area=eq.area,
                    sheet=eq.sheet,
                    parent_equipment=parent_tag,
                    functional_location=f"DEMO-U200-{eq.area}-{vtag}",
                )
            )
            bv_tags.append(vtag)
        envelopes.append(
            IsolationEnvelopeRecord(
                id=env_id,
                name=env_name,
                equipment_tags=eq_tags,
                boundary_sides=sides,
                boundary_valves=bv_tags,
                blind_estimate=len(bv_tags) + max(2, len(eq_tags) // 2),
                closed=True,
            )
        )

    control_valves: list[tuple[str, str, str]] = [
        ("FV-2011", "H-201", "Charge heater pass 1 flow control valve"),
        ("FV-2012", "H-201", "Charge heater pass 2 flow control valve"),
        ("FV-2015", "R-202", "Main reactor interbed quench flow control valve"),
        ("LV-2021", "D-201", "Feed surge drum level control valve"),
        ("LV-2031", "D-202", "HP separator liquid letdown level control valve"),
        ("PV-2021", "D-202", "HP loop pressure control valve to flare"),
        ("PV-2041", "D-203", "LP separator offgas pressure control valve"),
        ("FV-2051", "C-201", "Product stripper reflux flow control valve"),
    ]
    for vtag, parent_tag, desc in control_valves:
        eq = major_by_tag[parent_tag]
        valves.append(
            ValveRecord(
                tag=vtag,
                description=desc,
                valve_type="globe",
                role="control",
                area=eq.area,
                sheet=eq.sheet,
                parent_equipment=parent_tag,
                functional_location=f"DEMO-U200-{eq.area}-{vtag}",
            )
        )

    # 140 instruments (PT, TT, FT, LT, AT), including LT-2302 on D-202 from scenario-spec.md section 4.1
    instruments: list[InstrumentRecord] = [
        InstrumentRecord(
            tag="LT-2302",
            description="HP separator D-202 hydrocarbon/water interface level transmitter",
            instrument_type="LT",
            measures_tag="D-202",
            area="200-E",
            sheet="200-PID-003",
            functional_location="DEMO-U200-200-E-LT-2302",
        )
    ]
    inst_types: list[tuple[str, str]] = [
        ("PT", "pressure transmitter"),
        ("TT", "temperature transmitter"),
        ("FT", "flow transmitter"),
        ("LT", "level transmitter"),
        ("AT", "process analyzer"),
    ]
    seq_by_type = {"PT": 2101, "TT": 2201, "FT": 2401, "LT": 2303, "AT": 2501}
    idx = 0
    while len(instruments) < 140:
        eq = major_equipment[idx % len(major_equipment)]
        itype, iname = inst_types[idx % len(inst_types)]
        num = seq_by_type[itype]
        seq_by_type[itype] += 1
        tag = f"{itype}-{num}"
        instruments.append(
            InstrumentRecord(
                tag=tag,
                description=f"{eq.tag} {iname}",
                instrument_type=itype,  # type: ignore[arg-type]
                measures_tag=eq.tag,
                area=eq.area,
                sheet=eq.sheet,
                functional_location=f"DEMO-U200-{eq.area}-{tag}",
            )
        )
        idx += 1

    # 64 piping segments (includes 200-P-0412 near E-201C and all 14 lines from 200-PID-002)
    piping_segments: list[PipingSegmentRecord] = [
        PipingSegmentRecord(
            line_number="200-P-0412",
            description="Reactor effluent high-temperature transfer line near E-201C",
            fluid_code="HC",
            piping_class="15A1",
            size_in=10,
            area="200-C",
            sheet="200-PID-002",
            parent_equipment="E-201C",
        )
    ]
    pid002_lines = [
        ("8\"-P-2001-15A1", "HC", 8, "E-201A", "Combined feed inlet to E-201A"),
        ("6\"-G-2002-15A1", "H2", 6, "E-201A", "Recycle gas to combined feed"),
        ("8\"-P-2003-15A1", "HC", 8, "E-201B", "Feed train E-201A to E-201B"),
        ("8\"-P-2004-15A1", "HC", 8, "E-201C", "Feed train E-201B to E-201C"),
        ("8\"-P-2005-15A1", "HC", 8, "H-201", "Feed from E-201C to H-201 pass 1"),
        ("6\"-P-2006-15A1", "HC", 6, "H-201", "Feed branch to H-201 pass 2"),
        ("8\"-P-2007-15A1", "HC", 8, "R-201", "Heater outlet to guard reactor R-201"),
        ("6\"-P-2008-15A1", "HC", 6, "H-201", "Heater pass 2 outlet to transfer header"),
        ("10\"-P-2009-15A1", "HC", 10, "R-202", "Guard reactor R-201 to main reactor R-202"),
        ("3\"-G-2010-15A1", "H2", 3, "R-202", "Interbed quench gas to R-202 nozzle N2"),
        ("10\"-P-2011-15A1", "HC", 10, "E-201C", "Main reactor R-202 effluent to E-201C shell"),
        ("10\"-P-2012-15A1", "HC", 10, "E-201B", "Effluent E-201C shell to E-201B shell"),
        ("10\"-P-2013-15A1", "HC", 10, "E-201A", "Effluent E-201B shell to E-201A shell"),
        ("10\"-P-2014-15A1", "HC", 10, "E-201A", "Effluent from E-201A shell to A-201"),
    ]
    for lno, fluid, sz, parent, desc in pid002_lines:
        eq = major_by_tag[parent]
        piping_segments.append(
            PipingSegmentRecord(
                line_number=lno,
                description=desc,
                fluid_code=fluid,
                piping_class="15A1",
                size_in=sz,
                area=eq.area,
                sheet=eq.sheet,
                parent_equipment=parent,
            )
        )
    line_num = 401
    p_idx = 0
    while len(piping_segments) < 64:
        if line_num == 412:
            line_num += 1
        eq = major_equipment[p_idx % len(major_equipment)]
        piping_segments.append(
            PipingSegmentRecord(
                line_number=f"200-P-{line_num:04d}",
                description=f"Process piping segment associated with {eq.tag}",
                fluid_code="H2" if eq.area == "200-F" else "HC",
                piping_class="15A1" if eq.design_pressure_barg >= 90 else "3A1",
                size_in=8 if eq.design_pressure_barg >= 90 else 6,
                area=eq.area,
                sheet=eq.sheet,
                parent_equipment=eq.tag,
            )
        )
        line_num += 1
        p_idx += 1

    inactive = [
        InactiveTagRecord(
            tag="E-301B",
            unit="300",
            status="other_unit",
            description="Unit 300 naphtha hydrotreater feed/effluent exchanger B",
            intended_unit200_tag="E-201B",
        ),
        InactiveTagRecord(
            tag="P-301A",
            unit="300",
            status="other_unit",
            description="Unit 300 charge pump A",
            intended_unit200_tag="P-201A",
        ),
        InactiveTagRecord(
            tag="PSV-2099",
            unit="200",
            status="retired",
            description="Retired legacy relief valve on D-202 (replaced by PSV-2104)",
            intended_unit200_tag="PSV-2104",
        ),
        InactiveTagRecord(
            tag="E-209",
            unit="200",
            status="retired",
            description="Retired legacy product cooler (replaced by E-204)",
            intended_unit200_tag="E-204",
        ),
    ]

    master = EquipmentMaster(
        unit="Unit 200 Diesel Hydrotreater",
        site="Demo Refinery (fictional)",
        major_equipment=major_equipment,
        psvs=psvs,
        valves=valves,
        instruments=instruments,
        piping_segments=piping_segments,
        inactive_or_external_tags=inactive,
    )
    envelopes_doc = IsolationEnvelopesDoc(
        unit="Unit 200 Diesel Hydrotreater",
        envelopes=envelopes,
    )
    return master, envelopes_doc


def build_plot_plan() -> PlotPlan:
    areas = [
        PlotArea(code="200-A", name="Feed", x_min_m=2.0, x_max_m=34.0, y_min_m=4.0, y_max_m=34.0),
        PlotArea(code="200-B", name="Reactor structure", x_min_m=36.0, x_max_m=62.0, y_min_m=4.0, y_max_m=34.0),
        PlotArea(code="200-C", name="Exchanger bay", x_min_m=26.0, x_max_m=62.0, y_min_m=46.0, y_max_m=76.0),
        PlotArea(code="200-D", name="Heater", x_min_m=2.0, x_max_m=22.0, y_min_m=46.0, y_max_m=76.0),
        PlotArea(code="200-E", name="Separation", x_min_m=64.0, x_max_m=92.0, y_min_m=46.0, y_max_m=76.0),
        PlotArea(code="200-F", name="Gas compression", x_min_m=94.0, x_max_m=118.0, y_min_m=4.0, y_max_m=76.0),
        PlotArea(code="200-G", name="Stripping", x_min_m=64.0, x_max_m=92.0, y_min_m=4.0, y_max_m=34.0),
    ]

    equipment = [
        # 200-A Feed
        PlotEquipmentPosition(tag="FL-201A", area="200-A", x_m=8.0, y_m=12.0, elevation_m=0.0, width_m=3.0, depth_m=3.0),
        PlotEquipmentPosition(tag="FL-201B", area="200-A", x_m=8.0, y_m=24.0, elevation_m=0.0, width_m=3.0, depth_m=3.0),
        PlotEquipmentPosition(tag="D-201", area="200-A", x_m=18.0, y_m=18.0, elevation_m=3.0, width_m=5.0, depth_m=10.0),
        PlotEquipmentPosition(tag="P-201A", area="200-A", x_m=28.0, y_m=12.0, elevation_m=0.0, width_m=3.0, depth_m=3.0),
        PlotEquipmentPosition(tag="P-201B", area="200-A", x_m=28.0, y_m=24.0, elevation_m=0.0, width_m=3.0, depth_m=3.0),
        # 200-B Reactor structure (grade, 12m, 24m platforms)
        PlotEquipmentPosition(tag="R-201", area="200-B", x_m=44.0, y_m=18.0, elevation_m=0.0, width_m=5.0, depth_m=5.0),
        PlotEquipmentPosition(tag="R-202", area="200-B", x_m=55.0, y_m=18.0, elevation_m=0.0, width_m=6.0, depth_m=6.0),
        # 200-C Exchanger bay (north bundle-pull area and crane pad)
        PlotEquipmentPosition(tag="E-201A", area="200-C", x_m=32.0, y_m=54.0, elevation_m=1.5, width_m=6.0, depth_m=3.0),
        PlotEquipmentPosition(tag="E-201B", area="200-C", x_m=44.0, y_m=54.0, elevation_m=1.5, width_m=6.0, depth_m=3.0),
        PlotEquipmentPosition(tag="E-201C", area="200-C", x_m=56.0, y_m=54.0, elevation_m=1.5, width_m=6.0, depth_m=3.0),
        PlotEquipmentPosition(tag="E-202", area="200-C", x_m=36.0, y_m=68.0, elevation_m=1.5, width_m=6.0, depth_m=3.0),
        PlotEquipmentPosition(tag="E-204", area="200-C", x_m=52.0, y_m=68.0, elevation_m=1.5, width_m=6.0, depth_m=3.0),
        # 200-D Heater (west end, >= 15m from all hydrocarbon drums/pumps)
        PlotEquipmentPosition(tag="H-201", area="200-D", x_m=12.0, y_m=60.0, elevation_m=0.0, width_m=10.0, depth_m=12.0),
        # 200-E Separation
        PlotEquipmentPosition(tag="A-201", area="200-E", x_m=78.0, y_m=69.0, elevation_m=6.0, width_m=14.0, depth_m=8.0),
        PlotEquipmentPosition(tag="D-202", area="200-E", x_m=71.0, y_m=54.0, elevation_m=2.0, width_m=5.0, depth_m=6.0),
        PlotEquipmentPosition(tag="D-203", area="200-E", x_m=85.0, y_m=54.0, elevation_m=2.0, width_m=5.0, depth_m=6.0),
        PlotEquipmentPosition(tag="P-204A", area="200-E", x_m=68.0, y_m=68.0, elevation_m=0.0, width_m=3.0, depth_m=3.0),
        PlotEquipmentPosition(tag="P-204B", area="200-E", x_m=88.0, y_m=68.0, elevation_m=0.0, width_m=3.0, depth_m=3.0),
        # 200-F Gas compression (east side compressor shelter)
        PlotEquipmentPosition(tag="D-204", area="200-F", x_m=100.0, y_m=14.0, elevation_m=1.0, width_m=4.0, depth_m=4.0),
        PlotEquipmentPosition(tag="C-202", area="200-F", x_m=111.0, y_m=14.0, elevation_m=0.0, width_m=4.5, depth_m=4.5),
        PlotEquipmentPosition(tag="K-201", area="200-F", x_m=101.0, y_m=28.0, elevation_m=1.5, width_m=5.0, depth_m=4.0),
        PlotEquipmentPosition(tag="KT-201", area="200-F", x_m=111.0, y_m=28.0, elevation_m=1.5, width_m=5.0, depth_m=4.0),
        PlotEquipmentPosition(tag="D-206", area="200-F", x_m=100.0, y_m=54.0, elevation_m=1.0, width_m=4.0, depth_m=4.0),
        PlotEquipmentPosition(tag="K-202A", area="200-F", x_m=111.0, y_m=54.0, elevation_m=1.5, width_m=6.0, depth_m=4.0),
        PlotEquipmentPosition(tag="K-202B", area="200-F", x_m=111.0, y_m=67.0, elevation_m=1.5, width_m=6.0, depth_m=4.0),
        # 200-G Stripping
        PlotEquipmentPosition(tag="C-201", area="200-G", x_m=70.0, y_m=12.0, elevation_m=0.0, width_m=5.0, depth_m=5.0),
        PlotEquipmentPosition(tag="E-203", area="200-G", x_m=79.0, y_m=12.0, elevation_m=3.0, width_m=5.0, depth_m=3.0),
        PlotEquipmentPosition(tag="D-205", area="200-G", x_m=87.0, y_m=12.0, elevation_m=3.0, width_m=4.0, depth_m=6.0),
        PlotEquipmentPosition(tag="P-202A", area="200-G", x_m=68.0, y_m=26.0, elevation_m=0.0, width_m=3.0, depth_m=3.0),
        PlotEquipmentPosition(tag="P-202B", area="200-G", x_m=75.0, y_m=26.0, elevation_m=0.0, width_m=3.0, depth_m=3.0),
        PlotEquipmentPosition(tag="P-203A", area="200-G", x_m=82.0, y_m=26.0, elevation_m=0.0, width_m=3.0, depth_m=3.0),
        PlotEquipmentPosition(tag="P-203B", area="200-G", x_m=88.0, y_m=26.0, elevation_m=0.0, width_m=3.0, depth_m=3.0),
    ]

    return PlotPlan(
        unit="Unit 200 Diesel Hydrotreater",
        width_m=120.0,
        height_m=80.0,
        pipe_rack_y_range_m=[36.0, 44.0],
        reactor_structure_elevations_m=[0.0, 12.0, 24.0],
        areas=areas,
        equipment=equipment,
    )
