import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { api } from "../api/client";
import { zulu } from "../lib/format";
import { OptionPanel } from "../components/OptionPanel";
import { SettingsWindow } from "../components/SettingsWindow";
import { LAYERS, LAYER_GROUPS, LIVE_CATS, LIVE_GROUP, type LayerId, type LiveCat, MODES, type Mode, type WxLayer, WX_LAYERS, layerMode, useStore } from "../store";

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
const VIEW: Record<Mode, { tab: string; hint: string; icon: ReactNode }> = {
  LIVE: { tab: "Live", hint: "Aircraft broadcasting on public ADS-B, updated every 10 s. Right-drag to rotate and tilt the 3D terrain.",
    icon: <path fill="currentColor" stroke="none" d="M12 2.5l1.5 6.3 7.5 4.4v1.9l-7.5-2.3-.4 5.5 2.7 2v1.4L12 20.7l-3.8 1v-1.4l2.7-2-.4-5.5L3 15.1v-1.9l7.5-4.4z" /> },
  WX: { tab: "Weather", hint: "Satellite clouds, rain and wind on a flat map. Click anywhere for a point forecast.",
    icon: <path d="M7 18.5h10.6a4.1 4.1 0 0 0 .6-8.15A6.1 6.1 0 0 0 6.5 9.6 4.5 4.5 0 0 0 7 18.5z" /> },
  INFRA: { tab: "Infra", hint: "Roads, rail and airports. Select an air base to see its nearest railheads, airports and IAF bases.",
    icon: <><path d="M8 21 11 3M16 21 13 3" /><path d="M12 6.5v2M12 11.5v2.5M12 17v3" /></> },
  OPS: { tab: "Ops", hint: "The simulated operational picture: planned sorties flying their routes, mission areas, generic threat zones and weather impact. Nothing here is real data.",
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
  "ops-sim": <span className="swatch-dot" style={{ background: "var(--sim)" }} />,
  "ops-unknown": <span className="swatch-dot" style={{ background: "var(--warning)" }} />,
  "ops-routes": <span className="swatch-line" style={{ borderColor: "var(--sim)" }} />,
  "ops-missions": <span className="swatch-dot" style={{ background: "var(--ok)", boxShadow: "0 0 0 2px var(--bg), 0 0 0 3px var(--caution)" }} />,
  "ops-threat": <span className="swatch" style={{ background: "rgb(248 113 113 / .18)", border: "1px dashed var(--base-hostile)" }} />,
  "ops-airspace": <span className="swatch" style={{ border: "1px dashed var(--line)" }} />,
  "ops-radar": <span className="swatch" style={{ borderRadius: "50%", border: "1px dotted var(--info)" }} />,
  "ops-ad": <span className="swatch" style={{ borderRadius: "50%", border: "1px dashed var(--accent)", background: "var(--accent-tint)" }} />,
  "ops-ad-sites": <span className="swatch" style={{ color: "var(--sim)", border: "1px solid var(--sim)", borderRadius: "0 0 50% 50%", textAlign: "center" }}>⌃</span>,
  "ops-wx": <span className="swatch" style={{ borderRadius: "50%", border: "2px solid var(--warning)" }} />,
};

/** Ops view status: the plan the simulated picture is flying, any re-task waiting, and the simulator clock. */
function OpsStatus() {
  const s = useStore();
  const sum = useQuery({ queryKey: ["ops-summary"], queryFn: () => api<{ committed_plan_id: number | null; open_disruptions: number;
    pending_retask_id: number | null; pending_retask_summary: string | null }>("/ops/summary"), refetchInterval: 20000 });
  const d = sum.data;
  const c = s.simClock;
  return (
    <div style={{ margin: "2px 0 6px" }}>
      <div className="tool-row" style={{ borderTop: 0 }}><span>Simulator clock</span>
        <b className="mono" style={{ marginLeft: "auto", color: "var(--sim)" }}>{c ? `${zulu(c.sim_now)} ×${c.speed}${c.paused ? " paused" : ""}` : "not running"}</b></div>
      <div className="tool-row"><span>Committed plan</span>
        <b className="mono" style={{ marginLeft: "auto", color: "var(--text-1)" }}>{d?.committed_plan_id ? `#${d.committed_plan_id}` : "none"}</b></div>
      {d?.pending_retask_id && <div className="tool-row" style={{ display: "block" }}>
        <span className="s-warning">◆ Re-task proposal waiting: {d.pending_retask_summary}</span>
        <div style={{ marginTop: 4 }}><a href={`/planner?plan=${d.pending_retask_id}`}>Review in the planner ›</a></div></div>}
      {!d?.committed_plan_id && <div className="toggle-note" style={{ margin: "4px 0 0" }}>No plan committed yet. <a href="/planner">Generate one in the planner ›</a></div>}
      {d && d.open_disruptions > 0 && <div className="toggle-note" style={{ margin: "4px 0 0" }}>{d.open_disruptions} open disruption{d.open_disruptions > 1 ? "s" : ""}</div>}
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
            {WX_LAYERS.map((w) => <Toggle key={w} swatch={WX[w].swatch} label={WX[w].label} on={s.wx[w]} onChange={() => s.toggleWx(w)} />)}
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
            {s.wx.rain && owm.data && !owm.data.owm && <div className="s-warning" style={{ fontSize: 12, marginTop: 6 }}>◆ Rain needs OWM_API_KEY in .env</div>}
          </>}

          {s.mode === "OPS" && <OpsStatus />}
          {viewLayers.map((k) => <Toggle key={k} swatch={SWATCH[k]} label={LAYERS[k].label} on={s.layers[k]} onChange={() => s.toggleLayer(k)} disabled={focus}
            count={k === "ops-sim" ? s.simTracks.filter((t) => t.kind === "SIM_IAF").length : k === "ops-unknown" ? s.simTracks.filter((t) => t.kind === "SIM_UNKNOWN").length : undefined} />)}
          {s.mode === "OPS" && <div className="toggle-note" style={{ margin: "6px 0 0" }}><span className="sim-badge">SIM</span> Every object in this view is simulated. Threat zones are generic risk bands and exercise injects, not real deployments.</div>}

        </aside>
      )}

      {pane === "settings" && (
        <aside className="flyout" aria-label="Map settings">
          {head("Map settings")}
          <p className="view-hint">Layers shown in every view.</p>
          {focus && <p className="view-hint">Connectivity focus hides other layers. Satellite imagery remains available.</p>}
          {LAYER_GROUPS.filter((g) => groupIds(g).every((k) => !layerMode(k))).map((g) => (
            <SettingsWindow key={g} title={g} meta={onCount(groupIds(g), s.layers)} open={settingsWindow === g}
              onOpen={() => setSettingsWindow(g)} onClose={() => setSettingsWindow((current) => current === g ? null : current)}>
              {(g === "View" ? ["relief"] as const : groupIds(g)).map((k) => <Toggle key={k} swatch={SWATCH[k]} label={LAYERS[k].label} on={s.layers[k]} onChange={() => s.toggleLayer(k)} disabled={focus} />)}
              {g === "View" && <>
                {s.layers.relief && <Ramp stops={["var(--relief-0)", "var(--relief-2)", "var(--relief-3)", "var(--relief-4)", "var(--relief-5)"]}
                  labels={["0 m", "1,000", "2,500", "4,500", "6,500"]} />}
                <label className="tool-row">Relief height
                  <input type="range" min={1} max={3} step={0.5} value={s.exaggeration} disabled={focus} onChange={(e) => s.set({ exaggeration: Number(e.target.value) })} />
                  <span className="mono" style={{ color: "var(--text-1)" }}>{s.exaggeration}×</span></label>
                <Toggle swatch={SWATCH.satellite} label={LAYERS.satellite.label} on={s.layers.satellite} onChange={() => s.toggleLayer("satellite")} />
                <Toggle swatch={<span className="toggle-count">3D</span>} label="3D tilt" on={s.tilt} onChange={() => s.set({ tilt: !s.tilt })} disabled={s.mode === "WX" || focus} />
                <div className="toggle-note" style={{ margin: "2px 0 0" }}>
                  {s.mode === "WX" ? "The Weather view is always flat; your tilt preference returns in Live, Infra and Ops." : "Right-drag to rotate and tilt. 3D tilt and relief height are saved for every view."}
                </div>
              </>}
            </SettingsWindow>
          ))}
          <SettingsWindow title="How to read the symbols" open={settingsWindow === "symbols"}
            onOpen={() => setSettingsWindow("symbols")} onClose={() => setSettingsWindow((current) => current === "symbols" ? null : current)}>
            <div className="toggle-note" style={{ fontSize: 12, lineHeight: "18px", color: "var(--text-2)", margin: 0 }}>
              <p style={{ margin: "4px 0" }}>Air bases are rectangular tags coloured by owner: neon blue IAF, grey Navy / Army / Coast Guard, red Pakistan and China, green other neighbours. Small runway tags are advanced landing grounds. Zoom in and the tag shows the base code.</p>
              <p style={{ margin: "4px 0" }}>The bar under an IAF tag is aircraft serviceability (full bar = 100%): green 70% or more, yellow 45–69%, red under 45%.</p>
              <p style={{ margin: "4px 0" }}>A dot on the tag's corner marks an open warning (orange) or critical (red) alert. The "Q" end-cap is the quick reaction alert posture: blue when met, red when short.</p>
              <p style={{ margin: "4px 0" }}>Civil airports are light tags with a dark airliner and the IATA code. Live aircraft: yellow civil, neon blue military, orange UAVs and drones, red in an emergency.</p>
              <p style={{ margin: "4px 0" }}>Telecom towers are masts with signal arcs on dark outlined tiles. Violet shields with an upward chevron are air defence sites, shown only in Ops. <span className="sim-badge">SIM</span> These sites and their launcher counts are simulated.</p>
              <p style={{ margin: "4px 0" }}>A selected live aircraft has a blue ring and solid blue recorded trail. A dashed teal line is its scheduled route (adsbdb, may differ from actual).</p>
              <p style={{ margin: "4px 0" }}>The glowing line is India's boundary as officially depicted by the Government of India.</p>
            </div>
          </SettingsWindow>
        </aside>
      )}
    </div>
  );
}
