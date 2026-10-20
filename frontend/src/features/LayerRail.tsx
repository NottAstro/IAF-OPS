import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { LiveScenario } from "../api/types";
import { FLYING, GLYPH, ROUTINE, type Script, type Status, isGround, routineStart, scriptFor, situationState, statusWord, validRun } from "./scripts";
import { INT_COLOUR } from "./scenarioview";
import { istTime, zulu } from "../lib/format";
import { OptionPanel } from "../components/OptionPanel";
import { SettingsWindow } from "../components/SettingsWindow";
import { LAYERS, LAYER_GROUPS, LIVE_CATS, LIVE_GROUP, type LayerId, type LiveCat, MODES, type Mode, type WxLayer, WX_LAYERS, layerMode, layerSim, useStore } from "../store";

const CAT: Record<LiveCat, { label: string; color: string; note: string }> = {
  civil: { label: "Civil aircraft", color: "var(--caution)", note: "Airliners, cargo, business jets and civil helicopters" },
  military: { label: "Military aircraft", color: "var(--accent)", note: "Indian military aircraft rarely broadcast on public ADS-B" },
  uav: { label: "UAVs & drones", color: "var(--warning)", note: "Most UAVs and drones don't broadcast on public ADS-B" },
};
const WX: Record<WxLayer, { label: string; swatch: ReactNode }> = {
  clouds: { label: "Cloud cover (satellite)", swatch: <span className="swatch" style={{ background: "radial-gradient(circle, #fff 30%, #9fc3ea 100%)" }} /> },
  rain: { label: "Rain", swatch: <span className="swatch" style={{ background: "linear-gradient(135deg, #7ec8ff, #6b5bff)" }} /> },
  wind: { label: "Wind flow", swatch: <span className="swatch-line" style={{ borderColor: "#e1f0ff" }} /> },
  metar: { label: "Airfield weather (METAR)", swatch: <span className="swatch-dot" style={{ background: "var(--ok)" }} /> },
};
/** Map settings → Map angle (D58): value, label, sub-label, icon. */
const ANGLES: [boolean, string, string, ReactNode][] = [
  [true, "Tilted", "3D terrain", <><path d="M8 5h18l6 15H2z" /><path d="m8 17 6-6 4 4 3-3 5 5" /></>],
  [false, "Straight", "top-down", <><rect x="8" y="2" width="18" height="18" rx="2" /><path d="M8 11h18M17 2v18" /><path d="m17 5-1.6 3h3.2z" /></>],
];
/** Icons for the Map settings rows (outline, currentColor). */
const GROUP_ICON: Record<string, ReactNode> = {
  View: <><path d="M12 3 3 8l9 5 9-5z" /><path d="m3 13 9 5 9-5" /></>,
  "Air bases": <path d="M12 3c.8 0 1.2.8 1.2 2v4.5l7 4v1.8l-7-2v4l2 1.6V20L12 19.3 9.8 20v-1.1l2-1.6v-4l-7 2v-1.8l7-4V5c0-1.2.4-2 1.2-2z" />,
  "Boundaries & names": <><path d="m3 6 6-2 6 2 6-2v14l-6 2-6-2-6 2z" /><path d="M9 4v14M15 6v14" /></>,
  symbols: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>,
};
const VIEW: Record<Mode, { tab: string; hint: string; icon: ReactNode }> = {
  LIVE: { tab: "Live", hint: "Aircraft broadcasting on public ADS-B, updated every 10 s. Tilted or straight: Map settings → Map angle.",
    icon: <path fill="currentColor" stroke="none" d="M12 2.5l1.5 6.3 7.5 4.4v1.9l-7.5-2.3-.4 5.5 2.7 2v1.4L12 20.7l-3.8 1v-1.4l2.7-2-.4-5.5L3 15.1v-1.9l7.5-4.4z" /> },
  WX: { tab: "Weather", hint: "Satellite clouds, rain and wind on a flat map. Click anywhere for a point forecast.",
    icon: <path d="M7 18.5h10.6a4.1 4.1 0 0 0 .6-8.15A6.1 6.1 0 0 0 6.5 9.6 4.5 4.5 0 0 0 7 18.5z" /> },
  INFRA: { tab: "Infra", hint: "Roads, rail, airports and simulated defence sites. Select an air base to see its nearest railheads, airports and IAF bases.",
    icon: <><path d="M8 21 11 3M16 21 13 3" /><path d="M12 6.5v2M12 11.5v2.5M12 17v3" /></> },
  OPS: { tab: "Ops", hint: "The simulated operational picture. Click a mission to follow it on the map.",
    icon: <><circle cx="12" cy="12" r="7.5" /><circle cx="12" cy="12" r="2.2" /><path d="M12 2.5v4M12 17.5v4M2.5 12h4M17.5 12h4" /></> },
};
const SWATCH: Record<LayerId, ReactNode> = {
  highways: <span className="swatch-line" style={{ borderColor: "var(--map-highway)", boxShadow: "0 0 6px var(--map-highway)" }} />,
  roads: <span className="swatch-line" style={{ borderColor: "var(--map-road-major)" }} />,
  rail: <span className="swatch-line" style={{ borderColor: "var(--map-rail-main)", borderTopWidth: 3, borderTopStyle: "dashed" }} />,
  stations: <span className="swatch" style={{ background: "var(--map-station)", width: 9, height: 9, borderRadius: 2, justifySelf: "center" }} />,
  "civil-airports": <span className="swatch" style={{ background: "#e3ecf8", borderRadius: 3 }} />,
  towers: <svg className="swatch" viewBox="0 0 24 24" fill="var(--bg)" stroke="var(--map-tower)" strokeWidth="1.6" aria-hidden><rect x="1" y="1" width="22" height="22" rx="4" /><path fill="none" d="m8 20 4-15 4 15M9 16h6M7 6Q2 10 7 13M17 6q5 4 0 7" /></svg>,
  relief: <span className="swatch" style={{ background: "linear-gradient(135deg, var(--relief-1), var(--relief-3), var(--relief-5))" }} />,
  satellite: <span className="swatch" style={{ background: "linear-gradient(135deg, #2b4a3a, #4a5b72)" }} />,
  "iaf-bases": <span className="swatch" style={{ background: "var(--base-iaf)", boxShadow: "0 0 6px var(--base-iaf)" }} />,
  algs: <span className="swatch" style={{ background: "var(--base-iaf)", width: 9, height: 9, justifySelf: "center" }} />,
  "other-mil": <span className="swatch" style={{ background: "var(--base-other)" }} />,
  "foreign-bases": <span className="swatch" style={{ background: "var(--base-hostile)" }} />,
  "india-border": <span className="swatch-line" style={{ borderColor: "var(--map-india-border)", boxShadow: "0 0 6px var(--map-india-border)" }} />,
  "intl-borders": <span className="swatch-line" style={{ borderColor: "var(--map-intl-border)" }} />,
  states: <span className="swatch-line" style={{ borderColor: "var(--map-admin1)", borderTopWidth: 1 }} />,
  districts: <span className="swatch-line" style={{ borderColor: "var(--map-admin2)", borderTopStyle: "dashed", borderTopWidth: 1 }} />,
  places: <span className="toggle-count" style={{ color: "var(--map-label)" }}>Aa</span>,
  "ops-missions": <span className="swatch-dot" style={{ background: "var(--ok)", boxShadow: "0 0 0 2px var(--bg), 0 0 0 3px var(--caution)" }} />,
  "ops-threat": <span className="swatch" style={{ background: "rgb(248 113 113 / .18)", border: "1px dashed var(--base-hostile)" }} />,
  "ops-radar-sites": <svg className="swatch" viewBox="0 0 24 24" fill="var(--bg)" stroke="var(--sim)" strokeWidth="1.8" aria-hidden><circle cx="12" cy="12" r="10" /><path fill="none" d="m11 13 6-6M11 9.5a3.5 3.5 0 0 1 3.5 3.5M11 7a6 6 0 0 1 6 6" /></svg>,
  "ops-ad-sites": <svg className="swatch" viewBox="0 0 24 24" fill="var(--bg)" stroke="var(--sim)" strokeWidth="1.8" aria-hidden><path d="M4 3h16v10q0 5-8 9-8-4-8-9z" /><path fill="none" d="m7.5 13 4.5-5 4.5 5M12 8v9" /></svg>,
  "ops-comms": <svg className="swatch" viewBox="0 0 24 24" fill="var(--bg)" stroke="var(--sim)" strokeWidth="1.8" aria-hidden><path d="M12 1 23 12 12 23 1 12z" /><path fill="none" d="m9 17 3-9 3 9M10 14h4" /></svg>,
  "ops-coverage": <span className="swatch" style={{ borderRadius: "50%", border: "1px dashed var(--info)", background: "var(--accent-tint)" }} />,
};

