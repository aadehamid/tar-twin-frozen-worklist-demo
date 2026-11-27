"""D8: recorded responses give the same verdicts offline as in the live run."""
import json
import os

import pytest

from cases import CASES
from checker import check

HERE = os.path.dirname(os.path.abspath(__file__))
BY_ID = {c["id"]: c for c in CASES}


@pytest.mark.parametrize("suffix", [""])
def test_replay_matches_live(suffix):
    rec = json.load(open(os.path.join(HERE, f"recorded{suffix}.json")))
    res = json.load(open(os.path.join(HERE, f"results{suffix}.json")))
    live = {(r["case"], r["run"]): r["verdict"] for r in res["D3"]["rows"]}
    assert len(rec) == 18
    for r in rec:
        if r["status"] == 200:
            assert check(r["response"], BY_ID[r["case"]]) == live[(r["case"], r["run"])]
