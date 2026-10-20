import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { scheduledDestination, shortAirport, useLivePath } from "../api/live";
import type { Base, LiveScenario, LiveTrack, Site } from "../api/types";
import { ErrorText, Loading, Row, Sim, ToneText } from "../components/ui";
import { COMMS_NAME, feet, istTime, label, num } from "../lib/format";
import { LIVE_GROUP, type Selection, useStore } from "../store";
import { MISSION_WORD, type Status, baseName, isGround, planFocus, statusWord } from "./scripts";

function Card({ title, children, sim }: { title: React.ReactNode; children: React.ReactNode; sim?: boolean }) {
  const set = useStore((s) => s.set);
  return (
    <div className="card" role="dialog" aria-label="Details">
      <div className="card-title"><span>{title} {sim && <Sim />}</span><button className="close" onClick={() => set({ selection: null })} aria-label="Close">×</button></div>
      {children}
    </div>
  );
}

export function InfoCard({ sel, liveTracks }: { sel: NonNullable<Selection>; liveTracks: LiveTrack[] }) {
  if (sel.kind === "plan-mission") return <PlanMissionCard run={sel.run} mission={sel.mission} />;
  if (sel.kind === "ad" || sel.kind === "radar" || sel.kind === "comms") return <SiteCard kind={sel.kind} id={sel.id} />;
  if (sel.kind === "public-base") return <PublicBase id={sel.id} />;
  if (sel.kind === "live") return <LiveCard track={liveTracks.find((t) => t.hex === sel.hex)} hex={sel.hex} />;
  if (sel.kind === "wx") return <WxCard lat={sel.lat} lon={sel.lon} />;
  if (sel.kind === "airport" || sel.kind === "tower" || sel.kind === "station") {
    const x = sel as unknown as Record<string, string | number | null>;
    return (
      <Card title={String(x.name ?? (sel.kind === "tower" ? "Telecom tower" : sel.kind === "station" ? "Railway station" : "Airport"))}>
        {sel.kind === "station" && <Row label="Type" value={x.rank === 0 ? "Major railway junction" : "Railway station"} />}
        {sel.kind === "airport" && <><Row label="ICAO / IATA" value={`${x.icao ?? "—"} / ${x.iata ?? "—"}`} /><Row label="Type" value={label(String(x.type))} /></>}
        {sel.kind === "tower" && <><Row label="Operator" value={String(x.operator ?? "—")} /><Row label="Height" value={x.height_m ? `${x.height_m} m` : "—"} /></>}
        <Row label="Location" value={`${Number(x.lat).toFixed(3)}, ${Number(x.lon).toFixed(3)}`} />
        <div className="dim" style={{ fontSize: 12, marginTop: 6 }}>{sel.kind === "airport" ? "OurAirports (public domain)" : "© OpenStreetMap contributors (ODbL)"}</div>
      </Card>
    );
  }
  return null;
}

// ---------------------------------------------------------------- Phase 2: operations view cards (all simulated)
const SITE: Record<"ad" | "radar" | "comms", [string, string]> = {
  ad: ["Air defence site", "/sites/ad"], radar: ["Radar site", "/sites/radars"], comms: ["Comms node", "/sites/comms"],
};

