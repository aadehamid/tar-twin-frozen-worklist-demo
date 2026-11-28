// Interactive planning mode specification extending worklist.qnt with:
// - Multiple exercises (isolation invariant: participant steps touch only their exercise)
// - Forward-only exercise clock gated on freeze before post-freeze checkpoints
// - Concurrent editors with optimistic version locking (no lost edits)
// - Approved-only post-freeze growth invariant
module planning_mode {
  pure val EXERCISES = Set(1, 2)
  pure val ITEMS = Set(1, 2)
  pure val CLOCK_MAX = 9 // 0=candidate_list..4=freeze, 5=t_minus_9..8=t_minus_1, 9=closed
  pure val FREEZE_STEP = 4
  pure val MAX_VERSION = 4

  type ExState = {
    clock: int,
    epoch: int,
    frozen: bool,
    hours: int -> int,
    version: int -> int,
    drb_ver: int -> int,
    copy: int -> int,
    approved_growth: int,
    pending_delta: int,
  }

  var exs: int -> ExState
  var g_actor: str      // "participant" | "facilitator" | "init"
  var g_target_ex: int
  var g_prev_exs: int -> ExState

  pure def blankEx(): ExState = {
    clock: 0,
    epoch: 1,
    frozen: false,
    hours: ITEMS.mapBy(i => 40),
    version: ITEMS.mapBy(i => 1),
    drb_ver: ITEMS.mapBy(i => 0),
    copy: ITEMS.mapBy(i => 0),
    approved_growth: 0,
    pending_delta: 0,
  }

  action init = all {
    exs' = EXERCISES.mapBy(e => blankEx()),
    g_actor' = "init",
    g_target_ex' = 1,
    g_prev_exs' = EXERCISES.mapBy(e => blankEx()),
  }

  // Concurrent editor edit: requires expected_ver == current version (prevents lost edits)
  action edit_item(e: int, i: int, expected_ver: int, new_hours: int): bool = {
    val st = exs.get(e)
    all {
      not(st.frozen),
      st.clock <= 3,
      expected_ver == st.version.get(i),
      st.version.get(i) < MAX_VERSION,
      new_hours > 0,
      new_hours != st.hours.get(i),
      exs' = exs.set(e, {
        ...st,
        hours: st.hours.set(i, new_hours),
        version: st.version.set(i, st.version.get(i) + 1),
      }),
      g_actor' = "participant",
      g_target_ex' = e,
      g_prev_exs' = exs,
    }
  }

  // TA manager final DRB accept binds to current item version
  action drb_accept(e: int, i: int): bool = {
    val st = exs.get(e)
    all {
      not(st.frozen),
      st.clock == 3,
      exs' = exs.set(e, {
        ...st,
        drb_ver: st.drb_ver.set(i, st.version.get(i)),
      }),
      g_actor' = "participant",
      g_target_ex' = e,
      g_prev_exs' = exs,
    }
  }

  // Facilitator advances clock forward only; cannot pass FREEZE_STEP while unfrozen
  action advance_clock(e: int, next_step: int): bool = {
    val st = exs.get(e)
    all {
      next_step > st.clock,
      next_step <= CLOCK_MAX,
      (next_step > FREEZE_STEP) implies st.frozen,
      exs' = exs.set(e, { ...st, clock: next_step }),
      g_actor' = "facilitator",
      g_target_ex' = e,
      g_prev_exs' = exs,
    }
  }

  // TA manager freezes at FREEZE_STEP; only items whose current version matches drb_ver are copied
  action freeze(e: int): bool = {
    val st = exs.get(e)
    all {
      not(st.frozen),
      st.clock == FREEZE_STEP,
      exs' = exs.set(e, {
        ...st,
        frozen: true,
        copy: ITEMS.mapBy(i => if (st.drb_ver.get(i) == st.version.get(i)) st.hours.get(i) else 0),
      }),
      g_actor' = "participant",
      g_target_ex' = e,
      g_prev_exs' = exs,
    }
  }

  // Pending post-freeze change does not alter live hours or approved_growth
  action raise_change(e: int, delta: int): bool = {
    val st = exs.get(e)
    all {
      st.frozen,
      st.clock < CLOCK_MAX,
      st.pending_delta == 0,
      delta > 0,
      exs' = exs.set(e, { ...st, pending_delta: delta }),
      g_actor' = "participant",
      g_target_ex' = e,
      g_prev_exs' = exs,
    }
  }

  // Approving pending change applies delta to approved_growth
  action approve_change(e: int): bool = {
    val st = exs.get(e)
    all {
      st.frozen,
      st.pending_delta > 0,
      exs' = exs.set(e, {
        ...st,
        approved_growth: st.approved_growth + st.pending_delta,
        pending_delta: 0,
      }),
      g_actor' = "participant",
      g_target_ex' = e,
      g_prev_exs' = exs,
    }
  }

  // Facilitator resets exactly one exercise, bumping its epoch and leaving others untouched
  action reset_exercise(e: int): bool = {
    val st = exs.get(e)
    all {
      exs' = exs.set(e, { ...blankEx(), epoch: st.epoch + 1 }),
      g_actor' = "facilitator",
      g_target_ex' = e,
      g_prev_exs' = exs,
    }
  }

  action step = any {
    nondet e = EXERCISES.oneOf()
    nondet i = ITEMS.oneOf()
    nondet h = Set(40, 80, 120).oneOf()
    edit_item(e, i, exs.get(e).version.get(i), h),
    nondet e = EXERCISES.oneOf()
    nondet i = ITEMS.oneOf()
    drb_accept(e, i),
    nondet e = EXERCISES.oneOf()
    nondet s = Set(1, 2, 3, 4, 5, 6, 7, 8, 9).oneOf()
    advance_clock(e, s),
    nondet e = EXERCISES.oneOf()
    freeze(e),
    nondet e = EXERCISES.oneOf()
    raise_change(e, 20),
    nondet e = EXERCISES.oneOf()
    approve_change(e),
    nondet e = EXERCISES.oneOf()
    reset_exercise(e),
  }

  // Invariants (docs/interactive-planning.md section 5)
  val ExerciseIsolation = EXERCISES.forall(other =>
    other != g_target_ex implies exs.get(other) == g_prev_exs.get(other)
  )

  val ClockCannotPassFreezeUnfrozen = EXERCISES.forall(e =>
    exs.get(e).clock > FREEZE_STEP implies exs.get(e).frozen
  )

  val ClockForwardUnlessReset = EXERCISES.forall(e =>
    exs.get(e).epoch == g_prev_exs.get(e).epoch implies exs.get(e).clock >= g_prev_exs.get(e).clock
  )

  val VersionsMonotonicUnlessReset = EXERCISES.forall(e =>
    exs.get(e).epoch == g_prev_exs.get(e).epoch implies
      ITEMS.forall(i => exs.get(e).version.get(i) >= g_prev_exs.get(e).version.get(i))
  )

  val GrowthOnlyWhenFrozen = EXERCISES.forall(e =>
    not(exs.get(e).frozen) implies exs.get(e).approved_growth == 0
  )

  val AllPlanningRules = ExerciseIsolation and ClockCannotPassFreezeUnfrozen
    and ClockForwardUnlessReset and VersionsMonotonicUnlessReset and GrowthOnlyWhenFrozen
}
