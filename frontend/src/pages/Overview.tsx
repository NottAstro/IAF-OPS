import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { ErrorText, Kpi, Loading, Sim, ToneText, onActivate } from "../components/ui";
import { INT_COLOUR, useSituations } from "../features/scenarioview";
import { situationState, validRun } from "../features/scripts";
import { istTime, sevTone } from "../lib/format";
import { useStore } from "../store";

interface Roll { bases: number; aircraft: number; serviceable: number; airborne: number; serviceability: number | null; qra_met: number; qra_bases: number;
  pilots_available: number; pilots: number; below_reserve: number; ad_ok: number; ad_total: number; radar_ok: number; radar_total: number }
interface BaseRow { id: number; code: string; name: string; command: string; lat: number; lon: number; aircraft: number; serviceable: number; airborne: number;
  serviceability: number | null; qra_met: boolean | null; qra_postures: number; pilots_available: number; pilots: number; atf_pct: number | null;
  below_reserve: boolean }
interface Ov { theatre: Roll; commands: (Roll & { code: string; name: string; operational: boolean })[]; bases: BaseRow[] }

const pct = (a: number, b: number) => Math.round((100 * a) / Math.max(b, 1));
const hm = (ms: number) => istTime(new Date(ms).toISOString()).replace(" IST", "");

/** The situations being handled now (D79): the same scripted state as the Planner and the Ops panel, values only (FR-CMD-04). */
function Situations() {
  const { sits, now, loading } = useSituations();
  const demo = useStore((s) => s.demo);
  const set = useStore((s) => s.set);
  const nav = useNavigate();
  if (loading) return null;
  const live = sits.filter((x) => x.runId != null).length;
  return (
    <section className="ov-sec">
      <h2 className="ov-h">Situations now <span>{live ? `${live} scenario${live === 1 ? "" : "s"} running, plus routine tasking` : "routine tasking only"}</span></h2>
      <div className="ov-sits">
        {sits.map((sit) => {
          const { approvedAt, rows, flying, next } = situationState(sit.script, validRun(demo[sit.key], sit.started), now);
          const summary = !approvedAt ? `${rows.length} missions · waiting for your decision`
            : [`${rows.length} missions`, flying ? `${flying} under way` : null, next ? `next launch ${hm(next)}` : flying ? null : "all back"].filter(Boolean).join(" · ");
          return (
            <div key={sit.key} className="ov-sit" style={{ borderLeftColor: sit.runId ? INT_COLOUR[sit.script.intensity] : "var(--accent)" }}>
              <div className="ov-sit-top"><b>{sit.script.name}</b>
                <span className={`fl-pill ${approvedAt ? "ok" : "warn"}`}>{approvedAt ? "approved" : "decide"}</span></div>
              <div className="ov-sit-sub">{sit.runId ? `${sit.script.category} · since ${hm(Date.parse(sit.started))}` : "today's tasking"}</div>
              <div className="ov-sit-sum">{summary}</div>
              <div className="ov-sit-act">
                <Link to={`/planner?run=${sit.key}&step=${approvedAt ? 4 : 1}`}>Planner ›</Link>
                {approvedAt && <a href="/map" onClick={(e) => { e.preventDefault(); set({ mode: "OPS", selection: null }); nav("/map"); }}>Ops map ›</a>}
              </div>
            </div>
          );
        })}
        {live === 0 && <Link className="ov-sit ov-sit-add" to="/scenarios">+ Start a scenario</Link>}
      </div>
    </section>
  );
}

