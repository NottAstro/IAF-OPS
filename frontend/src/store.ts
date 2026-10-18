import { create } from "zustand";
import type { FeedState, LiveTrack, SimClock, SimTrack } from "./api/types";

/** Map views. Each view shows only its own layers on top of the shared ones (bases, borders, names).
 * Live, Infra and Ops show 3D terrain with the saved tilt; Weather stays flat for clouds and wind. */
export type Mode = "LIVE" | "WX" | "INFRA" | "OPS";
export const MODES: { id: Mode; key: string; label: string }[] = [
  { id: "LIVE", key: "Live", label: "Live air traffic" },
  { id: "WX", key: "Wx", label: "Weather" },
  { id: "INFRA", key: "Infra", label: "Infrastructure" },
  { id: "OPS", key: "Ops", label: "Operations (simulated)" },  // Live stays real data only (D20); simulation lives here (D29)
];

export type Selection =
  | { kind: "base"; id: number }
  | { kind: "public-base"; id: number }
  | { kind: "live"; hex: string }
  | { kind: "airport"; id: number }
  | { kind: "tower"; id: number }
  | { kind: "ad"; id: number }
  | { kind: "station"; id: number }
  | { kind: "wx"; lat: number; lon: number }
  | { kind: "mission"; id: number }
  | { kind: "simtrack"; id: string }
  | { kind: "route"; id: number }
  | null;

/** `mode` set → the layer belongs to that view only; unset → shared by every view. */
export const LAYER_GROUPS = ["Operations", "Infrastructure", "View", "Air bases", "Boundaries & names"] as const;
export const LAYERS = {
  highways: { group: "Infrastructure", label: "National highways", on: true, mode: "INFRA" },
  roads: { group: "Infrastructure", label: "Main roads", on: true, mode: "INFRA" },
  rail: { group: "Infrastructure", label: "Railway lines", on: true, mode: "INFRA" },
  stations: { group: "Infrastructure", label: "Railway stations", on: true, mode: "INFRA" },
  "civil-airports": { group: "Infrastructure", label: "Civil airports", on: true, mode: "INFRA" },
  towers: { group: "Infrastructure", label: "Telecom towers", on: false, mode: "INFRA" },
  "ops-sim": { group: "Operations", label: "Simulated IAF sorties", on: true, mode: "OPS" },
  "ops-unknown": { group: "Operations", label: "Simulated unknown tracks", on: true, mode: "OPS" },
  "ops-routes": { group: "Operations", label: "Planned routes", on: true, mode: "OPS" },
  "ops-missions": { group: "Operations", label: "Mission areas, next 24 h", on: true, mode: "OPS" },
  "ops-threat": { group: "Operations", label: "Threat zones (generic)", on: true, mode: "OPS" },
  "ops-airspace": { group: "Operations", label: "Training areas, ranges, restricted", on: false, mode: "OPS" },
  "ops-radar": { group: "Operations", label: "Radar coverage", on: false, mode: "OPS" },
  "ops-ad": { group: "Operations", label: "Air defence coverage", on: false, mode: "OPS" },
  "ops-ad-sites": { group: "Operations", label: "Air defence sites (simulated)", on: true, mode: "OPS" },
  "ops-wx": { group: "Operations", label: "Weather impact, next 6 h", on: true, mode: "OPS" },
  relief: { group: "View", label: "Elevation colours", on: true },
  satellite: { group: "View", label: "Satellite imagery", on: false },
  "iaf-bases": { group: "Air bases", label: "IAF air bases", on: true },
  algs: { group: "Air bases", label: "Advanced landing grounds", on: true },
  "other-mil": { group: "Air bases", label: "Navy, Army & Coast Guard air stations", on: true },
  "foreign-bases": { group: "Air bases", label: "Neighbouring countries' air bases", on: true },
  "india-border": { group: "Boundaries & names", label: "India boundary (official)", on: true },
  "intl-borders": { group: "Boundaries & names", label: "Neighbour boundaries", on: true },
  states: { group: "Boundaries & names", label: "States & provinces", on: true },
  districts: { group: "Boundaries & names", label: "Districts", on: false },
  places: { group: "Boundaries & names", label: "Cities & towns", on: true },
} as const satisfies Record<string, { group: (typeof LAYER_GROUPS)[number]; label: string; on: boolean; mode?: Mode }>;
export type LayerId = keyof typeof LAYERS;
export const layerMode = (id: LayerId): Mode | undefined => (LAYERS[id] as { mode?: Mode }).mode;

/** Live view toggles; ADS-B categories fold into these three. */
export const LIVE_CATS = ["civil", "military", "uav"] as const;
export type LiveCat = (typeof LIVE_CATS)[number];
export const LIVE_GROUP: Record<LiveTrack["category"], LiveCat> = {
  CIVIL: "civil", CARGO: "civil", HELICOPTER: "civil", MILITARY: "military", UAV: "uav", DRONE: "uav",
};

