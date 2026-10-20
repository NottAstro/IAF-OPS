// After-action report for a scenario run (PHASE2_IMPLEMENTATION_PLAN §10.5). Starting and ending scenarios lives on the
// Scenarios page (pages/Scenarios.tsx, ARCHITECTURE D55). D66: a scripted scenario's report reads its script and this
// browser's decisions, like the Planner, so the two always agree.
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { ErrorText, Kpi, Loading, Pill, Row, Sim, ToneText } from "../components/ui";
import { PrioPill, hhmm } from "../features/ops";
import { istTime, label, num } from "../lib/format";
import type { Priority } from "../api/types";
import { type Script, SCRIPTS, baseName, chosen, statusAt, timesOf, validRun } from "../features/scripts";
import { useStore } from "../store";

interface Inject { offset_min?: number; kind: string; label?: string; params: Record<string, unknown>; applied_at: string | null; result?: string; live?: boolean }
interface Aar {
  run: { id: number; name: string; status: string; started_sim: string; ended_sim: string | null };
  injects: Inject[];
  disruptions: { id: number; ts: string; kind: string; message: string; status: string; proposal_ms: number | null; decision_s: number | null; proposal_summary: string | null }[];
  plans: { id: number; kind: string; status: string; summary: string | null; created_at: string; committed_at: string | null; approved_by: string | null }[];
  missions: { code: string; name: string; priority: Priority; mission_type: string; status: string; outcome: string; on_station_min: number; on_station_achieved_min: number }[];
  summary: { disruptions: number; proposals: number; proposal_ms_max: number | null; decision_s_median: number | null; plans_committed: number; MET: number; PARTIAL: number; MISSED: number; NONE: number };
}

export function AfterAction() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["aar", id], queryFn: () => api<Aar>(`/ops/exercise/runs/${id}/aar`), refetchInterval: 15000 });
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><ErrorText error={q.error} /></div>;
  const a = q.data, s = a.summary;
  const script = SCRIPTS.find((x) => x.name === a.run.name);
  if (script) return <ScriptedAar a={a} script={script} id={id!} />;
  return (
    <div className="page aar">
      <h1 className="page-title">After-action report <Sim /> <span className="muted" style={{ fontSize: 15, fontWeight: 400 }}>{a.run.name}</span>
        <span className="topbar-spacer" /><a className="btn btn-sm no-print" href={`/api/v1/ops/exercise/runs/${id}/aar.csv`}>Download CSV</a>
        <button className="btn btn-sm no-print" onClick={() => print()}>Print</button></h1>
      <div className="muted" style={{ marginBottom: 12 }}>{istTime(a.run.started_sim, true)} – {a.run.ended_sim ? istTime(a.run.ended_sim, true) : "running"} (simulated time). All data simulated.</div>
      <div className="kpis" style={{ gridTemplateColumns: "repeat(6, 1fr)", marginBottom: 16 }}>
        <Kpi label="Disruptions" value={s.disruptions} sub={`${s.proposals} re-task proposals`} />
        <Kpi label="Slowest proposal" value={s.proposal_ms_max != null ? `${num(s.proposal_ms_max / 1000, 1)} s` : "—"} sub="target ≤ 15 s" toneName={(s.proposal_ms_max ?? 0) > 15000 ? "warning" : undefined} />
        <Kpi label="Decision time (median)" value={s.decision_s_median != null ? `${num(s.decision_s_median)} s` : "—"} sub="disruption → committed fix" />
        <Kpi label="Plans committed" value={s.plans_committed} />
        <Kpi label="Missions met" value={s.MET} sub={`${s.PARTIAL} partial · ${s.MISSED} missed`} toneName={s.MISSED ? "warning" : undefined} />
        <Kpi label="Still open" value={s.NONE} sub="missions without an outcome yet" />
      </div>
      <div className="grid-2">
        <div>
          <h2 className="section-h">Injects</h2>
          {a.injects.map((i, k) => <Row key={k} label={<span className="mono">{i.applied_at ? hhmm(i.applied_at) : "pending"}</span>} value={i.result ?? i.label ?? label(i.kind)} />)}
          <h2 className="section-h">Plans and decisions</h2>
          {a.plans.map((p) => <Row key={p.id} label={<a href={`/planner?plan=${p.id}`}>#{p.id} {label(p.kind)}</a>} extra={<span className="dim" style={{ fontSize: 11 }}>{p.summary}</span>}
            value={<Pill status={p.status === "COMMITTED" || p.status === "SUPERSEDED" ? "OPERATIONAL" : p.status === "REJECTED" ? "CRITICAL" : "PLANNED"} text={`${label(p.status)}${p.approved_by ? ` · ${p.approved_by}` : ""}`} />} />)}
        </div>
        <div>
          <h2 className="section-h">Disruptions</h2>
          <div className="table-wrap"><table className="table" style={{ fontSize: 12 }}>
            <thead><tr><th>Sim time</th><th>What happened</th><th className="right">Proposal</th><th className="right">Decision</th><th>Status</th></tr></thead>
            <tbody>{a.disruptions.map((d) => (
              <tr key={d.id}><td className="mono">{hhmm(d.ts)}</td><td style={{ whiteSpace: "normal", maxWidth: 300 }}>{d.message}</td>
                <td className="num">{d.proposal_ms != null ? `${num(d.proposal_ms / 1000, 1)} s` : "—"}</td><td className="num">{d.decision_s != null ? `${d.decision_s} s` : "—"}</td>
                <td>{label(d.status)}</td></tr>
            ))}</tbody></table></div>
        </div>
      </div>
      <h2 className="section-h">Missions in the exercise window</h2>
      <div className="table-wrap"><table className="table">
        <thead><tr><th>Pri.</th><th>Mission</th><th>Type</th><th>Status</th><th>Outcome</th><th className="right">On station</th></tr></thead>
        <tbody>{a.missions.map((m) => (
          <tr key={m.code}><td><PrioPill p={m.priority} /></td><td><span className="mono">{m.code}</span> <span className="muted">{m.name}</span></td><td>{label(m.mission_type)}</td>
            <td>{label(m.status)}</td><td>{m.outcome === "NONE" ? <span className="dim">—</span> : <ToneText toneName={m.outcome === "MET" ? "ok" : m.outcome === "PARTIAL" ? "caution" : "critical"}>{label(m.outcome)}</ToneText>}</td>
            <td className="num">{num(m.on_station_achieved_min, 0)} / {m.on_station_min} min</td></tr>
        ))}</tbody></table></div>
    </div>
  );
}

