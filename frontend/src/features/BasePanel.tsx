import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { User } from "../api/types";
import { ErrorText, Gauge, Kpi, Loading, Pill, Row, Sim, ToneText } from "../components/ui";
import { RANK, day, feet, istTime, kl, label, num, sevTone, tone, zulu } from "../lib/format";
import { useStore } from "../store";
import { DESCRIPTION } from "../equipment/models";
import { EquipmentDetail, EquipmentTiles, type GalleryGroup, type GalleryType } from "./EquipmentGallery";

interface Ac { id: number; tail_no: string; status: string; type: string; category: string; role: string; squadron: string;
  home_base: string; current_base: string | null; home_base_id: number; current_base_id: number | null; airframe_hours: number;
  next_maint_due_hours: number; fuel_kg: number; max_fuel_kg: number; readiness_min: number | null; maint_eta: string | null; version: number }
interface Crew { id: number; rank: string; first_name: string; last_name: string; callsign: string; aircrew_role: string; stream: string;
  duty_status: string; medical_status: string; ops_category: string; appointment: string | null; total_hours: number; squadron: string | null;
  available: boolean; fatigued: boolean; lapsed: string | null; lapsing: boolean | null; hours_24h: number }
interface Fuel { id: number; grade: string; capacity_l: number; current_l: number; reserve_l: number; reorder_l: number; days_of_supply: number | null; daily_issue_l: number | null;
  replenish_eta: string | null; tank_count: number }
interface Summary {
  base: { id: number; code: string; name: string; command: string; command_name: string; wing: string | null; base_type: string;
    lat: number; lon: number; elevation_m: number | null; ops_status: string };
  aircraft: Ac[];
  parking: { slot_size: string; slots_total: number; slots_us: number; occupied: number }[];
  facilities: { kind: string; slot_size: string; slots_total: number; slots_unserviceable: number }[];
  qra: { type: string; required_aircraft: number; qra_aircraft: number; qra_crew: number; readiness_min: number; met: boolean }[];
  crew: Crew[];
  ground_crew: { trade: string; authorised: number; held: number; on_duty: number; standby: number; on_leave: number }[];
  ground_assets: { asset_class: string; asset_type: string; total: number; serviceable: number }[];
  air_defence: { id: number; code: string; system: string; category: string; status: string; launchers_ready: number; launchers_total: number;
    readiness_min: number; max_range_km: number; distance_km: number }[];
  radars: { id: number; code: string; type: string; status: string; max_range_km: number; distance_km: number }[];
  comms: { id: number; code: string; node_type: string; status: string }[];
  fuel: Fuel[];
  fuel_transactions: { ts: string; kind: string; quantity_l: number; grade: string; actor: string }[];
  runways: { designator: string; length_m: number | null; width_m: number | null; surface: string; status: string }[];
  nearby_algs: { id: number; code: string; name: string; distance_km: number }[];
  ground_items: { id: number; asset_class: string; asset_type: string; reg_or_serial: string; status: string; capacity_l: number | null; last_service_date: string | null }[];
  connectivity: { rail: Near[]; rail_major: Near[]; airports: Near[]; highways: { ref: string; distance_km: number }[]; bases: Near[] };
  warehouses: { id: number; name: string; kind: string; utilisation_pct: number; below_reorder: number; items: number; status: string }[];
  armament: { category: string; nomenclature: string; unit: string; on_hand: number; reorder: number }[];
  low_stock: { nomenclature: string; qty_on_hand: number; reorder_level: number; warehouse: string }[];
  sorties: { id: number; code: string; mission_type: string; priority: string; status: string; origin: string; planned_launch_ts: string;
    actual_launch_ts: string | null; aircraft: string | null; callsign: string | null }[];
  alerts: { id: number; kind: string; severity: string; message: string }[];
  weather: { available: boolean; station?: string; station_name?: string; distance_km?: number; own_station?: boolean; raw?: string;
    taf?: string | null; flight_category?: string; temp_c?: number; wind_dir?: number | string; wind_kt?: number; gust_kt?: number | null;
    visibility_sm?: string | number; altimeter_hpa?: number; obs_time?: string; note?: string; clouds?: { cover: string; base: number }[] };
}