/** Ops view status: the simulator clock, then one card per situation with its missions (D72, cards D74). */
const ST_TONE: Record<Status, string> = { waiting: "s-warning", approved: "s-ok", airborne: "s-sim", "on station": "s-sim",
  returning: "s-sim", landed: "dim", "not flown": "s-critical" };
const hm = (ms: number) => istTime(new Date(ms).toISOString()).replace(" IST", "");

/** A package's aircraft as a small top view, tinted by its state. */
const AcIcon = ({ type, tone }: { type: string; tone: string }) => (
  <svg className={`msn-ac ${tone}`} viewBox="0 0 24 24" aria-hidden>
    {GLYPH(type) === "helicopter"
      ? <g fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M4 5h16M12 5v3M12 16v5M10 21h4" /><ellipse cx="12" cy="12" rx="3.3" ry="4.3" fill="currentColor" /></g>
      : GLYPH(type) === "uav"
      ? <path fill="currentColor" d="M11 3h2v15h3v1.8H8V18h3zM1 8h22v2.2H1z" />
      : GLYPH(type) === "vehicle"
      ? <path fill="currentColor" fillRule="evenodd" d="M9 2.5h6a2.5 2.5 0 0 1 2.5 2.5v14a2.5 2.5 0 0 1-2.5 2.5H9A2.5 2.5 0 0 1 6.5 19V5A2.5 2.5 0 0 1 9 2.5zM8.3 6.5v3.2h7.4V6.5z" />
      : <path fill="currentColor" d="M12 2c.8 0 1.3 1.2 1.3 3v4.2l7.7 4.6v2l-7.7-2.2v4.3l2.4 1.9V21L12 20l-3.7 1v-1.2l2.4-1.9v-4.3L3 15.8v-2l7.7-4.6V5c0-1.8.5-3 1.3-3z" />}
  </svg>
);

