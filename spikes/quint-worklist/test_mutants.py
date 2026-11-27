import pathlib
import re

import pytest

import mutants

SPEC = (pathlib.Path(__file__).resolve().parents[2] / "specs" / "worklist.qnt").read_text()
RULES = set(re.findall(r"^  val (\w+) =", SPEC, re.M))


@pytest.mark.parametrize("m", mutants.MUTANTS, ids=lambda m: m["id"])
def test_each_mutant_changes_the_spec_once(m):
    out = mutants.apply(SPEC, m)
    assert out != SPEC
    assert m["rule"] in RULES


def test_every_rule_has_a_mutant():
    rules = {"ReadOnly", "BaselineFixed", "FreezeExact", "NothingMissed", "HumansDecide",
             "GrowthAddsUp", "Gate"}
    assert rules <= RULES
    assert rules == {m["rule"] for m in mutants.MUTANTS}


def test_ids_are_unique():
    ids = [m["id"] for m in mutants.MUTANTS]
    assert len(ids) == len(set(ids))


def test_apply_refuses_a_missing_or_repeated_snippet():
    with pytest.raises(ValueError):
        mutants.apply("abc", {"id": "x", "old": "zzz", "new": ""})
    with pytest.raises(ValueError):
        mutants.apply("aa", {"id": "x", "old": "a", "new": ""})


def rule_body(spec, rule):
    """The text of a rule definition, from `val Rule =` to the next blank or comment line."""
    lines = spec.splitlines()
    start = next(n for n, l in enumerate(lines) if l.startswith(f"  val {rule} ="))
    body = [lines[start]]
    for l in lines[start + 1:]:
        if not l.strip() or l.startswith("  //") or l.startswith("  val "):
            break
        body.append(l)
    return "\n".join(body)


@pytest.mark.parametrize("m", mutants.MUTANTS, ids=lambda m: m["id"])
def test_a_mutant_does_not_also_change_its_rule(m):
    # A mutant that edits a constant the rule itself reads changes the rule along with the
    # code, and the checker then has nothing to find. That happened once with SYSTEM_METHODS.
    edited = set(re.findall(r"pure val (\w+) =", m["old"]))
    body = rule_body(SPEC, m["rule"])
    assert not any(re.search(rf"\b{n}\b", body) for n in edited), (m["id"], edited)
    assert rule_body(mutants.apply(SPEC, m), m["rule"]) == body