interface Near { id?: number; name: string; code?: string; icao?: string; iata?: string; rank?: number; distance_km: number; lat: number; lon: number }

const TABS = [["Ov", "Overview"], ["Eq", "Equipment"], ["Cr", "Crew"], ["Bw", "Base & weather"]] as const;
const CLASS_ORDER = ["FIGHTER_MULTIROLE", "AIR_SUPERIORITY", "STRIKE", "TRAINER_ADVANCED", "TRAINER_INTERMEDIATE", "TRAINER_BASIC",
  "TRANSPORT_STRATEGIC", "TRANSPORT_TACTICAL", "TRANSPORT_LIGHT", "TANKER", "AEW_C", "ISR"];
const SERVICEABLE = new Set(["AVAILABLE", "STANDBY", "QRA", "AIRBORNE", "TURNAROUND"]);

export function BasePanel({ baseId, user }: { baseId: number; user: User }) {
  const s = useStore();
  const tab = s.panelTab;
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => { body.current?.scrollTo({ top: 0 }); }, [tab, baseId]);  // braces: newer Chrome returns a Promise from scrollTo
  const q = useQuery({ queryKey: ["summary", baseId], queryFn: () => api<Summary>(`/bases/${baseId}/summary`), refetchInterval: 20000 });
  const canEdit = user.role === "ADMIN" || (user.role === "BASE_COMMANDER" && user.base_id === baseId);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select")) return;
      if (e.key === "Escape") s.set({ selection: null });
      const i = Number(e.key) - 1;
      if (i >= 0 && i < TABS.length) s.set({ panelTab: TABS[i][0] });
    };
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <aside className="panel" aria-label="Base details">
      <div className="bezel bezel-v" role="tablist" aria-label="Base panel sections">
        {TABS.map(([k, name], i) => (
          <button key={k} role="tab" aria-selected={tab === k} aria-label={name} title={`${name} (${i + 1})`}
            className={`softkey${tab === k ? " on" : ""}`} onClick={() => s.set({ panelTab: k })}>{name}</button>
        ))}
      </div>
      <div className="panel-main">
        {q.isLoading && <div className="panel-head"><Loading /></div>}
        {q.error && <div className="panel-head"><ErrorText error={q.error} /></div>}
        {q.data && (
          <>
            <Header d={q.data} onClose={() => s.set({ selection: null })} />
            <div className="panel-body" ref={body}>
              {tab === "Ov" && <Overview d={q.data} />}
              {tab === "Eq" && <Equipment d={q.data} canEdit={canEdit} />}
              {tab === "Cr" && <CrewTab d={q.data} />}
              {tab === "Bw" && <BaseWeather d={q.data} />}
            </div>
          </>
        )}
      </div>
    </aside>
  );
}

function Header({ d, onClose }: { d: Summary; onClose: () => void }) {
  const b = d.base;
  const wx = d.weather;
  return (
    <div className="panel-head">
      <div className="panel-title">
        <span>{b.name.replace("Air Force Station ", "")} <span className="mono muted" style={{ fontSize: 15 }}>{b.code}</span></span>
        <button className="close" onClick={onClose} aria-label="Close panel (Esc)">×</button>
      </div>
      <div className="panel-meta">
        <span>{b.command_name}</span>{b.wing && <span>{b.wing}</span>}<span>{label(b.base_type)}</span>
        <span className="mono">{b.lat.toFixed(3)}, {b.lon.toFixed(3)}</span>{b.elevation_m != null && <span className="mono">{feet(b.elevation_m)}</span>}
      </div>
      <div className="status-strip" style={{ marginTop: 6 }}>
        <Pill status={b.ops_status} /> {wx.available && <Pill status={wx.flight_category} text={`${wx.flight_category} ${wx.station}`} />}
        {d.qra.map((qr) => <Pill key={qr.type} status={qr.met ? "OPERATIONAL" : "CRITICAL"} text={`QRA ${qr.qra_aircraft}/${qr.required_aircraft}`} />)}
        {d.alerts.length > 0 && <Pill status={d.alerts.some((a) => a.severity === "CRITICAL") ? "CRITICAL" : "WARNING"} text={`${d.alerts.length} alerts`} />}
      </div>
    </div>
  );
}

