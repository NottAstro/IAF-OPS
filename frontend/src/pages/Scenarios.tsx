// Scenarios (ARCHITECTURE D55; replaces Exercise control): the eight incidents, each one event. Pick one and start it;
// the Planner shows what happened and what to do about it. D66: each scenario runs with its script's fixed parameters,
// shown as plain facts, so the scripted Planner always fits. ADMIN acts as directing staff and Air HQ start and end
// them; other roles see the page read-only.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { ScenarioCatalogue, User } from "../api/types";
import { ErrorText, Loading, Sim } from "../components/ui";
import { PrioPill } from "../features/ops";
import { INT_COLOUR, IntensityDots, mins } from "../features/scenarioview";
import { scriptFor } from "../features/scripts";
import { istTime, label } from "../lib/format";
import { useStore } from "../store";

export function Scenarios({ user }: { user: User }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useStore((s) => s.toast);
  const q = useQuery({ queryKey: ["scenarios", "catalogue"], queryFn: () => api<ScenarioCatalogue>("/ops/scenarios"), refetchInterval: 5000 });
  const [selCode, setSelCode] = useState<string | null>(null);
  const canRun = user.role === "ADMIN" || user.role === "COMMAND_HQ";   // start / end scenarios
  const canClock = user.role === "ADMIN";                                // simulator speed and pause
  const sc = q.data?.scenarios.find((s) => s.code === selCode) ?? q.data?.scenarios.find((s) => s.run) ?? q.data?.scenarios[0];
  const script = scriptFor(sc?.code);

  const refresh = () => ["scenarios", "scenario-response", "plans", "disruptions", "missions", "summary"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const fail = (e: unknown) => toast(e instanceof ApiError ? e.message : "Failed", "CRITICAL");
  const start = useMutation({
    mutationFn: () => api<{ run_id: number }>(`/ops/scenarios/${sc!.code}/start`, { method: "POST", body: { params: script!.params, intensity: script!.intensity } }),
    onSuccess: refresh,                // the server announces the start to everyone (exercise.inject)
    onError: fail,
  });
  const end = useMutation({
    mutationFn: (id: number) => api(`/ops/scenarios/runs/${id}/end`, { method: "POST" }),
    onSuccess: () => { refresh(); toast("Scenario ended", "INFO"); },
    onError: fail,
  });
  const sim = useMutation({
    mutationFn: (a: { action: string; speed?: number }) => api(`/sim/${a.action}`, { method: "POST", body: a.speed ? { speed: a.speed } : undefined }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scenarios"] }), onError: fail,
  });

  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (!q.data) return <div className="page"><ErrorText error={q.error} /></div>;
  const d = q.data;
  const running = !!sc?.run;
  return (
    <div className="page">
      <h1 className="page-title">Scenarios <Sim title="Everything in a scenario is simulated" />
        <span className="topbar-spacer" />
        {d.sim && <span style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, fontWeight: 400 }}>
          <span className="muted">Clock speed</span>
          <span className="seg" style={{ width: 150 }}>{[1, 10, 60].map((x) => (
            <button key={x} className={d.sim!.speed === x ? "on" : ""} disabled={!canClock} onClick={() => sim.mutate({ action: "speed", speed: x })}>×{x}</button>))}</span>
          {canClock && <button className="btn btn-sm" onClick={() => sim.mutate({ action: d.sim!.paused ? "resume" : "pause" })}>{d.sim.paused ? "Resume" : "Pause"}</button>}
        </span>}
      </h1>
      <p className="muted" style={{ margin: "-8px 0 16px" }}>The situation starts here. Start one or more scenarios; the Planner answers with the missions they demand, the plan, its impacts and the resources it needs.</p>
      {!d.sim?.enabled && <div className="notice notice-warn" style={{ marginBottom: 12 }}>The simulator is off (SIM_ENABLED=false). Scenarios need it on.</div>}

      <div className="scn-wrap">
        <div>
          <div className="scn-cards">
            {d.scenarios.map((s) => (
              <button key={s.code} className={`scn-card${s.code === sc?.code ? " on" : ""}`} onClick={() => setSelCode(s.code)} aria-pressed={s.code === sc?.code}>
                <span className="cat">{label(s.category)}</span>
                <span className="n">{s.name}</span>
                <span className="e">{scriptFor(s.code)?.summary ?? s.summary}</span>
                <span className="f"><IntensityDots i={scriptFor(s.code)?.intensity ?? s.intensity} />{s.run ? <span className="live-tag">live {mins(s.run.elapsed_min)}</span> : <span>ready</span>}</span>
              </button>
            ))}
          </div>
          {d.ended.length > 0 && <div className="scn-ended"><h3>Ended</h3>
            {d.ended.map((r) => <div key={r.id} className="r"><span>{r.name}</span>
              <span><span className="mono dim">{istTime(r.ended_sim, true)}</span>{user.role !== "VIEWER" && <> · <Link to={`/exercise/runs/${r.id}`}>After-action report</Link></>}</span></div>)}
          </div>}
        </div>

        {sc && script && (
          <aside className="scn-side">
            <div className="cat">{label(sc.category)} · <span style={{ color: INT_COLOUR[script.intensity] }}>{script.intensity.toLowerCase()} intensity</span></div>
            <h2>{sc.name}</h2>
            <p>{script.lead}</p>
            <dl className="scn-facts">
              {script.facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
              <div><dt>Intensity</dt><dd><IntensityDots i={script.intensity} /> {label(script.intensity)}</dd></div>
            </dl>
            <div className="field"><span className="field-label">Missions it affects</span>
              <span style={{ display: "flex", flexDirection: "column", gap: 4 }}>{script.missions.map((m) => (
                <span key={m.id} style={{ fontSize: 13 }}><PrioPill p={m.priority} /> {m.name} <span className="dim">· {m.kind}</span></span>))}</span></div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 20, flexWrap: "wrap" }}>
              {running ? <>
                <span className="live-tag" style={{ marginRight: "auto" }}>live {mins(sc.run!.elapsed_min)}</span>
                {canRun && <button className="btn btn-danger" disabled={end.isPending} onClick={() => end.mutate(sc.run!.id)}>End scenario</button>}
                <button className="btn" onClick={() => nav(`/planner?run=${sc.run!.id}&step=1`)}>Open in Planner →</button>
              </> : canRun ? (
                <button className="btn btn-primary" disabled={start.isPending} onClick={() => start.mutate()}>
                  {start.isPending ? "Starting…" : "Start now"}</button>
              ) : <span className="muted">Air HQ or the directing staff (admin) start scenarios.</span>}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
