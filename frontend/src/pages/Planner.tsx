// Planner (PHASE2_IMPLEMENTATION_PLAN §10.2, ARCHITECTURE D55–D61). Situation cards; opening one walks it through four
// steps (Situation → Plan → Decide → Mission, features/scenarioview.tsx). "Details & tools" (landing page only) holds the
// expert views: every package and why, test an option (what-if and COA comparison), plan by hand, history.
// Decision support only: nothing reaches the sorties without an audited commit.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Fix, LiveScenario, PlanItemView, PlanKpis, PlanListRow, PlanView, Priority, User } from "../api/types";
import { ErrorText, Loading, Modal, Pill, Row, Sim, ToneText } from "../components/ui";
import { ManualTab } from "../features/manual";
import { ChangePill, Explanation, PrioPill, Unmet, hhmm } from "../features/ops";
import { PlannerFlow } from "../features/scenarioview";
import { RANK, label, num } from "../lib/format";
import { useStore } from "../store";

type Tab = "packages" | "options" | "manual" | "history";
const PRESET_LABEL: Record<string, string> = { BALANCED: "Balanced", MAX_COVERAGE: "Cover the most", MIN_RISK: "Lowest risk", MIN_FUEL: "Least fuel", STABILITY: "Fewest changes" };
const PRESETS = ["BALANCED", "MAX_COVERAGE", "MIN_RISK", "MIN_FUEL"];
const PRIOS: Priority[] = ["P1", "P2", "P3", "P4"];
const STATE: Record<string, [string, string]> = {         // plan status -> pill status, plain word
  COMMITTED: ["OPERATIONAL", "In force"], PROPOSED: ["WARNING", "Waiting for you"], APPROVED: ["WARNING", "Approved, not committed"],
  SUPERSEDED: ["RETIRED", "Replaced"], REJECTED: ["RETIRED", "Rejected"], DRAFT: ["RETIRED", "Draft"],   // neutral tone
};
const SORTIE_WORD: Record<string, string> = { PLANNED: "Planned", CREWED: "Crewed", READY: "Ready", AIRBORNE: "Flying", ON_STATION: "On station",
  RTB: "Returning", LANDED: "Landed", COMPLETED: "Done", CANCELLED: "Cancelled", ABORTED: "Aborted" };
const short = (n: string | undefined) => (n ?? "").replace(/^Air Force Station /, "");
const kindWord = (k: string) => (k === "RETASK" ? "Change to the plan" : k === "WHATIF" ? "What-if" : "Full plan");
type PlanList = { items: PlanListRow[]; committed_id: number | null; pending_retask_id: number | null; pending_id: number | null };

export function Planner({ user }: { user: User }) {
  const [params, setParams] = useSearchParams();
  const live = useQuery({ queryKey: ["scenarios", "live"], queryFn: () => api<LiveScenario[]>("/ops/scenarios/live"), refetchInterval: 5000 });
  // old links (?view=plan, ?plan=, ?item=) open the tools; ?run= opens that situation's four steps
  const tools = params.get("tools") === "1" || params.get("view") === "plan" || params.has("plan") || params.has("item");
  return (
    <div className="page">
      <h1 className="page-title">Planner <Sim title="Plans are built from simulated data" />
        <span className="muted" style={{ fontSize: 13, fontWeight: 400 }}>Decision support: a person approves every change</span></h1>
      <PlannerFlow user={user} />
      {!params.get("run") && <section className="tools">
        <button className="tools-h" aria-expanded={tools} onClick={() => setParams(tools ? {} : { tools: "1" })}>
          <span className={`chev${tools ? " open" : ""}`} aria-hidden>›</span><b>Details &amp; tools</b>
          <span className="muted">every package and why · test an option · plan by hand · history</span></button>
        {tools && <Tools user={user} live={live.data ?? []} />}
      </section>}
    </div>
  );
}