function groupBy<T>(xs: T[], key: (x: T) => string) {
  const m = new Map<string, T[]>();
  for (const x of xs) m.set(key(x), [...(m.get(key(x)) ?? []), x]);
  return m;
}

const SEV_GLYPH: Record<string, string> = { CRITICAL: "■", WARNING: "◆", CAUTION: "▲", INFO: "○" };
const SEV_ORDER: Record<string, number> = { CRITICAL: 0, WARNING: 1, CAUTION: 2, INFO: 3 };
const homeFleet = (d: Summary) => d.aircraft.filter((a) => a.home_base_id === d.base.id && a.status !== "DEPOT");

// ---------------------------------------------------------------- 1. Overview: readiness, what needs attention, fuel
function Overview({ d }: { d: Summary }) {
  // aircraft readiness excludes small quadcopters, the same definition as alerts and the map (v_aircraft_serviceability)
  const fleet = homeFleet(d).filter((a) => a.category !== "UAV_ROTARY_SMALL");
  const svc = fleet.filter((a) => SERVICEABLE.has(a.status)).length;
  const pct = fleet.length ? Math.round((100 * svc) / fleet.length) : null;
  const pilots = d.crew.filter((c) => c.aircrew_role === "PILOT" || c.aircrew_role === "RPA_PILOT");
  const avail = pilots.filter((c) => c.available).length;
  const ground = d.ground_items, groundOk = ground.filter((g) => g.status === "SERVICEABLE").length;
  const sensors = [...d.air_defence, ...d.radars];
  const sensorsOk = sensors.filter((x) => x.status === "OPERATIONAL").length;
  return (
    <>
      <div className="kpis" style={{ marginTop: 12, gridTemplateColumns: "repeat(2, 1fr)" }}>
        <Kpi label="Aircraft ready" value={fleet.length ? <>{svc}<small> of {fleet.length}</small></> : "None"}
          sub={pct != null ? `${pct}% serviceable` : "no aircraft based here"} toneName={sevTone(pct)} />
        <Kpi label="Pilots available" value={<>{avail}<small> of {pilots.length}</small></>}
          sub={d.crew.some((c) => c.fatigued) ? `${d.crew.filter((c) => c.fatigued).length} fatigued` : "none fatigued"}
          toneName={svc && avail < svc ? "caution" : undefined} />
        <Kpi label="Vehicles & support equipment" value={<>{groundOk}<small> of {ground.length}</small></>}
          sub={groundOk === ground.length ? "all ready" : `${ground.length - groundOk} not ready`}
          toneName={ground.length && groundOk / ground.length < 0.8 ? "caution" : undefined} />
        <Kpi label="Air defence & radars" value={sensors.length ? <>{sensorsOk}<small> of {sensors.length}</small></> : "None"}
          sub={sensors.length ? (sensorsOk === sensors.length ? "all operational" : `${sensors.length - sensorsOk} not operational`) : "none assigned"}
          toneName={sensors.length && sensorsOk < sensors.length ? "warning" : undefined} />
      </div>
      {d.qra.map((q) => (
        <div key={q.type} className={`qra-line s-${q.met ? "ok" : "critical"}`}>
          <b>{q.met ? "●" : "■"} Quick reaction alert</b>
          <span>{q.type}: {q.qra_aircraft} of {q.required_aircraft} aircraft, {q.qra_crew} of {q.required_aircraft} crew, {q.readiness_min} min readiness</span>
        </div>
      ))}

      {d.alerts.length > 0 && (
        <>
          <h3 className="section-h">Needs attention <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>{d.alerts.length} open alerts</span></h3>
          <ul className="attn">
            {[...d.alerts].sort((a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9)).map((a) => (
              <li key={a.id} className={`s-${a.severity.toLowerCase()}`}><span aria-label={label(a.severity)}>{SEV_GLYPH[a.severity] ?? "○"}</span>
                <span className="attn-text">{a.message.replace(`${d.base.code}: `, "")}</span></li>
            ))}
          </ul>
        </>
      )}

      <h3 className="section-h">Fuel <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>capacity and usage</span></h3>
      {d.fuel.length === 0 && <div className="empty">No fuel storage recorded at this base.</div>}
      {d.fuel.map((f) => {
        const pctF = Math.round((100 * f.current_l) / Math.max(1, f.capacity_l));
        const t = f.current_l < f.reserve_l ? "critical" : f.current_l < f.reorder_l ? "caution" : "ok";
        return (
          <div key={f.id} className="fuel-card">
            <div className="fuel-top">
              <span className="fuel-grade">{label(f.grade)}</span>
              <span className={`fuel-pct s-${t}`}>{pctF}%</span>
            </div>
            <Gauge value={f.current_l} max={f.capacity_l} reserve={f.reserve_l} reorder={f.reorder_l} />
            <dl className="fuel-facts">
              <div><dt>In stock</dt><dd>{kl(f.current_l)} of {kl(f.capacity_l)}</dd></div>
              <div><dt>Daily use</dt><dd>{f.daily_issue_l ? `about ${kl(f.daily_issue_l)} a day` : "none recently"}</dd></div>
              <div><dt>Lasts</dt><dd className={`s-${t}`}>{f.days_of_supply ? `${num(f.days_of_supply, 1)} days at this rate` : "—"}</dd></div>
              <div><dt>Reserve</dt><dd>{kl(f.reserve_l)} · {f.tank_count} tanks</dd></div>
              {f.replenish_eta && <div><dt>Next delivery</dt><dd className="s-info">{istTime(f.replenish_eta, true)}</dd></div>}
            </dl>
          </div>
        );
      })}
      {d.fuel_transactions.length > 0 && <>
        <h3 className="section-h" style={{ fontSize: 14 }}>Recent fuel movements</h3>
        {d.fuel_transactions.slice(0, 6).map((t, i) => (
          <Row key={i} label={<>{label(t.kind)} <span className="dim">{t.grade}</span></>} extra={<span className="mono dim">{istTime(t.ts, true)}</span>} value={kl(t.quantity_l)} />
        ))}
      </>}
    </>
  );
}

