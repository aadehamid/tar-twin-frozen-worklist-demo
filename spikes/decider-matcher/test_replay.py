"""D8: recorded responses give the same verdicts offline as in the live run."""
import json
import os

from cases import CASES
from checker import check

HERE = os.path.dirname(os.path.abspath(__file__))
BY_ID = {c["id"]: c for c in CASES}


def test_replay_matches_live():
    rec = json.load(open(os.path.join(HERE, "recorded.json")))
    res = json.load(open(os.path.join(HERE, "results.json")))
    live = {(r["case"], r["run"]): r["verdict"] for r in res["D3"]["rows"]}
    expected = {(c["id"], run) for c in CASES for run in range(3)}
    assert {(r["case"], r["run"]) for r in rec} == expected
    assert set(live) == expected
    for r in rec:
        assert r["status"] == 200, f"{r['case']} run {r['run']} was not a 200; rerun before recording"
        assert check(r["response"], BY_ID[r["case"]]) == live[(r["case"], r["run"])]
