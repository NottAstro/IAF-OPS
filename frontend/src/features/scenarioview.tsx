// The Planner (ARCHITECTURE D55, D56, D59, D60, D61). The landing page is one card per situation (each live scenario and
// routine tasking). Opening a card walks that one situation through four steps, with nothing else on screen:
//   1 Situation: what happened and what it means for the plan
//   2 Plan: for each impact the planner's recommendation and why, its other options, and a pick of your own (checked with
//     the planner's rules, decide/choose.py); fixes; stock to move
//   3 Decide: only what you decided
//   4 Mission: approve it (commit; stock moves leave) and watch it become missions
// Values come from /ops/scenarios/situation and the plan under review; a plan is committed or rejected as one (D40).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Assessment, Fix, Impact, ImpactChange, Intensity, MissionOptions, PlanItemView, PlanView, ScenarioBlock, Situation, TransferMove, User, When } from "../api/types";
import { ErrorText, Loading, Sim } from "../components/ui";
import { istTime } from "../lib/format";
import { useStore } from "../store";

export const INT_COLOUR: Record<Intensity, string> = { LOW: "var(--ok)", MEDIUM: "var(--caution)", HIGH: "var(--warning)", SEVERE: "var(--critical)" };
const INT_N: Record<Intensity, number> = { LOW: 1, MEDIUM: 2, HIGH: 3, SEVERE: 4 };
const SEV: Record<string, [string, string]> = { c: ["■", "var(--critical)"], w: ["◆", "var(--warning)"], y: ["▲", "var(--caution)"], n: ["—", "var(--text-3)"] };
const REQ: Record<string, [string, string]> = { met: ["✓ available", "var(--ok)"], approve: ["once approved", "var(--warning)"], wait: ["waiting", "var(--caution)"] };

/** Intensity as four dots (colour plus count, never colour alone). */
export const IntensityDots = ({ i }: { i: Intensity | null | undefined }) => (
  <span className="int-dots" title={i ? `${i.toLowerCase()} intensity` : undefined}>
    {[1, 2, 3, 4].map((k) => <i key={k} style={i && k <= INT_N[i] ? { background: INT_COLOUR[i] } : undefined} />)}
  </span>
);

const hh = (d: string | undefined | null) => (d ? istTime(d).replace(" IST", "") : "—");
export const mins = (m: number) => (m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`);

function whenText(w: When | null): [string, boolean] {
  if (!w) return ["—", false];
  if (w.kind === "airborne") return [`airborne · lands ${hh(w.b)}`, true];
  if (w.kind === "on_station") return [`on station · until ${hh(w.b)}`, true];
  if (w.kind === "done") return ["done", false];
  if (w.kind === "at") return [hh(w.a), false];
  return [`${hh(w.a)} – ${hh(w.b)}`, false];
}

const qtyText = (m: { kind: string; qty: number; label: string }) =>
  m.kind === "FUEL" ? `${Math.round(m.qty / 1000)} kL ATF` : `${Math.round(m.qty)} × ${m.label.toLowerCase()}`;

// ---------------------------------------------------------------- situations
interface Sit { key: string; run: ScenarioBlock["run"] | null; name: string; lead: string; timeline: ScenarioBlock["timeline"];
  impacts: Impact[]; bases: number[]; colour: string; analysis: Assessment | null; over: boolean; overSince: string | null }
/** An item to decide: a scenario impact, enriched by the impact assessment (D62) when there is one. */
type Task = Impact & { blocked?: string; ch?: ImpactChange }

const PRIO_SEV: Record<string, Impact["sev"]> = { P1: "c", P2: "w", P3: "y", P4: "n" };
const CHANGED: Record<string, string> = { new: "the planner adds it", moved: "the planner moves it", "tails / crew swapped": "the planner gives it other aircraft or crew",
  divert: "an airborne package diverts", "re-roled in flight": "an airborne package is re-roled to it" };

/** Each live scenario, then routine tasking (the routine missions the plan changes or can't cover). */
function situations(s: Situation): Sit[] {
  const out: Sit[] = s.scenarios.map((b) => ({ key: String(b.run.id), run: b.run, name: b.run.name, lead: b.lead, timeline: b.timeline,
    impacts: b.impacts, bases: b.bases ?? [], colour: b.run.intensity ? INT_COLOUR[b.run.intensity] : "var(--text-3)",
    analysis: b.analysis ?? null, over: !!b.over, overSince: b.over_since ?? null }));
  const changed: Impact[] = s.missions.filter((m) => !m.run_id && m.change && m.status !== "uncovered").map((m) => ({
    sev: PRIO_SEV[m.priority] ?? "y", what: m.name, sub: CHANGED[m.change ?? ""] ?? `the planner changes it (${m.change})`, rec: m.package ?? "—", alts: [],
    when: m.when, status: m.status === "proposed" ? "proposed" : "in", mission_id: m.mission_id, mission: m.code, priority: m.priority }));
  out.push({ key: "routine", run: null, name: "Routine tasking", lead: "Daily patrols, training, airlift and ISR, planned alongside every scenario.",
    timeline: [], impacts: [...changed, ...s.impacts.filter((x) => (x.scenario ?? "Routine") === "Routine")], bases: [], colour: "var(--text-3)",
    analysis: null, over: false, overSince: null });
  return out;
}

function tally(x: Sit) {
  const act = x.impacts.filter((i) => i.status !== "info");
  return { act, effects: x.impacts.filter((i) => i.status === "info"),
    review: act.filter((i) => i.status === "proposed" || i.status === "apply").length,
    uncovered: act.filter((i) => i.status === "uncovered").length, waiting: act.filter((i) => i.status === "waiting").length,
    airborne: act.filter((i) => i.when && (i.when.kind === "airborne" || i.when.kind === "on_station")).length };
}

/** The items to decide. With an impact assessment, each change it found becomes one item that says what the mission was,
 * why it can't stay, and what the plan under review does now; impacts it doesn't cover follow. */
function buildTasks(sit: Sit, act: Impact[], plan: PlanView | undefined): Task[] {
  const a = sit.analysis;
  if (!a) return act;
  const cur = new Map(act.filter((x) => x.mission_id).map((x) => [x.mission_id!, x]));
  const out: Task[] = a.changes.map((c) => {
    const now = cur.get(c.mission_id);
    const pi = plan?.items.find((i) => i.mission.id === c.mission_id);
    const was = c.before ? `it was planned as ${c.before.n} × ${c.before.type} from ${c.before.base} at ${hh(c.before.launch)}` : "";
    const what = c.kind === "added" ? `New ${c.priority} mission: ${c.name}` : c.kind === "dropped" ? `${c.name} can't be flown`
      : c.reason_code === "CAPACITY_CONFLICT" || c.reason_code === "RETIMED" ? `${c.name} has to change`
      : c.after && c.before && c.after.base === c.before.base ? `${c.name} can't launch at ${hh(c.before.launch)}`
      : `${c.name} can't launch from ${c.before?.base}`;
    const status: Impact["status"] = now?.status ?? (pi ? (plan?.plan.status === "COMMITTED" ? "in" : "proposed") : "uncovered");
    const rec = now?.rec ?? (pi ? `${pi.n_aircraft} × ${pi.type.name} from ${pi.base.name.replace("Air Force Station ", "")}`
      : c.after ? `${c.after.n} × ${c.after.type} from ${c.after.base}` : "Not flown");
    return { sev: PRIO_SEV[c.priority] ?? "y", what, sub: `${c.priority} · needed ${hh(c.window[0])}–${hh(c.window[1])}${was ? ` · ${was}` : ""}`,
      rec, alts: now?.alts ?? [], when: now?.when ?? (pi ? { kind: "window", a: pi.launch_ts, b: pi.recovery_ts } : null), status,
      mission_id: c.mission_id, mission: c.code, priority: c.priority, fix: now?.fix, ch: c,
      blocked: c.kind === "added" ? undefined : c.reason ?? undefined };
  });
  const seen = new Set(a.changes.map((c) => c.mission_id));
  return [...out, ...act.filter((x) => !x.mission_id || !seen.has(x.mission_id))];
}

