// Exercise control and after-action report (PHASE2_IMPLEMENTATION_PLAN §8, §10.5). ADMIN acts as directing staff:
// runs the simulator, loads a scenario, injects events; the re-tasking monitor and the planner respond.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { ErrorText, Kpi, Loading, Pill, Row, Sim, ToneText } from "../components/ui";
import { PrioPill, hhmm } from "../features/ops";
import { istTime, label, num } from "../lib/format";
import { useStore } from "../store";
import type { Priority } from "../api/types";

interface Inject { offset_min?: number; kind: string; label?: string; params: Record<string, unknown>; applied_at: string | null; result?: string; live?: boolean }
interface State {
  run: { id: number; name: string; started_sim: string; injects: Inject[]; kpi_timeline: Record<string, number | string>[] } | null;
  sim: { enabled: boolean; sim_now: string; speed: number; paused: boolean; tick_no: number } | null;
  kinds: Record<string, string>;
  scenarios: { id: number; name: string; description: string; speed: number; injects: Inject[] }[];
  runs: { id: number; name: string; status: string; started_sim: string; ended_sim: string | null }[];
}
const PARAMS: Record<string, Record<string, string | number>> = {
  RUNWAY_CLOSED: { base: "AUTO", hours: 6 }, WX_FRONT: { bases: "VETZ,VEJT", cat: "IFR", hours: 6 },
  THREAT_ZONE: { lon: 93.0, lat: 27.3, radius_km: 40, risk: 0.9, hours: 6 }, AIRCRAFT_GROUNDING: { type: "Su-30MKI", count: 4, base: "AUTO", hours: 48 },
  MISSION_POPUP: { mission_type: "CASEVAC", priority: "P1", target_base: "VILH", window_h: 3 }, FUEL_DELAY: { base: "VEHX", hours: 24, loss_pct: 35 },
  RADAR_DOWN: { base: "VIAX", hours: 6 }, UNKNOWN_TRACK: {},
};