/** Ops panel missions (D72, D74): one card per situation (left edge in its intensity colour, approved / decide pill, a one-line
 * summary), opening to one row per mission: priority badge, mission, aircraft and package, status, and a progress bar while
 * it flies. Cards start closed (D78). A click frames that package on the map (D71); a second click frames it again. Routine
 * tasking is listed once approved. */
function OpsStatus() {
  const s = useStore();
  const live = useQuery({ queryKey: ["scenarios", "live"], queryFn: () => api<LiveScenario[]>("/ops/scenarios/live"), refetchInterval: 15000 });
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const c = s.simClock, now = c?.sim_now ?? new Date().toISOString(), t = Date.parse(now);
  const sel = s.selection?.kind === "plan-mission" ? s.selection : null;
  const groups: { key: string; name: string; script: Script; started: string }[] = (live.data ?? []).flatMap((r) => {
    const script = scriptFor(r.code);
    return script ? [{ key: String(r.id), name: r.name, script, started: r.started_sim }] : [];
  });
  if (validRun(s.demo.routine, routineStart(now))?.approvedAt) groups.push({ key: "routine", name: ROUTINE.name, script: ROUTINE, started: routineStart(now) });
  return (
    <div style={{ margin: "2px 0 6px" }}>
      <div className="tool-row" style={{ borderTop: 0 }}><span>Simulator</span>
        <b className="mono" style={{ marginLeft: "auto", color: "var(--sim)" }}>{c ? `${zulu(c.sim_now)} ×${c.speed}${c.paused ? " paused" : ""}` : "not running"}</b></div>
      <div className="ms-cap ops-sec">Missions <span>click one to see it on the map</span></div>
      <div className="msn-list">
        {groups.map(({ key, name, script, started }) => {
          const sit = situationState(script, validRun(s.demo[key], started), now), { approvedAt, flying, next } = sit;
          const rows = sit.rows.map((r) => ({ ...r, pct: FLYING.includes(r.st) ? ((t - r.launch) / (r.back - r.launch)) * 100 : null }));
          const summary = !approvedAt ? `${rows.length} missions · waiting for your decision`
            : [`${rows.length} missions`, flying ? `${flying} under way` : null, next ? `next launch ${hm(next)}` : flying ? null : "all back"].filter(Boolean).join(" · ");
          const isOpen = open[key] ?? false;   // every card starts closed
          const edge = key === "routine" ? "var(--accent)" : INT_COLOUR[script.intensity];
          return (
            <section key={key} className={`msn-card${isOpen ? " open" : ""}`} style={{ borderLeftColor: edge }}>
              <button type="button" className="msn-head" aria-expanded={isOpen} onClick={() => setOpen({ ...open, [key]: !isOpen })}>
                <span className="msn-title">{name}</span>
                <span className={`fl-pill ${approvedAt ? "ok" : "warn"}`}>{approvedAt ? "approved" : "decide"}</span>
                <span className="msn-sum">{summary}</span>
                <span className="chev" aria-hidden>›</span>
              </button>
              {isOpen && <>
                {rows.map(({ m, pkg, st, launch, pct }) => (
                  <button key={m.id} type="button" className={`msn-row${sel?.run === key && sel.mission === m.id ? " on" : ""}`}
                    onClick={() => s.set({ selection: { kind: "plan-mission", run: key, mission: m.id, fit: Date.now() } })}>
                    <span className={`msn-pri ${m.priority.toLowerCase()}`}>{m.priority}</span>
                    <span className="msn-name">{m.name}</span>
                    <span className="msn-sub">
                      {pkg && <AcIcon type={pkg.type} tone={ST_TONE[st]} />}
                      <span className="msn-pkg">{pkg ? `${pkg.n} × ${pkg.type}` : "no package"}</span>
                      <b className={ST_TONE[st]}>{st === "approved" ? `${isGround(pkg?.type) ? "leaves" : "launch"} ${hm(launch)}` : statusWord(st, pkg?.type)}</b>
                    </span>
                    {pct != null && <span className="msn-bar" aria-hidden><i style={{ width: `${Math.min(100, Math.max(2, pct))}%` }} /></span>}
                  </button>
                ))}
                <Link className="msn-foot" to={`/planner?run=${key}&step=${approvedAt ? 4 : 1}`}>Open in Planner ›</Link>
              </>}
            </section>
          );
        })}
      </div>
      {groups.length === 0 && <div className="toggle-note" style={{ margin: "4px 0 0" }}>No scenario running. <Link to="/scenarios">Start one ›</Link></div>}
    </div>
  );
}

