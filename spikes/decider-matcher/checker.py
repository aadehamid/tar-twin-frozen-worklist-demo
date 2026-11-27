"""Code checks on a Decider response (docs/spikes/decider-matcher.md section 3).
Outcomes: 'proposal' (band high or low), 'abstained' or 'rejected'. Never an accept."""
from cases import facts_for
from decider import options

HIGH = 0.8  # provisional, set in phase 4


def _answer(resp, name, opts):
    a = (resp or {}).get("answers", {}).get(name)
    if not isinstance(a, dict) or a.get("type") != "choice":
        return None, f"missing {name} answer"
    probs, conf = a.get("probabilities"), a.get("confidence")
    if a.get("choice") not in opts:
        return None, f"{name} choice outside options"
    if not isinstance(probs, dict) or set(probs) != set(opts):
        return None, f"{name} probabilities do not match options"
    if abs(sum(probs.values()) - 1) > 0.01:
        return None, f"{name} probabilities do not sum to 1"
    if not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
        return None, f"{name} confidence outside 0 to 1"
    return a, None


def check(resp, case):
    opts = options(case)
    tag, err = _answer(resp, "tag", opts["tag"])
    if err:
        return {"outcome": "rejected", "reason": err}
    ev, err = _answer(resp, "evidence", opts["evidence"])
    if err:
        return {"outcome": "rejected", "reason": err}
    if tag["choice"] == "none":
        return {"outcome": "abstained", "reason": "none", "tag": "none",
                "confidence": round(tag["confidence"], 3)}
    owner = facts_for(case)[ev["choice"]][0]
    if owner != tag["choice"]:
        return {"outcome": "rejected", "reason": f"evidence {ev['choice']} belongs to {owner}",
                "tag": tag["choice"]}
    return {"outcome": "proposal", "reason": "passed checks", "tag": tag["choice"],
            "band": "high" if tag["confidence"] >= HIGH else "low",
            "confidence": round(tag["confidence"], 3), "evidence": ev["choice"]}