export function Exercise() {
  const qc = useQueryClient();
  const toast = useStore((s) => s.toast);
  const q = useQuery({ queryKey: ["exercise"], queryFn: () => api<State>("/ops/exercise/state"), refetchInterval: 5000 });
  const [kind, setKind] = useState("RUNWAY_CLOSED");
  const [params, setParams] = useState<Record<string, string | number>>({ ...PARAMS.RUNWAY_CLOSED });
  const done = (msg: string) => { qc.invalidateQueries({ queryKey: ["exercise"] }); toast(msg, "INFO"); };
  const fail = (e: unknown) => toast(e instanceof ApiError ? e.message : "Failed", "CRITICAL");
  const sim = useMutation({ mutationFn: (a: { action: string; speed?: number }) => api(`/sim/${a.action}`, { method: "POST", body: a.speed ? { speed: a.speed } : undefined }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["exercise"] }), onError: fail });
  const start = useMutation({ mutationFn: (scenario_id: number | null) => api("/ops/exercise/start", { method: "POST", body: { scenario_id } }),
    onSuccess: () => done("Exercise started"), onError: fail });
  const stop = useMutation({ mutationFn: () => api("/ops/exercise/stop", { method: "POST" }), onSuccess: () => done("Exercise ended"), onError: fail });
  const inject = useMutation({
    mutationFn: () => api<{ message: string }>("/ops/exercise/inject", { method: "POST", body: { kind, params: {
      ...params, ...(typeof params.bases === "string" ? { bases: String(params.bases).split(",").map((x) => x.trim()).filter(Boolean) } : {}),
      ...(params.base === "" ? { base: undefined } : {}) } } }),
    onSuccess: (r) => done(r.message), onError: fail,
  });
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><ErrorText error={q.error} /></div>;
  const s = q.data;
  const run = s.run;
  const elapsed = run && s.sim ? (new Date(s.sim.sim_now).getTime() - new Date(run.started_sim).getTime()) / 60000 : 0;
  return (
    <div className="page">
      <h1 className="page-title">Exercise control <Sim title="Everything in an exercise is simulated" />
        <span className="muted" style={{ fontSize: 13, fontWeight: 400 }}>Directing staff: run the clock, inject events, watch the plan respond</span></h1>
      <div className="grid-2">
        <div>
          <h2 className="section-h">Simulator</h2>
          {!s.sim?.enabled && <div className="notice notice-warn">The tick simulator is off (SIM_ENABLED=false in .env). Exercises need it on.</div>}
          {s.sim && <>
            <Row label="Simulated time" value={<span className="mono">{istTime(s.sim.sim_now, true)} · tick {s.sim.tick_no}</span>} />
            <Row label="State" value={s.sim.paused ? <ToneText toneName="caution">Paused</ToneText> : <ToneText toneName="ok">Running ×{s.sim.speed}</ToneText>} />
            <div className="toolbar" style={{ marginTop: 8 }}>
              <button className="btn" onClick={() => sim.mutate({ action: s.sim!.paused ? "resume" : "pause" })}>{s.sim.paused ? "Resume" : "Pause"}</button>
              <button className="btn" onClick={() => sim.mutate({ action: "step" })}>Step one tick</button>
              {[1, 10, 60].map((x) => <button key={x} className={`btn${s.sim!.speed === x ? " btn-primary" : ""}`} onClick={() => sim.mutate({ action: "speed", speed: x })}>×{x}</button>)}
            </div>
          </>}

          <h2 className="section-h">Scenarios</h2>
          {s.scenarios.map((sc) => (
            <div key={sc.id} className="scenario">
              <div className="card-title" style={{ fontSize: 15 }}><span>{sc.name}</span>
                <button className="btn btn-sm btn-primary" disabled={start.isPending} onClick={() => start.mutate(sc.id)}>Start ×{sc.speed}</button></div>
              <div className="muted" style={{ fontSize: 12, margin: "2px 0 6px" }}>{sc.description}</div>
              {sc.injects.map((i, k) => <Row key={k} label={<span className="mono">+{i.offset_min} min</span>} value={i.label ?? label(i.kind)} />)}
            </div>
          ))}
          <div className="toolbar" style={{ marginTop: 8 }}><button className="btn" disabled={start.isPending} onClick={() => start.mutate(null)}>Start free play</button></div>
        </div>

        <div>
          <h2 className="section-h">Running exercise {run && <button className="btn btn-sm btn-danger" onClick={() => stop.mutate()}>End exercise</button>}</h2>
          {!run && <div className="empty">No exercise running. Start a scenario or free play.</div>}
          {run && <>
            <Row label="Exercise" value={run.name} />
            <Row label="Elapsed (simulated)" value={<span className="mono">{num(elapsed, 0)} min</span>} />
            <h3 className="section-h" style={{ fontSize: 14 }}>Injects</h3>
            {run.injects.map((i, k) => (
              <Row key={k} label={<span className="mono">{i.applied_at ? hhmm(i.applied_at) : `+${i.offset_min} min`}</span>}
                extra={<span className="dim" style={{ fontSize: 11 }}>{i.result ?? ""}</span>}
                value={i.applied_at ? <ToneText toneName="ok">{i.live ? "Live" : "Applied"}</ToneText> : <ToneText toneName="neutral">Pending</ToneText>} />
            ))}
            {run.kpi_timeline.length > 0 && <>
              <h3 className="section-h" style={{ fontSize: 14 }}>KPI samples (every 30 simulated min)</h3>
              <div className="table-wrap"><table className="table" style={{ fontSize: 12 }}>
                <thead><tr><th>Sim time</th><th className="right">S %</th><th className="right">Airborne</th><th className="right">Alerts</th><th className="right">Tasked</th><th className="right">Met</th><th className="right">Disruptions</th></tr></thead>
                <tbody>{run.kpi_timeline.slice(-8).map((r) => (
                  <tr key={String(r.sim_ts)}><td className="mono">{hhmm(String(r.sim_ts))}</td><td className="num">{num(r.svc as number, 1)}</td><td className="num">{num(r.airborne as number)}</td>
                    <td className="num">{num(r.alerts as number)}</td><td className="num">{num(r.tasked as number)}</td><td className="num">{num(r.met as number)}</td><td className="num">{num(r.disruptions as number)}</td></tr>
                ))}</tbody></table></div>
            </>}
          </>}

          <h2 className="section-h">Inject now</h2>
          <div className="form-grid">
            <label className="field"><span className="field-label">Event</span>
              <select className="select" value={kind} onChange={(e) => { setKind(e.target.value); setParams({ ...PARAMS[e.target.value] }); }}>
                {Object.entries(s.kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            {Object.entries(params).map(([k, v]) => (
              <label key={k} className="field"><span className="field-label">{label(k)}</span>
                <input className="input" value={String(v)} onChange={(e) => setParams({ ...params, [k]: e.target.value })} /></label>
            ))}
          </div>
          <div className="toolbar" style={{ marginTop: 8 }}><button className="btn btn-primary" disabled={inject.isPending} onClick={() => inject.mutate()}>Inject</button></div>

          <h2 className="section-h">After-action reports</h2>
          {s.runs.length === 0 && <div className="empty">No exercises run yet.</div>}
          {s.runs.map((r) => (
            <Row key={r.id} label={<a href={`/exercise/runs/${r.id}`}>{r.name}</a>} extra={<span className="mono dim">{istTime(r.started_sim, true)}</span>}
              value={<Pill status={r.status === "RUNNING" ? "LIVE" : "COMPLETED"} text={label(r.status)} />} />
          ))}
        </div>
      </div>
    </div>
  );
}

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