/** Simulated air defence, radar or comms site (Ops view only). Same query keys as the map, so it reads the cache. */
function SiteCard({ kind, id }: { kind: "ad" | "radar" | "comms"; id: number }) {
  const s = useStore();
  const [title, path] = SITE[kind];
  const q = useQuery({ queryKey: ["sites", kind === "radar" ? "radars" : kind], queryFn: () => api<Site[]>(path), staleTime: 60000 });
  const bases = useQuery({ queryKey: ["bases"], queryFn: () => api<Base[]>("/bases"), staleTime: Infinity });
  if (s.mode !== "INFRA") return null;
  if (!q.data) return <Card title={title} sim>{q.error ? <ErrorText error={q.error} /> : <Loading />}</Card>;
  const d = q.data.find((x) => x.id === id);
  if (!d) return <Card title={title} sim><div className="empty">Site no longer available.</div></Card>;
  const base = bases.data?.find((b) => b.code === d.base);
  return <Card title={<span className="mono">{d.code ?? "—"}</span>} sim>
    <div className="muted" style={{ margin: "2px 0 6px" }}>{title}</div>
    {kind === "ad" && <Row label="System" value={d.system ?? "—"} />}
    {kind === "radar" && <Row label="Type" value={d.type ?? "—"} />}
    {kind === "comms" && <Row label="Node type" value={COMMS_NAME[d.node_type ?? ""] ?? label(d.node_type)} />}
    {kind !== "comms" && <Row label="Category" value={d.category ? label(d.category) : "—"} />}
    <Row label="Status" value={d.status ? label(d.status) : "—"} />
    {kind === "ad" && <Row label="Launchers ready / total" value={`${d.launchers_ready ?? "—"} / ${d.launchers_total ?? "—"}`} />}
    {kind !== "comms" && <Row label="Range" value={d.max_range_km != null ? `${num(d.max_range_km)} km` : "—"} />}
    <Row label={kind === "ad" ? "Protected base" : "Base"} value={base ? <button className="btn btn-ghost btn-sm" onClick={() => s.set({ selection: { kind: base.side === "OWN" ? "base" : "public-base", id: base.id }, panelTab: "Bw" })}>{base.code}</button> : d.base ?? "—"} />
    <Row label="Latitude / longitude" value={`${d.lat != null ? d.lat.toFixed(4) : "—"}, ${d.lon != null ? d.lon.toFixed(4) : "—"}`} />
    {kind !== "comms" && <div className="dim" style={{ fontSize: 12, marginTop: 6 }}>The ring on the map is this site's coverage.</div>}
  </Card>;
}

const PLAN_STATUS: Record<Status, [string, string]> = { waiting: ["warn", "waiting for approval"], approved: ["ok", "approved"],
  airborne: ["info", "airborne"], "on station": ["info", "on station"], returning: ["info", "returning"], landed: ["ok", "landed"],
  "not flown": ["crit", "not flown"] };

/** A scripted planner mission focused on the Ops map (D71): the package, where it is in its sortie, and why. */
function PlanMissionCard({ run, mission }: { run: string; mission: string }) {
  const live = useQuery({ queryKey: ["scenarios", "live"], queryFn: () => api<LiveScenario[]>("/ops/scenarios/live"), refetchInterval: 15000 });
  const demo = useStore((s) => s.demo);
  const now = useStore((s) => s.simClock?.sim_now) ?? new Date().toISOString();
  const mode = useStore((s) => s.mode);
  if (mode !== "OPS") return null;
  if (!live.data && run !== "routine") return <Card title="Mission" sim><Loading /></Card>;
  const f = planFocus(live.data, demo, run, mission, now);
  if (!f) return <Card title="Mission" sim><div className="empty">That scenario has ended.</div></Card>;
  const { script, m, pkg, st, launch, back } = f;
  const t = Date.parse(now), pct = launch && back ? Math.min(100, Math.max(0, ((t - launch) / (back - launch)) * 100)) : 0;
  const hm = (v: number | null) => (v == null ? "—" : istTime(new Date(v).toISOString()).replace(" IST", ""));
  return (
    <Card title={`${m.priority} ${m.name}`} sim>
      <div className="muted" style={{ margin: "2px 0 8px" }}>{script.name}</div>
      <Row label="Mission" value={MISSION_WORD[m.mtype]} />
      <Row label="Package" value={pkg ? `${pkg.n} × ${pkg.type}` : "none: can't be flown as asked"} />
      {pkg && <Row label="From" value={`${baseName(pkg.base)}${isGround(pkg.type) ? " · by road" : ""}`} />}
      <Row label="Status" value={<span className={`fl-pill ${PLAN_STATUS[st][0]}`}>{st === "waiting" ? PLAN_STATUS[st][1] : statusWord(st, pkg?.type)}</span>} />
      {pkg && <Row label={isGround(pkg.type) ? "Leaves / back" : "Launch / lands"} value={<span className="mono">{hm(launch)} – {hm(back)} IST</span>} />}
      {pkg && f.approvedAt && <div className="pm-bar" aria-label={`${Math.round(pct)}% of the sortie flown`}><i style={{ width: `${pct}%` }} /></div>}
      {pkg && <div className="dim" style={{ fontSize: 12, marginTop: 8 }}>Why: {pkg.why.join(" · ")}</div>}
      <div style={{ marginTop: 10 }}><Link to={`/planner?run=${run}&step=4`}>Open in Planner ›</Link></div>
    </Card>
  );
}

function PublicBase({ id }: { id: number }) {
  const q = useQuery({ queryKey: ["public-base", id], queryFn: () => api<Record<string, unknown> & { runways: { designator: string; length_m: number; surface: string }[] }>(`/bases/${id}/public`) });
  if (!q.data) return <Card title="Base">{q.error ? <ErrorText error={q.error} /> : <Loading />}</Card>;
  const b = q.data;
  return (
    <Card title={String(b.name)}>
      <div className="notice" style={{ margin: "6px 0" }}>{String(b.note)}</div>
      <Row label="Country / operator" value={`${b.country_iso3} · ${b.operator}`} />
      <Row label="Affiliation" value={<ToneText toneName={b.affiliation === "HOSTILE" ? "critical" : b.affiliation === "NEUTRAL" ? "ok" : "info"}>{label(String(b.affiliation))}</ToneText>} />
      <Row label="Elevation" value={feet(b.elevation_m as number)} />
      {b.runways.map((r, i) => <Row key={i} label={`Runway ${r.designator}`} value={r.length_m ? `${num(r.length_m)} m ${label(r.surface)}` : "—"} />)}
      <div className="dim" style={{ fontSize: 12, marginTop: 6 }}>{String(b.public_notes ?? "")}</div>
      <a href={String(b.source_ref)} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>Source</a>
    </Card>
  );
}

function LiveCard({ track, hex }: { track?: LiveTrack; hex: string }) {
  const mode = useStore((s) => s.mode);
  const cats = useStore((s) => s.liveCats);
  const visible = !!track && mode === "LIVE" && !track.on_ground && cats[LIVE_GROUP[track.category]];
  const { trail, enrich: e } = useLivePath(hex, track?.callsign ?? null, visible);
  if (!track) return <Card title={hex}><div className="empty">Track no longer in view.</div></Card>;
  const a = e.data?.aircraft;
  const r = e.data?.route;
  const recorded = visible ? trail.data?.length ?? 0 : 0;
  const destination = visible ? scheduledDestination(r) : null;
  return (
    <Card title={<span className="mono">{track.callsign ?? hex.toUpperCase()}</span>}>
      {track.emergency && <div className="pill s-critical" style={{ margin: "4px 0" }}>■ {track.emergency}</div>}
      <Row label="Category" value={label(track.category)} />
      <Row label="Type" value={a?.type ?? track.desc ?? track.icao_type ?? "—"} />
      <Row label="Registration" value={a?.registration ?? track.reg ?? "—"} />
      <Row label="Operator" value={a?.registered_owner ?? track.operator ?? "—"} />
      {r && <Row label="Route" value={<>{`${r.origin?.iata_code ?? "?"} → ${r.destination?.iata_code ?? "?"}`}
        {(r.origin?.name || r.destination?.name) && <div className="dim" style={{ fontSize: 12 }}>{shortAirport(r.origin?.name) || "?"} → {shortAirport(r.destination?.name) || "?"}</div>}</>} />}
      <Row label="Flight path" value={recorded || destination ? <>
        {!!recorded && <span>Recorded trail · {recorded} point{recorded === 1 ? "" : "s"}</span>}
        {!!recorded && destination && <br />}
        {destination && <span>Scheduled to {r?.destination?.iata_code ?? "destination"}</span>}
      </> : <strong>Flight path unavailable</strong>} />
      <Row label="Altitude" value={track.alt_m != null ? feet(track.alt_m) : "—"} />
      <Row label="Ground speed / track" value={`${num(track.gs_kt)} kt / ${num(track.track_deg)}°`} />
      <Row label="Squawk" value={<span className="mono">{track.squawk ?? "—"}</span>} />
      <Row label="Source / age" value={`${track.source} · ${track.age_s} s`} />
      <div className="dim" style={{ fontSize: 12, marginTop: 6 }}>Live public ADS-B (not simulated). Enrichment: adsbdb.</div>
      <div className="dim" style={{ fontSize: 12, marginTop: 6 }}>The recorded trail only covers the time since the server started seeing this aircraft. Scheduled route (adsbdb, may differ from actual).</div>
    </Card>
  );
}

interface Forecast {
  current: Record<string, number | string>;
  hourly: Record<string, (number | string)[]>;
  elevation: number;
  source: string;
}

function WxCard({ lat, lon }: { lat: number; lon: number }) {
  const q = useQuery({ queryKey: ["wx-point", lat.toFixed(1), lon.toFixed(1)], queryFn: () => api<Forecast>(`/wx/point?lat=${lat}&lon=${lon}`) });
  if (q.error) return <Card title="Point forecast"><ErrorText error={q.error} /></Card>;
  if (!q.data) return <Card title="Point forecast"><Loading /></Card>;
  const c = q.data.current;
  const h = q.data.hourly;
  const idx = [0, 3, 6, 9, 12, 18, 24, 36, 47];
  return (
    <Card title={`Point forecast ${lat.toFixed(2)}, ${lon.toFixed(2)}`}>
      <Row label="Elevation" value={`${num(q.data.elevation)} m / ${feet(q.data.elevation)}`} />
      <Row label="Temperature" value={`${c.temperature_2m} °C · RH ${c.relative_humidity_2m}%`} />
      <Row label="Wind (10 m)" value={`${c.wind_direction_10m}° ${c.wind_speed_10m} kt G${c.wind_gusts_10m}`} />
      <Row label="Cloud low / mid / high" value={`${c.cloud_cover_low} / ${c.cloud_cover_mid} / ${c.cloud_cover_high} %`} />
      <Row label="Visibility" value={`${num(Number(c.visibility) / 1000, 1)} km`} />
      <Row label="Precipitation / QNH" value={`${c.precipitation} mm · ${c.pressure_msl} hPa`} />
      <div className="table-wrap" style={{ marginTop: 8, maxHeight: 220 }}>
        <table className="table" style={{ fontSize: 12 }}>
          <thead><tr><th>IST</th><th>°C</th><th>Wind kt</th><th>500 hPa</th><th>Cloud L/M/H</th><th>Vis km</th><th>FZL ft</th></tr></thead>
          <tbody>{idx.map((i) => (
            <tr key={i}><td className="num">{String(h.time[i]).slice(5, 13).replace("T", " ")}</td><td className="num">{h.temperature_2m[i]}</td>
              <td className="num">{h.wind_direction_10m[i]}°/{h.wind_speed_10m[i]}</td><td className="num">{h.wind_direction_500hPa[i]}°/{h.wind_speed_500hPa[i]}</td>
              <td className="num">{h.cloud_cover_low[i]}/{h.cloud_cover_mid[i]}/{h.cloud_cover_high[i]}</td>
              <td className="num">{num(Number(h.visibility[i]) / 1000, 0)}</td><td className="num">{num(Number(h.freezing_level_height[i]) * 3.28084)}</td></tr>
          ))}</tbody>
        </table>
      </div>
      <div className="dim" style={{ fontSize: 12, marginTop: 6 }}>Weather data by Open-Meteo.com (CC BY 4.0)</div>
    </Card>
  );
}