function Tools({ user, live }: { user: User; live: LiveScenario[] }) {
  const qc = useQueryClient();
  const toast = useStore((s) => s.toast);
  const [params, setParamsRaw] = useSearchParams();
  const setParams = (p: Record<string, string>) => setParamsRaw({ tools: "1", ...p });   // keep the tools open
  const [tab, setTab] = useState<Tab>("packages");
  const [preset, setPreset] = useState("BALANCED");
  const [sel, setSel] = useState<{ kind: "item" | "unmet"; id: number } | null>(params.get("item") ? { kind: "item", id: Number(params.get("item")) } : null);
  const canPlan = user.role === "ADMIN" || user.role === "COMMAND_HQ";
  const split = useMutation({                   // D42: apply a checked split fix to an uncovered mission
    mutationFn: ({ id, f }: { id: number; f: Fix }) => api<{ parts: { id: number; code: string }[] }>(`/ops/missions/${id}/split`,
      { method: "POST", body: { kind: f.kind, parts: f.parts, t0: f.t0, sizes: f.sizes ?? null } }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["missions"] }); toast(`Split into ${r.parts.map((x) => x.code).join(", ")}. Re-plan to cover them.`, "INFO"); },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Split failed", "CRITICAL"),
  });
  const list = useQuery({ queryKey: ["plans", "list"], queryFn: () => api<PlanList>("/ops/plans?limit=25"), refetchInterval: 10000 });
  const want = params.get("plan");
  // what the tools show: the proposal waiting for a decision, else the plan in force (History opens any other)
  const pid = want && want !== "current" ? Number(want) : list.data?.pending_id ?? list.data?.committed_id ?? list.data?.items[0]?.id;
  const plan = useQuery({ queryKey: ["plan", pid], queryFn: () => api<PlanView>(`/ops/plans/${pid}`), enabled: !!pid, refetchInterval: 15000 });
  const p = plan.data;

  const invalidate = () => ["plans", "plan", "missions", "ops-summary", "ops-routes", "disruptions", "summary", "situation"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const open = (id: number | null) => { setParams(id ? { plan: String(id) } : {}); setSel(null); setTab("packages"); };
  const gen = useMutation({
    mutationFn: (pr: string) => api<{ plan_id: number; kpis: PlanKpis }>("/ops/plans", { method: "POST", body: { preset: pr } }),
    onSuccess: (r) => {
      open(null);
      invalidate();
      toast(`New plan proposed: ${r.kpis.covered} of ${r.kpis.missions} missions covered. Commit or reject it above.`, "INFO");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Planning failed", "CRITICAL"),
  });

  const item = sel?.kind === "item" ? p?.items.find((i) => i.id === sel.id) : undefined;
  const unmet = sel?.kind === "unmet" ? p?.unmet.find((u) => u.id === sel.id) : undefined;
  const st = p?.plan.status ?? "";
  const showing = !p ? "" : ["PROPOSED", "APPROVED"].includes(st) ? (p.plan.kind === "RETASK" ? "the change waiting for your decision" : "the new plan waiting for your decision")
    : st === "COMMITTED" ? "the plan in force" : `an older ${kindWord(p.plan.kind).toLowerCase()} from ${hhmm(p.plan.created_at)} (${(STATE[st]?.[1] ?? label(st)).toLowerCase()})`;

  return (
    <div className="tools-body">
      {list.isLoading && <Loading />}
      {plan.error && <ErrorText error={plan.error} />}
      <div className="tools-bar">
        {p && <span className="muted">Showing {showing}{want && want !== "current" && <> · <a href="#" onClick={(e) => { e.preventDefault(); open(null); }}>back to the current plan</a></>}</span>}
        {p && st === "COMMITTED" && <a className="btn btn-sm" href={`/planner/ato/${p.plan.id}`}>Air tasking order</a>}
        <span className="topbar-spacer" />
        {canPlan && <>
          <select className="select" aria-label="Plan for" value={preset} onChange={(e) => setPreset(e.target.value)} title="What the planner prefers once every mission it can cover is covered">
            {PRESETS.map((x) => <option key={x} value={x}>{PRESET_LABEL[x]}</option>)}
          </select>
          <button className="btn" disabled={gen.isPending} onClick={() => confirm("Plan everything still to fly from scratch? You get a proposal; nothing changes until you commit.") && gen.mutate(preset)}>
            {gen.isPending ? "Planning…" : "Re-plan everything"}</button>
        </>}
      </div>

      {p && <>
        <div className="tabs" role="tablist">
          {([["packages", `Every package (${p.items.length}${p.unmet.length ? ` · ${p.unmet.length} not covered` : ""})`], ["options", "Test an option"],
            ["manual", "Plan by hand"], ["history", "History"]] as [Tab, string][]).map(([k, n]) => (
            <button key={k} role="tab" aria-selected={tab === k} className={`tab${tab === k ? " on" : ""}`} onClick={() => setTab(k)}>{n}</button>
          ))}
        </div>

        {tab === "packages" && (
          <div className="planner-grid two">
            <Packages p={p} sel={sel} onSel={setSel} />
            <aside className="plan-detail">
              {!sel && <div className="empty">Pick a package to see why the planner chose it, or a mission that isn't covered to see what would fix it.</div>}
              {item && <ItemDetail it={item} plan={p} user={user} />}
              {unmet && <>
                <div className="detail-title"><PrioPill p={unmet.mission.priority} /> {unmet.mission.name}
                  {unmet.dropped_item_id ? <ChangePill c="DROPPED" /> : <ToneText toneName="caution">Not covered</ToneText>}</div>
                <div className="muted" style={{ marginBottom: 8 }}><span className={`tag${unmet.mission.exercise_run_id ? " scn" : ""}`}>{unmet.mission.tag}</span>{" "}
                  <span className="mono dim">{unmet.mission.code.replace(/^SIM-/, "")}</span></div>
                <Unmet m={unmet.mission} reasons={unmet.reasons} fixes={unmet.fixes} busy={split.isPending}
                  onApply={canPlan ? (f) => confirm(`${f.text}?\n\nThis replaces ${unmet.mission.code} with ${f.parts} missions. Re-plan afterwards.`)
                    && split.mutate({ id: unmet.mission.id, f }) : undefined} />
              </>}
            </aside>
          </div>
        )}
        {tab === "options" && <TestOption canPlan={canPlan} live={live} />}
        {tab === "manual" && <ManualTab canPlan={canPlan} />}
        {tab === "history" && <History rows={list.data?.items ?? []} shown={pid} canPlan={canPlan} onOpen={open} />}
      </>}
    </div>
  );
}

/** Packages grouped by who asked for them: not covered first, then each scenario, then routine tasking. */
function Packages({ p, sel, onSel }: { p: PlanView; sel: { kind: string; id: number } | null; onSel: (s: { kind: "item" | "unmet"; id: number }) => void }) {
  const retask = p.plan.kind === "RETASK";
  const groups = useMemo(() => {
    const by = new Map<string, PlanItemView[]>();
    for (const i of p.items) by.set(i.mission.tag, [...(by.get(i.mission.tag) ?? []), i]);
    const rank = (i: PlanItemView) => (retask && i.change && i.change !== "KEPT" ? 0 : 1);
    return [...by.entries()].sort(([a], [b]) => (a === "Routine" ? 1 : b === "Routine" ? -1 : a.localeCompare(b)))
      .map(([tag, xs]) => [tag, [...xs].sort((a, b) => rank(a) - rank(b) || PRIOS.indexOf(a.mission.priority) - PRIOS.indexOf(b.mission.priority)
        || a.launch_ts.localeCompare(b.launch_ts))] as [string, PlanItemView[]]);
  }, [p, retask]);
  const un = [...p.unmet].sort((a, b) => PRIOS.indexOf(a.mission.priority) - PRIOS.indexOf(b.mission.priority));
  return (
    <div className="mission-col">
      {un.length > 0 && <>
        <div className="col-h"><span className="s-caution">▲ Not covered</span><span className="dim mono">{un.length}</span></div>
        {un.map((u) => (
          <button key={`u${u.id}`} className={`mission-row unmet${sel?.kind === "unmet" && sel.id === u.id ? " on" : ""}`} onClick={() => onSel({ kind: "unmet", id: u.id })}>
            <span className="top"><span><PrioPill p={u.mission.priority} /> {u.mission.name}</span>{u.mission.exercise_run_id ? <span className="tag scn">{u.mission.tag}</span> : null}</span>
            <span className="s-caution" style={{ fontSize: 11 }}>{u.dropped_item_id ? "dropped by this change" : u.reasons[0]?.text ?? "no package fits"}</span>
          </button>
        ))}
      </>}
      {groups.map(([tag, xs]) => (
        <div key={tag}>
          <div className="col-h"><span className={tag === "Routine" ? "" : "s-warning"}>{tag === "Routine" ? "Routine tasking" : tag}</span><span className="dim mono">{xs.length}</span></div>
          {xs.map((i) => (
            <button key={i.id} className={`mission-row${sel?.kind === "item" && sel.id === i.id ? " on" : ""}`} onClick={() => onSel({ kind: "item", id: i.id })}>
              <span className="top"><span><PrioPill p={i.mission.priority} /> {i.mission.name}</span>
                {retask && i.change && i.change !== "KEPT" ? <ChangePill c={i.change} />
                  : <span className="st">{i.sortie ? SORTIE_WORD[i.sortie.status] ?? label(i.sortie.status) : retask ? "Unchanged" : "Proposed"}</span>}</span>
              <span className="dim" style={{ fontSize: 11 }}>{i.n_aircraft} × {i.type.name} · {short(i.base.name)} · {hhmm(i.launch_ts)}{i.support ? " · with tanker" : ""}</span>
            </button>
          ))}
        </div>
      ))}
      {!p.items.length && !un.length && <div className="empty">No packages in this plan.</div>}
    </div>
  );
}

function ItemDetail({ it, plan, user }: { it: PlanItemView; plan: PlanView; user: User }) {
  const [swap, setSwap] = useState(false);
  const canSwap = ["PROPOSED", "APPROVED"].includes(plan.plan.status) && (user.role === "ADMIN" || (user.role === "BASE_COMMANDER" && user.base_id === it.base.id));
  const w = it.score?.weapons ?? {};
  const back = it.recovery_base && it.recovery_base.id !== it.base.id ? ` at ${short(it.recovery_base.name)}` : "";
  return (
    <>
      <div className="detail-title"><PrioPill p={it.mission.priority} /> {it.mission.name} {it.change && it.change !== "KEPT" && <ChangePill c={it.change} />}</div>
      <div className="muted" style={{ marginBottom: 8 }}><span className={`tag${it.mission.exercise_run_id ? " scn" : ""}`}>{it.mission.tag}</span>{" "}
        <span className="mono dim">{it.mission.code.replace(/^SIM-/, "")}</span>{it.sortie && <> · {SORTIE_WORD[it.sortie.status] ?? label(it.sortie.status)}</>}</div>
      <p className="pk-say">{it.n_aircraft} × {it.type.name} from {short(it.base.name)}: launch {hhmm(it.launch_ts)}
        {it.on_station_ts ? `, on station ${hhmm(it.on_station_ts)}` : ""}, back{back} {hhmm(it.recovery_ts)} IST.
        {it.support ? ` A ${it.support.type?.name ?? "tanker"} from ${short(it.support.base?.name)} refuels it at ${hhmm(it.support.rv_start)}.` : ""}</p>
      {canSwap && <div className="toolbar" style={{ marginBottom: 8 }}><button className="btn btn-sm" onClick={() => setSwap(true)}>Swap tails or crew</button></div>}
      <h4 className="section-h" style={{ fontSize: 14 }}>Why this package</h4>
      <Explanation it={it} />
      <details className="pk-more"><summary>Tails and crew</summary>
        <Row label="Tails" value={<span className="mono">{it.aircraft.map((a) => a.tail_no).join(", ")}</span>}
          extra={it.score?.snag ? <span className="dim" style={{ fontSize: 11 }}>
            predicted defect risk {it.aircraft.map((a) => `${Math.round(100 * (it.score!.snag!.tails[a.tail_no] ?? 0))}%`).join(" · ")}</span> : undefined} />
        {it.crew.map((c) => <Row key={c.id} label={label(c.position)} value={`${RANK[c.rank] ?? c.rank} ${c.name}`} extra={c.callsign ? <span className="mono dim">{c.callsign}</span> : undefined} />)}
        {Object.keys(w).length > 0 && <Row label="Weapons (generic)" value={Object.entries(w).map(([k, v]) => `${v} ${k.replace("ARMAMENT_", "").replace(/_/g, "-")}`).join(", ")} />}
        {it.sortie && <Row label="Sortie" value={<><span className="mono">{it.sortie.code}</span> <Pill status={it.sortie.status} /></>} />}
      </details>
      {it.support && <details className="pk-more"><summary>Tanker</summary>
        <Row label="Tanker" value={`1 × ${it.support.type?.name ?? "tanker"}`} extra={<span className="mono">{it.support.base?.code}</span>} />
        <Row label="Launch · on track · recover" value={`${hhmm(it.support.launch_ts)} · ${hhmm(it.support.rv_start)}–${hhmm(it.support.rv_end)} · ${hhmm(it.support.recovery_ts)}`} />
        <Row label="Refuelling point" value={<span className="mono">{it.support.rv[1].toFixed(2)}, {it.support.rv[0].toFixed(2)}</span>} />
        <Row label="Tanker tail" value={<span className="mono">{it.support.aircraft.map((a) => a.tail_no).join(", ")}</span>} />
        {it.support.crew.filter((c) => c.position === "CAPTAIN").map((c) => <Row key={c.id} label="Tanker captain" value={`${RANK[c.rank] ?? c.rank} ${c.name}`} />)}
        {it.support.sortie && <Row label="Tanker sortie" value={<><span className="mono">{it.support.sortie.code}</span> <Pill status={it.support.sortie.status} /></>} />}
      </details>}
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

/** Every plan, newest first, with what made it: the replacement for the disruptions table. */
function History({ rows, shown, canPlan, onOpen }: { rows: PlanListRow[]; shown: number | undefined; canPlan: boolean; onOpen: (id: number) => void }) {
  const qc = useQueryClient();
  const toast = useStore((s) => s.toast);
  const check = useMutation({
    mutationFn: () => api<{ proposal: { plan_id: number; summary: string } | null }>("/ops/disruptions/check", { method: "POST" }),
    onSuccess: (r) => {
      ["disruptions", "plans", "situation"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      toast(r.proposal ? `A change to the plan is proposed: ${r.proposal.summary}. Decide on it at the top.` : "The plan in force still holds: nothing to change.", "INFO");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Check failed", "CRITICAL"),
  });
  return (
    <div>
      <div className="toolbar" style={{ marginBottom: 8 }}>
        <span className="muted" style={{ fontSize: 12 }}>The plan in force is re-checked against the live (simulated) picture every 12 s. When a rule breaks, the planner proposes a change at the top of the page.</span>
        <span className="topbar-spacer" />
        {canPlan && <button className="btn btn-sm" disabled={check.isPending} onClick={() => check.mutate()}>{check.isPending ? "Checking…" : "Re-check now"}</button>}
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Time (IST)</th><th>Plan</th><th>Why</th><th>Result</th><th>State</th></tr></thead>
          <tbody>{rows.filter((r) => r.kind !== "WHATIF").map((r) => (
            <tr key={r.id} className={`clickable${r.id === shown ? " on" : ""}`} onClick={() => onOpen(r.id)}>
              <td className="mono">{hhmm(r.created_at)}</td>
              <td>{kindWord(r.kind)}</td>
              <td style={{ whiteSpace: "normal" }}>{r.why ?? <span className="muted">{r.kind === "RETASK" ? "re-plan of every package still to fly"
                : `full plan for the next 24 hours${r.created_by ? `, by ${r.created_by}` : ""}`}</span>}</td>
              <td style={{ whiteSpace: "normal" }}>{r.kind === "RETASK" ? r.summary : r.kpis ? `${r.kpis.covered} of ${r.kpis.missions} covered` : r.summary}</td>
              <td><Pill status={STATE[r.status]?.[0] ?? "RETIRED"} text={STATE[r.status]?.[1] ?? label(r.status)} /></td>
            </tr>
          ))}</tbody>
        </table>
        {!rows.length && <div className="empty" style={{ padding: 12 }}>No plans yet.</div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- test an option (what-if and COA comparison in one)
interface Run { label: string; preset: string; kpis: PlanKpis; items: Record<string, { base: string; type: string; launch: string; priority: string }>;
  unmet: { code: string; priority: Priority; name: string; reason: string; example: string; fix: string }[] }
interface Compare { runs: Run[]; notes: string[]; changed: string[] }
interface Delta { kind: string; params: Record<string, string | number | string[]> }
const DEFAULTS: Record<string, Record<string, string | number>> = {
  GROUND_TYPE: { type: "Su-30MKI", count: 20, base: "" }, CLOSE_RUNWAY: { base: "VIAX", hours: 8, from_h: 0 },
  WX_FRONT: { bases: "VETZ,VEJT,VECA", cat: "IFR", hours: 8, from_h: 0 }, THREAT_ZONE: { lon: 75.2, lat: 32.6, radius_km: 50, risk: 0.9, hours: 12 },
  MISSION_SURGE: { factor: 1.5 }, FUEL_DELAY: { base: "VEHX", loss_pct: 50 }, BASE_ATTACK: { base: "VIHX", hours: 12, damage: 0.3 },
};

function CompareTable({ c, withChange }: { c: Compare; withChange: boolean }) {
  const name = (r: Run) => (r.label === "Baseline" ? "Without the change" : r.label === "What-if" ? `With the change (${PRESET_LABEL[r.preset] ?? r.preset})`
    : `${PRESET_LABEL[r.preset] ?? r.label}${withChange ? ", with the change" : ""}`);
  const rows: [string, (k: PlanKpis) => string][] = [
    ["Missions covered", (k) => `${k.covered} of ${k.missions}`], ["P1 covered", (k) => `${k.by_priority.P1?.covered ?? 0} of ${k.by_priority.P1?.of ?? 0}`],
    ["P2 covered", (k) => `${k.by_priority.P2?.covered ?? 0} of ${k.by_priority.P2?.of ?? 0}`], ["Sorties", (k) => num(k.sorties)],
    ["Fuel (ATF)", (k) => `${num((k.fuel_l ?? 0) / 1000, 0)} kL`], ["Highest route risk", (k) => num(k.risk_peak, 2)],
  ];
  const last = c.runs[c.runs.length - 1];
  return (
    <>
      {c.notes.length > 0 && <div className="notice" style={{ margin: "8px 0" }}>{c.notes.map((n) => <div key={n}>◆ {n}</div>)}</div>}
      <div className="table-wrap" style={{ marginTop: 8 }}>
        <table className="table">
          <thead><tr><th>Simulated outcome</th>{c.runs.map((r) => <th key={r.label} className="right">{name(r)}</th>)}</tr></thead>
          <tbody>{rows.map(([n, f]) => (
            <tr key={n}><td>{n}</td>{c.runs.map((r, i) => {
              const v = f(r.kpis), base = f(c.runs[0].kpis);
              return <td key={r.label} className="num">{i > 0 && v !== base ? <ToneText toneName="caution">{v}</ToneText> : v}</td>;
            })}</tr>
          ))}</tbody>
        </table>
      </div>
      {c.changed.length > 0 && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Packages that move to another base: {c.changed.map((x) => x.replace(/^SIM-/, "")).join(", ")}</div>}
      {last.unmet.length > 0 && <>
        <h4 className="section-h" style={{ fontSize: 14 }}>Not covered in "{name(last)}"</h4>
        {last.unmet.map((u) => (
          <Row key={u.code} label={<><PrioPill p={u.priority} /> {u.name}</>}
            extra={<span className="dim" style={{ fontSize: 11 }}>{u.reason}{u.example ? `: ${u.example}` : ""}</span>} value={u.fix ? <span className="s-info" style={{ fontSize: 11 }}>○ {u.fix}</span> : ""} />
        ))}
      </>}
    </>
  );
}

/** What-if and course-of-action comparison in one: optionally change the picture, plan it one to three ways, compare. */
function TestOption({ canPlan, live }: { canPlan: boolean; live: LiveScenario[] }) {
  const meta = useQuery({ queryKey: ["whatif-meta"], queryFn: () => api<{ deltas: Record<string, string>; presets: string[]; types: string[]; bases: string[] }>("/ops/whatif/meta"), staleTime: Infinity });
  const [deltas, setDeltas] = useState<Delta[]>([]);
  const [presets, setPresets] = useState<string[]>(["BALANCED"]);
  const run = useMutation({ mutationFn: () => api<Compare>("/ops/whatif", { method: "POST", body: { deltas: deltas.map((d) => ({
    kind: d.kind, params: { ...d.params, ...(typeof d.params.bases === "string" ? { bases: String(d.params.bases).split(",").map((x) => x.trim()).filter(Boolean) } : {}) } })),
    presets } }) });
  if (!canPlan) return <div className="empty">Testing options is for Air HQ and the directing staff.</div>;
  const set = (i: number, k: string, v: string) => setDeltas(deltas.map((d, j) => (j === i ? { ...d, params: { ...d.params, [k]: v } } : d)));
  const ready = deltas.length > 0 || presets.length > 1;
  return (
    <div className="opt">
      <p className="muted" style={{ marginTop: 0 }}>Try something before it happens. The planner re-plans a copy of today's picture{live.length ? ` (with ${live.map((r) => r.name).join(", ")} live)` : ""} and
        shows what it would cover. Nothing is written.</p>
      <h4 className="section-h" style={{ fontSize: 14 }}>1 · What if… <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>optional</span></h4>
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
      <button className="btn btn-sm" style={{ marginTop: 6 }} onClick={() => setDeltas([...deltas, { kind: "CLOSE_RUNWAY", params: { ...DEFAULTS.CLOSE_RUNWAY } }])}>Add a change</button>
      <h4 className="section-h" style={{ fontSize: 14 }}>2 · Plan it as <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>pick up to three to compare</span></h4>
      <div className="toolbar">
        {PRESETS.map((x) => (
          <label key={x} className="check"><input type="checkbox" checked={presets.includes(x)}
            onChange={() => setPresets(presets.includes(x) ? presets.filter((y) => y !== x) : [...presets, x].slice(-3))} /> {PRESET_LABEL[x]}</label>
        ))}
        <span className="topbar-spacer" />
        <button className="btn btn-primary" disabled={run.isPending || !ready || !presets.length} onClick={() => run.mutate()}
          title={ready ? undefined : "Add a change, or pick two ways to plan"}>{run.isPending ? "Re-planning…" : "Run"}</button>
      </div>
      {!ready && <div className="muted" style={{ fontSize: 12 }}>Add a change, or pick two ways to plan, then Run.</div>}
      {run.error && <ErrorText error={run.error} />}
      {run.data && <CompareTable c={run.data} withChange={deltas.length > 0} />}
    </div>
  );
}
