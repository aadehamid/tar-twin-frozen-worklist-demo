// Freeze, sync, change and review workflow of the frozen work list demo.
// IMPACT Web is the system of record. The twin reads it through syncs and never writes to it.
// Rules checked are in docs/verification.md section 4. Run with spikes/quint-worklist/run_spike.py.
module worklist {
  // Small bounds keep the state space finite for TLC and quick for Apalache.
  pure val ITEMS = Set(1, 2)
  pure val CHANGES = Set(1, 2)
  pure val HOURS = Set(0, 4, 8)
  pure val DELTAS = Set(-4, 4)
  pure val MAX_SYNCS = 3
  pure val MAX_VERSION = 3            // edits and approvals per request, to keep versions finite
  pure val GATE_PCT = 50
  pure val METHODS = Set("exact", "rule_high", "rule_low", "ai")
  pure val SYSTEM_METHODS = Set("exact", "rule_high")

  type Change = { item: int, base: int, target: int, delta: int, status: str }
  type Match = { state: str, method: str, by: str }
  type Sync = { id: int, lo: int, hi: int, frozen: bool, copy: int -> int }
  type IwState = { hours: int -> int, version: int -> int, drb: int -> bool, frozen: bool,
                   copy: int -> int, changes: int -> Change, pos: int -> int, len: int }

  // IMPACT Web
  var iw_hours: int -> int            // live estimate per request, 0 means not on the list
  var iw_version: int -> int          // bumps on every committed edit
  var iw_drb: int -> bool             // final DRB accept on the current version
  var iw_frozen: bool
  var iw_copy: int -> int             // the frozen copy, written once at freeze
  var iw_changes: int -> Change       // change requests after freeze, status none until raised
  var iw_pos: int -> int              // the change feed: position of each approved change, 1-based, 0 if not in it
  var iw_len: int                     // feed length

  // Twin
  var tw_baseline: int -> int
  var tw_has_baseline: bool
  var tw_cursor: int                  // feed position read up to
  var tw_events: int -> int           // change events per change request
  var tw_growth: int                  // scope growth in hours
  var tw_inflight: Set[Sync]          // syncs started and not finished
  var tw_syncs: int                   // syncs started so far
  var tw_match: int -> Match
  var tw_ready: bool

  // Ghost state, only for stating the step rules
  var g_actor: str
  var g_prev_iw: IwState
  var g_prev_baseline: int -> int
  var g_prev_has_baseline: bool
  var g_freeze_hours: int -> int      // live hours at the moment of freeze

  val iw_state: IwState = { hours: iw_hours, version: iw_version, drb: iw_drb, frozen: iw_frozen,
                            copy: iw_copy, changes: iw_changes, pos: iw_pos, len: iw_len }

  pure def max(a: int, b: int): int = if (a > b) a else b
  pure def sumDelta(cs: Set[int], chg: int -> Change): int = cs.fold(0, (acc, c) => acc + chg.get(c).delta)

  val frozenItems = ITEMS.filter(i => tw_baseline.get(i) > 0)
  val acceptedFrozen = frozenItems.filter(i => tw_match.get(i).state == "accepted")
  val gateOk = frozenItems.size() > 0 and acceptedFrozen.size() * 100 >= GATE_PCT * frozenItems.size()
  // Changes at feed indexes lo to hi - 1, counting from 0
  def logIds(lo: int, hi: int): Set[int] = CHANGES.filter(c => iw_pos.get(c) > lo and iw_pos.get(c) <= hi)
  val approved = CHANGES.filter(c => iw_changes.get(c).status == "approved")

  action ghost(actor: str): bool = all {
    g_actor' = actor,
    g_prev_iw' = iw_state,
    g_prev_baseline' = tw_baseline,
    g_prev_has_baseline' = tw_has_baseline,
  }

  action iw_unchanged = all {
    iw_hours' = iw_hours, iw_version' = iw_version, iw_drb' = iw_drb, iw_frozen' = iw_frozen,
    iw_copy' = iw_copy, iw_changes' = iw_changes, iw_pos' = iw_pos, iw_len' = iw_len,
  }

