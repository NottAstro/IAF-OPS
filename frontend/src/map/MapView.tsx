// The one MapLibre map (FR-MAP-01..13). Flat Web Mercator framed on India; features talk to it via the store
// and the exported camera helpers below, never by importing maplibre-gl themselves (AGENTS.md §5).
import { useQuery } from "@tanstack/react-query";
import maplibregl, { type GeoJSONSource, type Map as MlMap, type MapGeoJSONFeature } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature, Geometry, Point } from "geojson";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { Base, BaseStatus, LiveTrack } from "../api/types";
import { LIVE_GROUP, type LayerId, type Selection, layerMode, useStore } from "../store";
import { FLIGHT_CAT_TOKEN, cssVar } from "./colors";
import { FOCUS_LAYERS, INDIA_BOUNDS, INTERACTIVE, LAYER_IDS, OVERLAY_BEFORE, REGION_BOUNDS, buildStyle } from "./style";
import { type BlockOpts, baseBlock, glyphIcon, iconImage } from "./symbols";
import { useWind } from "./wind";

interface Metar { icao: string; lat: number; lon: number; flight_category: string }
interface Near { name: string; code?: string; icao?: string; iata?: string; lat: number; lon: number; distance_km: number | string }
interface Connectivity { rail: Near[]; rail_major: Near[]; airports: Near[]; bases: Near[] }

