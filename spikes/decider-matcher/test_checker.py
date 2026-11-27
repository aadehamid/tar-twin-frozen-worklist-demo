"""D6: checker unit tests with crafted Decider responses. No network."""
import copy
import json
import os

import pytest

from cases import CASES
from checker import check, usable
from decider import options

C1 = CASES[0]
HERE = os.path.dirname(os.path.abspath(__file__))


def resp(tag, evidence, conf=0.9):
    def ans(opts, pick, c):
        rest = (1 - 0.9) / (len(opts) - 1)
        return {"type": "choice", "choice": pick, "confidence": c,
                "probabilities": {o: (0.9 if o == pick else rest) for o in opts}}
    o = options(C1)
    return {"answers": {"tag": ans(o["tag"], tag, conf), "evidence": ans(o["evidence"], evidence, 0.9)}}


def test_choice_outside_options_rejected():
    r = resp("E-201B", "F-E201B-1")
    r["answers"]["tag"]["choice"] = "R-202"
    v = check(r, C1)
    assert v["outcome"] == "rejected" and v["kind"] == "malformed"


@pytest.mark.parametrize("bad", [None, {}, [], "x", {"answers": None}, {"answers": []},
                                 {"answers": {"tag": None}}, {"answers": {"tag": "E-201B"}}])
def test_malformed_shapes_rejected_without_raising(bad):
    v = check(bad, C1)
    assert v["outcome"] == "rejected" and v["kind"] == "malformed"


def test_missing_evidence_rejects_a_pick():
    r = resp("E-201B", "F-E201B-1")
    del r["answers"]["evidence"]
    assert check(r, C1)["kind"] == "malformed"


def test_probabilities_must_be_finite_and_in_range():
    r = resp("E-201B", "F-E201B-1")
    p = r["answers"]["tag"]["probabilities"]
    p["E-201A"], p["E-201B"] = -0.5, 1.5 - sum(v for k, v in p.items() if k not in ("E-201A", "E-201B"))
    assert abs(sum(p.values()) - 1) < 1e-9
    assert check(r, C1)["reason"] == "tag probability outside 0 to 1"
    r = resp("E-201B", "F-E201B-1")
    r["answers"]["tag"]["probabilities"]["E-201A"] = float("nan")
    assert check(r, C1)["outcome"] == "rejected"
    r = resp("E-201B", "F-E201B-1")
    r["answers"]["tag"]["probabilities"]["E-201A"] = True
    assert check(r, C1)["outcome"] == "rejected"


def test_bad_sum_rejected():
    r = resp("E-201B", "F-E201B-1")
    r["answers"]["tag"]["probabilities"]["E-201B"] -= 0.1
    assert check(r, C1)["reason"] == "tag probabilities do not sum to 1"


@pytest.mark.parametrize("conf", [1.2, -0.1, float("inf"), "0.9", None, 10**309])
def test_bad_confidence_rejected(conf):
    assert check(resp("E-201B", "F-E201B-1", conf=conf), C1)["outcome"] == "rejected"


def test_none_abstains_with_other_owner_evidence():
    assert check(resp("none", "F-E201A-1"), C1)["outcome"] == "abstained"


def test_none_abstains_with_missing_or_broken_evidence():
    r = resp("none", "F-E201A-1")
    del r["answers"]["evidence"]
    assert check(r, C1)["outcome"] == "abstained"
    r = resp("none", "F-E201A-1")
    r["answers"]["evidence"]["choice"] = "F-MADE-UP"
    assert check(r, C1)["outcome"] == "abstained"


def test_evidence_from_other_tag_rejects_pick():
    v = check(resp("E-201B", "F-E201C-2"), C1)
    assert v["outcome"] == "rejected" and v["kind"] == "evidence_owner"


def test_wrong_candidate_with_own_fact_is_a_proposal_but_not_usable():
    v = check(resp("E-201A", "F-E201A-1"), C1)
    assert v["outcome"] == "proposal" and not usable(v, C1["answer"])


def test_rejected_pick_of_true_tag_is_not_usable():
    v = check(resp("E-201B", "F-E201C-2"), C1)
    assert v["tag"] == C1["answer"] and not usable(v, C1["answer"])


def test_bands():
    assert check(resp("E-201B", "F-E201B-1", 0.9), C1)["band"] == "high"
    assert check(resp("E-201B", "F-E201B-1", 0.5), C1)["band"] == "low"


def test_never_accepts():
    samples = [resp("E-201B", "F-E201B-1", 1.0), resp("none", "F-E201A-1"), {}]
    assert all(check(copy.deepcopy(s), C1)["outcome"] in {"proposal", "abstained", "rejected"} for s in samples)


def test_runner_summary_on_failures():
    """The runner's gates must fail, not crash, on rejected or failed calls."""
    from summary import summarize
    rows = []
    for c in CASES:
        for run in range(3):
            if c["id"] == "C1" and run == 0:
                status, data = 500, {"error": "boom"}
            elif c["id"] == "C1":
                status, data = 200, resp("E-201B", "F-E201C-2")  # owner rejection on the true tag
            else:
                status, data = 200, {"answers": None, "model": "perplexity/pplx-decider-v1.3-x"}
            rows.append((c, run, status, data))
    s = summarize(rows, expect_prefix="perplexity/pplx-decider-v1.3")
    assert s["D1"] is False and s["D2"] is False and s["D4"] is False
    assert s["correct_of_3"]["C1"] == 0


def test_huge_json_int_probability_rejected_without_raising():
    r = json.loads(json.dumps(resp("E-201B", "F-E201B-1")).replace('"confidence": 0.9', '"confidence": 1' + "0" * 309, 1))
    assert check(r, C1)["outcome"] == "rejected"
    r = resp("E-201B", "F-E201B-1")
    r["answers"]["tag"]["probabilities"]["E-201A"] = 10**309
    assert check(r, C1)["outcome"] == "rejected"


def test_cost_normalization():
    from summary import cost_of
    assert cost_of({"usage": {"cost": 0.002}}) == 0.002
    for bad in [{}, {"usage": None}, {"usage": {"cost": "abc"}}, {"usage": {"cost": True}},
                {"usage": {"cost": float("nan")}}, {"usage": {"cost": 10**309}}, None]:
        assert cost_of(bad) is None
