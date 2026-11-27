"""K5: checker unit tests with crafted answers. No model, no network."""
import json

from cases import CASES
from checker_inkling import check

C1 = CASES[0]


def ans(tag, evidence, conf=0.9):
    return json.dumps({"tag": tag, "confidence": conf, "reason": "r", "evidence": evidence})


def test_valid_none_abstains_without_fact_check():
    assert check(ans("none", []), C1)["outcome"] == "abstained"
    assert check(ans("none", ["F-FAKE"]), C1)["outcome"] == "abstained"


def test_pick_outside_candidates_rejected():
    assert check(ans("R-202", ["F-E201B-1"]), C1)["reason"] == "pick not in candidates"


def test_unknown_fact_rejected():
    assert check(ans("E-201B", ["F-E201B-1", "F-MADE-UP"]), C1)["outcome"] == "rejected"


def test_facts_of_other_tags_rejected():
    r = check(ans("E-201B", ["F-E201A-1", "F-E201C-2"]), C1)
    assert r["reason"] == "no cited fact belongs to the picked tag"


def test_broken_json_rejected():
    assert check("{tag: E-201B", C1)["outcome"] == "rejected"
    assert check(json.dumps({"tag": "E-201B"}), C1)["outcome"] == "rejected"
    assert check(json.dumps({"tag": "E-201B", "confidence": 2, "reason": "r", "evidence": []}), C1)["outcome"] == "rejected"


def test_wrong_candidate_with_genuine_fact_is_a_proposal():
    r = check(ans("E-201A", ["F-E201A-1"]), C1)
    assert r["outcome"] == "proposal" and r["tag"] != C1["answer"]


def test_correct_pick_is_a_proposal():
    assert check(ans("E-201B", ["F-E201B-1", "F-E201B-2"]), C1)["outcome"] == "proposal"


def test_never_auto_accepts():
    samples = [ans("E-201B", ["F-E201B-1"], 1.0), ans("none", []), "garbage"]
    assert all(check(s, C1)["outcome"] != "accepted" for s in samples)
