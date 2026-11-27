"""Live run of the six cases against OpenRouter's Decisions API.
Run inside `pplx credentials run`. Writes recorded.json and results.json."""
import json
import os
import statistics
import sys
import time

import httpx  # not urllib: urllib cannot tunnel through an https:// HTTPS_PROXY and hangs

from cases import CASES
from decider import request
from summary import cost_of, summarize

MODEL = os.environ.get("DECIDER_MODEL", "perplexity/pplx-decider-v1.3:free")
# Prefix the served `model` field must start with. Set it when running the v1.2 fallback (D10).
EXPECT = os.environ.get("DECIDER_EXPECT_PREFIX", "perplexity/pplx-decider-v1.3")
URL = "https://openrouter.ai/api/alpha/decisions"
RUNS = 3
HERE = os.path.dirname(os.path.abspath(__file__))
SUFFIX = os.environ.get("RUN_SUFFIX", "")
CLIENT = httpx.Client(timeout=httpx.Timeout(30, connect=10))


def post(body):
    """Return (status, json_or_error_dict, seconds, retried_429)."""
    retried = 0
    while True:
        t0 = time.time()
        try:
            r = CLIENT.post(URL, json=body)
        except httpx.HTTPError as e:
            return 0, {"error": type(e).__name__}, time.time() - t0, retried
        if r.status_code == 429 and not retried:
            retried = 1
            time.sleep(5)
            continue
        try:
            data = r.json() if r.status_code == 200 else {"error": r.text[:300]}
        except ValueError:
            return r.status_code, {"error": "non-JSON body"}, time.time() - t0, retried
        if not isinstance(data, dict):
            data = {"error": "JSON body is not an object", "body": data}
        return r.status_code, data, time.time() - t0, retried


def alias_version():
    status, data, _, _ = post(request("~perplexity/pplx-decider-latest", CASES[0]))
    return data.get("model") if status == 200 else f"http {status}"


recorded, rows = [], []
for case in CASES:
    for run in range(RUNS):
        status, data, secs, retried = post(request(MODEL, case))
        recorded.append({"case": case["id"], "run": run, "status": status, "retried_429": retried,
                         "response": data, "latency_s": round(secs, 3), "cost": cost_of(data)})
        rows.append((case, run, status, data))
        print(case["id"], run, status, f"{secs:.2f}s", flush=True)

s = summarize(rows, EXPECT)
lat = [r["latency_s"] for r in recorded]
results = {
    "model": MODEL,
    "D1": {"status": "PASS" if s["D1"] else "FAIL", "expect_prefix": EXPECT,
           "served": sorted({str(r["model"]) for r in s["rows"]}), "latest_alias_serves": alias_version()},
    "D2": {"status": "PASS" if s["D2"] else "FAIL"},
    "D3": {"status": "RECORD", "rows": [{k: r[k] for k in ("case", "run", "status", "verdict", "usable")}
                                       for r in s["rows"]]},
    "D4": {"status": "PASS" if s["D4"] else "FAIL", "correct_of_3": s["correct_of_3"]},
    "D5": {"status": "PASS" if s["D5"] else "FAIL", "verdict_signatures": s["verdict_signatures"],
           "top_p_spread": s["top_p_spread"]},
    "D7": {"status": "RECORD", "latency_median_s": statistics.median(lat), "latency_max_s": max(lat),
           "cost_usd_total": round(sum(r["cost"] for r in recorded if r["cost"] is not None), 6),
           "calls_without_cost": sum(r["cost"] is None for r in recorded)},
    "D10": {"status": "RECORD", "calls_retried_after_429": sum(r["retried_429"] for r in recorded)},
}
json.dump(recorded, open(os.path.join(HERE, f"recorded{SUFFIX}.json"), "w"), indent=1)
json.dump(results, open(os.path.join(HERE, f"results{SUFFIX}.json"), "w"), indent=1)
for r in s["rows"]:
    print(r["case"], r["run"], r["verdict"], flush=True)
print(json.dumps({k: v["status"] for k, v in results.items() if k != "model"}))
sys.exit(0 if all(s[k] for k in ("D1", "D2", "D4", "D5")) else 1)
