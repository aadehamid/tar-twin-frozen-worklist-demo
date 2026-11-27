# Scenario spec: Unit 200 diesel hydrotreater

Version 0.1, for review. All names, tags, people, hours and costs here are invented. Counts marked "target" are what the data generator aims for, and the scenario tests check them.

## 1. Why a diesel hydrotreater

A hydrotreater turnaround is usually set by the catalyst cycle. It packs most of the problems the 3.1 MVP is meant to solve into one unit: a high-pressure loop with a large blind list, exchanger bundle pulls that need cranes and laydown, a heater, a recycle gas compressor, a column with tray work at height, and dozens of relief valves. Many jobs share the same isolation and the same scaffold, which is the setting where shared-cost clusters pay off.

## 2. The unit

### 2.1 Process summary

Diesel feed from tankage passes the feed filters into the feed surge drum. The charge pumps lift it to reactor pressure, where it mixes with recycle hydrogen. It is preheated in the feed/effluent exchangers and the charge heater, then goes through the guard reactor and the main reactor. Reactor effluent gives up heat in the feed/effluent exchangers, has wash water injected, and is cooled in the effluent air cooler and trim cooler. It is then separated in the cold high-pressure separator. Gas goes through the amine scrubber to the recycle gas compressor. Liquid drops to the low-pressure separator and on to the product stripper. Stripped diesel is pumped out through the product cooler to tankage. Makeup hydrogen comes in through two makeup compressors.

### 2.2 Major equipment (target: 32 items)

| Area | Tag | Description |
|---|---|---|
| 200-A Feed | FL-201A, FL-201B | Feed filters |
| | D-201 | Feed surge drum |
| | P-201A, P-201B | Charge pumps |
| 200-B Reactor structure | R-201 | Guard reactor |
| | R-202 | Main reactor, two beds with quench |
| 200-C Exchanger bay | E-201A, E-201B, E-201C | Feed/effluent exchangers in series |
| | E-202 | Effluent trim cooler |
| | E-204 | Product cooler |
| 200-D Heater | H-201 | Charge heater, two passes |
| 200-E Separation | A-201 | Effluent air cooler, 4 bays |
| | D-202 | Cold high-pressure separator |
| | D-203 | Low-pressure separator |
| | P-204A, P-204B | Wash water pumps |
| 200-F Gas compression | D-204 | Recycle gas knockout drum |
| | C-202 | Recycle gas amine scrubber |
| | K-201 | Recycle gas compressor, centrifugal |
| | KT-201 | Steam turbine driver for K-201 |
| | D-206 | Makeup gas knockout drum |
| | K-202A, K-202B | Makeup hydrogen compressors, reciprocating |
| 200-G Stripping | C-201 | Product stripper, 30 trays |
| | E-203 | Stripper overhead condenser |
| | D-205 | Stripper overhead drum |
| | P-202A, P-202B | Stripper reflux pumps |
| | P-203A, P-203B | Stripper bottoms pumps |

Supporting tags bring the total to about 400 (target 380 to 450): about 30 PSVs (`PSV-2xxx`), about 120 manual and control valves (`HV-`, `XV-`, `FV-`, `LV-`, `PV-`), about 140 instruments, and the piping segments between them.

### 2.3 P&ID sheets (target: 5)

| Sheet | Title | Covers |
|---|---|---|
| 200-PID-001 | Feed section | FL-201A/B, D-201, P-201A/B |
| 200-PID-002 | Reaction | E-201A/B/C, H-201, R-201, R-202, quench |
| 200-PID-003 | Effluent cooling and separation | A-201, E-202, D-202, D-203, P-204A/B |
| 200-PID-004 | Recycle and makeup gas | D-204, C-202, K-201, KT-201, D-206, K-202A/B |
| 200-PID-005 | Product stripping | C-201, E-203, D-205, P-202A/B, P-203A/B, E-204 |

### 2.4 Isolation envelopes (target: 6)

