"""K7: recorded responses give the same verdicts offline as in the live run."""
import json
import os

import pytest

from cases import CASES
from checker_inkling import check

HERE = os.path.dirname(os.path.abspath(__file__))
BY_ID = {c["id"]: c for c in CASES}


@pytest.mark.parametrize("suffix", [""])
def test_replay_matches_live(suffix):
    rec = json.load(open(os.path.join(HERE, f"recorded{suffix}.json")))
    res = json.load(open(os.path.join(HERE, f"results{suffix}.json")))
    live = {(c, r): v for c, r, v in res["K3"]["verdicts"]}
    assert len(rec) == 18
    for r in rec:
        v = check(r["content"], BY_ID[r["case"]]) if r["content"] is not None else None
        if v is not None:
            assert v == live[(r["case"], r["run"])]