const COMMS_NAME: Record<string, string> = { DATALINK_GS: "Data link ground station", VUHF_RELAY: "V/UHF radio relay", HF_STATION: "HF radio station",
  SATCOM_GS: "Satellite terminal", C2_NODE: "Command & control node", NETWORK_HUB: "Network hub" };


const ROLE_DESC: Record<string, string> = {
  FIGHTER_MULTIROLE: "Multirole fighter", AIR_SUPERIORITY: "Air superiority fighter", STRIKE: "Ground-attack strike aircraft",
  TRAINER_ADVANCED: "Advanced jet trainer", TRAINER_INTERMEDIATE: "Intermediate jet trainer", TRAINER_BASIC: "Basic trainer",
  TRANSPORT_STRATEGIC: "Heavy strategic transport", TRANSPORT_TACTICAL: "Tactical transport", TRANSPORT_LIGHT: "Light transport",
  TANKER: "Air-to-air refuelling tanker", AEW_C: "Airborne early warning and control", ISR: "Surveillance aircraft",
  UTILITY_HELO: "Utility transport helicopter", LIGHT_HELO: "Light utility helicopter", ATTACK_HELO: "Attack helicopter",
  HEAVY_LIFT_HELO: "Heavy-lift helicopter", UAV_MALE: "Long-endurance surveillance drone", UAV_TACTICAL: "Tactical surveillance drone",
  SMALL_UAS: "Small quadcopter drone",
};
const NAME: Record<string, string> = { GPU: "Ground power unit (GPU)", MOBILE_ATC: "Mobile ATC tower", AC_COOLING_CART: "Cooling cart",
  TOW_TRACTOR: "Aircraft tug", DEICER: "De-icing truck", HYDRANT_DISPENSER: "Hydrant dispenser", CARGO_LOADER: "Cargo loader" };
const CAT_NAME: Record<string, string> = { FIXED_WING: "Jets & fixed-wing", ROTARY_WING: "Helicopter", UAV_FIXED_WING: "UAV", UAV_ROTARY_SMALL: "Drone" };
const CAT_ORDER = ["FIXED_WING", "ROTARY_WING", "UAV_FIXED_WING", "UAV_ROTARY_SMALL"];

