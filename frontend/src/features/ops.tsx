// Phase 2 building blocks (PHASE2_IMPLEMENTATION_PLAN §10): pills, the package timeline, explanations and the plan KPI
// strip. Built only from the existing tokens and components; no new colours, fonts or libraries.
import type { ReactNode } from "react";
import type { Fix, PlanItemView, PlanKpis, PlanMission, Priority, Reason } from "../api/types";
import { Kpi, Row, ToneText, onActivate } from "../components/ui";
import { istTime, label, num, zulu } from "../lib/format";
import { barsOf, packLanes } from "./timeline";

const PRIO: Record<Priority, [string, string]> = { P1: ["critical", "■"], P2: ["warning", "◆"], P3: ["caution", "▲"], P4: ["neutral", "—"] };

/** Priority as glyph + word (urgency vocabulary; never colour alone). */
export const PrioPill = ({ p }: { p: Priority }) => (
  <span className={`pill s-${PRIO[p][0]}`} title={`Priority ${p[1]}`}><span aria-hidden>{PRIO[p][1]}</span>{p}</span>
);

const CHANGE: Record<string, [string, string, string]> = {
  KEPT: ["neutral", "—", "Kept"], SWAP: ["info", "○", "Tails / crew swapped"], MOVED: ["caution", "▲", "Moved"],
  NEW: ["ok", "●", "New"], DROPPED: ["critical", "■", "Dropped"], DIVERT: ["warning", "◆", "Divert"],
  REROLE: ["warning", "◆", "Re-roled in flight"],
};
export const ChangePill = ({ c }: { c: string | null }) => {
  const [t, g, w] = CHANGE[c ?? "KEPT"] ?? CHANGE.KEPT;
  return <span className={`pill s-${t}`}><span aria-hidden>{g}</span>{w}</span>;
};

export const hhmm = (d: string | null | undefined) => (d ? istTime(d).replace(" IST", "") : "—");

/** Plan KPI strip: values only, coverage by priority first. */
export function PlanKpiStrip({ k, extra }: { k: PlanKpis; extra?: ReactNode }) {
  const p = k.by_priority;
  const pct = k.missions ? Math.round((100 * k.covered) / k.missions) : 0;
  return (
    <div className="kpis plan-kpis">
      <Kpi label="Missions covered" value={<>{k.covered}<small> of {k.missions}</small></>} sub={`${pct}%`} toneName={k.unmet ? "caution" : undefined} />
      {(["P1", "P2", "P3", "P4"] as Priority[]).map((x) => p?.[x]?.of ? (
        <Kpi key={x} label={`${x} covered`} value={<>{p[x].covered}<small> of {p[x].of}</small></>}
          toneName={p[x].covered < p[x].of ? (x === "P1" ? "critical" : x === "P2" ? "warning" : "caution") : undefined} />
      ) : null)}
      {k.sorties != null && <Kpi label="Sorties / flying hours" value={<>{k.sorties}<small> · {num(k.flying_hours, 0)} h</small></>}
        sub={k.tanker_sorties ? `incl. ${k.tanker_sorties} tanker sortie${k.tanker_sorties > 1 ? "s" : ""}` : undefined} />}
      {k.fuel_l != null && <Kpi label="ATF planned" value={`${num((k.fuel_l ?? 0) / 1000, 0)} kL`} />}
      {k.snag_expected != null && <Kpi label="Expected defects" value={num(k.snag_expected, 1)} sub="predicted, all tails" />}
      {k.risk_peak != null && <Kpi label="Route risk" value={`${num(k.risk_peak, 2)}`} sub={`mean ${num(k.risk_mean, 2)}`} toneName={(k.risk_peak ?? 0) >= 0.5 ? "caution" : undefined} />}
      {k.qra_postures != null && <Kpi label="QRA kept" value={<>{k.qra_postures}<small> of {k.qra_postures}</small></>}
        sub={k.qra_backfill ? `${k.qra_backfill} aircraft held back to backfill` : "no QRA aircraft tasked"} />}
      <Kpi label="Solver" value={`${num((k.total_ms ?? k.solve_ms) / 1000, 1)} s`} sub={`${label(k.solver_status)}${k.candidates ? ` · ${k.candidates} options` : ""}`} />
      {extra}
    </div>
  );
}

/** Package timeline (Gantt): one row per base, one bar per package (and per tanker leg, on the tanker's base), the
 * horizon across. Hand-drawn SVG; layout in timeline.ts. */
