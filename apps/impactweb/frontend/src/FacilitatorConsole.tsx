import React, { useCallback, useEffect, useState } from "react";
import {
  AppliedInject,
  ArchiveRecord,
  ExerciseDetail,
  ExerciseListItem,
  LibraryInject,
  MembershipDetail,
  apiFetch,
} from "./api";

interface FacilitatorConsoleProps {
  token: string | null;
  exercise: ExerciseDetail;
  exercises: ExerciseListItem[];
  onSelectExercise: (id: string) => void;
  onRefreshWorkspace: () => Promise<void>;
  onFeedback: (msg: { kind: "error" | "success"; text: string }) => void;
}

const CLOCK_STEPS = [
  "candidate_list",
  "fit_to_frame",
  "challenge",
  "drb",
  "freeze",
  "t_minus_9",
  "t_minus_6",
  "t_minus_3",
  "t_minus_1",
  "closed",
];

const ROLES = ["facilitator", "ta_manager", "planner", "source_group", "drb_member", "viewer"];
const SOURCE_GROUPS = [
  "fixed_equipment",
  "rotating",
  "inspection",
  "operations",
  "projects",
  "instrumentation",
];

function labelize(raw: string): string {
  if (raw === "drb") return "DRB";
  if (raw.startsWith("t_minus_")) return `T-${raw.slice("t_minus_".length)}`;
  return raw.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export const FacilitatorConsole: React.FC<FacilitatorConsoleProps> = ({
  token,
  exercise,
  exercises,
  onSelectExercise,
  onRefreshWorkspace,
  onFeedback,
}) => {
  const [memberships, setMemberships] = useState<MembershipDetail[]>([]);
  const [library, setLibrary] = useState<LibraryInject[]>([]);
  const [appliedInjects, setAppliedInjects] = useState<AppliedInject[]>([]);
  const [archives, setArchives] = useState<ArchiveRecord[]>([]);

  // New exercise form
  const [newExName, setNewExName] = useState("Unit 200 Planning Rehearsal");
  const [newExMode, setNewExMode] = useState<"planning" | "demo">("planning");
  const [newExFixture, setNewExFixture] = useState<"seeded" | "partial" | "blank">("partial");

  // Clock advance control
  const currentIdx = CLOCK_STEPS.indexOf(exercise.clock_step);
  const nextDefaultStep = CLOCK_STEPS[Math.min(currentIdx + 1, CLOCK_STEPS.length - 1)];
  const [targetStep, setTargetStep] = useState(nextDefaultStep);

  // Membership form
  const [memEmail, setMemEmail] = useState("j.planner@demo.local");
  const [memName, setMemName] = useState("");
  const [memRole, setMemRole] = useState("planner");
  const [memGroup, setMemGroup] = useState("fixed_equipment");

  // Custom inject form
  const [customId, setCustomId] = useState("CUST-01");
  const [customTitle, setCustomTitle] = useState("");
  const [customDesc, setCustomDesc] = useState("");
  const [customKind, setCustomKind] = useState<"note" | "work_request" | "change_request" | "budget_cut">("note");

  useEffect(() => {
    setTargetStep(CLOCK_STEPS[Math.min(CLOCK_STEPS.indexOf(exercise.clock_step) + 1, CLOCK_STEPS.length - 1)]);
  }, [exercise.clock_step, exercise.id]);

  const loadConsole = useCallback(async () => {
    try {
      const [mems, lib, appInj, arch] = await Promise.all([
        apiFetch<MembershipDetail[]>(`/api/v1/exercises/${exercise.id}/memberships`, token),
        apiFetch<LibraryInject[]>("/api/v1/injects/library", token),
        apiFetch<AppliedInject[]>(`/api/v1/exercises/${exercise.id}/injects`, token),
        apiFetch<ArchiveRecord[]>(`/api/v1/exercises/${exercise.id}/archives`, token),
      ]);
      setMemberships(mems);
      setLibrary(lib);
      setAppliedInjects(appInj);
      setArchives(arch);
    } catch (err) {
      onFeedback({ kind: "error", text: err instanceof Error ? err.message : "Failed to load facilitator console" });
    }
  }, [exercise.id, token, onFeedback]);

  useEffect(() => {
    void loadConsole();
  }, [loadConsole]);

  async function handleCreateExercise(e: React.FormEvent) {
    e.preventDefault();
    try {
      const created = await apiFetch<{ id: string; seeded_count: number }>("/api/v1/exercises", token, {
        method: "POST",
        body: JSON.stringify({
          name: newExName,
          mode: newExMode,
          starting_fixture: newExFixture,
        }),
      });
      await onRefreshWorkspace();
      onSelectExercise(created.id);
      onFeedback({
        kind: "success",
        text: `Created exercise ${created.id} (${newExMode}, ${newExFixture} fixture with ${created.seeded_count} work requests).`,
      });
    } catch (err) {
      onFeedback({ kind: "error", text: err instanceof Error ? err.message : "Could not create exercise" });
    }
  }

  async function handleAdvanceClock() {
    try {
      const res = await apiFetch<{ clock_step: string }>(`/api/v1/exercises/${exercise.id}/clock`, token, {
        method: "POST",
        body: JSON.stringify({ target_step: targetStep, reason: "Facilitator clock move" }),
      });
      await onRefreshWorkspace();
      await loadConsole();
      onFeedback({ kind: "success", text: `Clock moved to ${labelize(res.clock_step)}.` });
    } catch (err) {
      onFeedback({ kind: "error", text: err instanceof Error ? err.message : "Clock advance refused" });
    }
  }

  async function handleToggleSetting(field: "twin_write_through" | "allow_external_ai", nextValue: boolean) {
    try {
      await apiFetch(`/api/v1/exercises/${exercise.id}/settings`, token, {
        method: "PATCH",
        body: JSON.stringify({ [field]: nextValue }),
      });
      await onRefreshWorkspace();
      onFeedback({
        kind: "success",
        text: `Updated ${labelize(field)} to ${nextValue ? "on" : "off"} for ${exercise.id}.`,
      });
    } catch (err) {
      onFeedback({ kind: "error", text: err instanceof Error ? err.message : "Failed to update setting" });
    }
  }

  async function handleUpsertMember(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiFetch(`/api/v1/exercises/${exercise.id}/memberships`, token, {
        method: "POST",
        body: JSON.stringify({
          email: memEmail,
          full_name: memName.trim() || null,
          role: memRole,
          source_group: memRole === "source_group" ? memGroup : null,
        }),
      });
      await loadConsole();
      await onRefreshWorkspace();
      onFeedback({ kind: "success", text: `Saved membership for ${memEmail} as ${labelize(memRole)}.` });
    } catch (err) {
      onFeedback({ kind: "error", text: err instanceof Error ? err.message : "Could not save membership" });
    }
  }

  async function handleRemoveMember(userId: string, email: string) {
    try {
      await apiFetch(`/api/v1/exercises/${exercise.id}/memberships/${encodeURIComponent(userId)}`, token, {
        method: "DELETE",
      });
      await loadConsole();
      onFeedback({ kind: "success", text: `Removed ${email} from ${exercise.id}. Access ended immediately.` });
    } catch (err) {
      onFeedback({ kind: "error", text: err instanceof Error ? err.message : "Could not remove member" });
    }
  }

  async function handleApplyLibraryInject(injectId: string) {
    try {
      const res = await apiFetch<{ applied: boolean; already_applied: boolean }>(
        `/api/v1/exercises/${exercise.id}/injects`,
        token,
        {
          method: "POST",
          body: JSON.stringify({ inject_id: injectId }),
        },
      );
      await loadConsole();
      await onRefreshWorkspace();
      onFeedback({
        kind: "success",
        text: res.already_applied
          ? `Inject ${injectId} was already applied once (idempotent).`
          : `Applied inject ${injectId} in ${labelize(exercise.clock_step)}.`,
      });
    } catch (err) {
      onFeedback({ kind: "error", text: err instanceof Error ? err.message : "Inject refused" });
    }
  }

  async function handleApplyCustomInject(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiFetch(`/api/v1/exercises/${exercise.id}/injects`, token, {
        method: "POST",
        body: JSON.stringify({
          inject_id: customId,
          custom: true,
          title: customTitle,
          description: customDesc,
          allowed_phases: [exercise.clock_step],
          action_kind: customKind,
        }),
      });
      setCustomTitle("");
      setCustomDesc("");
      await loadConsole();
      await onRefreshWorkspace();
      onFeedback({ kind: "success", text: `Applied custom inject ${customId}.` });
    } catch (err) {
      onFeedback({ kind: "error", text: err instanceof Error ? err.message : "Custom inject blocked" });
    }
  }

  async function handleResetExercise() {
    try {
      const res = await apiFetch<{ epoch: number; seeded_count: number }>(
        `/api/v1/exercises/${exercise.id}/reset`,
        token,
        { method: "POST" },
      );
      await loadConsole();
      await onRefreshWorkspace();
      onFeedback({
        kind: "success",
        text: `Reset ${exercise.id} to epoch ${res.epoch} (${res.seeded_count} requests restored; prior event log archived).`,
      });
    } catch (err) {
      onFeedback({ kind: "error", text: err instanceof Error ? err.message : "Reset failed" });
    }
  }

  const appliedIds = new Set(appliedInjects.map((i) => i.inject_id));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Create exercise</h2>
            <p className="panel-subtitle">
              Each exercise is isolated by exercise ID over the shared read-only Unit 200 plant graph ({exercises.length}{" "}
              active exercise{exercises.length === 1 ? "" : "s"}).
            </p>
          </div>
        </div>
        <form className="panel-body" onSubmit={handleCreateExercise} style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div className="field" style={{ flex: "1 1 220px", margin: 0 }}>
            <label htmlFor="new-ex-name">Exercise name</label>
            <input
              id="new-ex-name"
              className="input"
              required
              value={newExName}
              onChange={(e) => setNewExName(e.target.value)}
            />
          </div>
          <div className="field" style={{ width: 150, margin: 0 }}>
            <label htmlFor="new-ex-mode">Mode</label>
            <select id="new-ex-mode" className="select" value={newExMode} onChange={(e) => setNewExMode(e.target.value as "planning" | "demo")}>
              <option value="planning">Planning</option>
              <option value="demo">Demo</option>
            </select>
          </div>
          <div className="field" style={{ width: 170, margin: 0 }}>
            <label htmlFor="new-ex-fixture">Starting fixture</label>
            <select id="new-ex-fixture" className="select" value={newExFixture} onChange={(e) => setNewExFixture(e.target.value as "seeded" | "partial" | "blank")}>
              <option value="seeded">Seeded (200)</option>
              <option value="partial">Partial (100)</option>
              <option value="blank">Blank (0)</option>
            </select>
          </div>
          <button type="submit" className="btn btn-primary">
            Create exercise
          </button>
        </form>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Exercise clock and governance switches</h2>
            <p className="panel-subtitle">
              Active exercise {exercise.id} is at {labelize(exercise.clock_step)} (epoch {exercise.epoch},{" "}
              {exercise.frozen ? "frozen" : "unfrozen"}). The clock moves forward only and cannot pass Freeze until the
              TA manager freezes the list.
            </p>
          </div>
          <div className="action-row">
            <select aria-label="Target clock step" className="select" value={targetStep} onChange={(e) => setTargetStep(e.target.value)}>
              {CLOCK_STEPS.map((st, idx) => (
                <option key={st} value={st} disabled={idx <= currentIdx}>
                  {labelize(st)}
                </option>
              ))}
            </select>
            <button type="button" className="btn btn-primary" onClick={handleAdvanceClock} disabled={currentIdx >= CLOCK_STEPS.length - 1}>
              Advance clock
            </button>
          </div>
        </div>
        <div className="panel-body" style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
            <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              <input
                type="checkbox"
                checked={exercise.twin_write_through}
                onChange={(e) => handleToggleSetting("twin_write_through", e.target.checked)}
              />
              Allow twin write-through (demo change requests)
            </label>
            <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              <input
                type="checkbox"
                checked={Boolean(exercise.allow_external_ai)}
                onChange={(e) => handleToggleSetting("allow_external_ai", e.target.checked)}
              />
              Allow external AI matching (off by default in planning mode)
            </label>
          </div>
          <button type="button" className="btn btn-danger" onClick={handleResetExercise}>
            Reset exercise (bump epoch)
          </button>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Exercise memberships</h2>
            <p className="panel-subtitle">
              Role assignments and revocations take effect immediately on the next request across IMPACT Web and the
              digital twin.
            </p>
          </div>
        </div>
        <div className="panel-body">
          <form onSubmit={handleUpsertMember} style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 14 }}>
            <div className="field" style={{ flex: "1 1 200px", margin: 0 }}>
              <label htmlFor="mem-email">Email</label>
              <input id="mem-email" className="input" type="email" required value={memEmail} onChange={(e) => setMemEmail(e.target.value)} />
            </div>
            <div className="field" style={{ width: 160, margin: 0 }}>
              <label htmlFor="mem-name">Name (optional)</label>
              <input id="mem-name" className="input" value={memName} onChange={(e) => setMemName(e.target.value)} placeholder="Synthetic name" />
            </div>
            <div className="field" style={{ width: 150, margin: 0 }}>
              <label htmlFor="mem-role">Role</label>
              <select id="mem-role" className="select" value={memRole} onChange={(e) => setMemRole(e.target.value)}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {labelize(r)}
                  </option>
                ))}
              </select>
            </div>
            {memRole === "source_group" && (
              <div className="field" style={{ width: 160, margin: 0 }}>
                <label htmlFor="mem-group">Source group</label>
                <select id="mem-group" className="select" value={memGroup} onChange={(e) => setMemGroup(e.target.value)}>
                  {SOURCE_GROUPS.map((g) => (
                    <option key={g} value={g}>
                      {labelize(g)}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <button type="submit" className="btn btn-primary">
              Add or update member
            </button>
          </form>

          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Source group</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {memberships.map((m) => (
                  <tr key={m.user_id}>
                    <td>{m.full_name}</td>
                    <td className="mono">{m.email}</td>
                    <td>{labelize(m.role)}</td>
                    <td>{m.source_group ? labelize(m.source_group) : "All"}</td>
                    <td>
                      <button type="button" className="btn btn-sm" onClick={() => handleRemoveMember(m.user_id, m.email)}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Library and custom injects</h2>
            <p className="panel-subtitle">
              Injects are phase-limited, logged, and idempotent. Custom inject text is checked by the synthetic-data
              filter before storage.
            </p>
          </div>
        </div>
        <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Inject ID</th>
                  <th>Event</th>
                  <th>Allowed phases</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {library.map((inj) => {
                  const done = appliedIds.has(inj.inject_id);
                  const phaseAllowed = inj.allowed_phases.includes(exercise.clock_step);
                  return (
                    <tr key={inj.inject_id}>
                      <td className="mono">{inj.inject_id}</td>
                      <td>
                        <div style={{ fontWeight: 500 }}>{inj.title}</div>
                        <div className="field-hint">{inj.description}</div>
                      </td>
                      <td>{inj.allowed_phases.map(labelize).join(", ")}</td>
                      <td>
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={done}
                          onClick={() => handleApplyLibraryInject(inj.inject_id)}
                        >
                          {done ? "Applied" : phaseAllowed ? "Apply inject" : "Outside phase"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <form onSubmit={handleApplyCustomInject} style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end", paddingTop: 12, borderTop: "1px solid var(--border-hairline)" }}>
            <div className="field" style={{ width: 120, margin: 0 }}>
              <label htmlFor="cust-id">Custom ID</label>
              <input id="cust-id" className="input" required value={customId} onChange={(e) => setCustomId(e.target.value)} />
            </div>
            <div className="field" style={{ flex: "1 1 200px", margin: 0 }}>
              <label htmlFor="cust-title">Title</label>
              <input id="cust-title" className="input" required value={customTitle} onChange={(e) => setCustomTitle(e.target.value)} placeholder="Synthetic event title" />
            </div>
            <div className="field" style={{ flex: "2 1 260px", margin: 0 }}>
              <label htmlFor="cust-desc">Description</label>
              <input id="cust-desc" className="input" required value={customDesc} onChange={(e) => setCustomDesc(e.target.value)} placeholder="Synthetic details for the team" />
            </div>
            <div className="field" style={{ width: 150, margin: 0 }}>
              <label htmlFor="cust-kind">Effect</label>
              <select id="cust-kind" className="select" value={customKind} onChange={(e) => setCustomKind(e.target.value as "note" | "work_request" | "change_request" | "budget_cut")}>
                <option value="note">Log note</option>
                <option value="work_request">Candidate request</option>
                <option value="change_request">Post-freeze CR</option>
                <option value="budget_cut">Budget cut (10%)</option>
              </select>
            </div>
            <button type="submit" className="btn">
              Apply custom inject
            </button>
          </form>
        </div>
      </section>

      {archives.length > 0 && (
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Archived event logs from prior epochs</h2>
              <p className="panel-subtitle">
                Reset archives previous history rather than deleting it so earlier debriefs remain readable.
              </p>
            </div>
          </div>
          <div className="panel-body">
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Epoch</th>
                    <th>Archived at</th>
                    <th>Clock at reset</th>
                    <th>Requests / decisions / CRs</th>
                  </tr>
                </thead>
                <tbody>
                  {archives.map((a) => (
                    <tr key={a.id}>
                      <td className="mono">Epoch {a.epoch}</td>
                      <td className="mono">{new Date(a.archived_at).toLocaleString()}</td>
                      <td>{labelize(String(a.summary.clock_step_at_reset ?? ""))}</td>
                      <td className="mono">
                        {String(a.summary.work_request_count ?? 0)} / {String(a.summary.decision_count ?? 0)} /{" "}
                        {String(a.summary.change_request_count ?? 0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}
    </div>
  );
};
