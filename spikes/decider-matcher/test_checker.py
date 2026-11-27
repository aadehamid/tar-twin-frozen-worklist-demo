"""D6: checker unit tests with crafted Decider responses. No network."""
import copy

from cases import CASES
from checker import check
from decider import options

C1 = CASES[0]


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
    assert check(r, C1)["reason"] == "tag choice outside options"


def test_missing_answer_rejected():
    r = resp("E-201B", "F-E201B-1")
    del r["answers"]["evidence"]
    assert check(r, C1)["outcome"] == "rejected"
    assert check({}, C1)["outcome"] == "rejected"
    assert check(None, C1)["outcome"] == "rejected"


def test_bad_probabilities_rejected():
    r = resp("E-201B", "F-E201B-1")
    r["answers"]["tag"]["probabilities"]["E-201B"] -= 0.1
    assert check(r, C1)["reason"] == "tag probabilities do not sum to 1"


def test_bad_confidence_rejected():
    assert check(resp("E-201B", "F-E201B-1", conf=1.2), C1)["outcome"] == "rejected"


def test_none_abstains_even_with_other_evidence():
    assert check(resp("none", "F-E201A-1"), C1)["outcome"] == "abstained"


def test_evidence_from_other_tag_rejects_pick():
    r = check(resp("E-201B", "F-E201C-2"), C1)
    assert r["outcome"] == "rejected" and "belongs to E-201C" in r["reason"]


def test_wrong_candidate_with_own_fact_is_a_proposal():
    r = check(resp("E-201A", "F-E201A-1"), C1)
    assert r["outcome"] == "proposal" and r["tag"] != C1["answer"]


def test_bands():
    assert check(resp("E-201B", "F-E201B-1", 0.9), C1)["band"] == "high"
    assert check(resp("E-201B", "F-E201B-1", 0.5), C1)["band"] == "low"


def test_never_accepts():
    samples = [resp("E-201B", "F-E201B-1", 1.0), resp("none", "F-E201A-1"), {}]
    assert all(check(copy.deepcopy(s), C1)["outcome"] in {"proposal", "abstained", "rejected"} for s in samples)
