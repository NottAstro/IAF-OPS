// Manual planning baseline (ARCHITECTURE D43, PS-8): plan the snapshot by hand against the clock, with the real rules
// as the referee, then compare with the optimiser on the same snapshot. Existing components and tokens only.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Priority } from "../api/types";
import { ErrorText, Kpi, Sim, ToneText } from "../components/ui";
import { istTime, num } from "../lib/format";
import { PrioPill, hhmm } from "./ops";

interface Opt { base_id: number; base: string; type_id: number; type: string; aircraft: number }
interface MMission { mission_id: number; code: string; name: string; type: string; priority: Priority; window_start: string; window_end: string;
  required: number; on_station_min: number; depends_on: number | null; options: Opt[] }
interface Session { id: number; started_at: string; missions: MMission[] }
interface Pick { base: string; time: string }
interface RowResult { ok: boolean; reason?: string; detail?: string; note?: string }
interface Check { rows: Record<string, RowResult>; covered: number; missions: number; violations: number;
  by_priority: Record<Priority, { covered: number; of: number }> }
interface Outcome { manual: { covered: number; missions: number; by_priority: Record<Priority, { covered: number; of: number }> };
  optimiser: { covered: number; missions: number; by_priority: Record<Priority, { covered: number; of: number }>; total_ms: number };
  elapsed_s: number; checks: number; rows: Record<string, RowResult> }
interface Past { id: number; started_at: string; missions: number; checks: number; planner: string | null; result: Omit<Outcome, "rows"> }

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** On-station times a planner can choose: every 30 min from the window start while the time on station still fits. */
function times(m: MMission): string[] {
  const out: string[] = [];
  const end = new Date(m.window_end).getTime() - m.on_station_min * 60e3;
  for (let t = new Date(m.window_start).getTime(); t <= end && out.length < 24; t += 30 * 60e3) out.push(new Date(t).toISOString());
  return out.length ? out : [m.window_start];
}

