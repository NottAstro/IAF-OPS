// The one MapLibre map (FR-MAP-01..13). Flat Web Mercator framed on India; features talk to it via the store
// rather than importing maplibre-gl themselves (AGENTS.md §5).
import { useQuery } from "@tanstack/react-query";
import maplibregl, { type GeoJSONSource, type Map as MlMap, type MapGeoJSONFeature } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature, Geometry, Point } from "geojson";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { scheduledAirports, useLivePath } from "../api/live";
import { type ConnectionSummary, type NearbyBase, useRoadConnection } from "../api/connectivity";
import type { Base, BaseStatus, LiveScenario, LiveTrack, Site } from "../api/types";
import { GLYPH, MISSION_WORD, ROUTINE, type Status, baseName, chosen, isGround, planFocus, routineStart, scriptFor, slotOffset, statusAt, statusWord, timesOf, validRun } from "../features/scripts";
import { LIVE_GROUP, type LayerId, type Selection, layerFixed, layerMode, useStore } from "../store";
import { FLIGHT_CAT_TOKEN, cssVar } from "./colors";
import { CONNECTIVITY_LAYERS, FOCUS_DIM, FOCUS_LAYERS, FOCUS_PKG_LAYERS, INDIA_BOUNDS, INTERACTIVE, LAYER_IDS, OVERLAY_BEFORE, REGION_BOUNDS, RING_LAYERS, buildStyle } from "./style";
import { type BlockOpts, baseBlock, glyphIcon, iconImage, missionIcon } from "./symbols";
import { useWind } from "./wind";
import { greatCircle } from "./flightPath";
import { COMMS_NAME, istTime, label } from "../lib/format";

interface Metar { icao: string; lat: number; lon: number; flight_category: string }
interface Near { name: string; code?: string; icao?: string; iata?: string; lat: number; lon: number; distance_km: number | string }
interface Connectivity { rail: Near[]; rail_major: Near[]; airports: Near[]; bases: NearbyBase[] }
interface Fc { type: "FeatureCollection"; features: Feature[] }

let current: MlMap | null = null;
/** Mission-area colour by state, the same tones as the Ops panel's mission rows (D78). */
const MISSION_TONE: Record<Status, string> = { waiting: "--warning", approved: "--ok", airborne: "--sim", "on station": "--sim",
  returning: "--sim", landed: "--neutral", "not flown": "--neutral" };
const PANEL_SHIFT = -200; // keep a selected base clear of the side panel
const TILT = 42;          // default 3D camera pitch in degrees (higher shows the horizon at country zoom)
const FOCUS_KM = 60;

const feature = (geometry: Geometry, properties: Record<string, unknown>): Feature => ({ type: "Feature", geometry, properties });
const point = (lon: number, lat: number, p: Record<string, unknown>) => feature({ type: "Point", coordinates: [lon, lat] }, p);
const setData = (m: MlMap, id: string, features: Feature[]) =>
  (m.getSource(id) as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features });
const circle = (lon: number, lat: number, km: number) =>
  Array.from({ length: 97 }, (_, i) => {
    const a = (i / 96) * Math.PI * 2;
    return [lon + (km / (111.32 * Math.cos((lat * Math.PI) / 180))) * Math.sin(a), lat + (km / 111.32) * Math.cos(a)];
  });

/** Coverage pop (D63): a radar / AD site's own ring, labelled at its north edge. The selected site's ring stays; the
 * hovered one follows the pointer. Both share the `ops-ring` source. */
type SiteKind = "radar" | "ad" | "comms";
const SITE_LAYER: Record<string, SiteKind> = { "ops-radar-sites": "radar", "ops-ad-sites": "ad", "ops-comms": "comms",
  "ops-radar-sites-near": "radar", "ops-ad-sites-near": "ad", "ops-comms-near": "comms" };
const COMMS_RANK: Record<string, number> = { C2_NODE: 0, NETWORK_HUB: 0, SATCOM_GS: 1, HF_STATION: 2 };
let ringSel: Feature[] = [];
let ringHover: Feature[] = [];
let hoverKey = "";
const drawRings = (m: MlMap) => setData(m, "ops-ring", [...ringSel, ...ringHover]);
function siteRing(p: Record<string, unknown>, lon: number, lat: number): Feature[] {
  const km = Number(p.range_km);
  if (!km || p.kind === "comms") return [];
  return [feature({ type: "Polygon", coordinates: [circle(lon, lat, km)] }, { kind: p.kind }),
    point(lon, lat + km / 111.32, { kind: p.kind, label: `${p.code} · ${p.name} · ${km} km` })];
}

/** Satellite IR (bright = cold cloud tops) → white, translucent cloud cover over the dark map. */
let cloudsProtocol = false;
function registerClouds() {
  if (cloudsProtocol) return;
  cloudsProtocol = true;
  maplibregl.addProtocol("clouds", async (params, abort) => {
    const res = await fetch(params.url.replace("clouds://", `${location.protocol}//`), { signal: abort.signal, credentials: "same-origin" });
    if (!res.ok) throw new Error(`cloud tile ${res.status}`);
    const bmp = await createImageBitmap(await res.blob());
    const cv = new OffscreenCanvas(bmp.width, bmp.height);
    const g = cv.getContext("2d")!;
    g.drawImage(bmp, 0, 0);
    const img = g.getImageData(0, 0, bmp.width, bmp.height);
    const d = img.data;
    for (let i = 0; i < d.length; i += 4) {
      const t = Math.min(1, Math.max(0, (d[i] - 95) / 125)); // ponytail: fixed brightness ramp; warm ground ~<95, deep convection ~220
      const a = t * t * (3 - 2 * t);
      d[i] = 185 + 70 * a;
      d[i + 1] = 205 + 50 * a;
      d[i + 2] = 232 + 23 * a;
      d[i + 3] = Math.round(d[i + 3] * a * 0.95);
    }
    g.putImageData(img, 0, 0);
    return { data: await (await cv.convertToBlob({ type: "image/png" })).arrayBuffer() };
  });
}

