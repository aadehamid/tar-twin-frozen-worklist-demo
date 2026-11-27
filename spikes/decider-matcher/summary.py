"""Turn live rows into the D1, D2, D4 and D5 gates. Pure function, tested offline.

rows: list of (case, run, http_status, response_json).
Gates use structured verdict fields only, never reason text.
"""
from checker import check, usable


def _top_p(data):
    try:
        return max(data["answers"]["tag"]["probabilities"].values())
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def summarize(rows, expect_prefix):
    out_rows = []
    for case, run, status, data in rows:
        if status == 200:
            verdict = check(data, case)
        else:
            verdict = {"outcome": "rejected", "kind": "http", "reason": f"http {status}"}
        model = data.get("model") if isinstance(data, dict) else None
        out_rows.append({"case": case["id"], "run": run, "status": status, "model": model,
                         "verdict": verdict, "usable": usable(verdict, case["answer"]),
                         "top_p": _top_p(data) if verdict["kind"] != "malformed" else None})
    ids = list(dict.fromkeys(r["case"] for r in out_rows))
    by = {i: [r for r in out_rows if r["case"] == i] for i in ids}
    correct = {i: sum(r["usable"] for r in by[i]) for i in ids}
    signatures = {i: sorted({f"{r['verdict']['outcome']}:{r['verdict'].get('tag')}" for r in by[i]}) for i in ids}
    spread = {}
    for i in ids:
        ps = [r["top_p"] for r in by[i] if r["top_p"] is not None]
        spread[i] = round(max(ps) - min(ps), 4) if len(ps) == len(by[i]) else None
    return {
        "rows": out_rows,
        "D1": all(r["status"] == 200 and str(r["model"]).startswith(expect_prefix) for r in out_rows),
        "D2": all(r["status"] == 200 and r["verdict"]["kind"] != "malformed" for r in out_rows),
        "D4": all(correct.get(i, 0) >= 2 for i in ("C1", "C2", "C3", "C6")),
        "D5": all(len(s) == 1 for s in signatures.values()) and all(v is not None for v in spread.values()),
        "correct_of_3": correct,
        "verdict_signatures": signatures,
        "top_p_spread": spread,
    }