export const WX_LAYERS = ["clouds", "rain", "wind", "metar"] as const;
export type WxLayer = (typeof WX_LAYERS)[number];

/** A mission request being written while the user picks its area on the map (Missions → map → Missions). */
export interface MissionDraft {
  name: string; mission_type: string; priority: string; window_start: string; window_end: string; target: string;
  target_base_id: string; lon: string; lat: string; required_aircraft: string; on_station_min: string; max_risk: string;
  min_quals: string[]; notes: string;
}

interface Toast {
  id: number;
  text: string;
  severity: string;
}

interface State {
  mode: Mode;
  layers: Record<LayerId, boolean>;
  liveCats: Record<LiveCat, boolean>;
  wx: Record<WxLayer, boolean>;
  overlayOpacity: number;
  windModel: "gfs" | "ifs";
  selection: Selection;
  panelTab: string;
  liveTracks: LiveTrack[];
  feeds: Record<string, FeedState>;
  simTracks: SimTrack[];
  simClock: SimClock | null;
  missionDraft: MissionDraft | null;
  picking: "mission" | null;
  toasts: Toast[];
  camera: { lat: number; lon: number; zoom: number; bbox: [number, number, number, number] } | null;
  cursor: { lat: number; lon: number; elev?: number | null } | null;
  exaggeration: number;
  tilt: boolean;
  flyTo: { lat: number; lon: number; zoom: number; seq: number } | null;
  set: (p: Partial<State>) => void;
  toggleLayer: (id: LayerId) => void;
  toggleCat: (c: LiveCat) => void;
  toggleWx: (w: WxLayer) => void;
  toast: (text: string, severity?: string) => void;
  requestFly: (lat: number, lon: number, zoom?: number) => void;
}

/** Saved preferences, restricted to current keys and valid types (old saves may hold retired layers). */
function saved<T extends object>(key: string, fallback: T): T {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(key) ?? "{}");
    const v = parsed != null && typeof parsed === "object" ? parsed as Record<string, unknown> : {};
    return Object.fromEntries(Object.entries(fallback).map(([k, d]) => [k,
      typeof v[k] === typeof d && (typeof d !== "number" || (typeof v[k] === "number" && Number.isFinite(v[k]) && v[k] >= 1 && v[k] <= 3)) ? v[k] : d,
    ])) as T;
  } catch {
    return fallback;
  }
}

function persist(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable: per-viewer convenience only */
  }
}

const defaultLayers = Object.fromEntries(Object.entries(LAYERS).map(([k, v]) => [k, v.on])) as Record<LayerId, boolean>;
const defaultCats = Object.fromEntries(LIVE_CATS.map((c) => [c, true])) as Record<LiveCat, boolean>;

export const useStore = create<State>((set, get) => ({
  mode: "LIVE",
  layers: saved("airops.layers.v3", defaultLayers),
  liveCats: saved("airops.liveCats.v2", defaultCats),
  wx: saved("airops.wx.v2", { clouds: true, rain: true, wind: true, metar: true }),
  overlayOpacity: 0.85,
  windModel: "gfs",
  selection: null,
  panelTab: "Ov",
  liveTracks: [],
  feeds: {},
  simTracks: [],
  simClock: null,
  missionDraft: null,
  picking: null,
  toasts: [],
  camera: null,
  cursor: null,
  ...saved("airops.view.v1", { tilt: true, exaggeration: 1.5 }),
  flyTo: null,
  set: (p) => {
    if (p.tilt !== undefined || p.exaggeration !== undefined) {
      persist("airops.view.v1", { tilt: p.tilt ?? get().tilt, exaggeration: p.exaggeration ?? get().exaggeration });
    }
    set(p);
  },
  toggleLayer: (id) => {
    const layers = { ...get().layers, [id]: !get().layers[id] };
    persist("airops.layers.v3", layers);
    set({ layers });
  },
  toggleCat: (c) => {
    const liveCats = { ...get().liveCats, [c]: !get().liveCats[c] };
    persist("airops.liveCats.v2", liveCats);
    set({ liveCats });
  },
  toggleWx: (w) => {
    const wx = { ...get().wx, [w]: !get().wx[w] };
    persist("airops.wx.v2", wx);
    set({ wx });
  },
  toast: (text, severity = "WARNING") => {
    const id = Date.now() + Math.random();
    set({ toasts: [...get().toasts.slice(-2), { id, text, severity }] });
    if (severity !== "CRITICAL") setTimeout(() => set({ toasts: get().toasts.filter((t) => t.id !== id) }), 7000);
  },
  requestFly: (lat, lon, zoom = 8) => set({ flyTo: { lat, lon, zoom, seq: Date.now() } }),
}));