/** Map a clicked feature to a store selection. */
function toSelection(f: MapGeoJSONFeature): Selection {
  const p = f.properties as Record<string, string | number>;
  if (f.layer.id === "ops-missions") return { kind: "plan-mission", run: String(p.run), mission: String(p.mid) };   // D71: focus the package
  if (SITE_LAYER[f.layer.id]) return { kind: SITE_LAYER[f.layer.id], id: Number(p.id) };
  const [lon, lat] = (f.geometry as Point).coordinates;
  const id = f.layer.id;
  if (id === "live-air") return { kind: "live", hex: String(p.hex) };
  if (id.startsWith("bases-")) return { kind: p.kind as "base" | "public-base", id: Number(p.id) };
  if (id === "metar") return { kind: "wx", lat, lon };
  const kind = id === "airports" ? "airport" : id === "stations" ? "station" : id === "towers" ? "tower" : null;
  return kind ? ({ ...p, kind, id: Number(p.id), lat, lon } as never) : null;
}

function hoverText(f: MapGeoJSONFeature): [string, string] {
  const p = f.properties as Record<string, string | number | undefined>;
  const id = f.layer.id;
  if (id === "connectivity-bases") return [String(p.code), `${p.name}${p.distance_km != null ? ` · ${p.distance_km} km direct` : " · source base"}`];
  if (id === "ops-missions") return [String(p.code), `${p.priority} · ${p.name} · ${p.state} · click to follow it`];
  if (SITE_LAYER[id]) return [`${p.code} (simulated)`, [p.name, p.range_km ? `${p.range_km} km` : "", String(p.status ?? "").toLowerCase()].filter(Boolean).join(" · ")];
  if (id === "live-air") return [String(p.label || p.hex), String(p.desc ?? "")];
  if (id.startsWith("bases-"))
    return [String(p.name), [p.code, p.svc != null && p.svc !== "" ? `${p.svc}% serviceable` : "", p.qra ? `QRA ${p.qra}` : "",
      p.sev ? `${String(p.sev).toLowerCase()} alert` : ""].filter(Boolean).join(" · ")];
  if (id === "airports") return [String(p.name), [p.icao, p.iata].filter(Boolean).join(" / ")];
  if (id === "stations") return [String(p.name), p.rank === 0 ? "Major railway junction" : "Railway station"];
  if (id === "metar") return [String(p.icao), `METAR ${p.cat}`];
  return [String(p.name || "Telecom tower"), String(p.operator ?? "")];
}

