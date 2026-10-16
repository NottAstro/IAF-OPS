import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { LiveTrack } from "../api/types";
import { ErrorText, Loading, Row, Sim, ToneText } from "../components/ui";
import { feet, label, num } from "../lib/format";
import { type Selection, useStore } from "../store";

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
  const e = useQuery({
    queryKey: ["enrich", hex, track?.callsign], queryFn: () => api<{ aircraft?: Record<string, string>; route?: Record<string, { iata_code?: string; name?: string }> }>(`/live/aircraft/${hex}/enrich?callsign=${track?.callsign ?? ""}`),
    staleTime: 86400000,
  });
  if (!track) return <Card title={hex}><div className="empty">Track no longer in view.</div></Card>;
  const a = e.data?.aircraft;
  const r = e.data?.route;
  return (
    <Card title={<span className="mono">{track.callsign ?? hex.toUpperCase()}</span>}>
      {track.emergency && <div className="pill s-critical" style={{ margin: "4px 0" }}>■ {track.emergency}</div>}
      <Row label="Category" value={label(track.category)} />
      <Row label="Type" value={a?.type ?? track.desc ?? track.icao_type ?? "—"} />
      <Row label="Registration" value={a?.registration ?? track.reg ?? "—"} />
      <Row label="Operator" value={a?.registered_owner ?? track.operator ?? "—"} />
      {r && <Row label="Route" value={`${r.origin?.iata_code ?? "?"} → ${r.destination?.iata_code ?? "?"}`} />}
      <Row label="Altitude" value={track.alt_m != null ? feet(track.alt_m) : "—"} />
      <Row label="Ground speed / track" value={`${num(track.gs_kt)} kt / ${num(track.track_deg)}°`} />
      <Row label="Squawk" value={<span className="mono">{track.squawk ?? "—"}</span>} />
      <Row label="Source / age" value={`${track.source} · ${track.age_s} s`} />
      <div className="dim" style={{ fontSize: 12, marginTop: 6 }}>Live public ADS-B (not simulated). Enrichment: adsbdb.</div>
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
