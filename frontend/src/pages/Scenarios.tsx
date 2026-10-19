// Scenarios (ARCHITECTURE D55; replaces Exercise control): the eight incidents, each one event. Pick one, set its
// parameters or intensity, start it; the Planner shows its impact and what to do about it. ADMIN acts as directing
// staff and Air HQ start and end them; other roles see the page read-only.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Intensity, ParamValue, ScenarioCard, ScenarioCatalogue, ScenarioParam, User } from "../api/types";
import { ErrorText, Loading, Sim } from "../components/ui";
import { PrioPill } from "../features/ops";
import { INT_COLOUR, IntensityDots, mins } from "../features/scenarioview";
import { istTime, label } from "../lib/format";
import { useStore } from "../store";

const LEVELS: Intensity[] = ["LOW", "MEDIUM", "HIGH", "SEVERE"];

function defaults(sc: ScenarioCard, lvl: Intensity): Record<string, ParamValue> {
  const p: Record<string, ParamValue> = {};
  for (const f of sc.params) p[f.key] = f.default;
  return { ...p, ...(sc.intensity_presets[lvl] ?? {}) };
}

export function Scenarios({ user }: { user: User }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useStore((s) => s.toast);
  const q = useQuery({ queryKey: ["scenarios", "catalogue"], queryFn: () => api<ScenarioCatalogue>("/ops/scenarios"), refetchInterval: 5000 });
  const [selCode, setSelCode] = useState<string | null>(null);
  const [lvl, setLvl] = useState<Intensity>("MEDIUM");
  const [form, setForm] = useState<Record<string, ParamValue>>({});
  const canRun = user.role === "ADMIN" || user.role === "COMMAND_HQ";   // start / end scenarios
  const canClock = user.role === "ADMIN";                                // simulator speed and pause
  const sc = q.data?.scenarios.find((s) => s.code === selCode) ?? q.data?.scenarios.find((s) => s.run) ?? q.data?.scenarios[0];
  useEffect(() => {                    // a new selection starts from its own intensity and defaults (or what it runs with)
    if (!sc) return;
    const l = sc.run?.intensity ?? sc.intensity;
    setLvl(l);
    setForm(sc.run ? sc.run.params : defaults(sc, l));
  }, [sc?.code, sc?.run?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => ["scenarios", "scenario-response", "plans", "disruptions", "missions", "summary"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const fail = (e: unknown) => toast(e instanceof ApiError ? e.message : "Failed", "CRITICAL");
  const start = useMutation({
    mutationFn: () => api<{ run_id: number }>(`/ops/scenarios/${sc!.code}/start`, { method: "POST", body: { params: form, intensity: lvl } }),
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
                <span className="e">{s.summary}</span>
                <span className="f"><IntensityDots i={s.run?.intensity ?? s.intensity} />{s.run ? <span className="live-tag">live {mins(s.run.elapsed_min)}</span> : <span>ready</span>}</span>
              </button>
            ))}
          </div>
          {d.ended.length > 0 && <div className="scn-ended"><h3>Ended</h3>
            {d.ended.map((r) => <div key={r.id} className="r"><span>{r.name}</span>
              <span><span className="mono dim">{istTime(r.ended_sim, true)}</span>{user.role !== "VIEWER" && <> · <Link to={`/exercise/runs/${r.id}`}>After-action report</Link></>}</span></div>)}
          </div>}
        </div>

        {sc && (
          <aside className="scn-side">
            <div className="cat">{label(sc.category)} · <span style={{ color: INT_COLOUR[lvl] }}>{lvl.toLowerCase()} intensity</span></div>
            <h2>{sc.name}</h2>
            <p>{sc.description}</p>
            <div className="field"><span className="field-label">Adds missions</span>
              {sc.adds.length ? <span style={{ display: "flex", flexDirection: "column", gap: 4 }}>{sc.adds.map((a, k) => (
                <span key={k} style={{ fontSize: 13 }}><PrioPill p={a.priority} /> {a.label}</span>))}</span>
                : <span className="muted" style={{ fontSize: 13 }}>None: it takes resources away, and the planner works round it.</span>}</div>
            {sc.params.filter((f) => f.kind !== "hidden").map((f) => (
              <Field key={f.key} f={f} value={form[f.key]} disabled={running || !canRun} cat={d}
                onChange={(v) => setForm({ ...form, [f.key]: v })} />
            ))}
            <label className="field"><span className="field-label">Intensity</span>
              <span className="seg">{LEVELS.map((l) => (
                <button key={l} className={l === lvl ? "on" : ""} disabled={running || !canRun}
                  onClick={() => { setLvl(l); setForm(defaults(sc, l)); }}>{label(l)}</button>))}</span></label>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 20, flexWrap: "wrap" }}>
              {running ? <>
                <span className="live-tag" style={{ marginRight: "auto" }}>live {mins(sc.run!.elapsed_min)}</span>
                {canRun && <button className="btn btn-danger" disabled={end.isPending} onClick={() => end.mutate(sc.run!.id)}>End scenario</button>}
                <button className="btn" onClick={() => nav(`/planner?view=situation&run=${sc.run!.id}`)}>Open in Planner →</button>
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

function Field({ f, value, disabled, cat, onChange }: { f: ScenarioParam; value: ParamValue | undefined; disabled: boolean;
  cat: ScenarioCatalogue; onChange: (v: ParamValue) => void }) {
  const name = (code: string) => cat.bases.find((b) => b.code === code)?.name ?? code;
  return (
    <label className="field" onClick={(e) => f.kind === "choice" && e.preventDefault()}>
      <span className="field-label">{f.label}</span>
      {f.kind === "base" && <select className="select" value={String(value ?? "")} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {cat.bases.map((b) => <option key={b.code} value={b.code}>{b.name} {b.code}</option>)}</select>}
      {f.kind === "type" && <select className="select" value={String(value ?? "")} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {cat.types.map((t) => <option key={t}>{t}</option>)}</select>}
      {f.kind === "choice" && <span className="seg">{(f.options ?? []).map((o) => (
        <button key={String(o)} type="button" className={o === value ? "on" : ""} disabled={disabled} onClick={() => onChange(o)}>{o}{f.unit ? ` ${f.unit}` : ""}</button>))}</span>}
      {f.kind === "text" && <input className="input" value={String(value ?? "")} disabled={disabled} onChange={(e) => onChange(e.target.value)} />}
      {f.kind === "bases" && <span className="chips">
        {((value as string[]) ?? []).map((c) => <span key={c} className="chip">{name(c)}
          {!disabled && <button type="button" aria-label={`Remove ${name(c)}`} onClick={() => onChange((value as string[]).filter((x) => x !== c))}>×</button>}</span>)}
        {!disabled && <select className="select" value="" style={{ width: 120 }} onChange={(e) => e.target.value && onChange([...((value as string[]) ?? []), e.target.value])}>
          <option value="">Add base…</option>
          {cat.bases.filter((b) => !((value as string[]) ?? []).includes(b.code)).map((b) => <option key={b.code} value={b.code}>{b.name}</option>)}</select>}
      </span>}
    </label>
  );
}
