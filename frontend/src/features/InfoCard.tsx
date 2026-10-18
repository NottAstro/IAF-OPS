import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { scheduledDestination, useLivePath } from "../api/live";
import type { Base, Fix, LiveTrack, MissionRow, PlanItemView, Reason, Site } from "../api/types";
import { ErrorText, Loading, Pill, Row, Sim, ToneText } from "../components/ui";
import { RANK, feet, istTime, label, num } from "../lib/format";
import { LIVE_GROUP, type Selection, useStore } from "../store";

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
  if (sel.kind === "mission") return <MissionCard id={sel.id} />;
  if (sel.kind === "route") return <RouteCard id={sel.id} />;
  if (sel.kind === "simtrack") return <SimTrackCard id={sel.id} />;
  if (sel.kind === "ad") return <AdCard id={sel.id} />;
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
function AdCard({ id }: { id: number }) {
  const s = useStore();
  const q = useQuery({ queryKey: ["sites", "ad"], queryFn: () => api<Site[]>("/sites/ad"), staleTime: 60000 });
  const bases = useQuery({ queryKey: ["bases"], queryFn: () => api<Base[]>("/bases"), staleTime: Infinity });
  if (s.mode !== "OPS") return null;
  if (!q.data) return <Card title="Air defence site" sim>{q.error ? <ErrorText error={q.error} /> : <Loading />}</Card>;
  const d = q.data.find((x) => x.id === id);
  if (!d) return <Card title="Air defence site" sim><div className="empty">Site no longer available.</div></Card>;
  const base = bases.data?.find((b) => b.code === d.base);
  return <Card title={<span className="mono">{d.code ?? "—"}</span>} sim>
    <Row label="Code" value={d.code ?? "—"} />
    <Row label="System" value={d.system ?? "—"} />
    <Row label="Category" value={d.category ? label(d.category) : "—"} />
    <Row label="Status" value={d.status ? label(d.status) : "—"} />
    <Row label="Launchers ready / total" value={`${d.launchers_ready ?? "—"} / ${d.launchers_total ?? "—"}`} />
    <Row label="Range" value={d.max_range_km != null ? `${num(d.max_range_km)} km` : "—"} />
    <Row label="Protected base" value={base ? <button className="btn btn-ghost btn-sm" onClick={() => s.set({ selection: { kind: base.side === "OWN" ? "base" : "public-base", id: base.id }, panelTab: "Ov" })}>{base.code}</button> : d.base ?? "—"} />
    <Row label="Latitude / longitude" value={`${d.lat != null ? d.lat.toFixed(4) : "—"}, ${d.lon != null ? d.lon.toFixed(4) : "—"}`} />
  </Card>;
}

function MissionCard({ id }: { id: number }) {
  const q = useQuery({ queryKey: ["missions", "one", id], queryFn: () => api<MissionRow & { unmet: { reasons: Reason[]; fixes: Fix[] } | null }>(`/ops/missions/${id}`) });
  if (!q.data) return <Card title="Mission" sim>{q.error ? <ErrorText error={q.error} /> : <Loading />}</Card>;
  const m = q.data;
  return (
    <Card title={<span className="mono">{m.code}</span>} sim>
      <div className="muted" style={{ margin: "2px 0 6px" }}>{m.name}</div>
      <Row label="Priority / type" value={`${m.priority} · ${label(m.mission_type)}`} />
      <Row label="Window" value={`${istTime(m.window_start, true)} – ${istTime(m.window_end)}`} />
      <Row label="Needs" value={`${m.required_aircraft} aircraft, ${m.on_station_min} min on station`} />
      <Row label="Status" value={<Pill status={m.status === "TASKED" || m.status === "ACTIVE" ? "OPERATIONAL" : m.status === "REQUESTED" ? "PLANNED" : "CAUTION"} text={label(m.status)} />} />
      {m.tasked_base && <Row label="Tasked" value={`${m.tasked_n} × ${m.tasked_type} from ${m.tasked_base}`} />}
      {m.sortie_code && <Row label="Sortie" value={<><span className="mono">{m.sortie_code}</span> <Pill status={m.sortie_status} /></>} />}
      {m.unmet && <>
        <div className="section-h" style={{ fontSize: 13 }}>Why not tasked</div>
        {m.unmet.reasons.slice(0, 2).map((r) => <div key={r.code} className="dim" style={{ fontSize: 12, margin: "2px 0" }}>▲ {r.text}{r.examples[0] ? `: ${r.examples[0]}` : ""}</div>)}
        {m.unmet.fixes[0] && <div className="s-info" style={{ fontSize: 12, marginTop: 4 }}>○ {m.unmet.fixes[0].text}</div>}
      </>}
      <div style={{ marginTop: 8 }}><a href={`/missions?focus=${m.id}`}>Open in missions ›</a></div>
    </Card>
  );
}