const Bar = ({ value, tone }: { value: number | null; tone: string }) => (
  <div className="ov-bar" aria-hidden><i style={{ width: `${value ?? 0}%`, background: `var(--${tone})` }} /></div>
);

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
  const ad = pct(t.ad_ok, t.ad_total), radar = pct(t.radar_ok, t.radar_total);
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
      <p className="muted ov-lead">Readiness across the theatre and the situations being handled now. Every figure is simulated.</p>

      <section className="ov-sec">
        <h2 className="ov-h">Readiness <span>theatre, {t.bases} bases</span></h2>
        <div className="kpis" style={{ gridTemplateColumns: "repeat(6, 1fr)" }}>
          <Kpi large label="Aircraft serviceable" value={`${t.serviceability ?? "—"}%`} bar={t.serviceability} sub={`${t.serviceable} of ${t.aircraft}`} toneName={sevTone(t.serviceability)} />
          <Kpi large label="QRA met" value={`${t.qra_met}/${t.qra_bases}`} bar={pct(t.qra_met, t.qra_bases)} sub="bases holding their alert"
            toneName={t.qra_met < t.qra_bases ? "warning" : "ok"} />
          <Kpi large label="Pilots available" value={t.pilots_available} bar={pct(t.pilots_available, t.pilots)} sub={`of ${t.pilots}`} />
          <Kpi large label="Fuel below reserve" value={t.below_reserve} sub={t.below_reserve ? "bases" : "no base below reserve"} toneName={t.below_reserve ? "critical" : "ok"} />
          <Kpi large label="Air defence ready" value={`${ad}%`} bar={ad} sub={`${t.ad_ok} of ${t.ad_total} sites`} toneName={sevTone(ad)} />
          <Kpi large label="Radar operational" value={`${radar}%`} bar={radar} sub={`${t.radar_ok} of ${t.radar_total} sites`} toneName={sevTone(radar)} />
        </div>
      </section>

      <Situations />

      <section className="ov-sec">
        <h2 className="ov-h">Commands <span>click one to list its bases and centre the map on it</span></h2>
        <div className="ov-cmds">
          {q.data.commands.map((c) => (
            <div key={c.code} className={`ov-cmd${cmd === c.code ? " on" : ""}`} onClick={() => openCommand(c.code)} onKeyDown={onActivate(() => openCommand(c.code))}
              role="button" tabIndex={0} aria-pressed={cmd === c.code} aria-label={`${c.name}: show bases`}>
              <div className="ov-cmd-top"><b>{c.code}</b>{!c.operational && <span className="dim">support</span>}<span className="dim ov-cmd-n">{c.bases} bases</span></div>
              <div className="ov-cmd-name">{c.name}</div>
              <div className="ov-cmd-svc">{c.serviceability == null ? <span className="dim">—</span> : <ToneText toneName={sevTone(c.serviceability)}>{c.serviceability}%</ToneText>}
                <span className="dim">{c.serviceability == null ? "no aircraft" : "serviceable"}</span></div>
              <Bar value={c.serviceability} tone={sevTone(c.serviceability)} />
              <div className="ov-cmd-facts">
                <span>QRA {c.qra_bases ? <ToneText toneName={c.qra_met < c.qra_bases ? "warning" : "ok"}>{c.qra_met}/{c.qra_bases}</ToneText> : "—"}</span>
                <span>Pilots {c.pilots_available}</span>
                <span>Fuel {c.below_reserve ? <ToneText toneName="critical">{c.below_reserve} low</ToneText> : "ok"}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="ov-sec">
        <h2 className="ov-h">Bases {cmd ? <span>in {cmd} · <a href="#" onClick={(e) => { e.preventDefault(); setCmd(null); }}>show all</a></span>
          : <span>lowest serviceability first · click a base to open it on the map</span>}</h2>
        <div className="table-wrap">
          <table className="table">
            <thead><tr>{th("code", "Base", false)}{th("command", "Command", false)}{th("aircraft", "Aircraft")}{th("serviceability", "Serviceable")}
              {th("qra_met", "QRA", false)}{th("pilots_available", "Pilots available")}{th("atf_pct", "Fuel (ATF %)")}</tr></thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.id} onClick={() => openBase(b)} style={{ cursor: "pointer" }} tabIndex={0} onKeyDown={onActivate(() => openBase(b))}>
                  <td><span className="mono">{b.code}</span> {b.name.replace("Air Force Station ", "")}</td><td>{b.command}</td>
                  <td className="num">{b.aircraft}</td>
                  <td className="num"><span className="ov-cell-bar"><ToneText toneName={sevTone(b.serviceability)}>{b.serviceability == null ? "—" : `${b.serviceability}%`}</ToneText>
                    <Bar value={b.serviceability} tone={sevTone(b.serviceability)} /></span></td>
                  <td>{b.qra_postures ? <ToneText toneName={b.qra_met ? "ok" : "critical"}>{b.qra_met ? "Met" : "Short"}</ToneText> : <span className="dim">—</span>}</td>
                  <td className="num">{b.pilots_available}/{b.pilots}</td>
                  <td className="num"><ToneText toneName={b.below_reserve ? "critical" : (b.atf_pct ?? 100) < 40 ? "caution" : "ok"}>{b.atf_pct ?? "—"}</ToneText></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
