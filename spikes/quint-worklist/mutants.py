"""Seeded bugs for the Quint spike. Each one replaces one exact snippet of specs/worklist.qnt and
must make the model checker find a counterexample to the rule it names. A rule no mutant can
break would be a rule the checks never exercise."""

MUTANTS = [
    {"id": "Q-M1", "rule": "ReadOnly",
     "what": "a twin review step changes the IMPACT Web request it matched",
     "old": "    iw_unchanged, // review_accept only reads IMPACT Web\n",
     "new": "    all { iw_hours' = iw_hours.set(i, iw_hours.get(i) + 1), iw_version' = iw_version,\n"
            "          iw_drb' = iw_drb, iw_frozen' = iw_frozen, iw_copy' = iw_copy,\n"
            "          iw_changes' = iw_changes, iw_pos' = iw_pos, iw_len' = iw_len },\n"},
    {"id": "Q-M2", "rule": "BaselineFixed",
     "what": "a sync applies approved change deltas to the baseline",
     "old": "      else\n        all { tw_baseline' = tw_baseline, tw_has_baseline' = tw_has_baseline },\n",
     "new": "      else\n        all { tw_baseline' = ITEMS.mapBy(i => tw_baseline.get(i)\n"
            "                + sumDelta(fresh.filter(c => iw_changes.get(c).item == i), iw_changes)),\n"
            "              tw_has_baseline' = tw_has_baseline },\n"},
    {"id": "Q-M3", "rule": "FreezeExact",
     "what": "a sync builds the baseline from the live requests instead of the frozen copy",
     "old": "frozen: iw_frozen, copy: iw_copy })),",
     "new": "frozen: iw_frozen, copy: iw_hours })),"},
    {"id": "Q-M4", "rule": "NothingMissed",
     "what": "a sync moves its cursor to the feed's current end, not the end it read",
     "old": "      tw_cursor' = max(tw_cursor, s.hi),\n",
     "new": "      tw_cursor' = iw_len,\n"},
    {"id": "Q-M5", "rule": "NothingMissed",
     "what": "events are counted, not keyed by change, so overlapping syncs double them",
     "old": "tw_events' = CHANGES.mapBy(c => if (ids.contains(c)) 1 else tw_events.get(c)),",
     "new": "tw_events' = CHANGES.mapBy(c => if (ids.contains(c)) tw_events.get(c) + 1 else tw_events.get(c)),"},
    {"id": "Q-M6", "rule": "HumansDecide",
     "what": "code accepts an AI proposal on its own",
     "old": "  pure val SYSTEM_METHODS = Set(\"exact\", \"rule_high\")\n",
     "new": "  pure val SYSTEM_METHODS = Set(\"exact\", \"rule_high\", \"ai\")\n"},
    {"id": "Q-M7", "rule": "GrowthAddsUp",
     "what": "a sync counts pending change requests toward growth",
     "old": "      tw_growth' = tw_growth + sumDelta(fresh, iw_changes),\n",
     "new": "      tw_growth' = tw_growth + sumDelta(fresh, iw_changes)\n"
            "        + sumDelta(CHANGES.filter(c => iw_changes.get(c).status == \"pending\"), iw_changes),\n"},
    {"id": "Q-M8", "rule": "Gate",
     "what": "the baseline is marked ready without the match rate gate",
     "old": "    tw_has_baseline, not(tw_ready), gateOk,\n",
     "new": "    tw_has_baseline, not(tw_ready),\n"},
    {"id": "Q-M9", "rule": "GrowthAddsUp",
     "what": "approval skips the base version check, so a stale change overwrites a newer one",
     "old": "      iw_version.get(ch.item) == ch.base,\n",
     "new": ""},
]


def apply(spec_text, mutant):
    """The spec with one mutant applied. Raises if its snippet isn't there exactly once."""
    n = spec_text.count(mutant["old"])
    if n != 1:
        raise ValueError(f"{mutant['id']}: snippet found {n} times")
    return spec_text.replace(mutant["old"], mutant["new"])
