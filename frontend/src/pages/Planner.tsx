// Planner (PHASE2_IMPLEMENTATION_PLAN §10.2): generate, explain, approve and commit plans; review re-task proposals;
// what-if and COA comparison. Decision support only: nothing reaches the sorties without an audited commit.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Disruption, Fix, PlanItemView, PlanKpis, PlanListRow, PlanView, Priority, User } from "../api/types";
import { ErrorText, Loading, Modal, Pill, Row, Sim, ToneText } from "../components/ui";
import { ManualTab } from "../features/manual";
import { ChangePill, Explanation, PlanKpiStrip, PrioPill, Timeline, Unmet, hhmm } from "../features/ops";
import { RANK, istTime, label, num } from "../lib/format";
import { useStore } from "../store";

type Tab = "plan" | "changes" | "whatif" | "coa" | "manual";
const PRESET_LABEL: Record<string, string> = { BALANCED: "Balanced", MAX_COVERAGE: "Max coverage", MIN_RISK: "Min risk", MIN_FUEL: "Min fuel", STABILITY: "Stability" };
const PRIOS: Priority[] = ["P1", "P2", "P3", "P4"];

export function Planner({ user }: { user: User }) {
  const qc = useQueryClient();
  const toast = useStore((s) => s.toast);
  const simClock = useStore((s) => s.simClock);
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState<Tab>("plan");
  const [preset, setPreset] = useState("BALANCED");
  const [sel, setSel] = useState<{ kind: "item" | "unmet"; id: number } | null>(params.get("item") ? { kind: "item", id: Number(params.get("item")) } : null);
  const canPlan = user.role === "ADMIN" || user.role === "COMMAND_HQ";
  const split = useMutation({                   // D42: apply a checked split fix to an uncovered mission
    mutationFn: ({ id, f }: { id: number; f: Fix }) => api<{ parts: { id: number; code: string }[] }>(`/ops/missions/${id}/split`,
      { method: "POST", body: { kind: f.kind, parts: f.parts, t0: f.t0, sizes: f.sizes ?? null } }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["missions"] }); toast(`Split into ${r.parts.map((x) => x.code).join(", ")}. Generate a new plan to cover them.`, "INFO"); },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Split failed", "CRITICAL"),
  });
  const list = useQuery({ queryKey: ["plans", "list"], queryFn: () => api<{ items: PlanListRow[]; committed_id: number | null; pending_retask_id: number | null }>("/ops/plans?limit=25"),
    refetchInterval: 15000 });
  const want = params.get("plan");
  const pid = want && want !== "current" ? Number(want)
    : list.data?.pending_retask_id ?? list.data?.items.find((p) => p.status === "PROPOSED" && p.kind === "PLAN")?.id ?? list.data?.committed_id ?? list.data?.items[0]?.id;
  const plan = useQuery({ queryKey: ["plan", pid], queryFn: () => api<PlanView>(`/ops/plans/${pid}`), enabled: !!pid, refetchInterval: 20000 });
  const p = plan.data;
  useEffect(() => { if (p && p.plan.kind === "RETASK" && p.plan.status === "PROPOSED") setTab((t) => (t === "plan" ? "changes" : t)); }, [p?.plan.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const invalidate = () => ["plans", "plan", "missions", "ops-summary", "ops-routes", "disruptions", "summary"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const gen = useMutation({
    mutationFn: (pr: string) => api<{ plan_id: number; kpis: PlanKpis }>("/ops/plans", { method: "POST", body: { preset: pr } }),
    onSuccess: (r) => {
      setParams({ plan: String(r.plan_id) });
      setSel(null);
      invalidate();
      toast(`Plan #${r.plan_id}: ${r.kpis.covered} of ${r.kpis.missions} missions covered in ${num((r.kpis.total_ms ?? r.kpis.solve_ms) / 1000, 1)} s`, "INFO");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Planning failed", "CRITICAL"),
  });
  const act = useMutation({
    // the plan id travels with the call: a closure could still hold the plan shown before the last "Generate"
    mutationFn: ({ action, id }: { action: "approve" | "commit" | "reject"; id: number }) =>
      api<{ ok: boolean; changes?: Record<string, number | string[]> }>(`/ops/plans/${id}/${action}`, { method: "POST" }),
    onSuccess: (r, { action, id: pidDone }) => {
      invalidate();
      if (action === "commit" && r.changes) {
        const counts = Object.entries(r.changes).filter(([, v]) => typeof v === "number" && v).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(", ");
        toast(`Plan #${pidDone} committed: ${counts || "no change"}`, "INFO");
        // the world moved since the plan was made: say exactly what commit repaired or skipped
        for (const n of ((r.changes.notes as string[]) ?? []).slice(0, 3)) toast(n, "WARNING");
      } else toast(action === "approve" ? "Plan approved" : "Plan rejected", "INFO");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Failed", "CRITICAL"),
  });

  const item = sel?.kind === "item" ? p?.items.find((i) => i.id === sel.id) : undefined;
  const unmet = sel?.kind === "unmet" ? p?.unmet.find((u) => u.id === sel.id) : undefined;
  const decidable = !!p && ["PROPOSED", "APPROVED"].includes(p.plan.status) && p.plan.kind !== "WHATIF" && canPlan;
  const changes = useMemo(() => (p?.items ?? []).filter((i) => i.change && i.change !== "KEPT"), [p]);

  return (
    <div className="page">
      <h1 className="page-title">Planner <Sim title="Plans are built from simulated data" />
        <span className="muted" style={{ fontSize: 13, fontWeight: 400 }}>Decision support: a person approves every change</span></h1>

      <div className="toolbar">
        <select className="select" aria-label="Plan" value={pid ?? ""} onChange={(e) => { setParams({ plan: e.target.value }); setSel(null); }}>
          {(list.data?.items ?? []).map((r) => (
            <option key={r.id} value={r.id}>#{r.id} {label(r.kind)} · {label(r.status)}{r.summary ? ` · ${r.summary}` : ""}</option>
          ))}
        </select>
        {canPlan && <>
          <select className="select" aria-label="Preset" value={preset} onChange={(e) => setPreset(e.target.value)} title="What the planner optimises after coverage">
            {["BALANCED", "MAX_COVERAGE", "MIN_RISK", "MIN_FUEL"].map((x) => <option key={x} value={x}>{PRESET_LABEL[x]}</option>)}
          </select>
          <button className="btn btn-primary" disabled={gen.isPending} onClick={() => gen.mutate(preset)}>{gen.isPending ? "Planning…" : "Generate plan"}</button>
        </>}
        <span className="topbar-spacer" />
        {decidable && <>
          {p!.plan.status === "PROPOSED" && <button className="btn" disabled={act.isPending} onClick={() => act.mutate({ action: "approve", id: p!.plan.id })}>Approve</button>}
          <button className="btn btn-primary" disabled={act.isPending} onClick={() => confirm(`Commit plan #${p!.plan.id}? Sorties will be created, moved or cancelled.`) && act.mutate({ action: "commit", id: p!.plan.id })}>
            {p!.plan.kind === "RETASK" ? "Commit re-task" : "Commit plan"}</button>
          <button className="btn btn-danger" disabled={act.isPending} onClick={() => act.mutate({ action: "reject", id: p!.plan.id })}>Reject</button>
        </>}
      </div>

      {list.data?.pending_retask_id && list.data.pending_retask_id !== pid && (
        <div className="notice notice-warn" style={{ marginBottom: 12 }}>
          <ToneText toneName="warning">Re-task proposal #{list.data.pending_retask_id} is waiting for a decision.</ToneText>{" "}
          <a href="#" onClick={(e) => { e.preventDefault(); setParams({ plan: String(list.data!.pending_retask_id) }); }}>Review it</a>
        </div>
      )}
      {list.isLoading && <Loading />}
      {!pid && list.data && <div className="empty">No plans yet. {canPlan ? "Generate the first plan for the next 24 hours." : "Air HQ hasn't generated a plan yet."}</div>}
      {plan.error && <ErrorText error={plan.error} />}

      {p && <>
        <div className="plan-head">
          <span><b>Plan #{p.plan.id}</b> · {label(p.plan.kind)} · <Pill status={p.plan.status === "COMMITTED" ? "OPERATIONAL" : p.plan.status === "PROPOSED" ? "PLANNED" : p.plan.status === "REJECTED" ? "CRITICAL" : "STANDBY"} text={label(p.plan.status)} /></span>
          <span className="muted">Horizon {istTime(p.plan.horizon_start, true)} – {istTime(p.plan.horizon_end, true)} (simulated time) · preset {PRESET_LABEL[p.plan.preset] ?? p.plan.preset}</span>
          {p.plan.committed_at && <span className="muted">committed {istTime(p.plan.committed_at, true)}</span>}
          {p.plan.kind !== "WHATIF" && user.role !== "VIEWER" && <a className="btn btn-sm" href={`/planner/ato/${p.plan.id}`}>Air tasking order</a>}
        </div>
        <PlanKpiStrip k={p.plan.kpis} extra={p.plan.kind === "RETASK" && p.plan.kpis.changes ? (
          <div className="kpi"><div className="kpi-label">Re-task</div><div className="kpi-value" style={{ fontSize: 15 }}>{p.plan.summary}</div>
            <div className="kpi-sub">{label(p.plan.kpis.rung)} · proposed in {num((p.plan.kpis.proposal_ms ?? 0) / 1000, 1)} s</div></div>) : undefined} />

        <div className="tabs" role="tablist" style={{ marginTop: 16 }}>
          {([["plan", "Plan"], ["changes", `Changes${changes.length || p.unmet.some((u) => u.dropped_item_id) ? ` (${changes.length + p.unmet.filter((u) => u.dropped_item_id).length})` : ""}`],
            ["whatif", "What-if"], ["coa", "Compare COAs"], ["manual", "Manual baseline"]] as [Tab, string][]).map(([k, n]) => (
            <button key={k} role="tab" aria-selected={tab === k} className={`tab${tab === k ? " on" : ""}`} onClick={() => setTab(k)}>{n}</button>
          ))}
        </div>

        {tab === "plan" && (
          <div className="planner-grid">
            <MissionColumn p={p} sel={sel} onSel={setSel} />
            <div style={{ minWidth: 0 }}>
              <Timeline items={p.items} start={p.plan.horizon_start} end={p.plan.horizon_end} selected={item?.id ?? null}
                onSelect={(id) => setSel({ kind: "item", id })} now={simClock?.sim_now} />
              {p.items.length === 0 && <div className="empty">No packages in this plan.</div>}
            </div>
            <aside className="plan-detail">
              {!sel && <div className="empty">Select a package or an uncovered mission to see why.</div>}
              {item && <ItemDetail it={item} plan={p} user={user} />}
              {unmet && <>
                <div className="detail-title"><PrioPill p={unmet.mission.priority} /> <span className="mono">{unmet.mission.code}</span>
                  {unmet.dropped_item_id ? <ChangePill c="DROPPED" /> : <ToneText toneName="caution">Not covered</ToneText>}</div>
                <div className="muted" style={{ marginBottom: 6 }}>{unmet.mission.name}</div>
                <Unmet m={unmet.mission} reasons={unmet.reasons} fixes={unmet.fixes} busy={split.isPending}
                  onApply={canPlan ? (f) => confirm(`${f.text}?\n\nThis replaces ${unmet.mission.code} with ${f.parts} missions. Generate a new plan afterwards.`)
                    && split.mutate({ id: unmet.mission.id, f }) : undefined} />
              </>}
            </aside>
          </div>
        )}
        {tab === "changes" && <ChangesTab p={p} changes={changes} canPlan={canPlan} onSel={(id) => { setSel({ kind: "item", id }); setTab("plan"); }} />}
        {tab === "whatif" && <WhatIf canPlan={canPlan} />}
        {tab === "coa" && <Coa canPlan={canPlan} />}
        {tab === "manual" && <ManualTab canPlan={canPlan} />}
      </>}
    </div>
  );
}

function MissionColumn({ p, sel, onSel }: { p: PlanView; sel: { kind: string; id: number } | null; onSel: (s: { kind: "item" | "unmet"; id: number }) => void }) {
  return (
    <div className="mission-col">
      {PRIOS.map((pr) => {
        const items = p.items.filter((i) => i.mission.priority === pr);
        const un = p.unmet.filter((u) => u.mission.priority === pr);
        if (!items.length && !un.length) return null;
        return (
          <div key={pr}>
            <div className="col-h"><PrioPill p={pr} /> <span className="dim mono">{items.length}/{items.length + un.length}</span></div>
            {un.map((u) => (
              <button key={`u${u.id}`} className={`mission-row unmet${sel?.kind === "unmet" && sel.id === u.id ? " on" : ""}`} onClick={() => onSel({ kind: "unmet", id: u.id })}>
                <span className="mono">{u.mission.code.replace(/^SIM-/, "")}</span>
                <span className="s-caution" style={{ fontSize: 11 }}>▲ {u.dropped_item_id ? "dropped" : u.reasons[0]?.text ?? "not covered"}</span>
              </button>
            ))}
            {items.map((i) => (
              <button key={i.id} className={`mission-row${sel?.kind === "item" && sel.id === i.id ? " on" : ""}`} onClick={() => onSel({ kind: "item", id: i.id })}>
                <span className="mono">{i.mission.code.replace(/^SIM-/, "")}</span>
                <span className="dim" style={{ fontSize: 11 }}>{i.n_aircraft} × {i.type.name} · {i.base.code} {hhmm(i.launch_ts)}{i.support ? " + tanker" : ""}{i.change && i.change !== "KEPT" ? ` · ${label(i.change)}` : ""}</span>
              </button>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function ItemDetail({ it, plan, user }: { it: PlanItemView; plan: PlanView; user: User }) {
  const [swap, setSwap] = useState(false);
  const canSwap = ["PROPOSED", "APPROVED"].includes(plan.plan.status) && (user.role === "ADMIN" || (user.role === "BASE_COMMANDER" && user.base_id === it.base.id));
  const w = it.score?.weapons ?? {};
  return (
    <>
      <div className="detail-title"><PrioPill p={it.mission.priority} /> <span className="mono">{it.mission.code}</span> <ChangePill c={it.change} /></div>
      <div className="muted" style={{ marginBottom: 6 }}>{it.mission.name}</div>
      <Row label="Package" value={`${it.n_aircraft} × ${it.type.name}`} extra={<span className="mono">{it.base.code}</span>} />
      <Row label="Launch · on station · recover" value={`${hhmm(it.launch_ts)} · ${hhmm(it.on_station_ts)} · ${hhmm(it.recovery_ts)}`} />
      {it.recovery_base && it.recovery_base.id !== it.base.id && <Row label="Recovers at" value={<ToneText toneName="warning">{it.recovery_base.code}</ToneText>} />}
      <Row label="Tails" value={<span className="mono">{it.aircraft.map((a) => a.tail_no).join(", ")}</span>}
        extra={it.score?.snag ? <span className="dim" style={{ fontSize: 11 }}>
          predicted defect risk {it.aircraft.map((a) => `${Math.round(100 * (it.score!.snag!.tails[a.tail_no] ?? 0))}%`).join(" · ")}</span> : undefined} />
      {it.crew.map((c) => <Row key={c.id} label={label(c.position)} value={`${RANK[c.rank] ?? c.rank} ${c.name}`} extra={c.callsign ? <span className="mono dim">{c.callsign}</span> : undefined} />)}
      {it.support && <>
        <h4 className="section-h" style={{ fontSize: 13 }}>Air-to-air refuelling</h4>
        <Row label="Tanker" value={`1 × ${it.support.type?.name ?? "tanker"}`} extra={<span className="mono">{it.support.base?.code}</span>} />
        <Row label="Launch · on track · recover" value={`${hhmm(it.support.launch_ts)} · ${hhmm(it.support.rv_start)}–${hhmm(it.support.rv_end)} · ${hhmm(it.support.recovery_ts)}`} />
        <Row label="Refuelling point" value={<span className="mono">{it.support.rv[1].toFixed(2)}, {it.support.rv[0].toFixed(2)}</span>} />
        <Row label="Tanker tail" value={<span className="mono">{it.support.aircraft.map((a) => a.tail_no).join(", ")}</span>} />
        {it.support.crew.filter((c) => c.position === "CAPTAIN").map((c) => <Row key={c.id} label="Tanker captain" value={`${RANK[c.rank] ?? c.rank} ${c.name}`} />)}
        {it.support.sortie && <Row label="Tanker sortie" value={<><span className="mono">{it.support.sortie.code}</span> <Pill status={it.support.sortie.status} /></>} />}
      </>}
      {Object.keys(w).length > 0 && <Row label="Weapons (generic)" value={Object.entries(w).map(([k, v]) => `${v} ${k.replace("ARMAMENT_", "").replace(/_/g, "-")}`).join(", ")} />}
      {it.sortie && <Row label="Sortie" value={<><span className="mono">{it.sortie.code}</span> <Pill status={it.sortie.status} /></>} />}
      {canSwap && <div className="toolbar" style={{ marginTop: 8 }}><button className="btn btn-sm" onClick={() => setSwap(true)}>Swap tails or crew</button></div>}
      <h4 className="section-h" style={{ fontSize: 14 }}>Why this package</h4>
      <Explanation it={it} />
      {swap && <SwapModal it={it} planId={plan.plan.id} onClose={() => setSwap(false)} />}
    </>
  );
}

interface Options { aircraft: { id: number; tail_no: string; hours_left: number; status: string; free: boolean; snag: number | null }[];
  pilots: { id: number; name: string; rank: string; rating: string; quals: string[]; free: boolean }[]; requirement: string }

function SwapModal({ it, planId, onClose }: { it: PlanItemView; planId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const opts = useQuery({ queryKey: ["plan-options", it.id], queryFn: () => api<Options>(`/ops/plans/${planId}/items/${it.id}/options`) });
  const [tails, setTails] = useState<number[]>(it.aircraft.map((a) => a.id));
  const captains = it.crew.filter((c) => ["CAPTAIN", "CO_PILOT", "INSTRUCTOR", "RPA_PILOT"].includes(c.position));
  const [pilots, setPilots] = useState<number[]>(captains.map((c) => c.id));
  const save = useMutation({
    mutationFn: () => {
      const crew = it.crew.map((c) => {
        const k = captains.findIndex((x) => x.id === c.id);
        const ac = tails[Math.min(Math.floor(it.aircraft.findIndex((a) => a.id === c.aircraft_id)), tails.length - 1)] ?? tails[0];
        return [k >= 0 ? pilots[k] : c.id, ac, c.position];
      });
      return api(`/ops/plans/${planId}/items/${it.id}`, { method: "PATCH", body: { aircraft_ids: tails, crew_positions: crew } });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["plan"] }); onClose(); },
  });
  return (
    <Modal title={`Swap tails or crew · ${it.mission.code}`} onClose={onClose}>
      {opts.isLoading && <Loading />}
      {opts.data && <>
        <div className="muted" style={{ marginBottom: 8 }}>Pilots must be {opts.data.requirement}. The change is checked against every rule before it is saved.</div>
        <div className="grid-2">
          <div>
            <h4 className="section-h" style={{ fontSize: 13 }}>Tails ({it.n_aircraft})</h4>
            {tails.map((t, i) => (
              <select key={i} className="select" style={{ width: "100%", marginBottom: 6 }} value={t} onChange={(e) => setTails(tails.map((x, j) => (j === i ? Number(e.target.value) : x)))}>
                {opts.data!.aircraft.map((a) => <option key={a.id} value={a.id} disabled={!a.free && !tails.includes(a.id)}>{a.tail_no} · {num(a.hours_left, 0)} h left{a.snag != null ? ` · ${Math.round(100 * a.snag)}% defect risk` : ""}{a.free ? "" : " · busy"}</option>)}
              </select>
            ))}
          </div>
          <div>
            <h4 className="section-h" style={{ fontSize: 13 }}>Pilots ({captains.length})</h4>
            {pilots.map((c, i) => (
              <select key={i} className="select" style={{ width: "100%", marginBottom: 6 }} value={c} onChange={(e) => setPilots(pilots.map((x, j) => (j === i ? Number(e.target.value) : x)))}>
                {opts.data!.pilots.map((x) => <option key={x.id} value={x.id} disabled={!x.free && !pilots.includes(x.id)}>{RANK[x.rank] ?? x.rank} {x.name} · {label(x.rating)}{x.free ? "" : " · busy"}</option>)}
              </select>
            ))}
          </div>
        </div>
      </>}
      {save.error && <ErrorText error={save.error} />}
      <div className="modal-actions"><button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={save.isPending || new Set(tails).size !== tails.length || new Set(pilots).size !== pilots.length} onClick={() => save.mutate()}>Save change</button></div>
    </Modal>
  );
}

function ChangesTab({ p, changes, canPlan, onSel }: { p: PlanView; changes: PlanItemView[]; canPlan: boolean; onSel: (id: number) => void }) {
  const qc = useQueryClient();
  const toast = useStore((s) => s.toast);
  const d = useQuery({ queryKey: ["disruptions"], queryFn: () => api<Disruption[]>("/ops/disruptions?limit=40"), refetchInterval: 15000 });
  const check = useMutation({
    mutationFn: () => api<{ disruptions: unknown[]; proposal: { plan_id: number; summary: string } | null }>("/ops/disruptions/check", { method: "POST" }),
    onSuccess: (r) => {
      ["disruptions", "plans"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      toast(r.proposal ? `Re-task proposal #${r.proposal.plan_id}: ${r.proposal.summary}` : "The committed plan still holds: nothing to re-task.", "INFO");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Check failed", "CRITICAL"),
  });
  const dropped = p.unmet.filter((u) => u.dropped_item_id);
  return (
    <div className="grid-2">
      <div>
        <h3 className="section-h">This plan's changes {p.plan.kind === "RETASK" && <span className="muted" style={{ fontSize: 12 }}>vs plan #{p.plan.parent_plan_id}</span>}</h3>
        {p.plan.kind !== "RETASK" && <div className="empty">This is a full plan. Re-task proposals list their changes here.</div>}
        {p.plan.kind === "RETASK" && p.plan.kpis.issues && <div className="notice" style={{ marginBottom: 8 }}>
          {p.plan.kpis.issues.slice(0, 5).map((x) => <div key={x}>◆ {x}</div>)}</div>}
        {changes.map((i) => (
          <Row key={i.id} onClick={() => onSel(i.id)} label={<><PrioPill p={i.mission.priority} /> <span className="mono">{i.mission.code.replace(/^SIM-/, "")}</span></>}
            extra={<span className="dim" style={{ fontSize: 11 }}>{i.n_aircraft} × {i.type.name} {i.base.code} {hhmm(i.launch_ts)}</span>} value={<ChangePill c={i.change} />} />
        ))}
        {dropped.map((u) => (
          <Row key={u.id} label={<><PrioPill p={u.mission.priority} /> <span className="mono">{u.mission.code.replace(/^SIM-/, "")}</span></>}
            extra={<span className="dim" style={{ fontSize: 11 }}>{u.reasons[0]?.text}</span>} value={<ChangePill c="DROPPED" />} />
        ))}
        {p.plan.kind === "RETASK" && !changes.length && !dropped.length && <div className="empty">No packages change.</div>}
      </div>
      <div>
        <h3 className="section-h">Disruptions {canPlan && <button className="btn btn-sm" disabled={check.isPending} onClick={() => check.mutate()}>{check.isPending ? "Checking…" : "Check the plan now"}</button>}</h3>
        <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>The plan is re-checked every 12 s against live (simulated) data. A broken rule becomes a disruption and a re-task proposal.</div>
        <div className="table-wrap" style={{ maxHeight: 420 }}>
          <table className="table" style={{ fontSize: 12 }}>
            <thead><tr><th>Sim time</th><th>What</th><th>Status</th><th className="right">Proposal</th></tr></thead>
            <tbody>{(d.data ?? []).map((x) => (
              <tr key={x.id}><td className="mono">{hhmm(x.ts)}</td><td style={{ whiteSpace: "normal", maxWidth: 320 }}>{x.message} <span className="dim">{label(x.kind)}</span></td>
                <td><Pill status={x.status === "RESOLVED" ? "OPERATIONAL" : x.status === "IGNORED" ? "OFF" : "WARNING"} text={label(x.status)} /></td>
                <td className="num">{x.proposal_plan_id ? <a href={`/planner?plan=${x.proposal_plan_id}`}>#{x.proposal_plan_id}</a> : "—"}{x.proposal_ms != null && <span className="dim"> {num(x.proposal_ms / 1000, 1)} s</span>}</td></tr>
            ))}</tbody>
          </table>
          {d.data?.length === 0 && <div className="empty" style={{ padding: 12 }}>No disruptions yet.</div>}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- what-if and COA comparison
interface Run { label: string; preset: string; kpis: PlanKpis; items: Record<string, { base: string; type: string; launch: string; priority: string }>;
  unmet: { code: string; priority: Priority; name: string; reason: string; example: string; fix: string }[] }
interface Compare { runs: Run[]; notes: string[]; changed: string[] }
interface Delta { kind: string; params: Record<string, string | number | string[]> }
const DEFAULTS: Record<string, Record<string, string | number>> = {
  GROUND_TYPE: { type: "Su-30MKI", count: 20, base: "" }, CLOSE_RUNWAY: { base: "VIAX", hours: 8, from_h: 0 },
  WX_FRONT: { bases: "VETZ,VEJT,VECA", cat: "IFR", hours: 8, from_h: 0 }, THREAT_ZONE: { lon: 75.2, lat: 32.6, radius_km: 50, risk: 0.9, hours: 12 },
  MISSION_SURGE: { factor: 1.5 }, FUEL_DELAY: { base: "VEHX", loss_pct: 50 }, BASE_ATTACK: { base: "VIHX", hours: 12, damage: 0.3 },
};

function CompareTable({ c }: { c: Compare }) {
  const rows: [string, (k: PlanKpis) => string][] = [
    ["Missions covered", (k) => `${k.covered} / ${k.missions}`], ...PRIOS.map((p): [string, (k: PlanKpis) => string] => [`${p} covered`, (k) => `${k.by_priority[p]?.covered ?? 0} / ${k.by_priority[p]?.of ?? 0}`]),
    ["Sorties", (k) => num(k.sorties)], ["Flying hours", (k) => num(k.flying_hours, 0)], ["ATF planned", (k) => `${num((k.fuel_l ?? 0) / 1000, 0)} kL`],
    ["Peak route risk", (k) => num(k.risk_peak, 2)], ["Solve time", (k) => `${num((k.total_ms ?? k.solve_ms) / 1000, 1)} s`],
  ];
  return (
    <>
      {c.notes.length > 0 && <div className="notice" style={{ margin: "8px 0" }}>{c.notes.map((n) => <div key={n}>◆ {n}</div>)}</div>}
      <div className="table-wrap" style={{ marginTop: 8 }}>
        <table className="table">
          <thead><tr><th>Simulated outcome</th>{c.runs.map((r) => <th key={r.label} className="right">{r.label}</th>)}</tr></thead>
          <tbody>{rows.map(([n, f]) => (
            <tr key={n}><td>{n}</td>{c.runs.map((r, i) => {
              const v = f(r.kpis), base = f(c.runs[0].kpis);
              return <td key={r.label} className="num">{i > 0 && v !== base ? <ToneText toneName="caution">{v}</ToneText> : v}</td>;
            })}</tr>
          ))}</tbody>
        </table>
      </div>
      {c.changed.length > 0 && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Packages that change base: {c.changed.map((x) => x.replace(/^SIM-/, "")).join(", ")}</div>}
      <h4 className="section-h" style={{ fontSize: 14 }}>Uncovered in "{c.runs[c.runs.length - 1].label}"</h4>
      {c.runs[c.runs.length - 1].unmet.map((u) => (
        <Row key={u.code} label={<><PrioPill p={u.priority} /> <span className="mono">{u.code.replace(/^SIM-/, "")}</span></>}
          extra={<span className="dim" style={{ fontSize: 11 }}>{u.reason}{u.example ? `: ${u.example}` : ""}</span>} value={u.fix ? <span className="s-info" style={{ fontSize: 11 }}>○ {u.fix}</span> : ""} />
      ))}
    </>
  );
}

function WhatIf({ canPlan }: { canPlan: boolean }) {
  const meta = useQuery({ queryKey: ["whatif-meta"], queryFn: () => api<{ deltas: Record<string, string>; presets: string[]; types: string[]; bases: string[] }>("/ops/whatif/meta"), staleTime: Infinity });
  const [deltas, setDeltas] = useState<Delta[]>([{ kind: "GROUND_TYPE", params: { ...DEFAULTS.GROUND_TYPE } }]);
  const run = useMutation({ mutationFn: () => api<Compare>("/ops/whatif", { method: "POST", body: { deltas: deltas.map((d) => ({
    kind: d.kind, params: { ...d.params, ...(typeof d.params.bases === "string" ? { bases: String(d.params.bases).split(",").map((x) => x.trim()).filter(Boolean) } : {}) } })),
    presets: ["BALANCED"] } }) });
  if (!canPlan) return <div className="empty">What-if analysis is for Air HQ, command HQ and the directing staff.</div>;
  const set = (i: number, k: string, v: string) => setDeltas(deltas.map((d, j) => (j === i ? { ...d, params: { ...d.params, [k]: v } } : d)));
  return (
    <div>
      <div className="muted" style={{ marginBottom: 8 }}>Change the picture, re-plan, compare. Runs on a copy: nothing is written.</div>
      {deltas.map((d, i) => (
        <div key={i} className="delta-row">
          <select className="select" value={d.kind} onChange={(e) => setDeltas(deltas.map((x, j) => (j === i ? { kind: e.target.value, params: { ...DEFAULTS[e.target.value] } } : x)))}>
            {Object.entries(meta.data?.deltas ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {Object.entries(d.params).map(([k, v]) => (
            <label key={k} className="field" style={{ minWidth: k === "bases" ? 200 : 90 }}><span className="field-label">{label(k)}</span>
              {k === "type" ? <select className="select" value={String(v)} onChange={(e) => set(i, k, e.target.value)}>{meta.data?.types.map((t) => <option key={t}>{t}</option>)}</select>
                : k === "base" ? <select className="select" value={String(v)} onChange={(e) => set(i, k, e.target.value)}><option value="">{d.kind === "GROUND_TYPE" ? "All bases" : "Choose"}</option>{meta.data?.bases.map((b) => <option key={b}>{b}</option>)}</select>
                : k === "cat" ? <select className="select" value={String(v)} onChange={(e) => set(i, k, e.target.value)}>{["MVFR", "IFR", "LIFR"].map((c) => <option key={c}>{c}</option>)}</select>
                : <input className="input" value={String(v)} onChange={(e) => set(i, k, e.target.value)} />}
            </label>
          ))}
          <button className="close" aria-label="Remove" onClick={() => setDeltas(deltas.filter((_, j) => j !== i))}>×</button>
        </div>
      ))}
      <div className="toolbar" style={{ marginTop: 8 }}>
        <button className="btn btn-sm" onClick={() => setDeltas([...deltas, { kind: "CLOSE_RUNWAY", params: { ...DEFAULTS.CLOSE_RUNWAY } }])}>Add change</button>
        <button className="btn btn-primary" disabled={run.isPending || !deltas.length} onClick={() => run.mutate()}>{run.isPending ? "Re-planning…" : "Run what-if"}</button>
      </div>
      {run.error && <ErrorText error={run.error} />}
      {run.data && <CompareTable c={run.data} />}
    </div>
  );
}

function Coa({ canPlan }: { canPlan: boolean }) {
  const [presets, setPresets] = useState<string[]>(["BALANCED", "MIN_RISK"]);
  const run = useMutation({ mutationFn: () => api<Compare>("/ops/whatif", { method: "POST", body: { deltas: [], presets } }) });
  if (!canPlan) return <div className="empty">Course-of-action comparison is for Air HQ, command HQ and the directing staff.</div>;
  return (
    <div>
      <div className="muted" style={{ marginBottom: 8 }}>The same picture planned with different priorities after coverage. Pick two or three.</div>
      <div className="toolbar">
        {["BALANCED", "MAX_COVERAGE", "MIN_RISK", "MIN_FUEL"].map((x) => (
          <label key={x} className="check"><input type="checkbox" checked={presets.includes(x)}
            onChange={() => setPresets(presets.includes(x) ? presets.filter((y) => y !== x) : [...presets, x].slice(-3))} /> {PRESET_LABEL[x]}</label>
        ))}
        <button className="btn btn-primary" disabled={run.isPending || presets.length < 2} onClick={() => run.mutate()}>{run.isPending ? "Planning…" : "Compare"}</button>
      </div>
      {run.error && <ErrorText error={run.error} />}
      {run.data && <CompareTable c={run.data} />}
    </div>
  );
}