let current: MlMap | null = null;
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
      if (!f) return void tip.remove();
      const [title, sub] = hoverText(f);
      tipEl.innerHTML = "";
      tipEl.append(Object.assign(document.createElement("b"), { textContent: title }));
      if (sub) tipEl.append(Object.assign(document.createElement("div"), { textContent: sub }));
      tip.setLngLat(e.lngLat).setDOMContent(tipEl).addTo(m);
    });
    m.on("mouseout", () => tip.remove());
    m.on("click", (e) => {
      const st = useStore.getState();
      const f = m.queryRenderedFeatures(e.point, { layers: live() })[0];
      const sel = f ? toSelection(f) : null;
      if (sel) return st.set({ selection: sel, panelTab: sel.kind === "base" && st.mode === "INFRA" ? "Bw" : "Ov" });
      const { lat, lng: lon } = e.lngLat;
      st.set({ selection: st.mode === "WX" ? { kind: "wx", lat, lon } : null });
    });
    return () => {
      current = null;
      tip.remove();
      m.remove();
      setMap(null);
    };
  }, []);

  // ---------------------------------------------------------------- data
  const bases = useQuery({ queryKey: ["bases"], queryFn: () => api<Base[]>("/bases"), staleTime: Infinity });
  const status = useQuery({ queryKey: ["base-status"], queryFn: () => api<BaseStatus[]>("/bases/status"), refetchInterval: 30000 });
  const box = s.camera?.bbox.map((v) => v.toFixed(1)).join(",") ?? "";
  const live = useQuery({
    queryKey: ["live", box],
    queryFn: () => api<{ tracks: LiveTrack[]; status: Record<string, never> }>(`/live/aircraft?bbox=${box}`),
    refetchInterval: 10000, enabled: s.mode === "LIVE" && !!box, placeholderData: (p) => p,
  });
  const metars = useQuery({
    queryKey: ["wx", "metars"], queryFn: () => api<{ stations: Metar[] }>("/wx/metars"), refetchInterval: 300000,
    enabled: s.mode === "WX" && s.wx.metar,
  });
  const selBase = s.selection?.kind === "base" ? s.selection.id : null;
  const summary = useQuery({
    queryKey: ["summary", selBase], queryFn: () => api<{ base: { lat: number; lon: number }; connectivity: Connectivity }>(`/bases/${selBase}/summary`),
    enabled: s.mode === "INFRA" && selBase != null,
  });
  useEffect(() => {
    if (live.data?.status) s.set({ feeds: { ...useStore.getState().feeds, ...live.data.status }, liveTracks: live.data.tracks });
  }, [live.data]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------- what each view shows
  useEffect(() => {
    if (!map) return;
    const vis = (id: string, on: boolean) => map.getLayer(id) && map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    for (const [key, ids] of Object.entries(LAYER_IDS)) {
      const k = key as LayerId;
      const only = layerMode(k);
      for (const id of ids) vis(id, s.layers[k] && (!only || only === s.mode));
    }
    vis("live-air", s.mode === "LIVE");
    vis("live-label", s.mode === "LIVE");
    vis("metar", s.mode === "WX" && s.wx.metar);
    vis("metar-label", s.mode === "WX" && s.wx.metar);
    for (const id of FOCUS_LAYERS) vis(id, s.mode === "INFRA");
    map.setPaintProperty("relief", "color-relief-opacity", s.layers.relief ? (s.mode === "WX" ? 0.35 : 0.8) : 0);
  }, [map, s.layers, s.mode, s.wx.metar]);

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
    if (s.mode !== "LIVE") return void setData(map, "live", []);
    const fetched = live.dataUpdatedAt || Date.now();
    const colors = { civil: cssVar("--caution"), military: cssVar("--accent"), uav: cssVar("--warning") };
    const crit = cssVar("--critical");
    const tracks = (live.data?.tracks ?? []).filter((t) => !t.on_ground && LIVE_GROUP[t.category] && s.liveCats[LIVE_GROUP[t.category]]);
    const draw = () => {
      const dt = (Date.now() - fetched) / 1000;
      setData(map, "live", tracks.map((t) => {
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
      }));
    };
    draw();
    const timer = setInterval(draw, 1000);
    return () => clearInterval(timer);
  }, [map, live.data, live.dataUpdatedAt, s.liveCats, s.mode]);

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
    if (s.wx.rain)
      add("wx-rain", `${location.origin}/api/v1/wx/owm/precipitation_new/{z}/{x}/{y}.png`, 256, 9, "Rain: © OpenWeatherMap");
    return () => {
      if (current !== map) return;
      for (const id of ids) {
        map.removeLayer(id);
        map.removeSource(id);
      }
    };
  }, [map, s.mode, s.wx.clouds, s.wx.rain]);
  useEffect(() => {
    for (const id of ["wx-clouds", "wx-rain"]) if (map?.getLayer(id)) map.setPaintProperty(id, "raster-opacity", s.overlayOpacity);
  }, [map, s.overlayOpacity]);

  useWind(map, s.mode === "WX" && s.wx.wind, s.windModel);

  // ---------------------------------------------------------------- 3D terrain everywhere except Weather, which is laid flat
  const wasFlat = useRef(true);  // true at start, so the map tilts into 3D once it has loaded
  const opened = useRef(false);
  useEffect(() => {
    if (!map) return;
    const flat = s.mode === "WX";
    map.setTerrain(flat ? null : { source: "dem3d", exaggeration: s.exaggeration });
    map.setPaintProperty("hillshade", "hillshade-exaggeration", flat ? 0.55 : 0.8);
    if (flat) {
      map.dragRotate.disable();
      map.touchPitch.disable();
      if (map.getPitch() || map.getBearing()) map.easeTo({ pitch: 0, bearing: 0, duration: 700 });
    } else {
      map.dragRotate.enable();
      map.touchPitch.enable();
      if (wasFlat.current && map.getPitch() < 10) {
        // on opening, tilting shrinks the far side, so zoom in a little to keep India filling the frame
        map.easeTo(opened.current ? { pitch: TILT, duration: 900 } : { pitch: TILT, zoom: map.getZoom() + 0.35, offset: [0, -40], duration: 1200 });
        opened.current = true;
      }
    }
    wasFlat.current = flat;
  }, [map, s.mode, s.exaggeration]);

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

/** Tilt toggle for the 3D terrain: oblique ↔ straight down (no effect in the flat Weather view). */
export function toggleTilt() {
  if (!current || !current.getTerrain()) return;
  current.easeTo({ pitch: current.getPitch() > 20 ? 0 : TILT, duration: 900 });
}