/** "Why" in words, from the package's own explanation (D62): what the base had free, time to station, route risk,
 * weather, and whether the base's fuel stays above reserve. */
function whyText(it: PlanItemView | undefined): string {
  if (!it?.explanation) return "";
  const rows = it.explanation.rows;
  const v = (l: string) => rows.find((r) => r.label === l)?.value;
  const imp = it.explanation.impact as { free?: { aircraft: number; pilots: number; type: string; base: string };
    fuel?: { base: string; after_pct: number; reserve_pct: number } };
  const parts: string[] = [];
  if (imp?.free) parts.push(`${imp.free.base} had ${imp.free.aircraft} ${imp.free.type} and ${imp.free.pilots} rested, qualified pilots free`);
  if (v("Transit")) parts.push(`${v("Transit")} to station`);
  const rk = parseFloat((v("Route risk") ?? "").replace("peak ", ""));
  if (!Number.isNaN(rk)) parts.push(`route risk ${rk < 0.2 ? "low" : rk < 0.5 ? "medium" : "high"}`);
  if (v("Weather")) parts.push(v("Weather")!);
  if (imp?.fuel) parts.push(imp.fuel.after_pct >= imp.fuel.reserve_pct
    ? `fuel there stays above reserve (${Math.round(imp.fuel.after_pct)}% after, reserve ${Math.round(imp.fuel.reserve_pct)}%)`
    : `fuel there drops below reserve (${Math.round(imp.fuel.after_pct)}%)`);
  return (rows[0]?.label === "Chosen by" ? "your pick, checked against every rule · " : "") + parts.join(" · ");
}

// ---------------------------------------------------------------- decisions (per plan and situation, this browser only)
type Decision = "keep" | "choice" | "accept" | "fix" | "approve" | "skip";
const taskKey = (t: Task, k: number) => (t.mission_id ? `m${t.mission_id}` : `i${k}`);

function useDecisions(planId: number | undefined, sit: string): [Record<string, Decision>, (k: string, d: Decision | null) => void] {
  const sk = `airops.planner.decisions.${planId ?? 0}.${sit}`;
  const read = () => { try { return JSON.parse(sessionStorage.getItem(sk) ?? "{}") as Record<string, Decision>; } catch { return {}; } };
  const [dec, setDec] = useState<Record<string, Decision>>(read);
  useEffect(() => setDec(read()), [sk]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k: string, d: Decision | null) => setDec((cur) => {
    const next = { ...cur };
    if (d) next[k] = d; else delete next[k];
    try { sessionStorage.setItem(sk, JSON.stringify(next)); } catch { /* private window: decisions last until reload */ }
    return next;
  });
  return [dec, set];
}