function Switch({ on, onChange, label, disabled }: { on: boolean; onChange: () => void; label: string; disabled?: boolean }) {
  return <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} className="switch" onClick={(e) => { e.stopPropagation(); onChange(); }} />;
}

function Toggle({ swatch, label, on, onChange, count, note, disabled }: { swatch: ReactNode; label: string; on: boolean; onChange: () => void; count?: ReactNode; note?: string; disabled?: boolean }) {
  return (
    <div className="toggle-row" onClick={disabled ? undefined : onChange}>
      {swatch}
      <span className="toggle-label">{label}</span>
      <span className="toggle-count">{count}</span>
      <Switch on={on} onChange={onChange} label={label} disabled={disabled} />
      {note && <span className="toggle-note">{note}</span>}
    </div>
  );
}

/** The simulated radar, air defence and comms sites (Infra panel, D75); "Show all coverage" appears once radar or AD sites are on. */
function SiteToggle({ id, disabled }: { id: LayerId; disabled: boolean }) {
  const s = useStore();
  const cover = id === "ops-coverage";
  if (cover && !s.layers["ops-radar-sites"] && !s.layers["ops-ad-sites"]) return null;
  return <Toggle swatch={SWATCH[id]} label={LAYERS[id].label} on={s.layers[id]} onChange={() => s.toggleLayer(id)} disabled={disabled}
    count={cover ? undefined : s.siteCounts[id]} note={cover ? "One outline per kind; sites that are down are left out." : undefined} />;
}

/** What the Ops map draws (D73, D76): a key that matches the map's styling (D78). */
const OpsKey = () => (
  <section>
    <div className="ms-cap ops-sec">On the map</div>
    <div className="ops-key">
      <div><span className="key-ring" aria-hidden />Mission area
        <small><i className="s-warning">waiting</i> · <i className="s-ok">approved</i> · <i className="s-sim">under way</i> · <i className="dim">done</i></small></div>
      <div><span className="key-band" aria-hidden />Threat zone (generic)<small>hatched band: higher risk</small></div>
    </div>
  </section>
);

