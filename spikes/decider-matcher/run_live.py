"""Live run of the six cases against OpenRouter's Decisions API.
Run inside `pplx credentials run`. Writes recorded.json and results.json (D1 to D5, D7, D10)."""
import json
import os
import statistics
import sys
import time

import httpx  # not urllib: urllib cannot tunnel through an https:// HTTPS_PROXY and hangs

from cases import CASES
from checker import check
from decider import request

MODEL = os.environ.get("DECIDER_MODEL", "perplexity/pplx-decider-v1.3:free")
URL = "https://openrouter.ai/api/alpha/decisions"
RUNS = 3
HERE = os.path.dirname(os.path.abspath(__file__))
SUFFIX = os.environ.get("RUN_SUFFIX", "")
CLIENT = httpx.Client(timeout=httpx.Timeout(30, connect=10))


def post(body):
    for attempt in range(2):
        t0 = time.time()
        try:
            r = CLIENT.post(URL, json=body)
        except httpx.HTTPError as e:
            return 0, {"error": type(e).__name__}, time.time() - t0, attempt
        if r.status_code == 429 and attempt == 0:
            time.sleep(5)
            continue
        data = r.json() if r.status_code == 200 else {"error": r.text[:300]}
        return r.status_code, data, time.time() - t0, attempt
    return r.status_code, {"error": "429 after retry"}, time.time() - t0, attempt


def alias_version():
    case = CASES[0]
    status, data, _, _ = post(request("~perplexity/pplx-decider-latest", case))
    return data.get("model") if status == 200 else f"http {status}"


recorded, rows = [], []
for case in CASES:
    for run in range(RUNS):
        status, data, secs, retries = post(request(MODEL, case))
        verdict = check(data, case) if status == 200 else {"outcome": "rejected", "reason": f"http {status}"}
        tag = (data.get("answers") or {}).get("tag", {}) if status == 200 else {}
        rec = {"case": case["id"], "run": run, "status": status, "retried_429": retries,
               "response": data, "latency_s": round(secs, 3)}
        recorded.append(rec)
        rows.append({"case": case["id"], "run": run, "status": status, "model": data.get("model"),
                     "verdict": verdict, "probabilities": tag.get("probabilities"),
                     "top_p": max((tag.get("probabilities") or {"": 0}).values()),
                     "correct": verdict.get("tag") == case["answer"], "latency_s": round(secs, 3),
                     "cost": (data.get("usage") or {}).get("cost"), "retried_429": retries})
        print(case["id"], run, status, verdict, f"{secs:.2f}s", flush=True)

d1 = all(r["status"] == 200 and str(r["model"]).startswith("perplexity/pplx-decider-v1.3") for r in rows)
MALFORMED = ("missing ", "outside options", "do not match", "do not sum", "confidence outside")
d2 = all(r["status"] == 200 and not any(m in r["verdict"]["reason"] for m in MALFORMED) for r in rows)
per_case = {c["id"]: sum(r["correct"] for r in rows if r["case"] == c["id"]) for c in CASES}
d4 = all(per_case[c] >= 2 for c in ("C1", "C2", "C3", "C6"))
picks = {c["id"]: {r["verdict"].get("tag") for r in rows if r["case"] == c["id"]} for c in CASES}
spread = {c["id"]: round(max(r["top_p"] for r in rows if r["case"] == c["id"]) -
                         min(r["top_p"] for r in rows if r["case"] == c["id"]), 4) for c in CASES}
d5 = all(len(p) == 1 for p in picks.values())
lat = [r["latency_s"] for r in rows]
results = {
    "model": MODEL,
    "D1": {"status": "PASS" if d1 else "FAIL", "served": sorted({str(r["model"]) for r in rows}),
           "latest_alias_serves": alias_version()},
    "D2": {"status": "PASS" if d2 else "FAIL"},
    "D3": {"status": "RECORD", "rows": [{k: r[k] for k in ("case", "run", "verdict", "probabilities")} for r in rows]},
    "D4": {"status": "PASS" if d4 else "FAIL", "correct_of_3": per_case},
    "D5": {"status": "PASS" if d5 else "FAIL", "picks": {k: sorted(map(str, v)) for k, v in picks.items()},
           "top_p_spread": spread},
    "D7": {"status": "RECORD", "latency_median_s": statistics.median(lat), "latency_max_s": max(lat),
           "cost_usd_total": round(sum(r["cost"] or 0 for r in rows), 6)},
    "D10": {"status": "RECORD", "calls_retried_after_429": sum(r["retried_429"] for r in rows)},
}
json.dump(recorded, open(os.path.join(HERE, f"recorded{SUFFIX}.json"), "w"), indent=1)
json.dump(results, open(os.path.join(HERE, f"results{SUFFIX}.json"), "w"), indent=1)
print(json.dumps({k: v["status"] for k, v in results.items() if k != "model"}))
sys.exit(0 if d1 and d2 and d4 and d5 else 1)