| Envelope | Contains | Block valve boundary (target) |
|---|---|---|
| ENV-200-01 Feed | FL-201A/B, D-201, P-201A/B suction | 14 |
| ENV-200-02 HP reaction loop | P-201A/B discharge, E-201A/B/C, H-201, R-201, R-202, A-201, E-202, D-202 | 38 |
| ENV-200-03 Recycle gas | D-204, C-202, K-201 | 16 |
| ENV-200-04 Makeup gas | D-206, K-202A/B | 12 |
| ENV-200-05 LP separation | D-203, P-204A/B | 10 |
| ENV-200-06 Stripper | C-201, E-203, D-205, P-202A/B, P-203A/B, E-204 | 22 |

The HP reaction loop is the big one. Every job inside it shares one blind list, which is where most of the isolation cluster saving comes from.

### 2.5 Plot plan

A 2D layout about 120 m by 80 m. A pipe rack runs east to west through the middle. The reactor structure has three levels (grade, 12 m, 24 m). The heater sits at the west end away from the hydrocarbon equipment. The exchanger bay has a bundle-pull area on the north side and a crane pad. The compressor shelter sits on the east side.

## 3. The turnaround event

| Field | Value |
|---|---|
| Event | TAR-200-2028, Unit 200 diesel hydrotreater |
| Site | Demo Refinery (fictional) |
| Driver | Catalyst end of run |
| Planned duration | 28 days, feed out to feed in |
| Candidate list | Target 200 work requests, about 120,000 estimated man-hours, about $28M |
| Budget target at DRB | About $22M. The candidate list is about 27% over target, so about $6M (21% of candidate cost) has to come out or be justified |

### Timeline (illustrative, months before feed out)

| Month | Step |
|---|---|
| T-18 | Candidate list opens. Source groups raise work requests in IMPACT Web |
| T-15 | Fit-to-frame screening |
| T-14 | Scope challenge. Duplicates and low-value items removed, shared setups bundled |
| T-13 | DRB review against the budget target. Cut line set |
| T-12 | Work list frozen. Baseline taken |
| T-12 to T-1 | Late adds and deletes, each logged against the baseline |

The demo clock can jump between these steps. The data behind each step is seeded, so the demo is the same every time.

## 4. The work list

### 4.1 Work request mix (target: 200)

| Category | Count | Typical line in the work list |
|---|---|---|
| Catalyst change-out and reactor internals | 14 | "R-202 MAIN REACTOR: N2 PURGE, UNLOAD CATALYST, INSPECT INTERNALS, RELOAD" |
| Exchanger bundle work | 22 | "E-201B FEED/EFF EXCH: BLIND, OPEN, PULL BUNDLE, HYDROBLAST, TEST, CLOSE" |
| Air cooler | 8 | "A-201 BAY 3: OPEN HEADER PLUGS, CLEAN TUBES, IRIS INSPECTION" |
| Heater | 12 | "H-201 CHARGE HEATER: DECOKE PASS 1 AND 2, TUBE THICKNESS SURVEY" |
| Columns and vessels | 24 | "C-201 STRIPPER: OPEN MANWAYS, INSPECT TRAYS 1-10, REPLACE VALVE TRAYS AS REQUIRED" |
| Rotating equipment | 20 | "K-201 RECYCLE COMPRESSOR: MAJOR OVERHAUL, BEARINGS AND SEALS" |
| Relief valves | 28 | "PSV-2104 ON D-202: REMOVE, BENCH TEST, RECERTIFY, REINSTALL" |
| Valve overhauls | 30 | "XV-2210 REACTOR INLET ISOLATION: OVERHAUL, LEAK TEST" |
| Thickness, CUI and piping inspection | 26 | "LINE 200-P-0412: UT THICKNESS SURVEY, CUI STRIP AND INSPECT AT SUPPORTS" |
| Instruments and analyzers | 10 | "LT-2302 HP SEPARATOR LEVEL: REPLACE TRANSMITTER, CALIBRATE" |
| Capital tie-in | 4 | "TIE-IN T-07 NEW WASH WATER LINE AT E-201A INLET" |
| General prep | 2 | "UNIT 200: STEAM OUT AND CHEMICAL CLEAN HP LOOP" |

Each request carries a driver (inspection, reliability, regulatory, capital, operations), a source group (fixed equipment, rotating, inspection, operations, projects, instrumentation), a RIPT score, an estimate split by craft, and a cost.

### 4.2 How the equipment field is filled (target mix)

The equipment field is free text, as it is in IMPACT Web during the code freeze. The generator fills it in four ways:

