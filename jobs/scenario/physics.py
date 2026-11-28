"""Closed refinery physics for Unit 200 diesel hydrotreater (42,000 BPSD).

Grounded in standard SI balances modeled after PPC governing equations:
- EQ-01: API gravity and standard reference density (rho_w = 999.016 kg/m^3 at 60 F)
- EQ-02: Exact SI mass balance across hydrocarbon + H2 battery limit
- EQ-05: GPSA polytropic compressor head and shaft power
- EQ-07: Hydrotreating chemical hydrogen uptake by SRGO / LCO blend
- Counter-current exchanger enthalpy closure with >= 4 C minimum approach
- Exothermic guard + two-bed reactor with interbed recycle-H2 quench balance
"""

from __future__ import annotations

from scenario.schemas import (
    ChargePumpBasis,
    ExchangerThermalBasis,
    FeedBasis,
    HydrogenBasis,
    LightProduct,
    ProcessBasis,
    ProductsBasis,
    ReactorThermalBasis,
    RecycleCompressorBasis,
    SourOffgasProduct,
    UlsdProduct,
)

RHO_W_60F = 999.016
C_BBL_M3 = 0.158987294928
MW_S = 32.065
MW_H2S = 34.0809
R_UNIVERSAL = 8.314462618


def build_process_basis() -> ProcessBasis:
    # Feed: 42,000 BPSD diesel blend (85 wt% SRGO, 15 wt% LCO <= 20 wt% cap), 33.8 API, 1.35 wt% S
    rate_bbl_day = 42_000.0
    api_feed = 33.8
    sg_feed = 141.5 / (api_feed + 131.5)
    rho_feed = sg_feed * RHO_W_60F
    m_feed_t_day = rate_bbl_day * C_BBL_M3 * rho_feed / 1000.0
    sr_wt = 0.85
    lco_wt = 0.15
    s_feed_wt = 0.0135

    # Hydrogen balance (EQ-07): SRGO 0.55 wt% H2, LCO 1.15 wt% H2, purge/dissolved 0.12 wt%
    c_h2_sr = 0.0055
    c_h2_lco = 0.0115
    c_h2_blend = sr_wt * c_h2_sr + lco_wt * c_h2_lco
    chem_h2_t_day = m_feed_t_day * c_h2_blend
    purge_h2_t_day = m_feed_t_day * 0.0012
    makeup_h2_t_day = chem_h2_t_day + purge_h2_t_day

    # Products & exact SI mass + elemental sulfur balance (EQ-02)
    total_in_t_day = m_feed_t_day + makeup_h2_t_day
    m_ulsd_t_day = round(m_feed_t_day * 0.9625, 6)
    ulsd_sulfur_ppmw = 9.2
    api_ulsd = 36.4
    sg_ulsd = 141.5 / (api_ulsd + 131.5)

    s_in_t_day = m_feed_t_day * s_feed_wt
    s_ulsd_t_day = m_ulsd_t_day * (ulsd_sulfur_ppmw * 1e-6)
    s_h2s_t_day = s_in_t_day - s_ulsd_t_day
    h2s_t_day = s_h2s_t_day * (MW_H2S / MW_S)

    m_wild_naphtha_t_day = round(m_feed_t_day * 0.0165, 6)
    m_sour_offgas_t_day = total_in_t_day - m_ulsd_t_day - m_wild_naphtha_t_day

    # Counter-current feed/effluent exchanger train E-201A -> E-201B -> E-201C (tube: feed, shell: effluent)
    m_tube = 67.5  # kg/s (combined liquid feed + recycle gas)
    cp_tube = 2.65  # kJ/(kg*K)
    m_shell = 68.4  # kg/s (reactor effluent incl. quench gas)
    cp_shell = 2.75  # kJ/(kg*K)

    dt_tube = 72.0  # C per shell (62 -> 134 -> 206 -> 278 C)
    duty_mw = m_tube * cp_tube * dt_tube / 1000.0
    dt_shell = (duty_mw * 1000.0) / (m_shell * cp_shell)

    shell_in_c = 374.0
    shell_mid_bc = shell_in_c - dt_shell
    shell_mid_ab = shell_mid_bc - dt_shell
    shell_out_a = shell_mid_ab - dt_shell

    exchangers = [
        ExchangerThermalBasis(
            tag="E-201A",
            tube_mass_kg_s=m_tube,
            tube_cp_kj_kg_k=cp_tube,
            tube_in_c=62.0,
            tube_out_c=134.0,
            shell_mass_kg_s=m_shell,
            shell_cp_kj_kg_k=cp_shell,
            shell_in_c=round(shell_mid_ab, 4),
            shell_out_c=round(shell_out_a, 4),
            duty_mw=round(duty_mw, 4),
        ),
        ExchangerThermalBasis(
            tag="E-201B",
            tube_mass_kg_s=m_tube,
            tube_cp_kj_kg_k=cp_tube,
            tube_in_c=134.0,
            tube_out_c=206.0,
            shell_mass_kg_s=m_shell,
            shell_cp_kj_kg_k=cp_shell,
            shell_in_c=round(shell_mid_bc, 4),
            shell_out_c=round(shell_mid_ab, 4),
            duty_mw=round(duty_mw, 4),
        ),
        ExchangerThermalBasis(
            tag="E-201C",
            tube_mass_kg_s=m_tube,
            tube_cp_kj_kg_k=cp_tube,
            tube_in_c=206.0,
            tube_out_c=278.0,
            shell_mass_kg_s=m_shell,
            shell_cp_kj_kg_k=cp_shell,
            shell_in_c=round(shell_in_c, 4),
            shell_out_c=round(shell_mid_bc, 4),
            duty_mw=round(duty_mw, 4),
        ),
    ]

    # Reactors R-201 (guard) and R-202 (two beds with recycle-gas quench between beds)
    bed1_mass = 67.5
    proc_cp = 2.75
    quench_cp = 11.4
    quench_t = 52.0
    b1_out = 368.0
    b2_in = 352.0
    quench_mass = (bed1_mass * proc_cp * (b1_out - b2_in)) / (quench_cp * (b2_in - quench_t))

    reactors = ReactorThermalBasis(
        r201_in_c=332.0,
        r201_out_c=346.0,
        r202_bed1_in_c=346.0,
        r202_bed1_out_c=b1_out,
        r202_bed2_in_c=b2_in,
        r202_bed2_out_c=374.0,
        bed1_out_mass_kg_s=bed1_mass,
        process_cp_kj_kg_k=proc_cp,
        quench_mass_kg_s=round(quench_mass, 6),
        quench_cp_kj_kg_k=quench_cp,
        quench_temp_c=quench_t,
    )

    # Charge pumps P-201A/B (one operating, one spare)
    vol_flow_m3_s = rate_bbl_day * C_BBL_M3 / 86_400.0
    p_suct = 4.5
    p_disch = 98.5
    eta_h = 0.76
    w_pump_kw = (vol_flow_m3_s * (p_disch - p_suct) * 1e5) / (eta_h * 1000.0)

    charge_pump = ChargePumpBasis(
        tags=["P-201A", "P-201B"],
        suction_barg=p_suct,
        discharge_barg=p_disch,
        vol_flow_m3_s=round(vol_flow_m3_s, 6),
        hydraulic_efficiency=eta_h,
        shaft_power_kw=round(w_pump_kw, 3),
    )

    # Recycle gas centrifugal compressor K-201 (GPSA polytropic EQ-05)
    k_suct = 74.0
    k_disch = 96.0
    k_t1_c = 48.0
    k_mw = 5.2  # g/mol (85 mol% H2, 15 mol% C1-C3)
    gamma_k = 1.36
    z_avg = 1.035
    eta_p = 0.79
    eta_m = 0.97
    m_comp = 4.85  # kg/s
    n_exp = (gamma_k / (gamma_k - 1.0)) * eta_p
    p1_abs = k_suct + 1.01325
    p2_abs = k_disch + 1.01325
    t1_k = k_t1_c + 273.15
    hp_j_kg = (
        (z_avg * R_UNIVERSAL * t1_k / (k_mw / 1000.0))
        * n_exp
        * ((p2_abs / p1_abs) ** (1.0 / n_exp) - 1.0)
    )
    w_comp_kw = (m_comp * hp_j_kg) / (eta_p * eta_m * 1000.0)

    recycle_comp = RecycleCompressorBasis(
        tag="K-201",
        suction_barg=k_suct,
        discharge_barg=k_disch,
        suction_temp_c=k_t1_c,
        gas_mw_g_mol=k_mw,
        gamma_k=gamma_k,
        z_avg=z_avg,
        polytropic_efficiency=eta_p,
        mechanical_efficiency=eta_m,
        mass_flow_kg_s=m_comp,
        polytropic_head_kj_kg=round(hp_j_kg / 1000.0, 4),
        shaft_power_kw=round(w_comp_kw, 3),
    )

    return ProcessBasis(
        event_id="TAR-200-2028",
        unit="Unit 200 Diesel Hydrotreater",
        feed=FeedBasis(
            rate_bbl_day=rate_bbl_day,
            api_gravity=api_feed,
            sg_60_60=round(sg_feed, 6),
            rho_ref_kg_m3=round(rho_feed, 4),
            mass_rate_t_day=round(m_feed_t_day, 6),
            sr_wt_fraction=sr_wt,
            lco_wt_fraction=lco_wt,
            sulfur_wt_fraction=s_feed_wt,
        ),
        hydrogen=HydrogenBasis(
            c_h2_sr_wt_fraction=c_h2_sr,
            c_h2_lco_wt_fraction=c_h2_lco,
            chemical_h2_t_day=round(chem_h2_t_day, 6),
            purge_and_dissolved_h2_t_day=round(purge_h2_t_day, 6),
            makeup_h2_t_day=round(makeup_h2_t_day, 6),
            recycle_gas_h2_mol_fraction=0.85,
        ),
        products=ProductsBasis(
            ulsd=UlsdProduct(
                mass_rate_t_day=m_ulsd_t_day,
                api_gravity=api_ulsd,
                sg_60_60=round(sg_ulsd, 6),
                sulfur_ppmw=ulsd_sulfur_ppmw,
                flash_point_c=64.5,
                cetane_number=47.2,
            ),
            wild_naphtha=LightProduct(mass_rate_t_day=m_wild_naphtha_t_day),
            sour_offgas=SourOffgasProduct(
                mass_rate_t_day=round(m_sour_offgas_t_day, 6),
                h2s_t_day=round(h2s_t_day, 6),
            ),
        ),
        feed_effluent_exchangers=exchangers,
        reactors=reactors,
        charge_pump=charge_pump,
        recycle_compressor=recycle_comp,
    )