const VERB = (d: unknown, hasPkg: boolean) => typeof d === "number" ? "Your choice" : d === "accept" || !hasPkg ? "Not flown" : "Kept";
const TONE: Record<string, string> = { landed: "ok", airborne: "info", "on station": "info", returning: "info", approved: "ok", waiting: "warning", "not flown": "critical" };

/** D66: the report for a scripted scenario: what happened, what was decided and how each mission went. Values only. */
function ScriptedAar({ a, script, id }: { a: Aar; script: Script; id: string }) {
  const rec = useStore((st) => st.demo[id]);
  const now = useStore((st) => st.simClock?.sim_now) ?? new Date().toISOString();
  const run = validRun(rec, a.run.started_sim);
  const at = run?.approvedAt ?? null;
  const rows = script.missions.map((m) => { const p = chosen(m, run?.dec[m.id]); return { m, p, d: run?.dec[m.id], st: statusAt(p, at, now) }; });
  const count = (f: (x: (typeof rows)[number]) => boolean) => rows.filter(f).length;
  const decideMin = at ? Math.round((Date.parse(at) - Date.parse(a.run.started_sim)) / 60e3) : null;
  const t0 = Date.parse(a.run.started_sim);
  return (
    <div className="page aar">
      <h1 className="page-title">After-action report <Sim /> <span className="muted" style={{ fontSize: 15, fontWeight: 400 }}>{script.name}</span>
        <span className="topbar-spacer" /><button className="btn btn-sm no-print" onClick={() => print()}>Print</button></h1>
      <div className="muted" style={{ marginBottom: 12 }}>{istTime(a.run.started_sim, true)} – {a.run.ended_sim ? istTime(a.run.ended_sim, true) : "running"} (simulated time). All data simulated.</div>
      <div className="kpis" style={{ gridTemplateColumns: "repeat(5, 1fr)", marginBottom: 16 }}>
        <Kpi label="Missions affected" value={script.missions.length} sub={`${count((x) => x.m.kind === "added")} new · ${count((x) => x.m.kind === "moved")} moved`} />
        <Kpi label="Decision" value={at ? `${decideMin} min` : "—"} sub={at ? `event → approval at ${hhmm(at)}` : "not approved yet"} toneName={at ? undefined : "warning"} />
        <Kpi label="Recommendations kept" value={count((x) => x.d === undefined || x.d === "keep")} sub={`${count((x) => typeof x.d === "number")} changed by you`} />
        <Kpi label="Flown" value={count((x) => x.st === "landed")} sub={`${count((x) => ["airborne", "on station", "returning"].includes(x.st))} in the air now`} />
        <Kpi label="Not flown" value={count((x) => x.st === "not flown")} toneName={count((x) => x.st === "not flown") ? "warning" : undefined} />
      </div>
      <h2 className="section-h">What happened</h2>
      {script.happened.map((h, k) => <Row key={k} label={h.what} value={<span className="mono dim">{h.ends != null ? `until ${istTime(new Date(t0 + h.ends * 60e3).toISOString(), true)}` : `from ${hhmm(a.run.started_sim)}`}</span>} />)}
      <h2 className="section-h">Missions</h2>
      <div className="table-wrap"><table className="table">
        <thead><tr><th>Pri.</th><th>Mission</th><th>Decision</th><th>Package</th><th>Launch – back</th><th>Status</th></tr></thead>
        <tbody>{rows.map(({ m, p, d, st }) => { const t = p ? timesOf(p, at, now) : null; return (
          <tr key={m.id}><td><PrioPill p={m.priority} /></td><td>{m.name} <span className="dim" style={{ fontSize: 11 }}>{m.kind}</span></td>
            <td>{at ? VERB(d, !!p) : <span className="dim">—</span>}</td><td>{p ? `${p.n} × ${p.type} from ${baseName(p.base)}` : <span className="dim">—</span>}</td>
            <td className="mono">{t && at ? `${hhmm(new Date(t.launch).toISOString())} – ${hhmm(new Date(t.back).toISOString())}` : <span className="dim">—</span>}</td>
            <td><ToneText toneName={TONE[st] ?? "neutral"}>{label(st)}</ToneText></td></tr>); })}</tbody></table></div>
    </div>
  );
}