function RouteCard({ id }: { id: number }) {
  const q = useQuery({ queryKey: ["plan", "item", id], queryFn: () => api<PlanItemView>(`/ops/plan-items/${id}`) });
  if (!q.data) return <Card title="Package" sim>{q.error ? <ErrorText error={q.error} /> : <Loading />}</Card>;
  const it = q.data;
  return (
    <Card title={<span className="mono">{it.mission.code}</span>} sim>
      <div className="muted" style={{ margin: "2px 0 6px" }}>{it.mission.name}</div>
      <Row label="Package" value={`${it.n_aircraft} × ${it.type.name} from ${it.base.code}`} />
      <Row label="Launch / recover" value={`${istTime(it.launch_ts)} – ${istTime(it.recovery_ts)}`} />
      <Row label="Tails" value={<span className="mono">{it.aircraft.map((a) => a.tail_no).join(", ")}</span>} />
      <Row label="Crew" value={it.crew.filter((c) => ["CAPTAIN", "INSTRUCTOR", "RPA_PILOT"].includes(c.position)).map((c) => `${RANK[c.rank] ?? c.rank} ${c.name}`).join(", ") || "—"} />
      {it.sortie && <Row label="Sortie" value={<><span className="mono">{it.sortie.code}</span> <Pill status={it.sortie.status} /></>} />}
      {it.explanation?.rows.slice(0, 3).map((r) => <Row key={r.label} label={r.label} value={r.value} />)}
      <div style={{ marginTop: 8 }}><a href={`/planner?plan=current&item=${it.id}`}>Open in planner ›</a></div>
    </Card>
  );
}

function SimTrackCard({ id }: { id: string }) {
  const t = useStore((s) => s.simTracks.find((x) => x.track_id === id));
  if (!t) return <Card title="Simulated track" sim><div className="empty">Track has landed or left the picture.</div></Card>;
  return (
    <Card title={<span className="mono">{t.callsign}</span>} sim>
      {t.kind === "SIM_UNKNOWN" ? <>
        <div className="notice" style={{ margin: "4px 0" }}>Simulated unknown track: it approaches the border and turns away. It never crosses into India.</div>
        <Row label="Phase" value={label(t.phase)} />
        <Row label="Detected" value={t.detected ? "Yes, inside radar cover" : "Not yet"} />
        {t.interceptor_base && <Row label="QRA scrambled from" value={t.interceptor_base} />}
      </> : <>
        <Row label="Aircraft" value={`${t.type ?? "—"} · ${t.tail_no ?? ""}`} />
        <Row label="Sortie" value={<span className="mono">{t.sortie_code}</span>} />
        <Row label="Mission" value={label(t.mission_type)} />
        <Row label="Phase / status" value={`${label(t.phase)} · ${label(t.status)}`} />
        <Row label="From" value={t.base ?? "—"} />
      </>}
      <Row label="Altitude / speed" value={`${feet(t.alt_m)} · ${num(t.gs_kt)} kt`} />
      <Row label="Heading" value={`${num(t.heading_deg)}°`} />
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
      {r && <Row label="Route" value={`${r.origin?.iata_code ?? "?"} → ${r.destination?.iata_code ?? "?"}`} />}
      <Row label="Flight path" value={recorded || destination ? <>
        {!!recorded && <span>Recorded trail · {recorded} points</span>}
        {!!recorded && destination && <br />}
        {destination && <span>Scheduled route shown</span>}
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