| Pattern | Share | Examples |
|---|---|---|
| Clean tag | 40% | `E-201B` |
| Tag variant | 30% | `E201B`, `E-201 B`, `E-201-B`, `200-E-201B` |
| Description only | 20% | "feed eff exchanger middle shell", "south charge pump", "recycle compressor" |
| Vague or wrong | 10% | "HP loop", "unit 200 general", a tag that exists in Unit 300, a retired tag |

Expected match results (targets):

| Stage | Match rate |
|---|---|
| Exact and rules only | about 70% |
| After fuzzy and AI proposals, before review | about 88% proposed |
| After planner review | 96% to 97%, which passes a 95% gate |

The remaining 3% to 4% are the honest "unit general" items that don't belong to one tag. They stay visible on the dashboard.

## 5. Problems planted in the data

These are the problems the workshop described. The demo has to find each one.

| Problem | Target count | How the demo shows it |
|---|---|---|
| Duplicate requests from different source groups for the same work | 9 pairs | Flagged at the scope challenge when two items resolve to the same tag with similar text |
| Shared scaffold | 7 clusters | Jobs on the reactor structure top heads, C-201 manways at the same elevation, A-201 header boxes |
| Shared isolation | 6 envelopes | Jobs inside ENV-200-02 share one blind list, counted once |
| Shared access and lifting | 3 clusters | E-201A/B/C bundle pulls sharing one crane setup and laydown |
| Wrong-unit or retired tags | 4 items | Caught by the match step and sent to review |
| Over budget at DRB | About 27% over target | Cut line by location shows what falls below the line |
| Changes after freeze | 18 adds and 6 deletes approved, plus 5 rejected | Scope growth climbs on the KPI panel, each change with a reason and source group |

Target scope growth after freeze: about 4,000 man-hours from approved changes net of deletes, which is about 3% to 4% of the frozen baseline.

## 6. Value panel

The panel uses the focus-area brief's defaults for 3.1 and labels them as unvalidated assumptions, not results:

| Lever | Default per TAR |
|---|---|
| Shared costs bundled | $1.13M |
| Scope removed or avoided | $0.75M |
| Duration (0.3 days) | $0.60M |
| Planning hours saved (250 hours) | $0.04M |
| Total | about $2.5M |

The demo also shows the counts the data produces (hours bundled, items removed, growth after freeze), so the audience can see what the twin measured separately from what the brief assumes.

## 7. Demo walkthrough (about 10 minutes)

The order follows the 3.1 slide in the MVP proposal.

1. **IMPACT Web (1 min).** Open TAR-200-2028. Show 200 candidate requests, the free-text equipment field and the banner saying the twin reads this system and never writes to it.
2. **Match rate (2 min).** In the twin, run sync. Match rate shows about 70% from exact and rule matches. Run the AI matcher. Open three proposals in the review queue: one clean accept, one where the AI cites DEXPI neighbours to pick E-201B over E-201A, and one wrong-unit tag that gets rejected. Open the mapping trace for one messy entry, "feed eff exchanger middle shell", and show each step from the raw IMPACT Web text to E-201B in the twin. Match rate after review passes the gate.
3. **Scope on the plant (2 min).** The plot plan fills with job markers. Click a job on E-201B. The graph panel runs Cypher in the browser and draws the chain: work request, E-201B, nozzles and piping, block valves, ENV-200-02, and every other job inside it. The P&ID viewer highlights the same envelope on sheet 200-PID-002.
4. **Shared-cost clusters (1.5 min).** Show the isolation, scaffold and access clusters. Hours and cost are counted once per cluster, and the total drops against the summed estimate. Show the 9 duplicate pairs found at the challenge.
5. **Cut line (1.5 min).** Set the DRB budget target. The plant colours above and below the line by location. Move one item across the line and watch the cluster saving change, because pulling one job out of a shared setup doesn't save the shared cost.
6. **Freeze and growth (1.5 min).** Freeze in IMPACT Web. The twin takes a baseline. Run the late-scope simulation. Adds and deletes arrive by sync, each logged with hours and reason. Scope growth in man-hours climbs on the KPI panel.
7. **Value and what's next (0.5 min).** Show the value panel with its unvalidated label. Point to the reserved slots for work packages (4.1) and activities and logistics (4.2).