export function Timeline({ items, start, end, selected, onSelect, now }: {
  items: PlanItemView[]; start: string; end: string; selected: number | null; onSelect: (id: number) => void; now?: string | null;
}) {
  const t0 = new Date(start).getTime(), t1 = new Date(end).getTime() + 3 * 3600e3;
  const W = 860, ROW = 22, LEFT = 64, TOP = 22;
  const x = (t: string | number) => LEFT + ((new Date(t).getTime() - t0) / (t1 - t0)) * (W - LEFT - 8);
  const ticks: number[] = [];
  for (let t = Math.ceil(t0 / 10800e3) * 10800e3; t <= t1; t += 10800e3) ticks.push(t);
  const bars = barsOf(items);
  const { rows, lane, lanes } = packLanes(bars, x);
  const rowTop = new Map<string, number>();
  let acc = TOP;
  for (const r of rows) { rowTop.set(r, acc); acc += lanes.get(r)! * ROW; }
  const H = acc + 6;
  return (
    <div className="timeline-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="group" aria-label={`Package timeline by base: ${bars.length} bars, Tab to move between them`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={TOP - 4} y2={H} className="tl-grid" />
            <text x={x(t)} y={12} className="tl-tick" textAnchor="middle">{hhmm(new Date(t).toISOString())}</text>
          </g>
        ))}
        {now && <line x1={x(now)} x2={x(now)} y1={TOP - 6} y2={H} className="tl-now" />}
        {rows.map((r) => {
          const top = rowTop.get(r)!, h = lanes.get(r)! * ROW;
          return (
            <g key={r}>
              <text x={4} y={top + 15} className="tl-base">{r}</text>
              <line x1={LEFT} x2={W} y1={top + h} y2={top + h} className="tl-rule" />
              {bars.filter((b) => b.row === r).map((b) => {
                const a = Math.max(LEFT, x(b.start)), z = Math.max(a + 3, x(b.end));
                const y = top + (lane.get(b.key) ?? 0) * ROW;
                return (
                  <g key={b.key} className={`tl-bar tl-${b.priority}${selected === b.itemId ? " on" : ""}${b.changed ? " changed" : ""}${b.support ? " support" : ""}`}
                    onClick={() => onSelect(b.itemId)} role="button" tabIndex={0} aria-pressed={selected === b.itemId}
                    aria-label={`${b.title}, ${hhmm(b.start)} to ${hhmm(b.end)}${b.changed ? ", changed" : ""}`} onKeyDown={onActivate(() => onSelect(b.itemId))}>
                    <title>{`${b.title} · ${hhmm(b.start)}–${hhmm(b.end)}`}</title>
                    <rect x={a} y={y + 4} width={z - a} height={ROW - 8} rx={2} />
                    {z - a > 46 && <text x={a + 4} y={y + 15} className="tl-label">{b.label}</text>}
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      <div className="status-strip" style={{ marginTop: 4, fontSize: 11 }}>
        <span className="s-critical">■ P1</span><span className="s-warning">◆ P2</span><span className="s-caution">▲ P3</span><span className="dim">— P4</span>
        <span className="dim">Bars run launch → recovery (IST). Dotted outline: tanker leg. Dashed outline: changed by a re-task. Times are simulated.</span>
      </div>
    </div>
  );
}

/** Why this package: score rows, binding constraints, alternatives that lost and why. */
export function Explanation({ it }: { it: PlanItemView }) {
  const e = it.explanation;
  return (
    <>
      {e?.rows.map((r) => <Row key={r.label + r.value} label={r.label} value={r.tone ? <ToneText toneName={r.tone}>{r.value}</ToneText> : r.value}
        extra={r.note ? <span className="dim" style={{ fontSize: 11 }}>{r.note}</span> : undefined} />)}
      {e && e.binding.length > 0 && <>
        <h4 className="section-h" style={{ fontSize: 13 }}>Binding constraints</h4>
        {e.binding.map((b) => <div key={b} className="dim" style={{ fontSize: 12, margin: "2px 0" }}>▲ {b}</div>)}
      </>}
      <h4 className="section-h" style={{ fontSize: 13 }}>Alternatives</h4>
      {!it.alternatives?.length && <div className="dim" style={{ fontSize: 12 }}>The only feasible option for this mission.</div>}
      {it.alternatives?.map((a) => (
        <Row key={a.base + a.type} label={<><span className="mono">{a.base}</span> {a.type}</>} extra={<span className="dim" style={{ fontSize: 11 }}>{a.why_not}</span>}
          value={<span className="dim">+{num(a.cost_delta, 1)}</span>} />
      ))}
      {e?.notes?.length ? <div className="notice" style={{ marginTop: 8 }}>{e.notes.join(" · ")}</div> : null}
    </>
  );
}

export function Unmet({ m, reasons, fixes }: { m: PlanMission; reasons: Reason[]; fixes: Fix[] }) {
  return (
    <>
      <Row label="Window" value={`${hhmm(m.window_start)}–${hhmm(m.window_end)} IST`} />
      <Row label="Needs" value={`${m.required_aircraft} aircraft · ${m.on_station_min} min on station · risk ≤ ${m.max_risk.toLowerCase()}`} />
      <h4 className="section-h" style={{ fontSize: 13 }}>Why it isn't covered</h4>
      {reasons.map((r) => (
        <div key={r.code} style={{ margin: "4px 0 8px" }}>
          <div><ToneText toneName={r.code === "CAPACITY_CONFLICT" ? "warning" : "caution"}>{r.text}</ToneText>
            <span className="dim mono" style={{ fontSize: 11 }}> ×{r.count}{r.nearest_km != null ? ` · nearest ${r.nearest_km} km` : ""}</span></div>
          {r.examples.slice(0, 3).map((x) => <div key={x} className="dim" style={{ fontSize: 12, marginLeft: 14 }}>{x}</div>)}
        </div>
      ))}
      {fixes.length > 0 && <h4 className="section-h" style={{ fontSize: 13 }}>What would fix it</h4>}
      {fixes.map((f) => <div key={f.text} className="s-info" style={{ fontSize: 13, margin: "3px 0" }}>○ {f.text}</div>)}
    </>
  );
}

export const zuluWindow = (a: string, b: string) => `${zulu(a)}–${zulu(b)}`;