  action tw_unchanged = all {
    tw_baseline' = tw_baseline, tw_has_baseline' = tw_has_baseline, tw_cursor' = tw_cursor,
    tw_events' = tw_events, tw_growth' = tw_growth, tw_inflight' = tw_inflight,
    tw_syncs' = tw_syncs, tw_match' = tw_match, tw_ready' = tw_ready,
  }

  action init = all {
    iw_hours' = ITEMS.mapBy(i => 0),
    iw_version' = ITEMS.mapBy(i => 0),
    iw_drb' = ITEMS.mapBy(i => false),
    iw_frozen' = false,
    iw_copy' = ITEMS.mapBy(i => 0),
    iw_changes' = CHANGES.mapBy(c => { item: 1, base: 0, target: 0, delta: 0, status: "none" }),
    iw_pos' = CHANGES.mapBy(c => 0),
    iw_len' = 0,
    tw_baseline' = ITEMS.mapBy(i => 0),
    tw_has_baseline' = false,
    tw_cursor' = 0,
    tw_events' = CHANGES.mapBy(c => 0),
    tw_growth' = 0,
    tw_inflight' = Set(),
    tw_syncs' = 0,
    tw_match' = ITEMS.mapBy(i => { state: "none", method: "", by: "" }),
    tw_ready' = false,
    g_actor' = "init",
    g_prev_iw' = { hours: ITEMS.mapBy(i => 0), version: ITEMS.mapBy(i => 0),
                   drb: ITEMS.mapBy(i => false), frozen: false, copy: ITEMS.mapBy(i => 0),
                   changes: CHANGES.mapBy(c => { item: 1, base: 0, target: 0, delta: 0, status: "none" }),
                   pos: CHANGES.mapBy(c => 0), len: 0 },
    g_prev_baseline' = ITEMS.mapBy(i => 0),
    g_prev_has_baseline' = false,
    g_freeze_hours' = ITEMS.mapBy(i => 0),
  }

  // IMPACT Web steps

  // Before freeze, planners edit requests directly. An edit clears the DRB decision.
  action iw_edit(i: int, h: int): bool = all {
    not(iw_frozen), h != iw_hours.get(i), iw_version.get(i) < MAX_VERSION,
    iw_hours' = iw_hours.set(i, h),
    iw_version' = iw_version.set(i, iw_version.get(i) + 1),
    iw_drb' = iw_drb.set(i, false),
    iw_frozen' = iw_frozen, iw_copy' = iw_copy, iw_changes' = iw_changes, iw_pos' = iw_pos, iw_len' = iw_len,
    tw_unchanged, ghost("iw"), g_freeze_hours' = g_freeze_hours,
  }

  action iw_drb_accept(i: int): bool = all {
    not(iw_frozen), iw_hours.get(i) > 0, not(iw_drb.get(i)),
    iw_drb' = iw_drb.set(i, true),
    iw_hours' = iw_hours, iw_version' = iw_version, iw_frozen' = iw_frozen, iw_copy' = iw_copy,
    iw_changes' = iw_changes, iw_pos' = iw_pos, iw_len' = iw_len,
    tw_unchanged, ghost("iw"), g_freeze_hours' = g_freeze_hours,
  }

  // Freeze copies the DRB-accepted requests. Nothing about the twin's gate is consulted.
  action iw_freeze = all {
    not(iw_frozen),
    iw_frozen' = true,
    iw_copy' = ITEMS.mapBy(i => if (iw_drb.get(i)) iw_hours.get(i) else 0),
    iw_hours' = iw_hours, iw_version' = iw_version, iw_drb' = iw_drb,
    iw_changes' = iw_changes, iw_pos' = iw_pos, iw_len' = iw_len,
    tw_unchanged, ghost("iw"), g_freeze_hours' = iw_hours,
  }

  // After freeze every change is a change request against the request's current version.
  action iw_raise(c: int, i: int, d: int): bool = all {
    iw_frozen, iw_changes.get(c).status == "none", iw_hours.get(i) + d >= 0,
    iw_changes' = iw_changes.set(c, { item: i, base: iw_version.get(i),
                                      target: iw_hours.get(i) + d, delta: d, status: "pending" }),
    iw_hours' = iw_hours, iw_version' = iw_version, iw_drb' = iw_drb, iw_frozen' = iw_frozen,
    iw_copy' = iw_copy, iw_pos' = iw_pos, iw_len' = iw_len,
    tw_unchanged, ghost("iw"), g_freeze_hours' = g_freeze_hours,
  }

  // Approval commits only if the request is still at the change's base version.
  action iw_approve(c: int): bool = {
    val ch = iw_changes.get(c)
    all {
      ch.status == "pending",
      iw_version.get(ch.item) == ch.base,
      iw_changes' = iw_changes.set(c, { ...ch, status: "approved" }),
      iw_hours' = iw_hours.set(ch.item, ch.target),
      iw_version' = iw_version.set(ch.item, iw_version.get(ch.item) + 1),
      iw_pos' = iw_pos.set(c, iw_len + 1),
      iw_len' = iw_len + 1,
      iw_drb' = iw_drb, iw_frozen' = iw_frozen, iw_copy' = iw_copy,
      tw_unchanged, ghost("iw"), g_freeze_hours' = g_freeze_hours,
    }
  }

  action iw_reject(c: int): bool = all {
    iw_changes.get(c).status == "pending",
    iw_changes' = iw_changes.set(c, { ...iw_changes.get(c), status: "rejected" }),
    iw_hours' = iw_hours, iw_version' = iw_version, iw_drb' = iw_drb, iw_frozen' = iw_frozen,
    iw_copy' = iw_copy, iw_pos' = iw_pos, iw_len' = iw_len,
    tw_unchanged, ghost("iw"), g_freeze_hours' = g_freeze_hours,
  }

  // Twin steps. Each one reads IMPACT Web and leaves it as it was.

  // A sync reads the feed position and the frozen copy when it starts. Syncs can overlap.
  action tw_sync_start = all {
    tw_syncs < MAX_SYNCS,
    tw_inflight' = tw_inflight.union(Set({ id: tw_syncs, lo: tw_cursor, hi: iw_len,
                                           frozen: iw_frozen, copy: iw_copy })),
    tw_syncs' = tw_syncs + 1,
    tw_baseline' = tw_baseline, tw_has_baseline' = tw_has_baseline, tw_cursor' = tw_cursor,
    tw_events' = tw_events, tw_growth' = tw_growth, tw_match' = tw_match, tw_ready' = tw_ready,
    iw_unchanged, ghost("twin"), g_freeze_hours' = g_freeze_hours,
  }

  // Finishing applies the feed entries it read. Events are keyed by change ID, so an entry two
  // overlapping syncs both read becomes one event, and the cursor only moves forward.
  action tw_sync_finish(s: Sync): bool = {
    val ids = logIds(s.lo, s.hi)
    val fresh = ids.filter(c => tw_events.get(c) == 0)
    all {
      tw_inflight.contains(s),
      tw_inflight' = tw_inflight.exclude(Set(s)),
      if (s.frozen and not(tw_has_baseline))
        all { tw_baseline' = s.copy, tw_has_baseline' = true }
      else
        all { tw_baseline' = tw_baseline, tw_has_baseline' = tw_has_baseline },
      tw_events' = CHANGES.mapBy(c => if (ids.contains(c)) 1 else tw_events.get(c)),
      tw_growth' = tw_growth + sumDelta(fresh, iw_changes),
      tw_cursor' = max(tw_cursor, s.hi),
      tw_syncs' = tw_syncs, tw_match' = tw_match, tw_ready' = tw_ready,
      iw_unchanged, ghost("twin"), g_freeze_hours' = g_freeze_hours,
    }
  }

  action tw_propose(i: int, m: str): bool = all {
    tw_has_baseline, tw_baseline.get(i) > 0, tw_match.get(i).state == "none",
    tw_match' = tw_match.set(i, { state: "proposed", method: m, by: "" }),
    tw_baseline' = tw_baseline, tw_has_baseline' = tw_has_baseline, tw_cursor' = tw_cursor,
    tw_events' = tw_events, tw_growth' = tw_growth, tw_inflight' = tw_inflight,
    tw_syncs' = tw_syncs, tw_ready' = tw_ready,
    iw_unchanged, ghost("twin"), g_freeze_hours' = g_freeze_hours,
  }

  // Code accepts on its own only exact and high-scoring rule matches, and says so in the trace.
  action tw_system_accept(i: int): bool = all {
    tw_match.get(i).state == "proposed", SYSTEM_METHODS.contains(tw_match.get(i).method),
    tw_match' = tw_match.set(i, { ...tw_match.get(i), state: "accepted", by: "system" }),
    tw_baseline' = tw_baseline, tw_has_baseline' = tw_has_baseline, tw_cursor' = tw_cursor,
    tw_events' = tw_events, tw_growth' = tw_growth, tw_inflight' = tw_inflight,
    tw_syncs' = tw_syncs, tw_ready' = tw_ready,
    iw_unchanged, ghost("twin"), g_freeze_hours' = g_freeze_hours,
  }

  action tw_review_accept(i: int): bool = all {
    tw_match.get(i).state == "proposed",
    tw_match' = tw_match.set(i, { ...tw_match.get(i), state: "accepted", by: "reviewer" }),
    tw_baseline' = tw_baseline, tw_has_baseline' = tw_has_baseline, tw_cursor' = tw_cursor,
    tw_events' = tw_events, tw_growth' = tw_growth, tw_inflight' = tw_inflight,
    tw_syncs' = tw_syncs, tw_ready' = tw_ready,
    iw_unchanged, // review_accept only reads IMPACT Web
    ghost("twin"), g_freeze_hours' = g_freeze_hours,
  }

  action tw_review_reject(i: int): bool = all {
    tw_match.get(i).state == "proposed",
    tw_match' = tw_match.set(i, { state: "none", method: "", by: "" }),
    tw_baseline' = tw_baseline, tw_has_baseline' = tw_has_baseline, tw_cursor' = tw_cursor,
    tw_events' = tw_events, tw_growth' = tw_growth, tw_inflight' = tw_inflight,
    tw_syncs' = tw_syncs, tw_ready' = tw_ready,
    iw_unchanged, ghost("twin"), g_freeze_hours' = g_freeze_hours,
  }

  action tw_mark_ready = all {
    tw_has_baseline, not(tw_ready), gateOk,
    tw_ready' = true,
    tw_baseline' = tw_baseline, tw_has_baseline' = tw_has_baseline, tw_cursor' = tw_cursor,
    tw_events' = tw_events, tw_growth' = tw_growth, tw_inflight' = tw_inflight,
    tw_syncs' = tw_syncs, tw_match' = tw_match,
    iw_unchanged, ghost("twin"), g_freeze_hours' = g_freeze_hours,
  }

  action step = any {
    nondet i = ITEMS.oneOf()
    nondet h = HOURS.oneOf()
    iw_edit(i, h),
    nondet i = ITEMS.oneOf()
    iw_drb_accept(i),
    iw_freeze,
    nondet c = CHANGES.oneOf()
    nondet i = ITEMS.oneOf()
    nondet d = DELTAS.oneOf()
    iw_raise(c, i, d),
    nondet c = CHANGES.oneOf()
    iw_approve(c),
    nondet c = CHANGES.oneOf()
    iw_reject(c),
    tw_sync_start,
    all { tw_inflight.size() > 0, nondet s = tw_inflight.oneOf() tw_sync_finish(s) },
    nondet i = ITEMS.oneOf()
    nondet m = METHODS.oneOf()
    tw_propose(i, m),
    nondet i = ITEMS.oneOf()
    tw_system_accept(i),
    nondet i = ITEMS.oneOf()
    tw_review_accept(i),
    nondet i = ITEMS.oneOf()
    tw_review_reject(i),
    tw_mark_ready,
  }

  // Rules from verification.md section 4

  // Read only. No twin step changes IMPACT Web state.
  val ReadOnly = g_actor == "twin" implies iw_state == g_prev_iw

  // Baseline fixed. Once the twin has a baseline, no step changes it.
  val BaselineFixed = g_prev_has_baseline implies (tw_has_baseline and tw_baseline == g_prev_baseline)

  // Freeze is exact. The twin baseline equals IMPACT Web's frozen copy.
  val FreezeExact = tw_has_baseline implies (iw_frozen and tw_baseline == iw_copy)

  // Nothing missed. The feed holds each approved change once. The twin has exactly one event
  // for each feed entry it has read up to, and none for anything else, however syncs overlap.
  // So once a sync catches up with the feed, every approved change is one event.
  val NothingMissed = and {
    iw_len == approved.size(),
    CHANGES.forall(c => (iw_pos.get(c) > 0) iff approved.contains(c)),
    approved.forall(c => iw_pos.get(c) <= iw_len),
    approved.forall(c => approved.forall(d => c != d implies iw_pos.get(c) != iw_pos.get(d))),
    tw_cursor <= iw_len,
    CHANGES.forall(c => tw_events.get(c) <= 1),
    CHANGES.forall(c => (tw_events.get(c) == 1) iff logIds(0, tw_cursor).contains(c)),
  }

  // Humans decide. An accepted match is either reviewer-accepted, or system-accepted and exact
  // or high-scoring rule. So an AI proposal is never accepted without a reviewer. The allowed
  // methods are written out here and not taken from SYSTEM_METHODS, so a change to what the
  // code may accept can't quietly change the rule as well.
  val HumansDecide = ITEMS.forall(i => tw_match.get(i).state == "accepted" implies
    (tw_match.get(i).by == "reviewer" or
     (tw_match.get(i).by == "system" and Set("exact", "rule_high").contains(tw_match.get(i).method))))

  // Growth adds up. Twin growth is the sum of the deltas of the changes it has events for, all
  // approved. In IMPACT Web, each request's live hours are its hours at freeze plus the deltas
  // of its approved changes, so pending and rejected changes add nothing.
  val GrowthAddsUp = and {
    tw_growth == sumDelta(CHANGES.filter(c => tw_events.get(c) > 0), iw_changes),
    CHANGES.forall(c => tw_events.get(c) > 0 implies iw_changes.get(c).status == "approved"),
    iw_frozen implies ITEMS.forall(i => iw_hours.get(i) ==
      g_freeze_hours.get(i) + sumDelta(approved.filter(c => iw_changes.get(c).item == i), iw_changes)),
  }

  // Gate. The baseline is marked ready only when the match rate on frozen items passes.
  val Gate = tw_ready implies gateOk

  val AllRules = ReadOnly and BaselineFixed and FreezeExact and NothingMissed and HumansDecide
    and GrowthAddsUp and Gate

  // Witnesses. Each must be reachable, or the rules above could hold only because the steps
  // that would break them never run.
  val ObsOverlap = tw_inflight.size() >= 2
  val ObsLateAddSynced = CHANGES.exists(c => tw_events.get(c) == 1 and iw_changes.get(c).delta > 0
    and iw_copy.get(iw_changes.get(c).item) == 0)
  // The replay example for phase 4: one request frozen, a late add on the other one synced.
  val ObsLateAddWithFrozenItem = ObsLateAddSynced and tw_has_baseline
    and ITEMS.exists(i => tw_baseline.get(i) > 0)
  val ObsNegativeGrowth = tw_growth < 0
  val ObsStaleChangeBlocked = CHANGES.exists(c => iw_changes.get(c).status == "pending"
    and iw_version.get(iw_changes.get(c).item) != iw_changes.get(c).base)
  val ObsAiReviewed = ITEMS.exists(i => tw_match.get(i).state == "accepted"
    and tw_match.get(i).method == "ai" and tw_match.get(i).by == "reviewer")
  val ObsReady = tw_ready
  val ObsFrozenNotReadyWithGrowth = iw_frozen and not(tw_ready) and tw_growth != 0
}