function Ramp({ stops, labels }: { stops: string[]; labels: string[] }) {
  return (
    <div style={{ margin: "6px 0 4px" }}>
      <div style={{ height: 8, borderRadius: 4, background: `linear-gradient(90deg, ${stops.join(", ")})` }} />
      <div className="mono dim" style={{ display: "flex", justifyContent: "space-between", fontSize: 10, marginTop: 2 }}>{labels.map((l) => <span key={l}>{l}</span>)}</div>
    </div>
  );
}

const GEAR = <><circle cx="12" cy="12" r="3.2" /><path d="M12 2.8v2.6M12 18.6v2.6M21.2 12h-2.6M5.4 12H2.8M18.5 5.5l-1.8 1.8M7.3 16.7l-1.8 1.8M18.5 18.5l-1.8-1.8M7.3 7.3 5.5 5.5" /><circle cx="12" cy="12" r="6.6" /></>;
const Icon = ({ children }: { children: ReactNode }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" strokeLinecap="round" aria-hidden>{children}</svg>
);

/** Left-middle dock: vertical view switcher + Map settings; the selected section opens in a panel beside it. */
export function LayerRail({ liveTracks }: { liveTracks: { category: keyof typeof LIVE_GROUP; on_ground: boolean }[] }) {
  const s = useStore();
  const [pane, setPane] = useState<"view" | "settings" | null>("view");
  const [settingsWindow, setSettingsWindow] = useState<string | null>(null);
  const focus = s.mode === "INFRA" && s.connectivityFocus != null;
  const sourceId = s.selection?.kind === "base" ? s.selection.id : null;
  const owm = useQuery({ queryKey: ["wx-status"], queryFn: () => api<{ owm: boolean }>("/wx/status"), enabled: s.mode === "WX" });
  const counts: Record<string, number> = {};
  for (const t of liveTracks) if (!t.on_ground && LIVE_GROUP[t.category]) counts[LIVE_GROUP[t.category]] = (counts[LIVE_GROUP[t.category]] ?? 0) + 1;
  const onCount = (ids: readonly string[], state: Record<string, boolean>) => `${ids.filter((k) => state[k]).length}/${ids.length} on`;
  const view = MODES.find((m) => m.id === s.mode)!;
  const groupIds = (g: string) => (Object.keys(LAYERS) as LayerId[]).filter((k) => LAYERS[k].group === g);
  const viewLayers = (Object.keys(LAYERS) as LayerId[]).filter((k) => layerMode(k) === s.mode);
  const pick = (m: Mode) => {
    if (m === s.mode && pane === "view") return setPane(null);
    s.set({ mode: m, selection: null });
    setPane("view");
  };
  const head = (title: string) => (
    <div className="view-head">
      <span className="view-title">{title}</span>
      <button className="close" onClick={() => setPane(null)} aria-label={`Close ${title.toLowerCase()}`}>×</button>
    </div>
  );
  return (
    <div className="dock-wrap">
      <nav className="dock" role="tablist" aria-orientation="vertical" aria-label="Map view">
        {MODES.map((m, i) => (
          <button key={m.id} role="tab" aria-selected={s.mode === m.id} title={`${m.label} (${i + 1})`}
            className={`dock-btn${s.mode === m.id ? " on" : ""}${s.mode === m.id && pane === "view" ? " open" : ""}`} onClick={() => pick(m.id)}>
            <Icon>{VIEW[m.id].icon}</Icon><span>{VIEW[m.id].tab}</span>
          </button>
        ))}
        <span className="dock-sep" />
        <button className={`dock-btn${pane === "settings" ? " on open" : ""}`} title="Map settings: base map, air bases, boundaries"
          aria-pressed={pane === "settings"} onClick={() => setPane(pane === "settings" ? null : "settings")}>
          <Icon>{GEAR}</Icon><span>Map</span>
        </button>
      </nav>

      {pane === "view" && (
        <aside className="flyout" aria-label={`${view.label} options`}>
          {head(view.label)}
          <p className="view-hint">{VIEW[s.mode].hint}</p>
          {s.mode === "INFRA" && <Toggle swatch={<span className="swatch-line" style={{ borderColor: "var(--accent)" }} />}
            label="Connectivity focus" on={focus} disabled={sourceId == null}
            onChange={() => s.set({ connectivityFocus: focus || sourceId == null ? null : { sourceId, destinationId: null, mode: "direct", fitSeq: 1 } })}
            note={sourceId == null ? "Select an IAF base to focus on nearby connections." : focus ? "Only nearby base connections are shown. Exit focus to restore your layers." : "Hide other layers and compare direct connections and shortest road routes."} />}

          {s.mode === "LIVE" && <>
            {LIVE_CATS.map((c) => (
              <Toggle key={c} swatch={<span className="swatch-dot" style={{ background: CAT[c].color }} />} label={CAT[c].label}
                on={s.liveCats[c]} onChange={() => s.toggleCat(c)} count={counts[c] ?? 0} note={c === "civil" || !counts[c] ? CAT[c].note : undefined} />
            ))}
            <div className="tool-row"><span>Airborne now</span><b className="mono" style={{ marginLeft: "auto", color: "var(--text-1)" }}>{Object.values(counts).reduce((a, b) => a + b, 0)}</b></div>
          </>}

          {s.mode === "WX" && <>
            {WX_LAYERS.map((w) => {
              const noKey = w === "rain" && owm.data?.owm === false;   // no OWM_API_KEY: no rain tiles to show
              return <Toggle key={w} swatch={WX[w].swatch} label={WX[w].label} on={s.wx[w] && !noKey} onChange={() => s.toggleWx(w)}
                disabled={noKey} note={noKey ? "Needs OWM_API_KEY in .env" : undefined} />;
            })}
            {(s.wx.clouds || s.wx.rain) && (
              <label className="tool-row">Cloud & rain opacity
                <input type="range" min={0.3} max={1} step={0.05} value={s.overlayOpacity} onChange={(e) => s.set({ overlayOpacity: Number(e.target.value) })} /></label>
            )}
            {s.wx.wind && <>
              <div className="tool-row">Wind model
                <OptionPanel label="Wind model" value={s.windModel} options={[{ value: "gfs", label: "GFS (NOAA)" }, { value: "ifs", label: "IFS (ECMWF)" }]}
                  onChange={(windModel) => s.set({ windModel })} /></div>
              <div className="toggle-note" style={{ margin: "4px 0 0" }}>Wind speed at 10 m (knots)</div>
              <Ramp stops={["#82afeb", "#e1f0ff", "#fde68a", "#f97316", "#ef4444"]} labels={["0", "15", "25", "35", "60+"]} />
            </>}
            {s.wx.metar && <div className="status-strip" style={{ fontSize: 11, marginTop: 4 }}>
              <span className="s-ok">● VFR</span><span className="s-info">○ MVFR</span><span className="s-warning">◆ IFR</span><span className="s-critical">■ LIFR</span>
            </div>}
          </>}

          {s.mode === "OPS" && <>
            <OpsStatus />
            <OpsKey />
            <div className="toggle-note" style={{ margin: "10px 0 0" }}><span className="sim-badge">SIM</span> Everything here is simulated.</div>
          </>}
          {s.mode !== "OPS" && viewLayers.filter((k) => !layerSim(k)).map((k) => <Toggle key={k} swatch={SWATCH[k]} label={LAYERS[k].label} on={s.layers[k]} onChange={() => s.toggleLayer(k)} disabled={focus} />)}
          {s.mode === "INFRA" && <section>
            <div className="ms-cap ops-sec">Defence & comms <span className="sim-badge">SIM</span></div>
            {viewLayers.filter(layerSim).map((k) => <SiteToggle key={k} id={k} disabled={focus} />)}
            <div className="toggle-note" style={{ margin: "6px 0 0" }}>Simulated sites placed by the generator, not real deployments. Hover or click one to see its coverage.</div>
          </section>}

        </aside>
      )}

      {pane === "settings" && (
        <aside className="flyout map-settings" aria-label="Map settings">
          {head("Map settings")}
          <section className="ms-sec">
            <div className="ms-cap">Map angle</div>
            <div className="angle" role="radiogroup" aria-label="Map angle">
              {ANGLES.map(([v, t, sub, icon]) => (
                <button key={t} role="radio" aria-checked={s.tilt === v} className={`angle-opt${s.tilt === v ? " on" : ""}`}
                  disabled={s.mode === "WX" || focus} onClick={() => s.set({ tilt: v })}>
                  <svg viewBox="0 0 34 24" aria-hidden>{icon}</svg>
                  <span><b>{t}</b><small>{sub}</small></span>
                </button>
              ))}
            </div>
            <p className="ms-note">
              {s.mode === "WX" ? "The Weather view is always straight, so clouds and wind line up. Your choice returns in Live, Infra and Ops."
                : s.tilt ? "Right-drag to rotate and tilt. Saved for every view." : "Flat and north-up. Saved for every view."}
            </p>
          </section>
          <section className="ms-sec">
            <div className="ms-cap">Layers <span>shown in every view</span></div>
            {focus && <p className="view-hint">Connectivity focus hides other layers. Satellite imagery remains available.</p>}
          {LAYER_GROUPS.filter((g) => groupIds(g).every((k) => !layerMode(k))).map((g) => (
            <SettingsWindow key={g} title={g} icon={GROUP_ICON[g]} meta={onCount(groupIds(g), s.layers).replace(" on", "")} open={settingsWindow === g}
              onOpen={() => setSettingsWindow(g)} onClose={() => setSettingsWindow((current) => current === g ? null : current)}>
              {(g === "View" ? ["relief"] as const : groupIds(g)).map((k) => <Toggle key={k} swatch={SWATCH[k]} label={LAYERS[k].label} on={s.layers[k]} onChange={() => s.toggleLayer(k)} disabled={focus} />)}
              {g === "View" && <>
                {s.layers.relief && <Ramp stops={["var(--relief-0)", "var(--relief-2)", "var(--relief-3)", "var(--relief-4)", "var(--relief-5)"]}
                  labels={["0 m", "1,000", "2,500", "4,500", "6,500"]} />}
                <label className="tool-row">Relief height
                  <input type="range" min={1} max={3} step={0.5} value={s.exaggeration} disabled={focus} onChange={(e) => s.set({ exaggeration: Number(e.target.value) })} />
                  <span className="mono" style={{ color: "var(--text-1)" }}>{s.exaggeration}×</span></label>
                <Toggle swatch={SWATCH.satellite} label={LAYERS.satellite.label} on={s.layers.satellite} onChange={() => s.toggleLayer("satellite")} />
              </>}
            </SettingsWindow>
          ))}
          <SettingsWindow title="How to read the symbols" icon={GROUP_ICON.symbols} open={settingsWindow === "symbols"}
            onOpen={() => setSettingsWindow("symbols")} onClose={() => setSettingsWindow((current) => current === "symbols" ? null : current)}>
            <div className="toggle-note" style={{ fontSize: 12, lineHeight: "18px", color: "var(--text-2)", margin: 0 }}>
              <p style={{ margin: "4px 0" }}>Air bases are rectangular tags coloured by owner: neon blue IAF, grey Navy / Army / Coast Guard, red Pakistan and China, green other neighbours. Small runway tags are advanced landing grounds. Zoom in and the tag shows the base code.</p>
              <p style={{ margin: "4px 0" }}>The bar under an IAF tag is aircraft serviceability (full bar = 100%): green 70% or more, yellow 45–69%, red under 45%.</p>
              <p style={{ margin: "4px 0" }}>A dot on the tag's corner marks an open warning (orange) or critical (red) alert. The "Q" end-cap is the quick reaction alert posture: blue when met, red when short.</p>
              <p style={{ margin: "4px 0" }}>Civil airports are light tags with a dark airliner and the IATA code. Live aircraft: yellow civil, neon blue military, orange UAVs and drones, red in an emergency.</p>
              <p style={{ margin: "4px 0" }}>Telecom towers are masts with signal arcs on dark outlined tiles. In Ops, violet shapes with a SIM tag are simulated sites: shields are air defence, round scopes are radars, diamonds are comms nodes. Hover or click a radar or air defence site to see its coverage ring. Faded sites are offline or in maintenance. <span className="sim-badge">SIM</span> These sites are simulated.</p>
              <p style={{ margin: "4px 0" }}>A selected live aircraft has a blue ring and solid blue recorded trail. A dashed teal line is its scheduled route (adsbdb, may differ from actual).</p>
              <p style={{ margin: "4px 0" }}>The glowing line is India's boundary as officially depicted by the Government of India.</p>
            </div>
          </SettingsWindow>
          </section>
        </aside>
      )}
    </div>
  );
}