// ---------------------------------------------------------------- 2. Equipment: everything at the base, open a type to see each item
function Equipment({ d, canEdit }: { d: Summary; canEdit: boolean }) {
  const qc = useQueryClient();
  const toast = useStore((x) => x.toast);
  const [open, setOpen] = useState<string | null>(null);
  const body = useRef<HTMLDivElement>(null);
  const m = useMutation({
    mutationFn: ({ a, status }: { a: Ac; status: string }) => api(`/inv/aircraft/${a.id}`, { method: "PATCH", body: { status, version: a.version, status_reason: status === "MAINT_UNSCHEDULED" ? "Marked U/S by station" : null } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["summary"] }),
    onError: (e) => toast(e instanceof ApiError ? e.message : "Update failed", "WARNING"),
  });
  const rank = (a: Ac) => CAT_ORDER.indexOf(a.category) * 100 + Math.max(0, CLASS_ORDER.indexOf(a.role));
  const aircraft = (cats: string[]): GalleryType[] => [...groupBy(homeFleet(d).filter((a) => cats.includes(a.category)), (a) => a.type).entries()]
    .sort((x, y) => rank(x[1][0]) - rank(y[1][0]))
    .map(([name, list]) => ({
      key: `ac:${name}`, name, desc: ROLE_DESC[list[0].role] ?? `${CAT_NAME[list[0].category] ?? ""} · ${label(list[0].role)}`,
      art: { kind: "aircraft", type: name, category: list[0].category }, ready: (st) => SERVICEABLE.has(st),
      items: list.map((a) => ({
        id: a.id, title: a.tail_no, status: a.status,
        facts: [["Squadron", a.squadron], ["Airframe hours", num(a.airframe_hours)],
          ["Next maintenance", `${num(Math.max(0, a.next_maint_due_hours - a.airframe_hours))} h`],
          ["Fuel", `${Math.round((100 * a.fuel_kg) / Math.max(1, a.max_fuel_kg))}%`],
          ["Location", a.current_base_id === a.home_base_id ? "Home base" : a.current_base ? `At ${a.current_base}` : "Away"],
          ...(a.readiness_min != null ? [["Readiness", `${a.readiness_min} min`] as [string, string]] : [])],
        actions: canEdit ? (
          (a.status === "AVAILABLE" || a.status === "STANDBY") ? <button className="btn btn-sm" onClick={() => m.mutate({ a, status: "MAINT_UNSCHEDULED" })}>Mark out of service</button>
            : (a.status === "MAINT_UNSCHEDULED" || a.status === "MAINT_SCHEDULED") ? <button className="btn btn-sm" onClick={() => m.mutate({ a, status: "AVAILABLE" })}>Mark ready</button>
            : undefined) : undefined,
      })),
    }));
  const ground = (cls: string): GalleryType[] => [...groupBy(d.ground_items.filter((g) => g.asset_class === cls), (g) => g.asset_type).entries()]
    .sort((x, y) => x[0].localeCompare(y[0]))
    .map(([type, list]) => ({
      key: `gr:${type}`, name: NAME[type] ?? label(type), desc: DESCRIPTION[type], art: { kind: "ground", type }, ready: (st) => st === "SERVICEABLE",
      items: list.map((g) => ({ id: g.id, title: g.reg_or_serial, status: g.status,
        facts: [["Last service", day(g.last_service_date)], ...(g.capacity_l ? [["Capacity", kl(g.capacity_l)] as [string, string]] : [])] })),
    }));
  const operational = (st: string) => st === "OPERATIONAL";
  const groups: GalleryGroup[] = [
    { title: "Aircraft", types: aircraft(["FIXED_WING"]) },
    { title: "Helicopters", types: aircraft(["ROTARY_WING"]) },
    { title: "UAVs & drones", types: aircraft(["UAV_FIXED_WING", "UAV_ROTARY_SMALL"]) },
    { title: "Air defence & artillery", types: [...groupBy(d.air_defence, (a) => a.system).entries()].map(([system, list]) => ({
      key: `ad:${system}`, name: system, desc: `${DESCRIPTION[system] ?? label(list[0].category)} · range ${list[0].max_range_km} km`,
      art: { kind: "ground", type: system }, ready: operational,
      items: list.map((a) => ({ id: a.id, title: a.code, status: a.status,
        facts: [["Launchers ready", `${a.launchers_ready}/${a.launchers_total}`], ["Readiness", `${a.readiness_min} min`], ["From base", `${num(a.distance_km, 1)} km`]] })),
    })) },
    { title: "Radars", types: [...groupBy(d.radars, (r) => r.type).entries()].map(([type, list]) => ({
      key: `rd:${type}`, name: type, desc: `${DESCRIPTION[type] ?? "Radar"} · range ${list[0].max_range_km} km`, art: { kind: "ground", type }, ready: operational,
      items: list.map((r) => ({ id: r.id, title: r.code, status: r.status, facts: [["Range", `${r.max_range_km} km`], ["From base", `${num(r.distance_km, 1)} km`]] })),
    })) },
    { title: "Vehicles", types: ground("VEHICLE") },
    { title: "Ground support equipment", types: ground("GSE") },
    { title: "Communications", types: [...groupBy(d.comms, (c) => c.node_type).entries()].map(([k, list]) => ({
      key: `cm:${k}`, name: COMMS_NAME[k] ?? label(k), desc: DESCRIPTION[k], art: { kind: "ground", type: k }, ready: (st) => st === "UP",
      items: list.map((c) => ({ id: c.id, title: c.code, status: c.status, facts: [] })),
    })) },
  ];
  const t = groups.flatMap((g) => g.types).find((x) => x.key === open);
  const show = (key: string | null) => {
    setOpen(key);
    requestAnimationFrame(() => body.current?.closest(".panel-body")?.scrollTo({ top: 0 }));
  };
  if (t) return <div ref={body}><EquipmentDetail t={t} backLabel="All equipment" onBack={() => show(null)} /></div>;
  return (
    <div ref={body}>
      <h3 className="section-h">Equipment at this base <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>click a type to see each one</span></h3>
      <EquipmentTiles groups={groups} onOpen={show} />
      {(d.warehouses.length > 0 || d.armament.length > 0) && <h3 className="section-h">Stores <Sim /></h3>}
      {d.warehouses.map((w) => (
        <Row key={w.id} label={w.name} extra={w.below_reorder ? <ToneText toneName="caution">{w.below_reorder} items low</ToneText> : ""} value={`${Math.round(w.utilisation_pct)}% full`} />
      ))}
      {d.armament.length > 0 && <>
        <h3 className="section-h" style={{ fontSize: 14 }}>Armament stock (generic categories)</h3>
        {d.armament.map((a) => <Row key={a.category} label={a.nomenclature} extra={a.on_hand < a.reorder ? <ToneText toneName="caution">Low</ToneText> : ""} value={`${num(a.on_hand)} ${a.unit.toLowerCase()}`} />)}
      </>}
      {d.low_stock.length > 0 && <>
        <h3 className="section-h" style={{ fontSize: 14 }}>Below reorder level</h3>
        {d.low_stock.map((l, i) => <Row key={i} label={l.nomenclature} extra={<span className="dim">{l.warehouse}</span>} value={`${num(l.qty_on_hand)} of ${num(l.reorder_level)}`} />)}
      </>}
    </div>
  );
}