// ---------------------------------------------------------------- the page
export function PlannerFlow({ user }: { user: User }) {
  const qc = useQueryClient();
  const toast = useStore((s) => s.toast);
  const [params, setParams] = useSearchParams();
  const q = useQuery({ queryKey: ["situation", null], queryFn: () => api<Situation>("/ops/scenarios/situation"), refetchInterval: 6000 });
  const canPlan = user.role === "ADMIN" || user.role === "COMMAND_HQ";
  const generate = useMutation({
    mutationFn: () => api<{ plan_id: number }>("/ops/plans", { method: "POST", body: { preset: "BALANCED" } }),
    onSuccess: () => { ["situation", "plans", "plan"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); toast("Plan ready for the current situation", "INFO"); },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Planning failed", "CRITICAL"),
  });
  if (q.isLoading) return <Loading />;
  if (!q.data) return <ErrorText error={q.error} />;
  const s = q.data;
  if (!s.runs.length && !s.plan) return <Guide canPlan={canPlan} onPlan={() => generate.mutate()} busy={generate.isPending} />;
  const sits = situations(s);
  const key = params.get("run");
  const cur = key ? sits.find((x) => x.key === key) : undefined;
  if (key && !cur) return <div className="live-empty"><h2>That scenario has ended</h2><p className="muted">Its missions were withdrawn.</p>
    <button className="btn" onClick={() => setParams({})}>← All situations</button></div>;
  const step = Math.min(4, Math.max(1, Number(params.get("step") ?? 1)));
  return cur
    ? <SituationFlow s={s} sits={sits} sit={cur} step={step} user={user} go={(n) => setParams({ run: cur.key, step: String(n) })} back={() => setParams({})} />
    : <Landing s={s} sits={sits} canPlan={canPlan} open={(k) => setParams({ run: k, step: "1" })} />;
}

function Landing({ s, sits, canPlan, open }: { s: Situation; sits: Sit[]; canPlan: boolean; open: (k: string) => void }) {
  return (
    <div>
      <p className="live-lead" style={{ marginTop: 0 }}>{s.decision ? <><b>The planner has a proposal waiting for your decision.</b> Open a situation to review it.</>
        : s.in_force ? <>Plan in force since {hh(s.in_force.since)}{s.in_force.flying ? `, ${s.in_force.flying} aircraft airborne` : ""}. Open a situation to see how it is answered.</>
        : "Open a situation to see how the planner answers it."} <Sim title="Everything here is simulated" /></p>
      <div className="sit-cards">
        {sits.map((x) => <SitCard key={x.key} x={x} same={x.run ? 0 : s.routine_unchanged} onOpen={() => open(x.key)} />)}
        {canPlan && <Link className="sit-card add" to="/scenarios"><span>+</span>Start a scenario</Link>}
      </div>
    </div>
  );
}

function SitCard({ x, same, onOpen }: { x: Sit; same: number; onOpen: () => void }) {
  const t = tally(x);
  const [tone, line] = x.over ? ["dim", `Over since ${hh(x.overSince)}. Open it to review what it did.`]
    : t.review ? ["warn", `◆ The planner proposes ${t.review} change${t.review > 1 ? "s" : ""}. Needs your review.`]
    : t.waiting ? ["info", "The planner is working out a plan…"]
    : t.uncovered ? ["crit", `■ ${t.uncovered} mission${t.uncovered > 1 ? "s" : ""} not covered`]
    : t.act.length === 0 ? ["ok", "✓ Nothing in the plan is affected"]
    : ["ok", `✓ Planned${t.airborne ? ` · ${t.airborne} airborne` : ""}`];
  return (
    <button className={`sit-card${x.run ? "" : " routine"}`} onClick={onOpen}>
      <h3><span className="dot" style={{ background: x.colour }} />{x.name}
        {x.run ? <span className="chip mono">since {hh(x.run.started_sim)}</span> : <span className="chip">today</span>}</h3>
      <p>{x.lead}</p>
      {x.analysis && <p className="brief1">{x.analysis.brief[0]}</p>}
      {t.effects.length > 0 && <div className="chips">{t.effects.slice(0, 3).map((e, k) => <span key={k} className="chip">{e.what}</span>)}</div>}
      {!x.run && <div className="chips"><span className="chip">{same} planned as usual</span>{t.uncovered > 0 && <span className="chip">{t.uncovered} not covered</span>}</div>}
      <div className={`sit-state ${tone}`}>{line}</div>
      <div className="foot"><span className="dim">{t.act.length} item{t.act.length === 1 ? "" : "s"} in the plan</span><span className="btn btn-sm btn-primary">Open →</span></div>
    </button>
  );
}

// ---------------------------------------------------------------- one situation, four steps
const STEPS: [string, string][] = [["Situation", "what happened"], ["Plan", "recommendations and options"], ["Decide", "what you decided"], ["Mission", "approve and watch"]];