export function ManualTab({ canPlan }: { canPlan: boolean }) {
  const qc = useQueryClient();
  const [s, setS] = useState<Session | null>(null);
  const [picks, setPicks] = useState<Record<number, Pick>>({});
  const [check, setCheck] = useState<Check | null>(null);
  const [done, setDone] = useState<Outcome | null>(null);
  const [now, setNow] = useState(Date.now());
  const [checks, setChecks] = useState(0);
  useEffect(() => { if (!s || done) return; const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, [s, done]);
  const past = useQuery({ queryKey: ["manual"], queryFn: () => api<{ items: Past[] }>("/ops/manual") });
  const body = () => ({ picks: Object.entries(picks).filter(([, p]) => p.base).map(([mid, p]) => {
    const [b, t] = p.base.split(":").map(Number);
    return { mission_id: Number(mid), base_id: b, type_id: t, on_station: p.time || null };
  }) });
  const start = useMutation({ mutationFn: () => api<Session>("/ops/manual", { method: "POST" }),
    onSuccess: (r) => { setS(r); setPicks({}); setCheck(null); setDone(null); setChecks(0); setNow(Date.now()); } });
  const run = useMutation({ mutationFn: () => api<Check>(`/ops/manual/${s!.id}/check`, { method: "POST", body: body() }),
    onSuccess: (r) => { setCheck(r); setChecks((n) => n + 1); } });
  const finish = useMutation({ mutationFn: () => api<Outcome>(`/ops/manual/${s!.id}/finish`, { method: "POST", body: body() }),
    onSuccess: (r) => { setDone(r); setCheck({ ...r.manual, rows: r.rows, violations: 0 } as Check); qc.invalidateQueries({ queryKey: ["manual"] }); } });
  const elapsed = s ? (done ? done.elapsed_s : (now - new Date(s.started_at).getTime()) / 1000) : 0;
  const err = start.error || run.error || finish.error;

  if (!s) return (
    <div>
      <h3 className="section-h">Manual planning baseline <Sim /></h3>
      <div className="muted" style={{ maxWidth: 760, marginBottom: 10 }}>
        Plan the next 24 hours by hand, against the clock: for each mission choose a base, an aircraft type and a time on station.
        The same rules as the planner judge your picks (range, weather, crew, rest, fuel, weapons, airspace, launch rate, the validator).
        When you finish, the optimiser plans the same snapshot so the two can be compared (PS-8).
      </div>
      {canPlan ? <button className="btn btn-primary" disabled={start.isPending} onClick={() => start.mutate()}>{start.isPending ? "Starting…" : "Start a timed session"}</button>
        : <div className="empty">Air HQ and command planners can run a session.</div>}
      {err && <ErrorText error={err} />}
      <h3 className="section-h" style={{ marginTop: 18 }}>Past sessions</h3>
      {!past.data?.items.length && <div className="empty">No finished sessions yet.</div>}
      {!!past.data?.items.length && <div className="table-wrap"><table className="table" style={{ fontSize: 12 }}>
        <thead><tr><th>Started</th><th>Planner</th><th className="right">Missions</th><th className="right">By hand</th><th className="right">Optimiser</th>
          <th className="right">P1 by hand / optimiser</th><th className="right">Time</th><th className="right">Checks</th></tr></thead>
        <tbody>{past.data.items.map((x) => (
          <tr key={x.id}><td className="mono">{istTime(x.started_at, true)}</td><td>{x.planner ?? "—"}</td><td className="num">{x.missions}</td>
            <td className="num">{x.result.manual.covered}</td><td className="num">{x.result.optimiser.covered}</td>
            <td className="num">{x.result.manual.by_priority.P1.covered} / {x.result.optimiser.by_priority.P1.covered}</td>
            <td className="num">{mmss(x.result.elapsed_s)} <span className="dim">vs {num(x.result.optimiser.total_ms / 1000, 1)} s</span></td>
            <td className="num">{x.checks}</td></tr>
        ))}</tbody>
      </table></div>}
    </div>
  );

  return (
    <div>
      <div className="kpis plan-kpis">
        <Kpi label="Time" value={mmss(elapsed)} sub={done ? "finished" : "running"} toneName={done ? undefined : "info"} />
        <Kpi label="Covered by hand" value={<>{check?.covered ?? 0}<small> of {s.missions.length}</small></>}
          sub={check ? `P1 ${check.by_priority.P1.covered} of ${check.by_priority.P1.of}` : "check to score"} />
        {done && <Kpi label="Optimiser, same snapshot" value={<>{done.optimiser.covered}<small> of {done.optimiser.missions}</small></>}
          sub={`P1 ${done.optimiser.by_priority.P1.covered} of ${done.optimiser.by_priority.P1.of} · ${num(done.optimiser.total_ms / 1000, 1)} s`} />}
        <Kpi label="Checks" value={String(done?.checks ?? checks)} sub="rule checks run" />
      </div>
      <div className="toolbar" style={{ margin: "10px 0" }}>
        {!done && <><button className="btn" disabled={run.isPending} onClick={() => run.mutate()}>{run.isPending ? "Checking…" : "Check my plan"}</button>
          <button className="btn btn-primary" disabled={finish.isPending} onClick={() => confirm("Stop the clock and score this plan?") && finish.mutate()}>
            {finish.isPending ? "Scoring…" : "Finish"}</button></>}
        {done && <button className="btn" onClick={() => setS(null)}>Back to sessions</button>}
        <span className="muted" style={{ fontSize: 12 }}>Times are simulated (IST). A pick that can't fly at the time you chose takes the nearest workable time.</span>
      </div>
      {err && <ErrorText error={err} />}
      <div className="table-wrap" style={{ maxHeight: 560 }}>
        <table className="table" style={{ fontSize: 12 }}>
          <thead><tr><th>Pri.</th><th>Mission</th><th>Window</th><th className="right">Needs</th><th>Base · type</th><th>On station</th><th>Verdict</th></tr></thead>
          <tbody>{s.missions.map((m) => {
            const p = picks[m.mission_id] ?? { base: "", time: "" };
            const r = check?.rows[String(m.mission_id)];
            const set = (k: keyof Pick, v: string) => setPicks({ ...picks, [m.mission_id]: { ...p, [k]: v } });
            return (
              <tr key={m.mission_id}>
                <td><PrioPill p={m.priority} /></td>
                <td style={{ maxWidth: 260 }}><span className="mono">{m.code.replace(/^SIM-/, "")}</span> <span className="dim">{m.name}</span></td>
                <td className="mono">{hhmm(m.window_start)}–{hhmm(m.window_end)}</td>
                <td className="num">{m.required} × {m.on_station_min} min</td>
                <td><select className="select" aria-label={`Base and type for ${m.code}`} value={p.base} disabled={!!done} onChange={(e) => set("base", e.target.value)}>
                  <option value="">Leave uncovered</option>
                  {m.options.map((o) => <option key={`${o.base_id}:${o.type_id}`} value={`${o.base_id}:${o.type_id}`}>{o.base} · {o.type} ({o.aircraft})</option>)}
                </select></td>
                <td><select className="select" aria-label={`Time on station for ${m.code}`} value={p.time} disabled={!!done || !p.base} onChange={(e) => set("time", e.target.value)}>
                  <option value="">Earliest</option>
                  {times(m).map((t) => <option key={t} value={t}>{hhmm(t)}</option>)}
                </select></td>
                <td style={{ whiteSpace: "normal", maxWidth: 280 }}>{!r ? <span className="dim">—</span>
                  : r.ok ? <ToneText toneName="ok">{r.note || "Flies"}</ToneText>
                  : <><ToneText toneName="caution">{r.reason}</ToneText>{r.detail && <div className="dim" style={{ fontSize: 11 }}>{r.detail}</div>}</>}</td>
              </tr>
            );
          })}</tbody>
        </table>
      </div>
      {err instanceof ApiError && err.status === 409 && <div className="notice">This session is already finished.</div>}
    </div>
  );
}