// ---------------------------------------------------------------- 3. Crew: every aircrew member, highest rank first
const RANK_ORDER = ["AIR_CMDE", "GP_CAPT", "WG_CDR", "SQN_LDR", "FLT_LT", "FG_OFFR"];
const RANK_FULL: Record<string, string> = {
  AIR_CMDE: "Air Commodore", GP_CAPT: "Group Captain", WG_CDR: "Wing Commander", SQN_LDR: "Squadron Leader", FLT_LT: "Flight Lieutenant", FG_OFFR: "Flying Officer",
};

function CrewTab({ d }: { d: Summary }) {
  const nav = useNavigate();
  const [role, setRole] = useState("ALL");
  const [q, setQ] = useState("");
  const roles = [...new Set(d.crew.map((c) => c.aircrew_role))];
  const needle = q.trim().toLowerCase();
  const list = d.crew
    .filter((c) => (role === "ALL" || c.aircrew_role === role)
      && (!needle || `${c.first_name} ${c.last_name} ${c.callsign ?? ""} ${c.squadron ?? ""}`.toLowerCase().includes(needle)))
    .sort((a, b) => RANK_ORDER.indexOf(a.rank) - RANK_ORDER.indexOf(b.rank) || a.last_name.localeCompare(b.last_name));
  const byRank = groupBy(list, (c) => c.rank);
  const onDuty = (st: string) => d.crew.filter((c) => c.duty_status === st).length;
  return (
    <>
      <div className="kpis" style={{ marginTop: 12 }}>
        <Kpi label="Aircrew" value={d.crew.length} sub={`${d.crew.filter((c) => c.available).length} available now`} />
        <Kpi label="Standby / QRA" value={`${onDuty("STANDBY")} / ${onDuty("QRA")}`} sub="aircrew" />
        <Kpi label="Fatigued / lapsed" value={`${d.crew.filter((c) => c.fatigued).length} / ${d.crew.filter((c) => c.lapsed).length}`}
          sub="currency lapsed" toneName={d.crew.some((c) => c.fatigued) ? "warning" : undefined} />
      </div>
      <div className="crew-tools">
        <input className="input" placeholder="Find by name, callsign or squadron" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find aircrew" />
        <select className="select" value={role} onChange={(e) => setRole(e.target.value)} aria-label="Filter by role">
          <option value="ALL">All roles</option>{roles.map((r) => <option key={r} value={r}>{label(r)}</option>)}
        </select>
      </div>
      {list.length === 0 && <div className="empty">No aircrew match.</div>}
      {RANK_ORDER.filter((r) => byRank.has(r)).map((r) => (
        <section key={r}>
          <h3 className="rank-h">{RANK_FULL[r]} <span>{byRank.get(r)!.length}</span></h3>
          {byRank.get(r)!.map((c) => (
            <Row key={c.id} onClick={() => nav(`/pilots/${c.id}`)}
              label={<>{RANK[c.rank]} {c.first_name} {c.last_name} <span className="dim">{label(c.aircrew_role)} · {c.squadron ?? c.appointment ?? "station"}</span></>}
              extra={<span className="status-strip">{c.fatigued && <ToneText toneName="warning">Fatigued</ToneText>}{c.lapsed && <ToneText toneName="caution">Lapsed</ToneText>}
                {!c.lapsed && c.lapsing && <ToneText toneName="caution">Lapsing</ToneText>}</span>}
              value={<Pill status={c.duty_status} />} />
          ))}
        </section>
      ))}
      <div className="dim" style={{ fontSize: 12, margin: "8px 0 4px" }}>All names are fictional. <Sim /></div>
      <h3 className="section-h">Ground crew by trade <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>on duty / held / authorised</span></h3>
      {d.ground_crew.map((g) => (
        <Row key={g.trade} label={label(g.trade)} extra={<span className="mono dim">{g.on_leave} leave · {g.standby} stby</span>}
          value={`${g.on_duty} / ${g.held} / ${g.authorised}`} />
      ))}
    </>
  );
}