function SituationFlow({ s, sits, sit, step, user, go, back }: { s: Situation; sits: Sit[]; sit: Sit; step: number; user: User;
  go: (n: number) => void; back: () => void }) {
  const qc = useQueryClient();
  const toast = useStore((st) => st.toast);
  const canPlan = user.role === "ADMIN" || user.role === "COMMAND_HQ";
  const plan = useQuery({ queryKey: ["plan", s.plan?.id], queryFn: () => api<PlanView>(`/ops/plans/${s.plan!.id}`), enabled: !!s.plan, refetchInterval: 15000 });
  const [dec, setDec] = useDecisions(s.plan?.id, sit.key);
  const t = tally(sit);
  const tasks = buildTasks(sit, t.act, plan.data);
  const scenarioBases = new Set(sits.filter((x) => x.run).flatMap((x) => x.bases));
  const moves = s.transfers.moves.filter((m) => sit.run ? sit.bases.includes(m.to_base.id) || sit.bases.includes(m.from_base.id)
    : !scenarioBases.has(m.to_base.id) && !scenarioBases.has(m.from_base.id));
  const chosen = (mid?: number) => !!mid && plan.data?.items.find((i) => i.mission.id === mid)?.explanation?.rows[0]?.label === "Chosen by";
  const decisionOf = (x: Task, k: number): Decision | undefined => dec[taskKey(x, k)] ?? (chosen(x.mission_id) ? "choice" : x.status === "in" ? "keep" : undefined);
  const open = tasks.filter((x, k) => !decisionOf(x, k)).length + moves.filter((m) => !dec[m.key]).length;
  const refresh = () => ["situation", "scenarios", "scenario-response", "plans", "plan", "disruptions", "ops-summary", "ops-routes",
    "ops-transfers", "missions", "plan-options"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const fail = (e: unknown) => toast(e instanceof ApiError ? e.message : "Failed", "CRITICAL");
  const split = useMutation({          // D42: a checked split fix
    mutationFn: ({ id, f }: { id: number; f: Fix }) => api(`/ops/missions/${id}/split`, { method: "POST", body: { kind: f.kind, parts: f.parts, t0: f.t0, sizes: f.sizes ?? null } }),
    onSuccess: () => { refresh(); toast("Fix applied. The planner covers the parts on its next check.", "INFO"); }, onError: fail,
  });
  const badge = [null, open ? `${open} to decide` : "all decided", Object.keys(dec).length ? `${Object.keys(dec).length} decided` : null,
    s.decision ? "waiting" : s.in_force ? "approved" : null];
  return (
    <div>
      <button className="back-link" onClick={back}>← All situations</button>
      <nav className="steps4" aria-label="Steps">
        {STEPS.map(([name, sub], i) => (
          <button key={name} className={i + 1 === step ? "on" : i + 1 < step ? "done" : ""} aria-current={i + 1 === step ? "step" : undefined} onClick={() => go(i + 1)}>
            <span className="n">{i + 1 < step ? "✓" : i + 1}</span><span><b>{name}</b><small>{sub}</small></span>
            {badge[i] && <span className={`badge${badge[i] === "waiting" || badge[i]?.includes("to decide") ? " warn" : ""}`}>{badge[i]}</span>}
          </button>
        ))}
      </nav>

      <div className="sit-head">
        <h2><span className="dot" style={{ background: sit.colour }} />{sit.name}
          {sit.run && (sit.over ? <span className="live-chip ended">over since {hh(sit.overSince)}</span> : <span className="live-chip">● live</span>)}
          {sit.run && <span className="muted" style={{ fontSize: 13, fontWeight: 400 }}>since {hh(sit.run.started_sim)}</span>}<Sim title="Everything in a scenario is simulated" /></h2>
        <p className="live-lead">{sit.lead}</p>
        {sit.timeline.length > 0 && <div className="mini-steps">{sit.timeline.map((x, k) => (
          <span key={k} className={x.state}><i />{hh(x.ts)} {x.label}{x.state === "now" ? " (now)" : ""}</span>))}</div>}
      </div>

      {step === 1 && <>
        {t.effects.length > 0 && <><h3 className="sec-h">What happened</h3>
          <ul className="caused">{t.effects.map((e, k) => <li key={k}><i style={{ color: SEV[e.sev][1] }}>{SEV[e.sev][0]}</i><span><b>{e.what}</b>{e.sub && <small>{e.sub}</small>}</span><span className="dim">{e.rec}</span></li>)}</ul></>}
        {sit.analysis ? <Assessed a={sit.analysis} /> : sit.run && <p className="muted" style={{ fontSize: 12 }}>The full impact assessment (the plan with
          and without this scenario) is made when a scenario starts; this one started before it existed. Below: what the plan's checks found.</p>}
        <h3 className="sec-h">{sit.analysis ? "Items to review in Plan" : "What it means for the plan"}</h3>
        {tasks.length === 0 ? <div className="empty">Nothing in the plan is affected{t.waiting ? " yet" : ""}.</div>
          : <ul className="caused">{tasks.map((x, k) => <li key={k}><i style={{ color: SEV[x.sev][1] }}>{SEV[x.sev][0]}</i><span>{x.what}{x.blocked ? <small>because {x.blocked}</small> : x.sub && <small>{x.sub}</small>}</span>
            <span className={x.status === "uncovered" ? "s-critical" : x.status === "in" ? "s-ok" : "s-warning"}>{x.status === "uncovered" ? "not covered" : x.status === "in" ? "in the plan" : "planner has an answer"}</span></li>)}</ul>}
        {moves.length > 0 && <p className="muted">It also needs stock moved between bases ({moves.length}).</p>}
        <NextBar note="The planner has already worked out an answer for each. Review them in Plan." label="Plan it →" onNext={() => go(2)} />
      </>}

      {step === 2 && <div className="plan-grid">
        <section style={{ minWidth: 0 }}>
          {tasks.length === 0 && moves.length === 0 && <div className="empty">Nothing to plan for this situation.</div>}
          {tasks.map((x, k) => (
            <TaskCard key={taskKey(x, k)} n={k + 1} t={x} plan={plan.data} decision={decisionOf(x, k)} canPlan={canPlan} busy={split.isPending}
              onDecide={(d) => setDec(taskKey(x, k), d)} onChosen={() => { setDec(taskKey(x, k), "choice"); refresh(); }}
              onFix={(f) => x.mission_id && split.mutate({ id: x.mission_id, f }, { onSuccess: () => setDec(taskKey(x, k), "fix") })} />
          ))}
          {moves.map((m, k) => (
            <div key={m.key} className={`tk${dec[m.key] ? " decided" : ""}`}>
              <div className="tk-top"><span className="num">{tasks.length + k + 1}</span>
                <div className="prob">{m.reason}<small>needed {m.needed_by ? hh(m.needed_by) : "to restock"}</small></div>
                <span className="fl-pill warn">stock move</span></div>
              <div className="tk-ans"><span />
                <div><div className="lbl">Planner's recommendation</div>
                  <div className="pick">Move {qtyText(m)} from <b>{m.from_base.name}</b> to {m.to_base.name} ({m.distance_km} km)</div>
                  <div className="why">Nearest base with spare stock above its own reserve · arrives {hh(m.eta)}{m.late ? <span className="s-caution"> (after it is needed)</span> : null}</div></div>
                <div className="tk-act">{dec[m.key] ? <><span className={dec[m.key] === "approve" ? "s-ok" : "dim"}>{dec[m.key] === "approve" ? "✓ Approve" : "Skip"}</span>
                    <button className="tog" onClick={() => setDec(m.key, null)}>change</button></>
                  : canPlan && <><button className="btn btn-sm" onClick={() => setDec(m.key, "approve")}>✓ Approve</button><button className="tog" onClick={() => setDec(m.key, "skip")}>skip</button></>}</div>
              </div>
            </div>
          ))}
          <NextBar note={open ? `${open} still to decide.` : "Everything is decided."} label="Next: decide →" onNext={() => go(3)} />
        </section>
        <aside className="req-side">
          <h2 className="needs-h">What this situation needs</h2>
          {s.requirements.filter((r) => (sit.run ? r.run_id === sit.run.id : !r.run_id)).map((x, k) => (
            <div key={k} className="req">
              <div className="a"><b style={{ fontWeight: 400 }}>{x.label}</b><span style={{ color: REQ[x.status][1] }}>{REQ[x.status][0]}</span></div>
              <div className="nf"><span className="k">Need</span><span>{x.need}</span><span className="k">From</span><span>{x.from} · {x.have}</span>
                {x.when && <><span className="k">When</span><span className="mono">{whenText(x.when)[0]}</span></>}</div>
              {x.q && <div className={`bar${x.status === "approve" ? " ap" : ""}`}><i style={{ width: `${Math.min(100, (100 * x.q[0]) / Math.max(x.q[1], 1e-9))}%` }} /></div>}
            </div>))}
          {!s.requirements.some((r) => (sit.run ? r.run_id === sit.run.id : !r.run_id)) && <div className="empty">Nothing beyond the bases' own stock.</div>}
        </aside>
      </div>}

      {step === 3 && <Decided tasks={tasks} moves={moves} decisionOf={decisionOf} dec={dec} open={open} back={() => go(2)} next={() => go(4)} />}
      {step === 4 && <Mission s={s} sits={sits} sit={sit} tasks={tasks} moves={moves.filter((m) => dec[m.key] === "approve")} canPlan={canPlan} refresh={refresh} />}
    </div>
  );
}

/** Step 1 (D62): what the scenario does to the plan, from planning the same moment without and with it. */
function Assessed({ a }: { a: Assessment }) {
  const b = a.before, w = a.with;
  const prio = (k: "P1" | "P2" | "P3" | "P4") => (x: typeof b) => `${x.by_priority[k]?.covered ?? 0} of ${x.by_priority[k]?.of ?? 0}`;
  const rows: [string, (x: typeof b) => string, (x: typeof b) => number][] = [
    ["Missions covered", (x) => `${x.covered} of ${x.missions}`, (x) => x.covered],
    ["P1 covered", prio("P1"), (x) => x.by_priority.P1?.covered ?? 0], ["P2 covered", prio("P2"), (x) => x.by_priority.P2?.covered ?? 0],
    ["Sorties", (x) => String(x.sorties ?? "—"), (x) => x.sorties ?? 0],
    ["Flying hours", (x) => (x.flying_hours ?? 0).toFixed(1), (x) => x.flying_hours ?? 0],
    ["Fuel (ATF)", (x) => `${Math.round((x.fuel_l ?? 0) / 1000)} kL`, (x) => (x.fuel_l ?? 0) / 1000],
  ];
  const KIND: Record<string, [string, string]> = { moved: ["warn", "moved"], dropped: ["crit", "not flown"], added: ["info", "added"] };
  return (
    <section className="assess">
      <h3 className="sec-h" style={{ marginTop: 0 }}>What it does to the plan <span className="dim" style={{ fontWeight: 400, fontSize: 12 }}>
        assessed {hh(a.assessed_at)} by planning the same moment without and with it</span></h3>
      <ul className="brief">{a.brief.map((x, k) => <li key={k}>{x}</li>)}</ul>
      <div className="assess-grid">
        <table className="table cmp">
          <thead><tr><th /><th className="right">Without it</th><th className="right">With it</th><th className="right">Change</th></tr></thead>
          <tbody>{rows.map(([n, f, v]) => { const d = v(w) - v(b); return (
            <tr key={n}><td>{n}</td><td className="num">{f(b)}</td><td className="num">{f(w)}</td>
              <td className={`num ${d === 0 ? "dim" : (n.includes("covered") ? d < 0 : d > 0) ? "s-warning" : "s-ok"}`}>{d === 0 ? "—" : `${d > 0 ? "+" : ""}${Number.isInteger(d) ? d : d.toFixed(1)}`}</td></tr>); })}</tbody>
        </table>
        <div className="chg">
          {a.changes.length === 0 && <div className="empty">No package changes: {a.flights_there_before ? "everything planned there still flies." : "nothing was planned where it hits."}</div>}
          {a.changes.map((c) => (
            <div key={c.mission_id} className="chg-row"><span className={`fl-pill ${KIND[c.kind][0]}`}>{KIND[c.kind][1]}</span>
              <div><b>{c.priority} {c.name}</b>
                <small>{c.before ? `was ${c.before.n} × ${c.before.type} from ${c.before.base} at ${hh(c.before.launch)}` : "new"}
                  {c.after ? ` → now ${c.after.n} × ${c.after.type} from ${c.after.base} at ${hh(c.after.launch)}` : c.kind !== "added" ? " → not flown" : " → not covered"}</small>
                {c.reason && <small className="because">because {c.reason}</small>}</div></div>
          ))}
        </div>
      </div>
    </section>
  );
}

const NextBar = ({ note, label, onNext }: { note: ReactNode; label: string; onNext: () => void }) => (
  <div className="next-bar"><span className="muted">{note}</span><button className="btn btn-primary" onClick={onNext}>{label}</button></div>
);

/** One impact: the planner's recommendation and why, then Keep / Accept, other options, fixes, or a pick of your own. */
function TaskCard({ n, t, plan, decision, canPlan, busy, onDecide, onChosen, onFix }: { n: number; t: Task; plan: PlanView | undefined;
  decision: Decision | undefined; canPlan: boolean; busy: boolean; onDecide: (d: Decision | null) => void; onChosen: () => void; onFix: (f: Fix) => void }) {
  const [more, setMore] = useState(false);
  const it = t.mission_id ? plan?.items.find((i) => i.mission.id === t.mission_id) : undefined;
  const why = whyText(it);
  const uncovered = t.status === "uncovered" || t.status === "apply";
  const [wt, air] = whenText(t.when);
  const word: Record<Decision, string> = { keep: "✓ Kept", choice: "✓ Your choice", accept: "✓ Accepted: not flown", fix: "✓ Fix applied", approve: "✓ Approve", skip: "Skipped" };
  return (
    <div className={`tk${decision ? " decided" : ""}`}>
      <div className="tk-top"><span className="num">{n}</span>
        <div className="prob">{t.what}{t.sub && <small>{t.sub}</small>}{t.blocked && <span className="blocked">Why it can't stay as it was: {t.blocked}.</span>}</div>
        <span className={`fl-pill ${uncovered ? "crit" : t.status === "in" ? "ok" : t.status === "waiting" ? "dim" : "warn"}`}>
          {uncovered ? "not covered" : t.status === "in" ? "in the plan" : t.status === "waiting" ? "planning…" : "proposed"}</span></div>
      <div className="tk-ans"><span />
        <div><div className="lbl">{decision === "choice" ? "Your choice" : uncovered ? "Planner's answer" : "Planner's recommendation"}</div>
          <div className="pick">{t.rec}{!uncovered && t.when && <span className={`mono${air ? " s-info" : " dim"}`} style={{ fontSize: 12 }}> · {wt}</span>}</div>
          {why && <div className="why">Why: {why}</div>}
          {uncovered && !t.blocked && t.sub && <div className="why">The planner could not fit it: {t.sub}</div>}</div>
        <div className="tk-act">
          {decision ? <><span className={decision === "skip" ? "dim" : "s-ok"}>{word[decision]}</span>{decision !== "choice" && <button className="tog" onClick={() => onDecide(null)}>change</button>}</>
            : canPlan && <button className="btn btn-sm" onClick={() => onDecide(uncovered ? "accept" : "keep")}>{uncovered ? "✓ Accept" : "✓ Keep"}</button>}
          {canPlan && t.mission_id && <button className="tog" onClick={() => setMore(!more)}>{uncovered ? "Fix or choose ▾" : "Other options ▾"}</button>}
        </div>
      </div>
      {more && t.mission_id && <Options missionId={t.mission_id} fix={t.fix ?? null} busy={busy} onFix={onFix} onChosen={() => { setMore(false); onChosen(); }} />}
    </div>
  );
}

/** The planner's other options and a pick of your own; whichever you choose is checked with the planner's rules (D61). */
function Options({ missionId, fix, busy, onFix, onChosen }: { missionId: number; fix: Fix | null; busy: boolean; onFix: (f: Fix) => void; onChosen: () => void }) {
  const toast = useStore((s) => s.toast);
  const q = useQuery({ queryKey: ["plan-options", missionId], queryFn: () => api<MissionOptions>(`/ops/plans/options?mission_id=${missionId}`) });
  const [pick, setPick] = useState("");
  const [time, setTime] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const choose = useMutation({
    mutationFn: (b: { base_id: number; type_id: number; on_station?: string }) =>
      api<{ package: string; launch: string }>("/ops/plans/choose", { method: "POST", body: { mission_id: missionId, ...b } }),
    onSuccess: (r) => { setErr(null); toast(`Your choice is in the plan: ${r.package}, launch ${hh(r.launch)}`, "INFO"); onChosen(); },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "That choice could not be checked"),
  });
  if (q.isLoading) return <div className="tk-opts"><Loading /></div>;
  if (!q.data) return <div className="tk-opts"><ErrorText error={q.error} /></div>;
  const o = q.data;
  const onStation = () => {                 // HH:MM in IST on the day the window opens
    if (!time) return undefined;
    const d = new Date(new Date(o.mission.window_start).getTime() + 5.5 * 3600e3).toISOString().slice(0, 10);
    return `${d}T${time}:00+05:30`;
  };
  return (
    <div className="tk-opts">
      {fix && <div className="opt-row"><span>Suggested fix: {fix.text}</span><button className="btn btn-sm btn-primary" disabled={busy} onClick={() => onFix(fix)}>Apply fix</button></div>}
      {o.alternatives.length > 0 && <div className="opt-h">The planner's other options</div>}
      {o.alternatives.map((a) => (
        <div key={`${a.base_id}-${a.type_id}`} className="opt-row"><span>{a.n ? `${a.n} × ` : ""}{a.type} from <b>{a.base_name ?? a.base}</b>, launch {hh(a.launch)}{" "}
          <span className="dim">· {a.transit_min != null ? `${a.transit_min} min to station (${(a.d_transit_min ?? 0) >= 0 ? "+" : ""}${a.d_transit_min ?? 0}) · fuel ${(a.d_fuel_l ?? 0) >= 0 ? "+" : ""}${((a.d_fuel_l ?? 0) / 1000).toFixed(1)} kL · route risk ${(a.risk ?? 0) < 0.2 ? "low" : (a.risk ?? 0) < 0.5 ? "medium" : "high"}` : a.why_not}</span></span>
          <button className="btn btn-sm" disabled={choose.isPending} onClick={() => choose.mutate({ base_id: a.base_id, type_id: a.type_id })}>Use this instead</button></div>
      ))}
      <div className="opt-h">Or choose yourself <span className="dim">(window {hh(o.mission.window_start)}–{hh(o.mission.window_end)}, {o.mission.required} aircraft, {o.mission.on_station_min} min on station)</span></div>
      <div className="opt-row mine">
        <select className="select" aria-label="Base and aircraft" value={pick} onChange={(e) => setPick(e.target.value)}>
          <option value="">Base and aircraft…</option>
          {o.manual.map((m) => <option key={`${m.base_id}-${m.type_id}`} value={`${m.base_id}-${m.type_id}`}>{m.base_name} · {m.type} ({m.aircraft} held)</option>)}
        </select>
        <label className="dim" style={{ fontSize: 12 }}>on station <input className="input" type="time" value={time} onChange={(e) => setTime(e.target.value)} aria-label="On station time (IST)" /></label>
        <button className="btn btn-sm btn-primary" disabled={!pick || choose.isPending} onClick={() => {
          const [b, ty] = pick.split("-").map(Number);
          choose.mutate({ base_id: b, type_id: ty, on_station: onStation() });
        }}>{choose.isPending ? "Checking…" : "Check and use"}</button>
      </div>
      {err && <div className="s-critical" style={{ fontSize: 13, marginTop: 6 }}>✕ {err}</div>}
      <div className="dim" style={{ fontSize: 11, marginTop: 6 }}>Every choice is checked with the planner's own rules (range, weather, runway, crew, fuel, weapons, launch slots) before it goes into the plan.</div>
    </div>
  );
}

function Decided({ tasks, moves, decisionOf, dec, open, back, next }: { tasks: Task[]; moves: TransferMove[];
  decisionOf: (x: Task, k: number) => Decision | undefined; dec: Record<string, Decision>; open: number; back: () => void; next: () => void }) {
  const rows = tasks.map((x, k) => [x, decisionOf(x, k)] as const).filter(([, d]) => d);
  const verb: Record<Decision, string> = { keep: "Keep", choice: "Your choice", accept: "Not flown", fix: "Fix", approve: "Approve", skip: "Skip" };
  return (
    <div>
      <h3 className="sec-h">What you decided</h3>
      {rows.length === 0 && moves.every((m) => !dec[m.key]) && <div className="empty">Nothing decided yet.</div>}
      <div className="decided">
        {rows.map(([x, d], k) => (
          <div key={k} className="d-row"><span className={`fl-pill ${d === "accept" ? "crit" : d === "choice" ? "info" : "ok"}`}>{verb[d!]}</span>
            <span>{x.what}</span><span className="ar">→</span><span>{d === "accept" ? "not flown" : x.rec}</span></div>))}
        {moves.filter((m) => dec[m.key]).map((m) => (
          <div key={m.key} className="d-row"><span className={`fl-pill ${dec[m.key] === "approve" ? "ok" : "dim"}`}>{dec[m.key] === "approve" ? "Move" : "Skip"}</span>
            <span>{qtyText(m)}</span><span className="ar">→</span><span>{m.from_base.name} → {m.to_base.name}, arrives {hh(m.eta)}</span></div>))}
      </div>
      {open > 0 ? <NextBar note={<span className="s-warning">◆ {open} not decided yet.</span>} label="← Back to plan" onNext={back} />
        : <NextBar note="Approving turns these decisions into missions." label="Next: mission →" onNext={next} />}
    </div>
  );
}

function Mission({ s, sits, sit, tasks, moves, canPlan, refresh }: { s: Situation; sits: Sit[]; sit: Sit; tasks: Task[]; moves: TransferMove[];
  canPlan: boolean; refresh: () => void }) {
  const toast = useStore((st) => st.toast);
  const approve = useMutation({
    mutationFn: async () => {
      if (s.decision) await api(`/ops/plans/${s.decision.plan_id}/commit`, { method: "POST" });
      if (moves.length) await api("/ops/transfers", { method: "POST", body: { run_id: sit.run?.id ?? null, moves: moves.map((m) => ({
        kind: m.kind, category: m.category, qty: m.qty, from_base_id: m.from_base.id, to_base_id: m.to_base.id, needed_by: m.needed_by, reason: m.reason })) } });
    },
    onSuccess: () => { refresh(); toast(`Approved: ${s.decision ? "the plan is in force" : ""}${s.decision && moves.length ? " and " : ""}${moves.length ? `${moves.length} stock move${moves.length > 1 ? "s" : ""} on the road` : ""}`, "INFO"); },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Approval failed", "CRITICAL"),
  });
  const reject = useMutation({
    mutationFn: () => api(`/ops/plans/${s.decision!.plan_id}/reject`, { method: "POST" }),
    onSuccess: () => { refresh(); toast("Rejected: the plan in force stays as it is", "INFO"); },
  });
  const also = sits.filter((x) => x.key !== sit.key && tally(x).review > 0).map((x) => x.name);
  const flown = tasks.filter((x) => x.status !== "uncovered" && x.status !== "apply");
  return (
    <div>
      {(s.decision || moves.length > 0) && <div className="approve-box">
        <div><b>Approve to turn your decisions into missions.</b> Sorties are created or changed{moves.length ? `, and ${moves.length} stock move${moves.length > 1 ? "s" : ""} leave the donor bases now` : ""}. Recorded in the audit log.
          {s.decision && also.length > 0 && <div className="muted" style={{ marginTop: 4 }}>The plan is approved as one, so this also approves the planner's proposal for {also.join(", ")}.</div>}</div>
        {canPlan ? <div className="approve-act">{s.decision && <button className="btn btn-danger" disabled={reject.isPending || approve.isPending} onClick={() => reject.mutate()}>Reject</button>}
          <button className="btn btn-primary" disabled={approve.isPending} onClick={() => approve.mutate()}>{approve.isPending ? "Approving…" : "Approve missions"}</button></div>
          : <span className="muted">waiting for Air HQ</span>}
      </div>}
      <h3 className="sec-h">Missions for this situation {!s.decision && s.in_force && <span className="s-ok" style={{ fontWeight: 400, fontSize: 12 }}>✓ in the plan in force since {hh(s.in_force.since)}</span>}</h3>
      {flown.length === 0 && <div className="empty">No mission flies for this situation.</div>}
      <div className="decided">
        {flown.map((x, k) => {
          const [wt, air] = whenText(x.when);
          const st = x.when?.kind === "airborne" ? ["s-info", "● airborne"] : x.when?.kind === "on_station" ? ["s-info", "● on station"]
            : x.when?.kind === "done" ? ["s-ok", "✓ landed"] : x.status === "in" ? ["s-ok", "✓ approved · planned"] : ["s-warning", "◆ waiting for approval"];
          return <div key={k} className="d-row m"><span className={st[0]}>{st[1]}</span><span>{x.what}</span><span>{x.rec}</span>
            <span className={`mono${air ? " s-info" : " dim"}`} style={{ fontSize: 12 }}>{wt}</span></div>;
        })}
        {tasks.filter((x) => x.status === "uncovered" || x.status === "apply").map((x, k) => (
          <div key={`u${k}`} className="d-row m"><span className="s-critical">■ not flown</span><span>{x.what}</span><span className="dim">{x.sub}</span><span /></div>))}
      </div>
      <p className="muted" style={{ marginTop: 12 }}>Watch them on <Link to="/map">Map → Ops</Link>: routes, convoys and the scenario's effects on bases.</p>
    </div>
  );
}

/** Nothing live and no plan: where to start. */
function Guide({ canPlan, onPlan, busy }: { canPlan: boolean; onPlan: () => void; busy: boolean }) {
  return (
    <div className="live-empty">
      <h2>Start from the situation</h2>
      <p className="muted">Start a scenario and the planner answers it at once: the missions it demands, a plan for them alongside routine
        tasking, what that breaks, and what it needs from which base, including fuel, weapons and spares to move between bases.</p>
      <ol>
        <li><span className="n">1</span><div><b>Start a scenario</b><div className="muted">Pick one of the eight, or several. This page updates by itself.</div>
          {canPlan ? <Link className="btn btn-sm btn-primary" to="/scenarios">Open Scenarios</Link> : <div className="muted">Air HQ or the directing staff start scenarios.</div>}</div></li>
        <li><span className="n">2</span><div><b>Or plan routine tasking first</b><div className="muted">The day's routine missions, without any incident.</div>
          {canPlan && <button className="btn btn-sm" disabled={busy} onClick={onPlan}>{busy ? "Planning…" : "Plan routine tasking"}</button>}</div></li>
      </ol>
    </div>
  );
}
