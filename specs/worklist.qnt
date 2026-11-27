// Freeze, sync, change and review workflow of the frozen work list demo.
// IMPACT Web is the system of record. The twin reads it through syncs. With write-through on, the
// twin can also raise a change request after freeze through IMPACT Web's own raise step, and
// nothing else. Write-through is a demo choice; decision D9 has the reasons.
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

  type Change = { item: int, base: int, target: int, delta: int, status: str, via: str }
  type Match = { state: str, method: str, by: str }
  type Sync = { id: int, lo: int, hi: int, frozen: bool, copy: int -> int }
  type Fin = { on: bool, lo: int, hi: int }
  type IwState = { hours: int -> int, version: int -> int, drb: int -> bool, drb_ver: int -> int,
                   frozen: bool, copy: int -> int, changes: int -> Change, pos: int -> int, len: int }

  // IMPACT Web
  var iw_hours: int -> int            // live estimate per request, 0 means not on the list
  var iw_version: int -> int          // bumps on every committed edit
  var iw_drb: int -> bool             // final DRB accept on the current version
  var iw_drb_ver: int -> int          // the version the DRB accepted, -1 if never
  var iw_frozen: bool
  var iw_copy: int -> int             // the frozen copy, written once at freeze
  var iw_changes: int -> Change       // change requests after freeze, status none until raised
  // The approval rows of design.md's change_feed. The real feed also carries edits, decisions
  // and the freeze record; only approvals turn into change events, so only they are modelled.
  var iw_pos: int -> int              // feed position of each approved change, 1-based, 0 if not in it
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
  var tw_write_mode: bool            // write-through switch, picked at the start and fixed

  // Ghost state, only for stating the step rules
  var g_actor: str
  var g_prev_iw: IwState
  var g_prev_baseline: int -> int
  var g_prev_has_baseline: bool
  var g_freeze_hours: int -> int      // live hours at the moment of freeze
  var g_freeze_ok: int -> bool        // at freeze, whether the DRB accepted the current version
  var g_prev_cursor: int
  var g_fin: Fin                      // the window of the sync that just finished, on = false otherwise

  val iw_state: IwState = { hours: iw_hours, version: iw_version, drb: iw_drb, drb_ver: iw_drb_ver,
                            frozen: iw_frozen, copy: iw_copy, changes: iw_changes, pos: iw_pos, len: iw_len }
  pure val NO_FIN: Fin = { on: false, lo: 0, hi: 0 }

  pure def max(a: int, b: int): int = if (a > b) a else b
  pure def sumDelta(cs: Set[int], chg: int -> Change): int = cs.fold(0, (acc, c) => acc + chg.get(c).delta)

  val frozenItems = ITEMS.filter(i => tw_baseline.get(i) > 0)
  val acceptedFrozen = frozenItems.filter(i => tw_match.get(i).state == "accepted")
  val gateOk = frozenItems.size() > 0 and acceptedFrozen.size() * 100 >= GATE_PCT * frozenItems.size()
  // Changes at feed indexes lo to hi - 1, counting from 0
  def logIds(lo: int, hi: int): Set[int] = CHANGES.filter(c => iw_pos.get(c) > lo and iw_pos.get(c) <= hi)
  val approved = CHANGES.filter(c => iw_changes.get(c).status == "approved")

  action ghost(actor: str, fin: Fin): bool = all {
    tw_write_mode' = tw_write_mode,     // every step calls ghost, so the switch never changes
    g_actor' = actor,
    g_fin' = fin,
    g_prev_cursor' = tw_cursor,
    g_prev_iw' = iw_state,
    g_prev_baseline' = tw_baseline,
    g_prev_has_baseline' = tw_has_baseline,
  }

  action iw_unchanged = all {
    iw_hours' = iw_hours, iw_version' = iw_version, iw_drb' = iw_drb, iw_drb_ver' = iw_drb_ver,
    iw_frozen' = iw_frozen, iw_copy' = iw_copy, iw_changes' = iw_changes, iw_pos' = iw_pos, iw_len' = iw_len,
  }

  action tw_unchanged = all {
    tw_baseline' = tw_baseline, tw_has_baseline' = tw_has_baseline, tw_cursor' = tw_cursor,
    tw_events' = tw_events, tw_growth' = tw_growth, tw_inflight' = tw_inflight,
    tw_syncs' = tw_syncs, tw_match' = tw_match, tw_ready' = tw_ready,
  }

  action init = {
    nondet w = Set(true, false).oneOf()
    all {
      tw_write_mode' = w,
      iw_hours' = ITEMS.mapBy(i => 0),
      iw_version' = ITEMS.mapBy(i => 0),
      iw_drb' = ITEMS.mapBy(i => false),
      iw_drb_ver' = ITEMS.mapBy(i => -1),
      iw_frozen' = false,
      iw_copy' = ITEMS.mapBy(i => 0),
      iw_changes' = CHANGES.mapBy(c => { item: 1, base: 0, target: 0, delta: 0, status: "none", via: "" }),
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
                     drb: ITEMS.mapBy(i => false), drb_ver: ITEMS.mapBy(i => -1), frozen: false,
                     copy: ITEMS.mapBy(i => 0),
                     changes: CHANGES.mapBy(c => { item: 1, base: 0, target: 0, delta: 0, status: "none", via: "" }),
                     pos: CHANGES.mapBy(c => 0), len: 0 },
      g_prev_baseline' = ITEMS.mapBy(i => 0),
      g_prev_has_baseline' = false,
      g_freeze_hours' = ITEMS.mapBy(i => 0),
      g_freeze_ok' = ITEMS.mapBy(i => false),
      g_prev_cursor' = 0,
      g_fin' = NO_FIN,
    }
  }

  // IMPACT Web steps

  // Before freeze, planners edit requests directly. An edit clears the DRB decision.
  action iw_edit(i: int, h: int): bool = all {
    not(iw_frozen), h != iw_hours.get(i), iw_version.get(i) < MAX_VERSION,
    iw_hours' = iw_hours.set(i, h),
    iw_version' = iw_version.set(i, iw_version.get(i) + 1),
    iw_drb' = iw_drb.set(i, false),
    iw_drb_ver' = iw_drb_ver, iw_frozen' = iw_frozen, iw_copy' = iw_copy, iw_changes' = iw_changes, iw_pos' = iw_pos, iw_len' = iw_len,
    tw_unchanged, ghost("iw", NO_FIN), g_freeze_hours' = g_freeze_hours, g_freeze_ok' = g_freeze_ok,
  }

  action iw_drb_accept(i: int): bool = all {
    not(iw_frozen), iw_hours.get(i) > 0, not(iw_drb.get(i)),
    iw_drb' = iw_drb.set(i, true),
    iw_drb_ver' = iw_drb_ver.set(i, iw_version.get(i)),
    iw_hours' = iw_hours, iw_version' = iw_version, iw_frozen' = iw_frozen, iw_copy' = iw_copy,
    iw_changes' = iw_changes, iw_pos' = iw_pos, iw_len' = iw_len,
    tw_unchanged, ghost("iw", NO_FIN), g_freeze_hours' = g_freeze_hours, g_freeze_ok' = g_freeze_ok,
  }

  // Freeze copies the DRB-accepted requests. Nothing about the twin's gate is consulted.
  action iw_freeze = all {
    not(iw_frozen),
    iw_frozen' = true,
    iw_copy' = ITEMS.mapBy(i => if (iw_drb.get(i)) iw_hours.get(i) else 0),
    iw_hours' = iw_hours, iw_version' = iw_version, iw_drb' = iw_drb, iw_drb_ver' = iw_drb_ver,
    iw_changes' = iw_changes, iw_pos' = iw_pos, iw_len' = iw_len,
    tw_unchanged, ghost("iw", NO_FIN), g_freeze_hours' = iw_hours,
    // What freeze ought to copy, worked out apart from the copy itself: the requests whose
    // current version is the one the DRB accepted.
    g_freeze_ok' = ITEMS.mapBy(i => iw_drb_ver.get(i) == iw_version.get(i)),
  }

  // After freeze every change is a change request against the request's current version.
  action iw_raise(c: int, i: int, d: int): bool = all {
    iw_frozen, iw_changes.get(c).status == "none", iw_hours.get(i) + d >= 0,
    iw_changes' = iw_changes.set(c, { item: i, base: iw_version.get(i),
                                      target: iw_hours.get(i) + d, delta: d, status: "pending", via: "iw" }),
    iw_hours' = iw_hours, iw_version' = iw_version, iw_drb' = iw_drb, iw_drb_ver' = iw_drb_ver,
    iw_frozen' = iw_frozen, iw_copy' = iw_copy, iw_pos' = iw_pos, iw_len' = iw_len,
    tw_unchanged, ghost("iw", NO_FIN), g_freeze_hours' = g_freeze_hours, g_freeze_ok' = g_freeze_ok,
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
      iw_drb' = iw_drb, iw_drb_ver' = iw_drb_ver, iw_frozen' = iw_frozen, iw_copy' = iw_copy,
      tw_unchanged, ghost("iw", NO_FIN), g_freeze_hours' = g_freeze_hours, g_freeze_ok' = g_freeze_ok,
    }
  }

  action iw_reject(c: int): bool = all {
    iw_changes.get(c).status == "pending",
    iw_changes' = iw_changes.set(c, { ...iw_changes.get(c), status: "rejected" }),
    iw_hours' = iw_hours, iw_version' = iw_version, iw_drb' = iw_drb, iw_drb_ver' = iw_drb_ver,
    iw_frozen' = iw_frozen, iw_copy' = iw_copy, iw_pos' = iw_pos, iw_len' = iw_len,
    tw_unchanged, ghost("iw", NO_FIN), g_freeze_hours' = g_freeze_hours, g_freeze_ok' = g_freeze_ok,
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
    iw_unchanged, ghost("twin", NO_FIN), g_freeze_hours' = g_freeze_hours, g_freeze_ok' = g_freeze_ok,
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
      iw_unchanged, ghost("twin", { on: true, lo: s.lo, hi: s.hi }), g_freeze_hours' = g_freeze_hours, g_freeze_ok' = g_freeze_ok,
    }
  }

  action tw_propose(i: int, m: str): bool = all {
    tw_has_baseline, tw_baseline.get(i) > 0, tw_match.get(i).state == "none",
    tw_match' = tw_match.set(i, { state: "proposed", method: m, by: "" }),
    tw_baseline' = tw_baseline, tw_has_baseline' = tw_has_baseline, tw_cursor' = tw_cursor,
    tw_events' = tw_events, tw_growth' = tw_growth, tw_inflight' = tw_inflight,
    tw_syncs' = tw_syncs, tw_ready' = tw_ready,
    iw_unchanged, ghost("twin", NO_FIN), g_freeze_hours' = g_freeze_hours, g_freeze_ok' = g_freeze_ok,
  }

  // Code accepts on its own only exact and high-scoring rule matches, and says so in the trace.
  action tw_system_accept(i: int): bool = all {
    tw_match.get(i).state == "proposed", SYSTEM_METHODS.contains(tw_match.get(i).method),
    tw_match' = tw_match.set(i, { ...tw_match.get(i), state: "accepted", by: "system" }),
    tw_baseline' = tw_baseline, tw_has_baseline' = tw_has_baseline, tw_cursor' = tw_cursor,
    tw_events' = tw_events, tw_growth' = tw_growth, tw_inflight' = tw_inflight,
    tw_syncs' = tw_syncs, tw_ready' = tw_ready,
    iw_unchanged, ghost("twin", NO_FIN), g_freeze_hours' = g_freeze_hours, g_freeze_ok' = g_freeze_ok,
  }

  action tw_review_accept(i: int): bool = all {
    tw_match.get(i).state == "proposed",
    tw_match' = tw_match.set(i, { ...tw_match.get(i), state: "accepted", by: "reviewer" }),
    tw_baseline' = tw_baseline, tw_has_baseline' = tw_has_baseline, tw_cursor' = tw_cursor,
    tw_events' = tw_events, tw_growth' = tw_growth, tw_inflight' = tw_inflight,
    tw_syncs' = tw_syncs, tw_ready' = tw_ready,
    iw_unchanged, // review_accept only reads IMPACT Web
    ghost("twin", NO_FIN), g_freeze_hours' = g_freeze_hours, g_freeze_ok' = g_freeze_ok,
  }

  action tw_review_reject(i: int): bool = all {
    tw_match.get(i).state == "proposed",
    tw_match' = tw_match.set(i, { state: "none", method: "", by: "" }),
    tw_baseline' = tw_baseline, tw_has_baseline' = tw_has_baseline, tw_cursor' = tw_cursor,
    tw_events' = tw_events, tw_growth' = tw_growth, tw_inflight' = tw_inflight,
    tw_syncs' = tw_syncs, tw_ready' = tw_ready,
    iw_unchanged, ghost("twin", NO_FIN), g_freeze_hours' = g_freeze_hours, g_freeze_ok' = g_freeze_ok,
  }

  // With write-through on, a planner raises a change request from the twin. The twin calls
  // IMPACT Web's raise step for the signed-in user, so the request is stamped against the current
  // version and waits for the DRB like any other. The twin can't approve it.
  action tw_raise(c: int, i: int, d: int): bool = all {
    tw_write_mode,
    iw_frozen, iw_changes.get(c).status == "none", iw_hours.get(i) + d >= 0, // the same guards as iw_raise
    iw_changes' = iw_changes.set(c, { item: i, base: iw_version.get(i),
                                      target: iw_hours.get(i) + d, delta: d, status: "pending", via: "twin" }),
    iw_hours' = iw_hours, iw_version' = iw_version, // the raise commits nothing to the request itself
    iw_drb' = iw_drb, iw_drb_ver' = iw_drb_ver, iw_frozen' = iw_frozen, iw_copy' = iw_copy,
    iw_pos' = iw_pos, iw_len' = iw_len,
    tw_unchanged, ghost("twin", NO_FIN), g_freeze_hours' = g_freeze_hours, g_freeze_ok' = g_freeze_ok,
  }

  action tw_mark_ready = all {
    tw_has_baseline, not(tw_ready), gateOk,
    tw_ready' = true,
    tw_baseline' = tw_baseline, tw_has_baseline' = tw_has_baseline, tw_cursor' = tw_cursor,
    tw_events' = tw_events, tw_growth' = tw_growth, tw_inflight' = tw_inflight,
    tw_syncs' = tw_syncs, tw_match' = tw_match,
    iw_unchanged, ghost("twin", NO_FIN), g_freeze_hours' = g_freeze_hours, g_freeze_ok' = g_freeze_ok,
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
    nondet c = CHANGES.oneOf()
    nondet i = ITEMS.oneOf()
    nondet d = DELTAS.oneOf()
    tw_raise(c, i, d),
  }

  // Rules from verification.md section 4

  // Workflow only. A twin step leaves IMPACT Web as it was, or, with write-through on and the
  // list frozen, raises exactly one change request from the twin, pending, against the request's
  // current version and hours, and changes nothing else. So the twin never approves, never edits a
  // request, never touches the freeze, the frozen copy or the feed. The conditions are written out
  // here and not taken from tw_raise, so a bug in the raise step can't change the rule as well.
  val WorkflowOnly = g_actor == "twin" implies (iw_state == g_prev_iw or and {
    tw_write_mode, iw_frozen,
    iw_hours == g_prev_iw.hours, iw_version == g_prev_iw.version, iw_drb == g_prev_iw.drb,
    iw_drb_ver == g_prev_iw.drb_ver, iw_frozen == g_prev_iw.frozen, iw_copy == g_prev_iw.copy,
    iw_pos == g_prev_iw.pos, iw_len == g_prev_iw.len,
    CHANGES.exists(c => and {
      g_prev_iw.changes.get(c).status == "none",
      iw_changes.get(c).status == "pending",
      iw_changes.get(c).via == "twin",
      iw_changes.get(c).base == iw_version.get(iw_changes.get(c).item),
      iw_changes.get(c).target == iw_hours.get(iw_changes.get(c).item) + iw_changes.get(c).delta,
      iw_changes.get(c).target >= 0,     // IMPACT Web's own raise refuses a negative target
      CHANGES.forall(e => e != c implies iw_changes.get(e) == g_prev_iw.changes.get(e)),
    }),
  })

  // Read-only mode. With write-through off, no change request comes from the twin.
  val ReadOnlyMode = not(tw_write_mode) implies CHANGES.forall(c => iw_changes.get(c).via != "twin")

  // Baseline fixed. Once the twin has a baseline, no step changes it.
  val BaselineFixed = g_prev_has_baseline implies (tw_has_baseline and tw_baseline == g_prev_baseline)

  // Freeze is exact. The twin baseline equals IMPACT Web's frozen copy.
  // And the frozen copy is exactly the DRB-accepted current requests at the moment of freeze.
  val FreezeExact = and {
    tw_has_baseline implies (iw_frozen and tw_baseline == iw_copy),
    iw_frozen implies iw_copy == ITEMS.mapBy(i => if (g_freeze_ok.get(i)) g_freeze_hours.get(i) else 0),
  }

  // Nothing missed. The feed holds each approved change once. The twin has exactly one event
  // for each feed entry it has read up to, and none for anything else, however syncs overlap.
  // And a sync that finishes applies the whole window it read: its cursor reaches the end it
  // read, and every entry in the window is an event. So a sync that starts after an approval
  // and finishes turns it into exactly one event. A sync already in flight may miss it, and
  // the model doesn't claim a sync will ever run.
  val NothingMissed = and {
    g_fin.on implies (tw_cursor == max(g_prev_cursor, g_fin.hi)
                      and logIds(g_fin.lo, g_fin.hi).forall(c => tw_events.get(c) == 1)),
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

  val AllRules = WorkflowOnly and ReadOnlyMode and BaselineFixed and FreezeExact and NothingMissed and HumansDecide
    and GrowthAddsUp and Gate

  // Witnesses. Each must be reachable, or the rules above could hold only because the steps
  // that would break them never run.
  val ObsOverlap = tw_inflight.size() >= 2
  // Two syncs in flight that both read the same approved change.
  val ObsOverlapSameChange = tw_inflight.exists(a => tw_inflight.exists(b => a.id != b.id
    and logIds(a.lo, a.hi).intersect(logIds(b.lo, b.hi)).size() > 0))
  // The DRB accepted a request, an edit then cleared that decision, and freeze left it out.
  val ObsStaleDrbExcluded = iw_frozen and ITEMS.exists(i => iw_drb_ver.get(i) >= 0
    and not(g_freeze_ok.get(i)) and g_freeze_hours.get(i) > 0 and iw_copy.get(i) == 0)
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
  // The closed loop: a change request raised from the twin, approved by the DRB, synced as an event.
  val ObsTwinRaisedSynced = CHANGES.exists(c => iw_changes.get(c).via == "twin"
    and iw_changes.get(c).status == "approved" and tw_events.get(c) == 1)
  // Read-only mode still works: growth after freeze, all of it raised in IMPACT Web.
  val ObsReadOnlyGrowth = not(tw_write_mode) and iw_frozen and tw_growth != 0
}