// ---------------------------------------------------------------- 4. Base & weather: weather, runways, parking, connections
function BaseWeather({ d }: { d: Summary }) {
  const w = d.weather;
  const set = useStore((x) => x.set);
  const req = useStore((x) => x.requestFly);
  const mode = useStore((x) => x.mode);
  const c = d.connectivity;
  const rail = [...c.rail_major, ...c.rail.filter((r) => r.name !== c.rail_major[0]?.name)];
  const shelters = d.facilities.filter((f) => ["HAS", "MAINT_HANGAR", "UAV_HANGAR"].includes(f.kind)).reduce((a, f) => a + f.slots_total, 0);
  return (
    <>
      <h3 className="section-h">Weather now <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>METAR / TAF</span></h3>
      {!w.available && <div className="notice">{w.note}</div>}
      {w.available && (
        <>
          {!w.own_station && <div className="notice" style={{ marginBottom: 4 }}>Nearest reporting station: {w.station} ({w.station_name}), {w.distance_km} km</div>}
          <Row label="Flight category" value={<Pill status={w.flight_category} />} />
          <Row label="Observed" value={<span className="mono">{zulu(w.obs_time)} ({istTime(w.obs_time)})</span>} />
          <Row label="Wind" value={`${w.wind_dir}° ${w.wind_kt} kt${w.gust_kt ? ` G${w.gust_kt}` : ""}`} />
          <Row label="Visibility" value={`${w.visibility_sm} SM`} />
          <Row label="Temperature / QNH" value={`${w.temp_c} °C · ${w.altimeter_hpa} hPa`} />
          <Row label="Cloud" value={(w.clouds ?? []).map((cl) => `${cl.cover}${String(Math.round((cl.base ?? 0) / 100)).padStart(3, "0")}`).join(" ") || "—"} />
          <div className="mono" style={{ fontSize: 12, marginTop: 8, whiteSpace: "pre-wrap" }}>{w.raw}</div>
          {w.taf && <div className="mono muted" style={{ fontSize: 12, marginTop: 6, whiteSpace: "pre-wrap" }}>{w.taf}</div>}
        </>
      )}
      <div className="toolbar" style={{ marginTop: 10 }}>
        <button className="btn btn-sm" onClick={() => set({ mode: "WX", selection: { kind: "wx", lat: d.base.lat, lon: d.base.lon } })}>48-hour forecast for this base</button>
      </div>

      <h3 className="section-h">Runways <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>dimensions public · status simulated</span></h3>
      {d.runways.length === 0 && <div className="empty">No runway data published for this field.</div>}
      {d.runways.map((r, i) => (
        <Row key={i} label={<span className="mono">{r.designator}</span>} extra={<span className="mono dim">{r.length_m ? `${num(r.length_m)} × ${num(r.width_m)} m` : "—"} {label(r.surface)}</span>}
          value={<Pill status={r.status} />} />
      ))}

      <h3 className="section-h">Parking & shelters</h3>
      {d.parking.map((p) => <Row key={p.slot_size} label={`Aircraft slots, size ${p.slot_size}`} extra={p.slots_us ? <span className="mono dim">{p.slots_us} out of use</span> : ""} value={`${p.occupied} of ${p.slots_total} used`} />)}
      <Row label="Hangars & hardened shelters" value={shelters} />

      <h3 className="section-h">Connections <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>straight-line distance</span></h3>
      {mode !== "INFRA" && <div className="notice" style={{ marginBottom: 6 }}>See these on the map in the Infra view.
        <button className="btn btn-sm" style={{ marginLeft: 8 }} onClick={() => useStore.getState().set({ mode: "INFRA" })}>Open Infra view</button></div>}
      {rail.map((r, i) => <Row key={`r${i}`} label={<><span style={{ color: "var(--map-rail-main)" }}>●</span> {r.name}</>}
        extra={<span className="dim">{r.rank === 0 ? "major junction" : "railhead"}</span>} value={`${r.distance_km} km`} onClick={() => req(r.lat, r.lon, 11)} />)}
      {c.airports.map((a, i) => <Row key={`a${i}`} label={<><span style={{ color: "var(--map-label)" }}>◯</span> {a.name}</>}
        extra={<span className="mono dim">{a.iata ?? a.icao}</span>} value={`${a.distance_km} km`} onClick={() => req(a.lat, a.lon, 10)} />)}
      {c.highways.map((h) => <Row key={h.ref} label={<><span style={{ color: "var(--map-highway)" }}>━</span> {h.ref.replaceAll(";", " / ")}</>}
        extra={<span className="dim">national highway</span>} value={`${h.distance_km} km`} />)}
      {c.bases.map((b) => <Row key={b.id} label={<><span style={{ color: "var(--base-iaf)" }}>◉</span> {b.name.replace(/^Air Force Station /, "")}</>}
        extra={<span className="mono dim">{b.code}</span>} value={`${b.distance_km} km`} onClick={() => set({ selection: { kind: "base", id: b.id! }, panelTab: "Bw" })} />)}
      {d.nearby_algs.length > 0 && <>
        <h3 className="section-h" style={{ fontSize: 14 }}>Landing grounds within 300 km</h3>
        {d.nearby_algs.map((a) => <Row key={a.id} label={a.name} value={`${a.distance_km} km`} onClick={() => set({ selection: { kind: "base", id: a.id } })} />)}
      </>}
      <div className="toolbar" style={{ marginTop: 12 }}><button className="btn" onClick={() => req(d.base.lat, d.base.lon, 13)}>Zoom to field</button></div>
      <div className="dim" style={{ fontSize: 12 }}>Aviation weather: NOAA Aviation Weather Center</div>
    </>
  );
}
