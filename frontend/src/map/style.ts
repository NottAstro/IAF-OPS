// Navy tactical basemap for MapLibre (DESIGN_SYSTEM §8). Flat Web Mercator, colours from tokens.css.
// OpenFreeMap (OpenMapTiles schema) supplies terrain features only: land cover, water, roads, rail, runways.
// Its `boundary`, `place`, `poi` and other label layers are deliberately NOT used (AGENTS.md §9): every boundary
// and name comes from our own GoI-compliant vector tiles (/api/v1/gis/tiles).
import type { ExpressionSpecification, LayerSpecification, SourceSpecification, StyleSpecification } from "maplibre-gl";
import type { LayerId } from "../store";
import { cssVar } from "./colors";
import { airportBlock, placeIcon, stationIcon } from "./symbols";

/** Camera limits: India fills the frame; panning stops short of Central Asia (no Tajikistan / Russia). */
export const REGION_BOUNDS: [[number, number], [number, number]] = [[50, 1], [115, 39.5]];
export const INDIA_BOUNDS: [[number, number], [number, number]] = [[68.1, 6.6], [97.4, 35.7]];

/** Bump whenever the tile SQL (backend/app/routers/gis.py) changes: browsers cache tiles for a day, keyed by URL. */
const TILE_VERSION = 3;
const REG = ["Noto Sans Regular"];
const BOLD = ["Noto Sans Bold"];
const ITAL = ["Noto Sans Italic"];
const x = (v: unknown) => v as ExpressionSpecification;
const zoomLin = (...stops: number[]) => x(["interpolate", ["linear"], ["zoom"], ...stops]);
const isIndia = x(["==", ["get", "country"], "IND"]);

/** Store layer toggles → MapLibre layer ids. `relief` is handled in MapView (always on, stronger in Terrain). */
export const LAYER_IDS: Record<LayerId, string[]> = {
  highways: ["highway-lo-glow", "highway-lo", "highway-glow", "highway", "road-ref"],
  roads: ["road-major", "road-minor"],
  rail: ["rail-lo", "rail-main", "rail-ties"],
  stations: ["stations"],
  "civil-airports": ["airports"],
  towers: ["towers"],
  relief: [],
  satellite: ["sat"],
  "iaf-bases": ["bases-iaf"],
  algs: ["bases-alg"],
  "other-mil": ["bases-mil"],
  "foreign-bases": ["bases-foreign"],
  "india-border": ["india-glow", "india"],
  "intl-borders": ["intl"],
  states: ["adm1", "lbl-state"],
  districts: ["adm2", "lbl-district"],
  places: ["lbl-place"],
};

/** Clickable layers, top-most first. */
export const INTERACTIVE = ["live-air", "bases-iaf", "bases-mil", "bases-foreign", "bases-alg", "metar", "airports", "stations", "towers"];
/** Weather rasters go under the boundaries, so borders and names stay readable through the clouds. */
export const OVERLAY_BEFORE = "adm2";
/** Base-connection spotlight layers (Infrastructure view). */
export const FOCUS_LAYERS = ["focus-mask", "focus-ring", "focus-link", "focus-link-label", "focus-end"];

