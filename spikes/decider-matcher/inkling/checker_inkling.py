"""Code checks on an AI answer, as in matching-showcase.md section 2.
Outcomes: 'proposal', 'abstained' or 'rejected'. Never an automatic accept."""
import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cases import CLASS, facts_for


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str
    confidence: float = Field(ge=0, le=1)
    reason: str
    evidence: list[str]


COMPATIBLE = {  # work type check, kept minimal for the spike
    "shell and tube exchanger", "pressure vessel", "reactor", "pressure relief valve",
}


def check(raw: str, case: dict) -> dict:
    try:
        ans = Answer.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        return {"outcome": "rejected", "reason": f"schema: {type(e).__name__}"}
    if ans.tag == "none":
        return {"outcome": "abstained", "reason": "valid none", "tag": "none"}
    if ans.tag not in case["candidates"]:
        return {"outcome": "rejected", "reason": "pick not in candidates", "tag": ans.tag}
    facts = facts_for(case)
    unknown = [f for f in ans.evidence if f not in facts]
    if unknown:
        return {"outcome": "rejected", "reason": f"unknown fact IDs {unknown}", "tag": ans.tag}
    if not any(facts[f][0] == ans.tag for f in ans.evidence):
        return {"outcome": "rejected", "reason": "no cited fact belongs to the picked tag", "tag": ans.tag}
    if CLASS.get(ans.tag) not in COMPATIBLE:
        return {"outcome": "rejected", "reason": "compatibility", "tag": ans.tag}
    return {"outcome": "proposal", "reason": "passed checks", "tag": ans.tag}
