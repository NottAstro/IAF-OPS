import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { ErrorText, Kpi, Loading, Row, Sim, ToneText, onActivate } from "../components/ui";
import { sevTone } from "../lib/format";
import { useStore } from "../store";

interface Roll { bases: number; aircraft: number; serviceable: number; airborne: number; serviceability: number | null; qra_met: number; qra_bases: number;
  pilots_available: number; pilots: number; below_reserve: number; ad_ok: number; ad_total: number; radar_ok: number; radar_total: number;
  alerts_critical: number; alerts_warning: number; alerts: number }
interface BaseRow { id: number; code: string; name: string; command: string; lat: number; lon: number; aircraft: number; serviceable: number; airborne: number;
  serviceability: number | null; qra_met: boolean | null; qra_postures: number; pilots_available: number; pilots: number; atf_pct: number | null;
  below_reserve: boolean; alerts: number; alerts_critical: number }
interface Ov { theatre: Roll; commands: (Roll & { code: string; name: string; operational: boolean })[]; bases: BaseRow[] }
interface OpsSum { rows: { command: string | null; priority: string; total: number; covered: number }[]; committed_plan_id: number | null;
  open_disruptions: number; pending_retask_id: number | null; pending_retask_summary: string | null }

/** Mission coverage for the next 24 h by command and priority: values only, no scores (FR-CMD-04). */
function MissionStrip() {
  const q = useQuery({ queryKey: ["ops-summary"], queryFn: () => api<OpsSum>("/ops/summary"), refetchInterval: 30000 });
  const nav = useNavigate();
  if (!q.data) return null;
  const cmds = ["WAC", "SWAC", "CAC", "EAC", "SAC"];
  const cell = (c: string | null, p?: string) => {
    const rs = q.data.rows.filter((r) => (c == null || r.command === c) && (!p || r.priority === p));
    const t = rs.reduce((a, r) => a + r.total, 0), v = rs.reduce((a, r) => a + r.covered, 0);
    return t ? <ToneText toneName={v < t ? (p === "P1" ? "critical" : p === "P2" ? "warning" : "caution") : "ok"}>{v}/{t}</ToneText> : <span className="dim">—</span>;
  };
  return (
    <>
      <h2 className="section-h" style={{ fontSize: "var(--t-h2)" }}>Missions, next 24 hours
        <span className="muted" style={{ fontSize: 13, fontWeight: 400 }}>
          {q.data.committed_plan_id ? <>tasked by plan <a href="#" onClick={(e) => { e.preventDefault(); nav("/planner"); }}>#{q.data.committed_plan_id}</a></> : "no plan committed"}
          {q.data.open_disruptions > 0 && <> · <ToneText toneName="warning">{q.data.open_disruptions} open disruptions</ToneText></>}
          {q.data.pending_retask_id && <> · <a href="#" onClick={(e) => { e.preventDefault(); nav("/planner"); }}>a change to the plan is waiting</a></>}
        </span></h2>
      <div className="table-wrap" style={{ marginBottom: 16 }}>
        <table className="table">
          <thead><tr><th>Covered / requested</th><th className="right">Theatre</th>{cmds.map((c) => <th key={c} className="right">{c}</th>)}</tr></thead>
          <tbody>
            {["P1", "P2", "P3", "P4"].map((p) => <tr key={p}><td>{p}</td><td className="num">{cell(null, p)}</td>{cmds.map((c) => <td key={c} className="num">{cell(c, p)}</td>)}</tr>)}
            <tr><td><b>All</b></td><td className="num">{cell(null)}</td>{cmds.map((c) => <td key={c} className="num">{cell(c)}</td>)}</tr>
          </tbody>
        </table>
      </div>
    </>
  );
}

export function Overview() {
  const q = useQuery({ queryKey: ["overview"], queryFn: () => api<Ov>("/overview"), refetchInterval: 30000 });
  const [cmd, setCmd] = useState<string | null>(null);
  const [sort, setSort] = useState<keyof BaseRow>("serviceability");
  const [asc, setAsc] = useState(true);
  const nav = useNavigate();
  const st = useStore();
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (q.error || !q.data) return <div className="page"><ErrorText error={q.error} /></div>;
  const t = q.data.theatre;
  const openBase = (b: BaseRow) => {
    st.set({ selection: { kind: "base", id: b.id }, panelTab: "Ov", mode: "LIVE" });
    nav("/map");
  };
  const openCommand = (code: string) => {
    const bs = q.data.bases.filter((b) => b.command === code);
    if (!bs.length) return;
    setCmd(code === cmd ? null : code);
    const lat = bs.reduce((a, b) => a + b.lat, 0) / bs.length, lon = bs.reduce((a, b) => a + b.lon, 0) / bs.length;
    st.requestFly(lat, lon, 5);
  };
  const rows = q.data.bases.filter((b) => !cmd || b.command === cmd).sort((a, b) => {
    const x = a[sort], y = b[sort];
    if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1; // nulls (bases without aircraft) last
    return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1);
  });
  const th = (k: keyof BaseRow, name: string, num = true) => (
    <th className={num ? "right" : ""} onClick={() => (sort === k ? setAsc(!asc) : (setSort(k), setAsc(true)))} aria-sort={sort === k ? (asc ? "ascending" : "descending") : "none"}>
      {name}{sort === k ? (asc ? " ▲" : " ▼") : ""}
    </th>
  );
  return (
    <div className="page">
      <h1 className="page-title">Command overview <Sim /></h1>
      <div className="kpis" style={{ gridTemplateColumns: "repeat(6, 1fr)", marginBottom: 16 }}>
        <Kpi large label="Aircraft serviceable" value={`${t.serviceability ?? "—"}%`} sub={`${t.serviceable}/${t.aircraft}`} toneName={sevTone(t.serviceability)} />
        <Kpi large label="QRA met" value={`${t.qra_met}/${t.qra_bases}`} sub="bases" toneName={t.qra_met < t.qra_bases ? "warning" : undefined} />
        <Kpi large label="Pilots available" value={t.pilots_available} sub={`of ${t.pilots}`} />
        <Kpi large label="Below fuel reserve" value={t.below_reserve} sub="bases" toneName={t.below_reserve ? "critical" : undefined} />
        <Kpi large label="AD / radar operational" value={`${Math.round((100 * t.ad_ok) / Math.max(t.ad_total, 1))}% / ${Math.round((100 * t.radar_ok) / Math.max(t.radar_total, 1))}%`} sub={`${t.ad_ok}/${t.ad_total} · ${t.radar_ok}/${t.radar_total}`} />
        <Kpi large label="Open alerts" value={t.alerts} sub={<><ToneText toneName="critical">{t.alerts_critical}</ToneText> · <ToneText toneName="warning">{t.alerts_warning}</ToneText></>}
          toneName={t.alerts_critical ? "critical" : t.alerts_warning ? "warning" : undefined} onClick={() => nav("/alerts")} />
      </div>
      <MissionStrip />
      <div className="grid-cmd">
        {q.data.commands.map((c) => (
          <div key={c.code} className="cmd-col" onClick={() => openCommand(c.code)} style={cmd === c.code ? { boxShadow: "inset 0 2px 0 var(--accent)" } : undefined}
            role="button" tabIndex={0} aria-label={`${c.name}: show bases`}>
            <div style={{ fontWeight: 700 }}>{c.code} <span className="dim" style={{ fontWeight: 400, fontSize: 11 }}>{c.operational ? "" : "support"}</span></div>
            <div className="dim" style={{ fontSize: 11, marginBottom: 6 }}>{c.name}</div>
            <Row label="Bases" value={c.bases} />
            <Row label="Serviceable" value={c.serviceability == null ? "—" : <ToneText toneName={sevTone(c.serviceability)}>{c.serviceability}%</ToneText>} />
            <Row label="QRA met" value={c.qra_bases ? <ToneText toneName={c.qra_met < c.qra_bases ? "warning" : "ok"}>{c.qra_met}/{c.qra_bases}</ToneText> : "—"} />
            <Row label="Pilots avail." value={c.pilots_available} />
            <Row label="Below reserve" value={c.below_reserve ? <ToneText toneName="critical">{c.below_reserve}</ToneText> : 0} />
            <Row label="Alerts" value={c.alerts_critical ? <ToneText toneName="critical">{c.alerts}</ToneText> : c.alerts} />
          </div>
        ))}
      </div>
      <h2 className="section-h" style={{ fontSize: "var(--t-h2)" }}>Bases {cmd && <span className="muted" style={{ fontSize: 14 }}>in {cmd} · <a href="#" onClick={(e) => { e.preventDefault(); setCmd(null); }}>show all</a></span>}</h2>
      <div className="table-wrap">
        <table className="table">
          <thead><tr>{th("code", "Base", false)}{th("command", "Cmd", false)}{th("aircraft", "Aircraft")}{th("serviceability", "S %")}
            {th("qra_met", "QRA", false)}{th("pilots_available", "Pilots avail.")}{th("atf_pct", "ATF %")}{th("alerts", "Alerts")}</tr></thead>
          <tbody>
            {rows.map((b) => (
              <tr key={b.id} onClick={() => openBase(b)} style={{ cursor: "pointer" }} tabIndex={0} onKeyDown={onActivate(() => openBase(b))}>
                <td><span className="mono">{b.code}</span> {b.name.replace("Air Force Station ", "")}</td><td>{b.command}</td>
                <td className="num">{b.aircraft}</td>
                <td className="num"><ToneText toneName={sevTone(b.serviceability)}>{b.serviceability ?? "—"}</ToneText></td>
                <td>{b.qra_postures ? <ToneText toneName={b.qra_met ? "ok" : "critical"}>{b.qra_met ? "Met" : "Short"}</ToneText> : <span className="dim">—</span>}</td>
                <td className="num">{b.pilots_available}/{b.pilots}</td>
                <td className="num"><ToneText toneName={b.below_reserve ? "critical" : (b.atf_pct ?? 100) < 40 ? "caution" : "ok"}>{b.atf_pct ?? "—"}</ToneText></td>
                <td className="num">{b.alerts ? <ToneText toneName={b.alerts_critical ? "critical" : "warning"}>{b.alerts}</ToneText> : 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