export function MapView({ hidden }: { hidden: boolean }) {
  const el = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MlMap | null>(null);
  const s = useStore();

  // ---------------------------------------------------------------- map (once)
  useEffect(() => {
    registerClouds();
    const left = (el.current!.clientWidth > 900 ? 300 : 24);
    const m = new maplibregl.Map({
      container: el.current!, style: buildStyle(), bounds: INDIA_BOUNDS, maxBounds: REGION_BOUNDS, minZoom: 3.5, maxZoom: 15,
      fitBoundsOptions: { padding: { top: 24, bottom: 36, left, right: 24 } },
      renderWorldCopies: false, maxPitch: 75, dragRotate: false, pitchWithRotate: false, fadeDuration: 120,
      attributionControl: { compact: true },
      transformRequest: (url) => (url.startsWith(location.origin) ? { url, credentials: "same-origin" } : { url }),
    });
    current = m;
    m.touchZoomRotate.disableRotation();
    m.touchPitch.disable();
    m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
    m.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    m.on("styleimagemissing", (e) => {
      const img = iconImage(e.id);
      if (img && !m.hasImage(e.id)) m.addImage(e.id, img.data, { pixelRatio: img.pixelRatio });
    });
    const pushCamera = () => {
      const b = m.getBounds(), c = m.getCenter();
      useStore.getState().set({ camera: { lat: c.lat, lon: c.lng, zoom: m.getZoom(), bbox: [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()] } });
    };
    m.on("moveend", pushCamera);
    m.on("load", () => {
      pushCamera();
      setMap(m);
    });

    const tip = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 14, className: "hover-tip", maxWidth: "260px" });
    const tipEl = document.createElement("div");
    let lastMove = 0;
    const live = () => INTERACTIVE.filter((id) => m.getLayer(id));
    m.on("mousemove", (e) => {
      if (performance.now() - lastMove < 60) return;
      lastMove = performance.now();
      const terrain = m.getTerrain();
      const elev = terrain ? m.queryTerrainElevation(e.lngLat) : null;
      useStore.getState().set({ cursor: { lat: e.lngLat.lat, lon: e.lngLat.lng, elev: elev == null ? null : elev / (terrain?.exaggeration || 1) } });
      const f = m.queryRenderedFeatures(e.point, { layers: live() })[0];
      m.getCanvas().style.cursor = f ? "pointer" : "";
      const key = f && SITE_LAYER[f.layer.id] ? `${f.layer.id}:${f.properties.id}` : "";
      if (key !== hoverKey) {   // pop the hovered radar / AD site's own ring
        hoverKey = key;
        const [lon, lat] = key ? (f!.geometry as Point).coordinates : [0, 0];
        ringHover = key ? siteRing(f!.properties, lon, lat) : [];
        drawRings(m);
      }
      if (!f) return void tip.remove();
      const [title, sub] = hoverText(f);
      tipEl.innerHTML = "";
      tipEl.append(Object.assign(document.createElement("b"), { textContent: title }));
      if (sub) tipEl.append(Object.assign(document.createElement("div"), { textContent: sub }));
      tip.setLngLat(e.lngLat).setDOMContent(tipEl).addTo(m);
    });
    m.on("mouseout", () => {
      tip.remove();
      if (hoverKey) { hoverKey = ""; ringHover = []; drawRings(m); }
    });
    m.on("click", (e) => {
      const st = useStore.getState();
      if (st.picking === "mission" && st.missionDraft) {   // Missions page "Pick on map": hand the point back and return
        st.set({ picking: null, missionDraft: { ...st.missionDraft, lat: e.lngLat.lat.toFixed(4), lon: e.lngLat.lng.toFixed(4) } });
        return void history.back();
      }
      const f = m.queryRenderedFeatures(e.point, { layers: live() })[0];
      if (f?.layer.id === "connectivity-bases" && st.connectivityFocus) {
        const id = Number(f.properties.id);
        if (id !== st.connectivityFocus.sourceId) st.set({ connectivityFocus: { ...st.connectivityFocus, destinationId: id } });
        return;
      }
      const sel = f ? toSelection(f) : null;
      if (sel) return st.set({ selection: sel, panelTab: sel.kind === "base" && st.mode === "INFRA" ? "Bw" : "Ov" });
      if (f) return;   // hover-only features (transfer lines) keep the current selection
      const { lat, lng: lon } = e.lngLat;
      st.set({ selection: st.mode === "WX" ? { kind: "wx", lat, lon } : null });
    });
    return () => {
      current = null;
      ringSel = []; ringHover = []; hoverKey = "";
      tip.remove();
      m.remove();
      setMap(null);
    };
  }, []);

  // ---------------------------------------------------------------- data
  const bases = useQuery({ queryKey: ["bases"], queryFn: () => api<Base[]>("/bases"), staleTime: Infinity });
  // While another page covers the map (hidden), nothing here polls or animates: it resumes on return to /map.
  const status = useQuery({ queryKey: ["base-status"], queryFn: () => api<BaseStatus[]>("/bases/status"), refetchInterval: hidden ? false : 30000 });
  const box = s.camera?.bbox.map((v) => v.toFixed(1)).join(",") ?? "";
  const live = useQuery({
    queryKey: ["live", box],
    queryFn: () => api<{ tracks: LiveTrack[]; status: Record<string, never> }>(`/live/aircraft?bbox=${box}`),
    refetchInterval: 10000, enabled: s.mode === "LIVE" && !!box && !hidden, placeholderData: (p) => p,
  });
  const selectedTrack = s.selection?.kind === "live" && s.mode === "LIVE" && !hidden
    ? s.liveTracks.find((t) => s.selection?.kind === "live" && t.hex === s.selection.hex && !t.on_ground && s.liveCats[LIVE_GROUP[t.category]]) : undefined;
  const path = useLivePath(selectedTrack?.hex ?? null, selectedTrack?.callsign ?? null, !!selectedTrack);
  useEffect(() => {
    // Initial selection fetches automatically; subsequent live polls refresh the same trail query.
    if (selectedTrack) void path.trail.refetch();
  }, [live.dataUpdatedAt]); // eslint-disable-line react-hooks/exhaustive-deps
  const metars = useQuery({
    queryKey: ["wx", "metars"], queryFn: () => api<{ stations: Metar[] }>("/wx/metars"), refetchInterval: 300000,
    enabled: s.mode === "WX" && s.wx.metar,
  });
  const owm = useQuery({ queryKey: ["wx-status"], queryFn: () => api<{ owm: boolean }>("/wx/status"), enabled: s.mode === "WX" });
  const rain = s.wx.rain && owm.data?.owm === true;   // without an OWM key the rain tiles only 404
  const selBase = s.selection?.kind === "base" ? s.selection.id : null;
  const focus = s.mode === "INFRA" && !hidden && s.connectivityFocus?.sourceId === selBase ? s.connectivityFocus : null;
  const road = useRoadConnection(focus?.sourceId ?? null, focus?.destinationId ?? null, focus?.mode === "road");
  const focusSummary = useQuery({ queryKey: ["base-connectivity", focus?.sourceId],
    queryFn: () => api<ConnectionSummary>(`/bases/${focus?.sourceId}/connections`), enabled: !!focus, staleTime: 300000 });
  const summary = useQuery({
    queryKey: ["summary", selBase], queryFn: () => api<{ base: { id: number; code: string; name: string; lat: number; lon: number }; connectivity: Connectivity }>(`/bases/${selBase}/summary`),
    enabled: s.mode === "INFRA" && selBase != null && !focus,
  });
  useEffect(() => {
    if (live.data?.status) s.set({ feeds: { ...useStore.getState().feeds, ...live.data.status }, liveTracks: live.data.tracks });
  }, [live.data]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------- operations view (Phase 2, all simulated)
  const ops = s.mode === "OPS" && !hidden;
  const threatZones = useQuery({ queryKey: ["ops-zones", "threat"], queryFn: () => api<Fc>("/ops/zones?kind=threat"), enabled: ops, refetchInterval: 30000 });
  // D66, D76: the Ops map draws the scripted missions' areas; a package's aircraft and route appear when it is focused (D71)
  const liveRuns = useQuery({ queryKey: ["scenarios", "live"], queryFn: () => api<LiveScenario[]>("/ops/scenarios/live"), enabled: ops, refetchInterval: 15000 });
  const simNow = s.simClock?.sim_now;
  const missionAreas = useMemo(() => {
    const now = simNow ?? new Date().toISOString();
    const runs = (liveRuns.data ?? []).flatMap((r) => {
      const script = scriptFor(r.code);
      return script ? [{ key: String(r.id), script, run: validRun(s.demo[String(r.id)], r.started_sim) }] : [];
    });
    runs.push({ key: "routine", script: ROUTINE, run: validRun(s.demo.routine, routineStart(now)) });
    // mission areas are the scripted missions too, so the map never shows a mission the Planner says is tasked as open;
    // they take the Ops panel's state colours (D78)
    const missions = runs.flatMap(({ key, script, run }) => script.missions.map((m) => {
      const pkg = chosen(m, run?.dec[m.id]), approvedAt = run?.approvedAt ?? null, st = statusAt(pkg, approvedAt, now);
      const sub = st === "waiting" ? "waiting for your decision"
        : st === "approved" && pkg ? `${isGround(pkg.type) ? "leaves" : "launch"} ${istTime(new Date(timesOf(pkg, approvedAt, now).launch)).replace(" IST", "")}`
        : statusWord(st, pkg?.type);
      const color = cssVar(MISSION_TONE[st]);
      return point(m.target[0], m.target[1], { scripted: true, run: key, mid: m.id, id: `${key}-${m.id}`, code: m.name, name: `${MISSION_WORD[m.mtype]} · ${script.name}`,
        priority: m.priority, state: sub, sub, label: `${m.priority} ${m.name}`, color, icon: missionIcon(m.mtype, color) });
    }));
    return missions;
  }, [liveRuns.data, s.demo, simNow]);
  // Simulated sites live in the Infra view (D75) and load whenever it is open, so the panel can count them while off (D63).
  const infra = s.mode === "INFRA" && !hidden;
  const radars = useQuery({ queryKey: ["sites", "radars"], queryFn: () => api<Site[]>("/sites/radars"), enabled: infra, staleTime: 60000 });
  const ads = useQuery({ queryKey: ["sites", "ad"], queryFn: () => api<Site[]>("/sites/ad"), enabled: infra, staleTime: 60000 });
  const comms = useQuery({ queryKey: ["sites", "comms"], queryFn: () => api<Site[]>("/sites/comms"), enabled: infra, staleTime: 60000 });
  const covRadar = infra && s.layers["ops-coverage"] && s.layers["ops-radar-sites"];
  const covAd = infra && s.layers["ops-coverage"] && s.layers["ops-ad-sites"];
  const radarCover = useQuery({ queryKey: ["sites", "coverage", "radar"], queryFn: () => api<Fc>("/sites/coverage?kind=radar"), enabled: covRadar, staleTime: 60000 });
  const adCover = useQuery({ queryKey: ["sites", "coverage", "ad"], queryFn: () => api<Fc>("/sites/coverage?kind=ad"), enabled: covAd, staleTime: 60000 });

  useEffect(() => {
    if (!map) return;
    setData(map, "ops-zones", (threatZones.data?.features ?? []).map((f) => ({ ...f, properties: { ...f.properties, layer: "threat" } })));
  }, [map, threatZones.data]);
  const sites = useMemo(() => {
    const site = (kind: SiteKind, x: Site, name: string, rank: number) => point(x.lon, x.lat, {
      id: x.id, kind, code: x.code, name, range_km: x.max_range_km ?? 0, status: x.status, rank });
    return [
      ...(radars.data ?? []).map((x) => site("radar", x, x.type ?? "Radar", -(x.max_range_km ?? 0))),
      ...(ads.data ?? []).map((x) => site("ad", x, x.system ?? "Air defence", -(x.max_range_km ?? 0))),
      ...(comms.data ?? []).map((x) => site("comms", x, COMMS_NAME[x.node_type ?? ""] ?? label(x.node_type), COMMS_RANK[x.node_type ?? ""] ?? 3)),
    ];
  }, [radars.data, ads.data, comms.data]);
  useEffect(() => {
    if (map) setData(map, "ops-sites", sites);
  }, [map, sites]);
  useEffect(() => {   // the selected radar / AD site keeps its ring
    if (!map) return;
    const sel = s.selection;
    const f = sel && (sel.kind === "radar" || sel.kind === "ad")
      ? sites.find((x) => x.properties?.kind === sel.kind && x.properties.id === sel.id) : undefined;
    ringSel = f ? siteRing(f.properties!, ...((f.geometry as Point).coordinates as [number, number])) : [];
    drawRings(map);
  }, [map, sites, s.selection]);
  useEffect(() => {
    if (map) setData(map, "ops-coverage", [...(covRadar ? radarCover.data?.features ?? [] : []), ...(covAd ? adCover.data?.features ?? [] : [])]);
  }, [map, covRadar, covAd, radarCover.data, adCover.data]);
  // D71: a planner package in focus (Planner step 4, the Ops panel or a click on its mission area): its aircraft and route
  // are drawn on the focus layers and the other mission areas fade until the card is closed.
  const pkgSel = s.selection?.kind === "plan-mission" ? s.selection : null;
  const pf = useMemo(() => pkgSel && ops ? planFocus(liveRuns.data, s.demo, pkgSel.run, pkgSel.mission, simNow ?? new Date().toISOString()) : null,
    [pkgSel?.run, pkgSel?.mission, ops, liveRuns.data, s.demo, simNow]); // eslint-disable-line react-hooks/exhaustive-deps
  const isFocused = (f: Feature) => !!pf && f.properties?.run === pkgSel?.run && f.properties?.mid === pkgSel?.mission;
  useEffect(() => {   // counts for the Infra panel's site toggles; undefined until loaded
    if (infra) s.set({ siteCounts: { "ops-radar-sites": radars.data?.length, "ops-ad-sites": ads.data?.length, "ops-comms": comms.data?.length } });
  }, [infra, radars.data, ads.data, comms.data]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (map) setData(map, "ops-missions", missionAreas.filter((f) => !isFocused(f)));
  }, [map, missionAreas, pf]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!map) return;
    if (!pf) return void setData(map, "ops-focus", []);
    const { m, pkg, ps } = pf, sim = cssVar("--sim");
    const out: Feature[] = [point(m.target[0], m.target[1], { role: "target", label: `${m.priority} ${m.name}`, icon: missionIcon(m.mtype, sim) })];
    if (pkg && ps) {
      // the package's label sits ahead of the leader once airborne, or on the base while it waits there
      const r = (ps.rot * Math.PI) / 180, what = `${pkg.n} × ${pkg.type}`;
      out.push(feature({ type: "LineString", coordinates: [ps.home, m.target] }, { role: "route" }),
        point(ps.home[0], ps.home[1], { role: "base", label: ps.atBase ? `${baseName(pkg.base)} · ${what}` : baseName(pkg.base) }),
        ...Array.from({ length: pkg.n }, (_, i) => point(ps.pos[0], ps.pos[1], { role: "ac", rot: ps.rot, off: slotOffset(i, pkg.n, ps.atBase),
          icon: glyphIcon(GLYPH(pkg.type), sim, 24), label: i === 0 && !ps.atBase ? `${what} SIM` : "",
          toff: [2.6 * Math.sin(r), -2.6 * Math.cos(r)] })));
    }
    setData(map, "ops-focus", out);
  }, [map, pf]);
  const focusOn = !!pf;
  useEffect(() => {
    if (!map) return;
    for (const [id, prop, v] of FOCUS_DIM) if (map.getLayer(id)) map.setPaintProperty(id, prop, focusOn ? v * 0.25 : v);
  }, [map, focusOn]);
  const pkgFit = useRef("");
  useEffect(() => {   // frame the base and the destination once per focus request (a new `fit` asks again)
    if (!map || !pf || !pkgSel) { pkgFit.current = ""; return; }
    const key = `${pkgSel.run}:${pkgSel.mission}:${pkgSel.fit ?? ""}`;
    if (pkgFit.current === key) return;
    pkgFit.current = key;
    const pts: [number, number][] = [pf.m.target, ...(pf.ps ? [pf.ps.home] : [])];
    const b = new maplibregl.LngLatBounds(pts[0], pts[0]);
    for (const p of pts) b.extend(p);
    const wide = map.getContainer().clientWidth > 1000;
    // a road rescue a few km out gets a closer frame than a sortie (D82); the frame waits for any camera move already
    // under way (the map's opening tilt would otherwise cancel it)
    const fit = () => map.fitBounds(b, { padding: { top: 120, bottom: 110, left: wide ? 360 : 60, right: wide ? 430 : 40 },
      maxZoom: pf.pkg && isGround(pf.pkg.type) ? 11 : 8, duration: 1300, essential: true });
    setTimeout(() => (map.isMoving() ? map.once("moveend", fit) : fit()), 60);   // not cancelled: later runs skip on the same key
  }, [map, pf, pkgSel?.fit]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------- what each view shows
  useEffect(() => {
    if (!map) return;
    const vis = (id: string, on: boolean) => map.getLayer(id) && map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    for (const [key, ids] of Object.entries(LAYER_IDS)) {
      const k = key as LayerId;
      const only = layerMode(k);
      for (const id of ids) vis(id, focus ? k === "india-border" || k === "intl-borders" || (k === "satellite" && s.layers.satellite)
        : (layerFixed(k) || s.layers[k]) && (!only || only === s.mode));
    }
    vis("live-air", s.mode === "LIVE");
    vis("live-label", s.mode === "LIVE");
    vis("metar", s.mode === "WX" && s.wx.metar);
    vis("metar-label", s.mode === "WX" && s.wx.metar);
    for (const id of FOCUS_LAYERS) vis(id, s.mode === "INFRA" && !focus);
    for (const id of RING_LAYERS) vis(id, s.mode === "INFRA" && !focus);
    for (const id of FOCUS_PKG_LAYERS) vis(id, s.mode === "OPS");
    for (const id of CONNECTIVITY_LAYERS) vis(id, !!focus);
    for (const id of ["lbl-country", "lbl-water", "runway", "hillshade"]) vis(id, !focus);
    map.setPaintProperty("relief", "color-relief-opacity", !focus && s.layers.relief ? (s.mode === "WX" ? 0.35 : 0.8) : 0);
  }, [map, s.layers, s.mode, s.wx.metar, focus]);

  // ---------------------------------------------------------------- air base badges
  const statusById = useMemo(() => new Map((status.data ?? []).map((v) => [v.base_id, v])), [status.data]);
  useEffect(() => {
    if (!map) return;
    const owner = { iaf: cssVar("--base-iaf"), mil: cssVar("--base-other"), hostile: cssVar("--base-hostile"), neutral: cssVar("--base-neutral") };
    const ice = cssVar("--text-1");
    const svcColor = (v: number) => cssVar(v >= 70 ? "--ok" : v >= 45 ? "--caution" : "--critical");
    setData(map, "bases", (bases.data ?? []).map((b) => {
      const own = b.side === "OWN";
      const layer = own ? (b.base_type === "ALG" ? "alg" : "iaf") : b.side === "FOREIGN" ? "foreign" : "mil";
      const st = statusById.get(b.id);
      const svc = layer === "iaf" ? st?.serviceability ?? null : null;
      const ring = layer === "iaf" || layer === "alg" ? owner.iaf : layer === "mil" ? owner.mil
        : b.affiliation === "HOSTILE" ? owner.hostile : owner.neutral;
      const sev = own && (st?.alert_severity === "CRITICAL" || st?.alert_severity === "WARNING") ? st.alert_severity : null;
      const qra = own && st?.qra_required ? (st.qra_met ? "met" : "short") : "";
      const block: BlockOpts = layer === "iaf"
        ? { color: ring, text: ice, kind: "jet", variant: "c", size: "l", code: b.code, pct: svc, pctColor: svc == null ? "" : svcColor(svc),
            alert: sev ? cssVar(sev === "CRITICAL" ? "--critical" : "--warning") : "", qra }
        : { color: ring, text: ring, kind: layer === "alg" ? "runway" : "jet", variant: "c", size: layer === "alg" ? "s" : "m", code: b.code };
      const name = b.name.replace(/^Air Force Station /, "");
      const props: Record<string, unknown> = {
        id: b.id, kind: own ? "base" : "public-base", layer, code: b.code, name: b.name, short: name, svc: svc ?? "",
        iconC: baseBlock(block), iconF: baseBlock({ ...block, variant: "f" }),
        rank: layer === "iaf" ? 0 : layer === "foreign" ? 1 : 2,
      };
      if (sev) props.sev = sev;
      if (qra) props.qra = qra;
      return point(b.lon, b.lat, props);
    }));
  }, [map, bases.data, statusById]);

  // ---------------------------------------------------------------- live ADS-B, dead-reckoned between polls for smooth motion
  useEffect(() => {
    if (!map) return;
    setData(map, "live-path", []);
    setData(map, "live-selection", []);
    if (s.mode !== "LIVE") return void setData(map, "live", []);
    if (hidden) return; // the 1 s dead-reckoning redraw re-renders the whole (3D) map: pause it off-screen
    const fetched = live.dataUpdatedAt || Date.now();
    const colors = { civil: cssVar("--caution"), military: cssVar("--accent"), uav: cssVar("--warning") };
    const crit = cssVar("--critical");
    const tracks = (live.data?.tracks ?? []).filter((t) => !t.on_ground && LIVE_GROUP[t.category] && s.liveCats[LIVE_GROUP[t.category]]);
    const draw = () => {
      const dt = (Date.now() - fetched) / 1000;
      const icons = tracks.map((t) => {
        const group = LIVE_GROUP[t.category];
        const secs = Math.min(t.age_s + dt, 60);
        const d = t.gs_kt && t.track_deg != null ? t.gs_kt * 0.514444 * secs : 0;
        const rad = ((t.track_deg ?? 0) * Math.PI) / 180;
        const cls = group === "military" && t.cls !== "helicopter" ? "fighter" : group === "uav" ? "uav" : t.cls;
        return point(t.lon + (d * Math.sin(rad)) / (111320 * Math.cos((t.lat * Math.PI) / 180)), t.lat + (d * Math.cos(rad)) / 111320, {
          hex: t.hex, label: t.callsign ?? t.hex.toUpperCase(), desc: t.desc ?? t.icao_type ?? "",
          icon: glyphIcon(cls, t.emergency ? crit : colors[group], group === "civil" ? 22 : 24),
          rot: t.track_deg ?? 0, op: t.age_s + dt > 60 ? 0.45 : 1,
        });
      });
      setData(map, "live", icons);
      const selected = selectedTrack && icons.find((f) => f.properties?.hex === selectedTrack.hex);
      setData(map, "live-selection", selected ? [selected] : []);
      const lines: Feature[] = [];
      if (selected) {
        const position = (selected.geometry as Point).coordinates;
        const recorded = path.trail.data ?? [];
        if (recorded.length) lines.push(feature({ type: "LineString", coordinates: [...recorded.map((p) => [p.lon, p.lat]), position] }, { kind: "trail" }));
        // D77: every dotted leg ends at a named airport: origin → first seen (scheduled), observed trail, aircraft → destination
        const ends = scheduledAirports(path.enrich.data?.route);
        const start = recorded.length ? [recorded[0].lon, recorded[0].lat] : position;
        if (ends) lines.push(
          feature({ type: "LineString", coordinates: greatCircle(ends.origin.at, start) }, { kind: "schedule", leg: "from" }),
          feature({ type: "LineString", coordinates: greatCircle(position, ends.destination.at) }, { kind: "schedule", leg: "to" }),
          point(...ends.origin.at, { kind: "airport", role: "from", title: [ends.origin.code, ends.origin.name].filter(Boolean).join(" · "), sub: "departed" }),
          point(...ends.destination.at, { kind: "airport", role: "to", title: [ends.destination.code, ends.destination.name].filter(Boolean).join(" · "), sub: "arriving" }));
        if (recorded.length) lines.push(point(start[0], start[1], { kind: "seen", role: "seen", title: `first seen ${istTime(new Date(recorded[0].ts * 1000)).replace(" IST", "")}`, sub: "" }));
      }
      setData(map, "live-path", lines);
    };
    draw();
    const timer = setInterval(draw, 1000);
    return () => clearInterval(timer);
  }, [map, live.data, live.dataUpdatedAt, s.liveCats, s.mode, hidden, selectedTrack, path.trail.data, path.enrich.data]);

  // ---------------------------------------------------------------- weather: airfield METAR + clouds + rain
  useEffect(() => {
    if (!map) return;
    setData(map, "metar", (metars.data?.stations ?? []).map((m) =>
      point(m.lon, m.lat, { icao: m.icao, cat: m.flight_category, color: cssVar(FLIGHT_CAT_TOKEN[m.flight_category] ?? "--neutral") })));
  }, [map, metars.data]);

  useEffect(() => {
    if (!map || s.mode !== "WX") return;
    const ids: string[] = [];
    const op = useStore.getState().overlayOpacity;
    const add = (id: string, tiles: string, tileSize: number, maxzoom: number, attribution: string) => {
      map.addSource(id, { type: "raster", tiles: [tiles], tileSize, maxzoom, attribution });
      map.addLayer({ id, type: "raster", source: id, paint: { "raster-opacity": op, "raster-fade-duration": 300, "raster-resampling": "linear" } }, OVERLAY_BEFORE);
      ids.push(id);
    };
    if (s.wx.clouds)
      add("wx-clouds", `clouds://${location.host}/api/v1/wx/ir?service=WMS&request=GetMap&version=1.3.0&styles=&format=image/png` +
        "&transparent=true&crs=EPSG:3857&width=512&height=512&bbox={bbox-epsg-3857}", 512, 7, "Clouds: NOAA nowCOAST satellite IR");
    if (rain)
      add("wx-rain", `${location.origin}/api/v1/wx/owm/precipitation_new/{z}/{x}/{y}.png`, 256, 9, "Rain: © OpenWeatherMap");
    return () => {
      if (current !== map) return;
      for (const id of ids) {
        map.removeLayer(id);
        map.removeSource(id);
      }
    };
  }, [map, s.mode, s.wx.clouds, rain]);
  useEffect(() => {
    for (const id of ["wx-clouds", "wx-rain"]) if (map?.getLayer(id)) map.setPaintProperty(id, "raster-opacity", s.overlayOpacity);
  }, [map, s.overlayOpacity]);

  useWind(map, s.mode === "WX" && s.wx.wind && !hidden, s.windModel);

  // ponytail: MapLibre has no pause API, and with 3D terrain it re-renders every frame even under another page. While
  // hidden we swallow repaint requests (state, camera and tiles are kept) and repaint once on return. Upgrade: a real
  // pause if MapLibre adds one.
  useEffect(() => {
    if (!map || !hidden) return;
    map.triggerRepaint = () => undefined;
    return () => {
      delete (map as Partial<Pick<MlMap, "triggerRepaint">>).triggerRepaint;
      map.resize();
      map.triggerRepaint();
    };
  }, [map, hidden]);

  // ---------------------------------------------------------------- 3D terrain everywhere except Weather, which is laid flat
  const wasFlat = useRef(true);  // true at start, so the map tilts into 3D once it has loaded
  const opened = useRef(false);
  const appliedTilt = useRef<boolean | null>(null);
  useEffect(() => {
    if (!map) return;
    const flat = s.mode === "WX" || !!focus;
    map.setTerrain(flat ? null : { source: "dem3d", exaggeration: s.exaggeration });
    map.setPaintProperty("hillshade", "hillshade-exaggeration", flat ? 0.55 : 0.8);
    if (flat || !s.tilt) {
      // Weather, connectivity focus or the "Straight" map angle: north-up and locked flat (no right-drag tilt)
      map.dragRotate.disable();
      map.touchPitch.disable();
      if (map.getPitch() || map.getBearing()) map.easeTo({ pitch: 0, bearing: 0, duration: 700 });
    } else {
      map.dragRotate.enable();
      map.touchPitch.enable();
      if (wasFlat.current || appliedTilt.current !== s.tilt) {
        // on opening, tilting shrinks the far side, so zoom in a little to keep India filling the frame
        const pitch = s.tilt ? TILT : 0;
        map.easeTo(opened.current ? { pitch, duration: 900 } : { pitch, zoom: map.getZoom() + 0.35, offset: [0, -40], duration: 1200 });
        opened.current = true;
      }
    }
    wasFlat.current = flat;
    appliedTilt.current = s.tilt;
  }, [map, s.mode, s.exaggeration, s.tilt, !!focus]);

  useEffect(() => {
    if (hidden && s.connectivityFocus) s.set({ connectivityFocus: null });
  }, [hidden, s.connectivityFocus, s.set]);

  // ---------------------------------------------------------------- infrastructure view: spotlight a base and its nearest connections
  useEffect(() => {
    if (!map) return;
    const c = summary.data?.connectivity;
    const b = summary.data?.base;
    if (s.mode !== "INFRA" || selBase == null || !c || !b) return void setData(map, "focus", []);
    const ring = circle(b.lon, b.lat, FOCUS_KM);
    const world = [[30, -30], [150, -30], [150, 70], [30, 70], [30, -30]];
    const links: Feature[] = [];
    const link = (n: Near | undefined, kind: string, label: string) => {
      if (!n) return;
      links.push(feature({ type: "LineString", coordinates: [[b.lon, b.lat], [n.lon, n.lat]] }, { role: "link", kind, label: `${label} · ${n.distance_km} km` }));
      links.push(point(n.lon, n.lat, { role: "end", kind }));
    };
    const rail = c.rail_major[0] ?? c.rail[0];
    link(rail, "rail", rail?.name.replace(/ Junction$/, " Jn") ?? "");
    if (c.rail[0] && c.rail[0].name !== rail?.name) link(c.rail[0], "rail", c.rail[0].name);
    link(c.airports[0], "air", `${c.airports[0]?.iata ?? c.airports[0]?.icao ?? ""} ${c.airports[0]?.name.replace(/ (International )?Airport$/, "") ?? ""}`);
    for (const n of c.bases) link(n, "base", n.code ?? n.name);
    setData(map, "focus", [
      feature({ type: "Polygon", coordinates: [world, ring.slice().reverse()] }, { role: "mask" }),
      feature({ type: "LineString", coordinates: ring }, { role: "ring" }),
      ...links,
    ]);
  }, [map, s.mode, selBase, summary.data]);

  // Connectivity focus is a temporary view override: saved layer and tilt preferences are never changed.
  useEffect(() => {
    if (!map) return;
    const b = focusSummary.data?.base, nearby = focusSummary.data?.connectivity.bases ?? [];
    if (!focus || !b || b.id !== focus.sourceId) return void setData(map, "connectivity", []);
    const points: Feature[] = [b, ...nearby].map((n) => point(n.lon, n.lat, {
      role: "base", id: n.id, code: n.code, name: n.name.replace(/^Air Force Station /, ""),
      ...("distance_km" in n ? { distance_km: n.distance_km } : {}),
      active: n.id === b.id || n.id === focus.destinationId,
      icon: baseBlock({ color: cssVar(n.id === b.id ? "--accent-strong" : "--base-iaf"), text: cssVar("--text-1"),
        kind: "jet", variant: "f", size: n.id === b.id ? "l" : "m", code: n.code }),
    }));
    for (const n of nearby) {
      const active = n.id === focus.destinationId;
      points.push(feature({ type: "LineString", coordinates: greatCircle([b.lon, b.lat], [n.lon, n.lat]) }, {
        role: "direct", active, opacity: focus.destinationId == null ? 0.85 : active && focus.mode === "direct" ? 1 : 0.22,
        label: `${n.code} · ${n.distance_km} km direct`,
      }));
    }
    if (focus.mode === "road" && road.data?.status === "available" && road.data.source_id === b.id && road.data.destination_id === focus.destinationId) {
      points.push(feature(road.data.geometry, { role: "road" }));
      const n = nearby.find((v) => v.id === focus.destinationId);
      const coords = road.data.geometry.coordinates;
      if (n) {
        points.push(feature({ type: "LineString", coordinates: [[b.lon, b.lat], coords[0]] }, { role: "access" }));
        points.push(feature({ type: "LineString", coordinates: [coords[coords.length - 1], [n.lon, n.lat]] }, { role: "access" }));
      }
    }
    setData(map, "connectivity", points);
  }, [map, focus, focusSummary.data, road.data]);

  const fitted = useRef("");
  useEffect(() => {
    if (!map || !focus) { fitted.current = ""; return; }
    const b = focusSummary.data?.base;
    if (!b || b.id !== focus.sourceId) return;
    const key = `${focus.sourceId}:${focus.fitSeq}`;
    if (fitted.current === key) return;
    const coords: [number, number][] = [[b.lon, b.lat], ...(focusSummary.data?.connectivity.bases ?? []).map((n): [number, number] => [n.lon, n.lat])];
    if (focus.mode === "road" && road.data?.status === "available") coords.push(...road.data.geometry.coordinates);
    const bounds = new maplibregl.LngLatBounds(coords[0], coords[0]);
    for (const p of coords) bounds.extend(p);
    const wide = map.getContainer().clientWidth > 1000;
    map.fitBounds(bounds, { padding: { top: 80, bottom: 65, left: wide ? 370 : 70, right: wide ? 385 : 30 }, maxZoom: 9, duration: 900 });
    fitted.current = key;
  }, [map, focus, focusSummary.data, road.data]);

  // ---------------------------------------------------------------- fly-to requests (search, overview, panel)
  useEffect(() => {
    if (map && s.flyTo) map.flyTo({ center: [s.flyTo.lon, s.flyTo.lat], zoom: s.flyTo.zoom, offset: [PANEL_SHIFT, 0], duration: 1400, essential: true });
  }, [map, s.flyTo]);

  useEffect(() => {
    const b = bases.data?.find((v) => v.id === selBase);
    if (!map || !b) return;
    const zoom = s.mode === "INFRA" ? 8 : Math.max(map.getZoom(), 7);
    map.flyTo({ center: [b.lon, b.lat], zoom, offset: [PANEL_SHIFT, 0], duration: 1200, essential: true });
  }, [map, selBase, bases.data]); // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={el} className="mapcanvas" style={{ visibility: hidden ? "hidden" : "visible" }} aria-label="Map of the region" />;
}
