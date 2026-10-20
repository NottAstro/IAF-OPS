import { create } from "zustand";
import type { FeedState, LiveTrack, SimClock } from "./api/types";
import type { DemoRun } from "./features/scripts";

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
  | { kind: "radar"; id: number }
  | { kind: "comms"; id: number }
  | { kind: "station"; id: number }
  | { kind: "wx"; lat: number; lon: number }
  | { kind: "plan-mission"; run: string; mission: string; fit?: number }   // D71: a scripted package, focused on the Ops map; a new `fit` re-frames it
  | null;

/** `mode` set → the layer belongs to that view only; unset → shared by every view. `sim` → a simulated layer, listed under
 * the Infra panel's "Defence & comms" with a SIM badge (D75). `fixed` → always drawn in its view, no toggle: the Ops
 * picture itself, explained by the panel's key (D73). */
export const LAYER_GROUPS = ["Operations", "Infrastructure", "View", "Air bases", "Boundaries & names"] as const;
export const LAYERS = {
  highways: { group: "Infrastructure", label: "National highways", on: true, mode: "INFRA" },
  roads: { group: "Infrastructure", label: "Main roads", on: true, mode: "INFRA" },
  rail: { group: "Infrastructure", label: "Railway lines", on: true, mode: "INFRA" },
  stations: { group: "Infrastructure", label: "Railway stations", on: true, mode: "INFRA" },
  "civil-airports": { group: "Infrastructure", label: "Civil airports", on: true, mode: "INFRA" },
  towers: { group: "Infrastructure", label: "Telecom towers", on: false, mode: "INFRA" },
  "ops-missions": { group: "Operations", label: "Mission area", on: true, mode: "OPS", fixed: true },
  "ops-radar-sites": { group: "Infrastructure", label: "Radar sites", on: false, mode: "INFRA", sim: true },      // D63, D75
  "ops-ad-sites": { group: "Infrastructure", label: "Air defence sites", on: false, mode: "INFRA", sim: true },
  "ops-comms": { group: "Infrastructure", label: "Comms nodes", on: false, mode: "INFRA", sim: true },           // D63, D75
  "ops-coverage": { group: "Infrastructure", label: "Show all coverage", on: false, mode: "INFRA", sim: true },  // D63, D75
  "ops-threat": { group: "Operations", label: "Threat zone (generic)", on: true, mode: "OPS", fixed: true },
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
} as const satisfies Record<string, { group: (typeof LAYER_GROUPS)[number]; label: string; on: boolean; mode?: Mode; sim?: true; fixed?: true }>;
export type LayerId = keyof typeof LAYERS;
export const layerMode = (id: LayerId): Mode | undefined => (LAYERS[id] as { mode?: Mode }).mode;
export const layerSim = (id: LayerId): boolean => !!(LAYERS[id] as { sim?: true }).sim;
export const layerFixed = (id: LayerId): boolean => !!(LAYERS[id] as { fixed?: true }).fixed;

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
  simClock: SimClock | null;
  /** Feature counts per Ops layer, published by MapView so the panel can show counts and say when a layer is empty. */
  siteCounts: Partial<Record<LayerId, number>>;
  /** Scripted Planner state per situation (D66): decisions and approval, this browser only. Key: run id or "routine". */
  demo: Record<string, DemoRun>;
  setDemo: (key: string, run: DemoRun | null) => void;
  missionDraft: MissionDraft | null;
  picking: "mission" | null;
  toasts: Toast[];
  camera: { lat: number; lon: number; zoom: number; bbox: [number, number, number, number] } | null;
  cursor: { lat: number; lon: number; elev?: number | null } | null;
  exaggeration: number;
  tilt: boolean;
  connectivityFocus: { sourceId: number; destinationId: number | null; mode: "direct" | "road"; fitSeq: number } | null;
  flyTo: { lat: number; lon: number; zoom: number; seq: number } | null;
  set: (p: Partial<State>) => void;
  toggleLayer: (id: LayerId) => void;
  toggleCat: (c: LiveCat) => void;
  toggleWx: (w: WxLayer) => void;
  toast: (text: string, severity?: string) => void;
  requestFly: (lat: number, lon: number, zoom?: number) => void;
}

/** Saved preferences, restricted to current keys and valid types (old saves may hold retired layers). `open`: keep any
 * key (a record keyed by id, like the demo state). */
function saved<T extends object>(key: string, fallback: T, open = false): T {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(key) ?? "{}");
    const v = parsed != null && typeof parsed === "object" ? parsed as Record<string, unknown> : {};
    if (open) return v as T;
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
  layers: saved("airops.layers.v4", defaultLayers),
  liveCats: saved("airops.liveCats.v2", defaultCats),
  wx: saved("airops.wx.v2", { clouds: true, rain: true, wind: true, metar: true }),
  overlayOpacity: 0.85,
  windModel: "gfs",
  selection: null,
  connectivityFocus: null,
  panelTab: "Ov",
  liveTracks: [],
  feeds: {},
  simClock: null,
  siteCounts: {},
  demo: saved("airops.demo.v1", {} as Record<string, DemoRun>, true),
  setDemo: (key, run) => {
    const demo = { ...get().demo };
    if (run) demo[key] = run; else delete demo[key];
    persist("airops.demo.v1", demo);
    set({ demo });
  },
  missionDraft: null,
  picking: null,
  toasts: [],
  camera: null,
  cursor: null,
  ...saved("airops.view.v1", { tilt: true, exaggeration: 1.5 }),
  flyTo: null,
  set: (p) => {
    const next = { ...get(), ...p };
    if (next.connectivityFocus && (next.mode !== "INFRA" || next.selection?.kind !== "base" || next.selection.id !== next.connectivityFocus.sourceId)) {
      p = { ...p, connectivityFocus: null };
    }
    if (p.tilt !== undefined || p.exaggeration !== undefined) {
      persist("airops.view.v1", { tilt: p.tilt ?? get().tilt, exaggeration: p.exaggeration ?? get().exaggeration });
    }
    set(p);
  },
  toggleLayer: (id) => {
    const layers = { ...get().layers, [id]: !get().layers[id] };
    persist("airops.layers.v4", layers);
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
    set({ toasts: [...get().toasts.slice(-1), { id, text, severity }] });   // two at most, bottom-right; every alert stays on the Alerts page
    setTimeout(() => set({ toasts: get().toasts.filter((t) => t.id !== id) }), severity === "CRITICAL" ? 12000 : 6000);
  },
  requestFly: (lat, lon, zoom = 8) => set({ flyTo: { lat, lon, zoom, seq: Date.now() } }),
}));