export function buildStyle(): StyleSpecification {
  const origin = location.origin;
  const bg = cssVar("--bg");
  const halo = cssVar("--bg", 0.85);
  const emptyFc = (): SourceSpecification => ({ type: "geojson", data: { type: "FeatureCollection", features: [] } });
  const linkColor = x(["match", ["get", "kind"], "rail", cssVar("--map-rail-main"), "air", cssVar("--map-label"), cssVar("--accent")]);
  const station = cssVar("--map-station");
  // compact block (glyph cell) far out, full tag with the code from `fullAt`; the name appears under it close in
  const baseSymbol = (id: string, layer: string, overlap: boolean, minzoom: number, fullAt: number): LayerSpecification => ({
    id, type: "symbol", source: "bases", minzoom, filter: ["==", ["get", "layer"], layer],
    layout: {
      "icon-image": x(["step", ["zoom"], ["get", "iconC"], fullAt, ["get", "iconF"]]),
      "icon-size": zoomLin(3.5, 0.85, 6, 1, 10, 1.15), "icon-allow-overlap": overlap,
      "symbol-sort-key": ["get", "rank"], "icon-padding": 2,
      "text-field": ["step", ["zoom"], "", 8.5, ["get", "short"]], "text-font": BOLD,
      "text-size": 10.5, "text-anchor": "top", "text-offset": [0, 1.4], "text-optional": true,
    },
    paint: { "text-color": layer === "iaf" ? cssVar("--accent-strong") : cssVar("--map-label"), "text-halo-color": halo, "text-halo-width": 1.5 },
  });
  const infraLine = (id: string, filter: unknown, minzoom: number, layout: object, paint: object): LayerSpecification =>
    ({ id, type: "line", source: "omt", "source-layer": "transportation", minzoom, filter: x(filter),
       layout: { visibility: "none", "line-cap": "round", "line-join": "round", ...layout }, paint } as LayerSpecification);

  const layers: LayerSpecification[] = [
    { id: "bg", type: "background", paint: { "background-color": cssVar("--map-land") } },
    // elevation tint under everything: subtle in every view, strong in Terrain
    { id: "relief", type: "color-relief", source: "dem",
      paint: {
        "color-relief-opacity": 0.42,
        "color-relief-color": x(["interpolate", ["linear"], ["elevation"],
          0, cssVar("--relief-0"), 300, cssVar("--relief-1"), 1000, cssVar("--relief-2"), 2500, cssVar("--relief-3"),
          4500, cssVar("--relief-4"), 6500, cssVar("--relief-5")]),
      } },
    { id: "lc-ice", type: "fill", source: "omt", "source-layer": "landcover", filter: ["==", ["get", "class"], "ice"],
      paint: { "fill-color": cssVar("--relief-5"), "fill-opacity": 0.22 } },
    { id: "lc-sand", type: "fill", source: "omt", "source-layer": "landcover", filter: ["==", ["get", "class"], "sand"],
      paint: { "fill-color": cssVar("--map-land-2"), "fill-opacity": 0.35 } },
    { id: "lc-wood", type: "fill", source: "omt", "source-layer": "landcover", filter: ["==", ["get", "class"], "wood"],
      paint: { "fill-color": "#0b2030", "fill-opacity": 0.35 } },
    { id: "lu-urban", type: "fill", source: "omt", "source-layer": "landuse", minzoom: 8,
      filter: ["in", ["get", "class"], ["literal", ["residential", "commercial", "industrial"]]],
      paint: { "fill-color": cssVar("--map-road", 0.3) } },
    { id: "water", type: "fill", source: "omt", "source-layer": "water", paint: { "fill-color": cssVar("--map-water") } },
    { id: "waterway", type: "line", source: "omt", "source-layer": "waterway", minzoom: 5, filter: ["==", ["get", "class"], "river"],
      paint: { "line-color": cssVar("--map-water"), "line-width": zoomLin(5, 0.6, 10, 2) } },
    { id: "sat", type: "raster", source: "sat", layout: { visibility: "none" },
      paint: { "raster-brightness-max": 0.75, "raster-saturation": -0.2, "raster-contrast": 0.1 } },
    { id: "hillshade", type: "hillshade", source: "dem",
      paint: {
        "hillshade-method": "igor", "hillshade-exaggeration": 0.55, "hillshade-shadow-color": bg,
        "hillshade-highlight-color": cssVar("--relief-4", 0.55), "hillshade-accent-color": cssVar("--relief-2"),
      } },
    { id: "runway", type: "line", source: "omt", "source-layer": "aeroway", minzoom: 10, filter: ["==", ["get", "class"], "runway"],
      paint: { "line-color": cssVar("--map-runway"), "line-width": zoomLin(10, 2, 14, 14) } },
    // infrastructure view
    infraLine("road-minor", ["in", ["get", "class"], ["literal", ["secondary", "tertiary"]]], 8, {},
      { "line-color": cssVar("--map-road"), "line-width": zoomLin(8, 0.4, 13, 1.8), "line-opacity": 0.85 }),
    infraLine("road-major", ["==", ["get", "class"], "primary"], 5.5, {},
      { "line-color": cssVar("--map-road-major"), "line-width": zoomLin(5.5, 0.5, 9, 1.4, 13, 3) }),
    { id: "highway-lo-glow", type: "line", source: "ours", "source-layer": "hwy_lo", maxzoom: 7, layout: { visibility: "none", "line-join": "round" },
      paint: { "line-color": cssVar("--map-highway"), "line-width": zoomLin(4, 3, 7, 5), "line-blur": 3, "line-opacity": 0.2 } },
    { id: "highway-lo", type: "line", source: "ours", "source-layer": "hwy_lo", maxzoom: 7, layout: { visibility: "none", "line-join": "round" },
      paint: { "line-color": cssVar("--map-highway"), "line-width": zoomLin(4, 0.7, 7, 1.3), "line-opacity": 0.9 } },
    { id: "rail-lo", type: "line", source: "ours", "source-layer": "rail_lo", maxzoom: 8, layout: { visibility: "none", "line-join": "round" },
      paint: { "line-color": cssVar("--map-rail-main"), "line-width": zoomLin(4, 0.7, 8, 1.5), "line-opacity": 0.85 } },
    infraLine("highway-glow", ["in", ["get", "class"], ["literal", ["motorway", "trunk"]]], 7, {},
      { "line-color": cssVar("--map-highway"), "line-width": zoomLin(4, 3, 9, 7, 13, 12), "line-blur": zoomLin(4, 3, 9, 6), "line-opacity": 0.22 }),
    infraLine("highway", ["in", ["get", "class"], ["literal", ["motorway", "trunk"]]], 7, {},
      { "line-color": cssVar("--map-highway"), "line-width": zoomLin(4, 0.7, 8, 1.6, 13, 3.5) }),
    infraLine("rail-main", ["all", ["==", ["get", "class"], "rail"], ["!", ["has", "service"]]], 8, { "line-cap": "butt" },
      { "line-color": cssVar("--map-rail-main"), "line-width": zoomLin(4.5, 0.8, 9, 2, 13, 3.2), "line-opacity": 0.9 }),
    infraLine("rail-ties", ["all", ["==", ["get", "class"], "rail"], ["!", ["has", "service"]]], 9, { "line-cap": "butt" },
      { "line-color": bg, "line-width": zoomLin(7, 0.6, 13, 1.4), "line-dasharray": [2, 2] }),
    { id: "towers", type: "circle", source: "ours", "source-layer": "tower", minzoom: 9, layout: { visibility: "none" },
      paint: { "circle-radius": 2.4, "circle-color": cssVar("--neutral"), "circle-opacity": 0.8 } },
    { id: "stations", type: "symbol", source: "ours", "source-layer": "station", layout: {
        visibility: "none",
        "icon-image": x(["case", ["==", ["get", "rank"], 0], stationIcon(station, 10, true), stationIcon(station, 7, false)]),
        "icon-size": zoomLin(5, 0.75, 9, 1, 13, 1.3), "symbol-sort-key": ["get", "rank"],
        "text-field": x(["step", ["zoom"], "", 7, ["case", ["==", ["get", "rank"], 0], ["get", "name"], ""], 11, ["get", "name"]]),
        "text-font": REG, "text-size": 10, "text-offset": [0, 0.9], "text-anchor": "top", "text-optional": true, "text-max-width": 8,
      },
      paint: { "text-color": cssVar("--map-rail-main"), "text-halo-color": halo, "text-halo-width": 1.2 } },
    // base-connection spotlight (Infrastructure view, a base selected): dims everything outside 60 km
    { id: "focus-mask", type: "fill", source: "focus", filter: ["==", ["get", "role"], "mask"], paint: { "fill-color": bg, "fill-opacity": 0.55 } },
    // boundaries: our GoI-compliant tiles only
    { id: "adm2", type: "line", source: "ours", "source-layer": "admin", minzoom: 6, filter: ["==", ["get", "level"], "ADM2"],
      paint: { "line-color": ["case", isIndia, cssVar("--map-admin2"), cssVar("--map-admin2", 0.5)], "line-width": 0.7, "line-dasharray": [3, 3] } },
    { id: "adm1", type: "line", source: "ours", "source-layer": "admin", filter: ["==", ["get", "level"], "ADM1"],
      paint: { "line-color": ["case", isIndia, cssVar("--map-admin1"), cssVar("--map-admin1", 0.55)], "line-width": zoomLin(3, 0.5, 8, 1.3) } },
    { id: "intl", type: "line", source: "ours", "source-layer": "admin", filter: ["all", ["==", ["get", "level"], "ADM0"], ["!", isIndia]],
      paint: { "line-color": cssVar("--map-intl-border"), "line-width": zoomLin(3, 0.9, 8, 1.6) } },
    { id: "india-glow", type: "line", source: "ours", "source-layer": "admin", filter: ["all", ["==", ["get", "level"], "ADM0"], isIndia],
      layout: { "line-join": "round" },
      paint: { "line-color": cssVar("--map-india-border"), "line-width": zoomLin(3, 5, 8, 10), "line-blur": zoomLin(3, 4, 8, 8), "line-opacity": 0.35 } },
    { id: "india", type: "line", source: "ours", "source-layer": "admin", filter: ["all", ["==", ["get", "level"], "ADM0"], isIndia],
      layout: { "line-join": "round" },
      paint: { "line-color": cssVar("--map-india-border"), "line-width": zoomLin(3, 1.3, 8, 2.2) } },
    { id: "focus-ring", type: "line", source: "focus", filter: ["==", ["get", "role"], "ring"],
      paint: { "line-color": cssVar("--accent"), "line-width": 1.4, "line-dasharray": [3, 2], "line-opacity": 0.8 } },
    { id: "focus-link", type: "line", source: "focus", filter: ["==", ["get", "role"], "link"],
      paint: { "line-color": linkColor, "line-width": 1.8, "line-dasharray": [1.5, 1.5] } },
    // labels (ours, plus ocean / sea names)
    { id: "lbl-water", type: "symbol", source: "omt", "source-layer": "water_name", filter: ["in", ["get", "class"], ["literal", ["ocean", "sea"]]],
      layout: { "text-field": ["coalesce", ["get", "name:en"], ["get", "name_en"], ["get", "name"]], "text-font": ITAL, "text-size": 12, "text-letter-spacing": 0.2, "text-max-width": 6 },
      paint: { "text-color": cssVar("--info", 0.45) } },
    { id: "road-ref", type: "symbol", source: "ours", "source-layer": "hwy_lo", minzoom: 6, filter: ["has", "ref"], layout: {
        visibility: "none", "symbol-placement": "line", "symbol-spacing": 420, "text-field": x(["get", "ref"]),
        "text-font": BOLD, "text-size": 9.5, "text-letter-spacing": 0.05, "text-rotation-alignment": "viewport", "text-padding": 6,
      },
      paint: { "text-color": cssVar("--bg"), "text-halo-color": cssVar("--map-highway"), "text-halo-width": 2.4 } },
    { id: "lbl-district", type: "symbol", source: "ours", "source-layer": "admin_label", minzoom: 6.5, filter: ["==", ["get", "level"], "ADM2"],
      layout: { "text-field": ["get", "name"], "text-font": REG, "text-size": 10, "symbol-sort-key": ["-", 0, ["get", "area_km2"]], "text-max-width": 7 },
      paint: { "text-color": cssVar("--text-3"), "text-halo-color": halo, "text-halo-width": 1 } },
    { id: "lbl-state", type: "symbol", source: "ours", "source-layer": "admin_label", minzoom: 4, maxzoom: 9, filter: ["==", ["get", "level"], "ADM1"],
      layout: {
        "text-field": ["upcase", ["get", "name"]], "text-font": BOLD, "text-size": zoomLin(4, 9, 7, 11), "text-letter-spacing": 0.14,
        "symbol-sort-key": ["-", 0, ["get", "area_km2"]], "text-max-width": 8,
      },
      paint: { "text-color": cssVar("--map-label-dim"), "text-halo-color": halo, "text-halo-width": 1 } },
    { id: "lbl-country", type: "symbol", source: "ours", "source-layer": "admin_label", maxzoom: 7, filter: ["==", ["get", "level"], "ADM0"],
      layout: {
        "text-field": ["upcase", ["get", "name"]], "text-font": BOLD, "text-size": zoomLin(3, 11, 6, 15), "text-letter-spacing": 0.3,
        "symbol-sort-key": ["-", 0, ["get", "area_km2"]], "text-max-width": 8,
      },
      paint: { "text-color": cssVar("--map-label-dim", 0.8), "text-halo-color": halo, "text-halo-width": 1 } },
    { id: "lbl-place", type: "symbol", source: "ours", "source-layer": "place", layout: {
        "icon-image": x(["case", ["in", ["get", "kind"], ["literal", ["PPLC", "PPLA"]]],
          placeIcon(cssVar("--map-label"), 8, true), placeIcon(cssVar("--map-label"), 5, false)]),
        "text-field": ["get", "name"],
        "text-font": x(["step", ["get", "pop"], ["literal", REG], 1000000, ["literal", BOLD]]),
        "text-size": x(["step", ["get", "pop"], 10.5, 100000, 11.5, 1000000, 12.5]),
        "text-variable-anchor": ["left", "right", "top", "bottom"], "text-radial-offset": 0.55, "text-justify": "auto",
        "symbol-sort-key": ["-", 0, ["get", "pop"]], "text-max-width": 8, "text-padding": 3,
      },
      paint: { "text-color": cssVar("--map-label"), "text-halo-color": halo, "text-halo-width": 1.3 } },
    // airports sit above city names so a city label never hides its airport
    { id: "airports", type: "symbol", source: "ours", "source-layer": "airport", layout: {
        visibility: "none",
        // plain tile far out; IATA tag for large airports from z6, for medium ones from z8
        "icon-image": x(["step", ["zoom"], airportBlock(), 6,
          ["match", ["get", "type"], "large_airport", ["concat", "ap|", ["coalesce", ["get", "iata"], ["get", "icao"], ""]], airportBlock()], 8,
          ["match", ["get", "type"], ["large_airport", "medium_airport"], ["concat", "ap|", ["coalesce", ["get", "iata"], ["get", "icao"], ["get", "ident"]]], airportBlock()]]),
        "icon-size": x(["interpolate", ["linear"], ["zoom"], 4, ["match", ["get", "type"], "large_airport", 0.95, "medium_airport", 0.8, 0.65],
          10, ["match", ["get", "type"], "large_airport", 1.15, "medium_airport", 1.05, 0.85]]),
        "symbol-sort-key": x(["match", ["get", "type"], "large_airport", 0, "medium_airport", 1, 2]), "icon-padding": 2,
        "text-field": x(["step", ["zoom"], "", 9.5, ["match", ["get", "type"], ["large_airport", "medium_airport"], ["get", "name"], ""]]),
        "text-font": REG, "text-size": 10, "text-offset": [0, 1.1], "text-anchor": "top", "text-optional": true, "text-max-width": 9,
      },
      paint: { "text-color": cssVar("--map-label"), "text-halo-color": halo, "text-halo-width": 1.2 } },
    { id: "focus-link-label", type: "symbol", source: "focus", filter: ["==", ["get", "role"], "link"], layout: {
        "symbol-placement": "line-center", "text-field": ["get", "label"], "text-font": BOLD, "text-size": 11,
        "text-allow-overlap": true, "text-offset": [0, -0.8], "text-max-angle": 60,
      },
      paint: { "text-color": linkColor, "text-halo-color": cssVar("--bg", 0.95), "text-halo-width": 2 } },
    { id: "focus-end", type: "circle", source: "focus", filter: ["==", ["get", "role"], "end"],
      paint: { "circle-radius": 9, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": linkColor, "circle-stroke-width": 1.8 } },
    { id: "metar", type: "circle", source: "metar", layout: { visibility: "none" },
      paint: {
        "circle-radius": zoomLin(3.5, 3.5, 8, 7), "circle-color": ["get", "color"], "circle-opacity": 0.95,
        "circle-stroke-color": bg, "circle-stroke-width": 1.5,
      } },
    { id: "metar-label", type: "symbol", source: "metar", minzoom: 6, layout: {
        visibility: "none", "text-field": ["concat", ["get", "icao"], " ", ["get", "cat"]], "text-font": BOLD, "text-size": 9.5,
        "text-offset": [0, 1.1], "text-anchor": "top", "text-optional": true,
      },
      paint: { "text-color": ["get", "color"], "text-halo-color": halo, "text-halo-width": 1.2 } },
    // bases: badges carry their own serviceability gauge, alert dot and QRA chip; IAF on top, never hidden
    baseSymbol("bases-alg", "alg", false, 5.5, 8),
    baseSymbol("bases-foreign", "foreign", false, 3.5, 6.5),
    baseSymbol("bases-mil", "mil", false, 4.5, 6.5),
    baseSymbol("bases-iaf", "iaf", true, 0, 5.5),
    // live air picture
    { id: "live-air", type: "symbol", source: "live",
      layout: {
        "icon-image": ["get", "icon"], "icon-rotate": ["get", "rot"], "icon-rotation-alignment": "map",
        "icon-size": zoomLin(3, 0.62, 6, 0.85, 9, 1.15), "icon-allow-overlap": true, "icon-ignore-placement": true,
      },
      paint: { "icon-opacity": ["get", "op"] } },
    { id: "live-label", type: "symbol", source: "live", minzoom: 7.5,
      layout: { "text-field": ["get", "label"], "text-font": REG, "text-size": 9.5, "text-offset": [0, 1.2], "text-anchor": "top", "text-optional": true },
      paint: { "text-color": cssVar("--text-2"), "text-halo-color": halo, "text-halo-width": 1 } },
  ];

  const terrarium = ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"];
  return {
    version: 8,
    glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
    sky: {
      "sky-color": bg, "horizon-color": cssVar("--relief-2"), "fog-color": cssVar("--surface-2"),
      "sky-horizon-blend": 0.7, "horizon-fog-blend": 0.6, "fog-ground-blend": 0.35, "atmosphere-blend": 0,
    },
    sources: {
      omt: { type: "vector", url: "https://tiles.openfreemap.org/planet" },
      ours: {
        type: "vector", tiles: [`${origin}/api/v1/gis/tiles/{z}/{x}/{y}.pbf?v=${TILE_VERSION}`], minzoom: 2, maxzoom: 12,
        attribution: "Boundaries: Survey of India via DataMeet, Natural Earth, geoBoundaries · Places: GeoNames · Airports: OurAirports · Stations: © OpenStreetMap",
      },
      dem: { type: "raster-dem", tiles: terrarium, tileSize: 256, maxzoom: 12, encoding: "terrarium", attribution: "Terrain: Mapzen / AWS Terrain Tiles" },
      dem3d: { type: "raster-dem", tiles: terrarium, tileSize: 256, maxzoom: 13, encoding: "terrarium" },
      sat: {
        type: "raster", tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
        tileSize: 256, maxzoom: 18, attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
      },
      bases: emptyFc(),
      live: emptyFc(),
      metar: emptyFc(),
      focus: emptyFc(),
    },
    layers,
  };
}
