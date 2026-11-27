"""Code checks on a Decider response (docs/spikes/decider-matcher.md section 3).

Every verdict has an `outcome` ('proposal', 'abstained' or 'rejected') and a `kind`
that names the rule, so callers never parse the free-text reason. Never an accept.
Compatibility (work type against class) is a phase 4 check. Here the candidates are
preselected, so it doesn't run.
"""
import math

from cases import facts_for
from decider import options

HIGH = 0.8  # provisional, set in phase 4


def _num01(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and 0 <= x <= 1


def _answer(resp, name, opts):
    """Return (answer, None) if well formed, else (None, reason)."""
    answers = resp.get("answers") if isinstance(resp, dict) else None
    a = answers.get(name) if isinstance(answers, dict) else None
    if not isinstance(a, dict) or a.get("type") != "choice":
        return None, f"missing {name} answer"
    probs, conf = a.get("probabilities"), a.get("confidence")
    if not isinstance(a.get("choice"), str) or a["choice"] not in opts:
        return None, f"{name} choice outside options"
    if not isinstance(probs, dict) or set(probs) != set(opts):
        return None, f"{name} probabilities do not match options"
    if not all(_num01(p) for p in probs.values()):
        return None, f"{name} probability outside 0 to 1"
    if abs(sum(probs.values()) - 1) > 0.01:
        return None, f"{name} probabilities do not sum to 1"
    if not _num01(conf):
        return None, f"{name} confidence outside 0 to 1"
    return a, None


def check(resp, case):
    opts = options(case)
    tag, err = _answer(resp, "tag", opts["tag"])
    if err:
        return {"outcome": "rejected", "kind": "malformed", "reason": err}
    if tag["choice"] == "none":
        # Abstention: no proposal, so the evidence answer isn't looked at at all.
        return {"outcome": "abstained", "kind": "none", "reason": "none", "tag": "none",
                "confidence": round(tag["confidence"], 3)}
    ev, err = _answer(resp, "evidence", opts["evidence"])
    if err:
        return {"outcome": "rejected", "kind": "malformed", "reason": err, "tag": tag["choice"]}
    owner = facts_for(case)[ev["choice"]][0]
    if owner != tag["choice"]:
        return {"outcome": "rejected", "kind": "evidence_owner",
                "reason": f"evidence {ev['choice']} belongs to {owner}", "tag": tag["choice"]}
    return {"outcome": "proposal", "kind": "passed", "reason": "passed checks", "tag": tag["choice"],
            "band": "high" if tag["confidence"] >= HIGH else "low",
            "confidence": round(tag["confidence"], 3), "evidence": ev["choice"]}


def usable(verdict, answer_key):
    """True if the verdict is the right usable result: a proposal for the true tag,
    or an abstention when the true answer is none. Rejections never count."""
    if answer_key == "none":
        return verdict["outcome"] == "abstained"
    return verdict["outcome"] == "proposal" and verdict.get("tag") == answer_key
