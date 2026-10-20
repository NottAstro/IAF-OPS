// Map icons drawn on canvas, on demand (DESIGN_SYSTEM §6). Each image id encodes everything needed to draw it,
// so the map's `styleimagemissing` event can build any icon lazily and identical icons are shared.
import { cssVar } from "./colors";

const ratio = () => Math.max(2, window.devicePixelRatio || 1); // oversample: icons scale up with zoom
const FONT = (px: number) => `700 ${px}px B612, sans-serif`;

export interface BlockOpts {
  /** owner colour: fills the glyph cell and draws the border */ color: string;
  /** code text colour on the dark part */ text: string;
  kind: "jet" | "runway";
  /** "c" compact (glyph cell only) or "f" full (cell + code + QRA chip) */ variant: "c" | "f";
  size: "l" | "m" | "s";
  code?: string; pct?: number | null; pctColor?: string; alert?: string; qra?: "met" | "short" | "";
}
/** Air base tag: owner-coloured glyph cell, dark code panel, serviceability bar underneath, alert dot, QRA chip. */
export const baseBlock = (o: BlockOpts) =>
  `bb|${o.color}|${o.text}|${o.kind}|${o.variant}|${o.size}|${o.code ?? ""}|${o.pct ?? ""}|${o.pctColor ?? ""}|${o.alert ?? ""}|${o.qra ?? ""}`;
/** Civil airport tag: light block with a dark airliner, plus the IATA / ICAO code when `code` is given. */
export const airportBlock = (code = "") => `ap|${code}`;
/** Railway station: small gold square; major junctions get a dark track bar. */
export const stationIcon = (color: string, size: number, major: boolean) => `rs|${color}|${size}|${major ? 1 : 0}`;
/** A mission's own symbol (D82): a dark disc ringed in the mission's state colour, with a glyph for what it does. */
export const missionIcon = (kind: string, color: string) => `mi|${kind}|${color}`;
/** Diagonal hatch, used as a fill pattern for high-risk threat bands (D78). */
export const hatchPattern = (color: string) => `hatch|${color}`;
/** Settlement dot; capitals get a ring. */
export const placeIcon = (color: string, size: number, capital: boolean) => `pd|${color}|${size}|${capital ? 1 : 0}`;
/** Top-down aircraft glyph, drawn pointing north (rotated on the map). */
export const glyphIcon = (cls: string, color: string, size: number) => `gl|${cls}|${color}|${size}`;
export const towerIcon = () => "site|tower";
/** Simulated sites (Ops only, D63): violet shapes, shield = air defence, round = radar, diamond = comms node. */
export const siteIcon = (kind: "ad" | "radar" | "comms") => `site|${kind}`;
/** Simulated site icons carry their SIM tag under the shape, so the marker and its SIM label collide as one box and
 * the label is never dropped (DESIGN_SYSTEM §9). Layers shift the image down by this much to centre the shape. */
export const SITE_ICON_OFFSET = 4.5;

const mast = (g: CanvasRenderingContext2D, s: number) => {
  g.moveTo(-4 * s, 7 * s); g.lineTo(0, -5 * s); g.lineTo(4 * s, 7 * s);
  g.moveTo(-2.5 * s, 3 * s); g.lineTo(2.5 * s, 3 * s);
  g.moveTo(-5 * s, -5 * s); g.quadraticCurveTo(-8 * s, -2 * s, -5 * s, 0);
  g.moveTo(5 * s, -5 * s); g.quadraticCurveTo(8 * s, -2 * s, 5 * s, 0);
};

/** Site glyphs stay distinct from base tags and aircraft: the real telecom tower is a square tile, simulated sites are
 * violet shapes with a SIM tag. */
function drawSite(kind: string) {
  const sim = kind !== "tower";
  const [c, g] = sim ? canvasRect(24, 33, 0) : canvas(24);
  if (sim) g.translate(12, 12);
  const color = cssVar(sim ? "--sim" : "--map-tower");
  g.strokeStyle = color;
  g.fillStyle = cssVar("--bg");
  g.lineWidth = 1.4;
  g.lineJoin = "round";
  g.lineCap = "round";
  g.beginPath();
  if (kind === "ad") {
    g.moveTo(-8, -9); g.lineTo(8, -9); g.lineTo(8, 1);
    g.quadraticCurveTo(8, 6, 0, 10); g.quadraticCurveTo(-8, 6, -8, 1); g.closePath();
  } else if (kind === "radar") g.arc(0, 0, 9.5, 0, Math.PI * 2);
  else if (kind === "comms") { g.moveTo(0, -10.5); g.lineTo(10.5, 0); g.lineTo(0, 10.5); g.lineTo(-10.5, 0); g.closePath(); }
  else g.roundRect(-10, -10, 20, 20, 4);
  g.fill(); g.stroke();
  g.beginPath();
  if (kind === "ad") {
    g.moveTo(-4.5, 1); g.lineTo(0, -4); g.lineTo(4.5, 1);
    g.moveTo(0, -4); g.lineTo(0, 5);
  } else if (kind === "radar") {   // scope: sweep line and two range arcs
    g.moveTo(-1, 1); g.lineTo(5, -5);
    g.moveTo(-1, -2.5); g.arc(-1, 1, 3.5, -Math.PI / 2, 0);
    g.moveTo(-1, -5); g.arc(-1, 1, 6, -Math.PI / 2, 0);
  } else if (kind === "comms") mast(g, 0.7);
  else {
    mast(g, 1);
    g.moveTo(-3.5, -3.5); g.quadraticCurveTo(-5, -2, -3.5, -0.5);
    g.moveTo(3.5, -3.5); g.quadraticCurveTo(5, -2, 3.5, -0.5);
  }
  g.stroke();
  if (sim) {
    g.fillStyle = color;
    g.beginPath(); g.roundRect(-8.5, 13, 17, 8, 2); g.fill();
    g.fillStyle = cssVar("--bg");
    g.font = FONT(6.5);
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText("SIM", 0, 17.3);
  }
  return c;
}

/** Mission symbols on a 26 px disc: parachute (rescue), cross (casualty evacuation), racetrack (combat air patrol), eye
 * (surveillance), radar arcs (early warning), crosshair (strike), T (training), crate (airlift), crate under a canopy
 * (supply drop), waves (flood relief). */
function drawMission(kind: string, color: string) {
  const [c, g] = canvas(28);
  g.fillStyle = cssVar("--bg");
  g.strokeStyle = color;
  g.lineWidth = 1.8;
  g.beginPath(); g.arc(0, 0, 12, 0, Math.PI * 2); g.fill(); g.stroke();
  g.fillStyle = color;
  g.lineWidth = 1.6;
  g.lineCap = "round";
  g.lineJoin = "round";
  const canopy = (y: number, r: number) => { g.beginPath(); g.arc(0, y, r, Math.PI, 0); g.closePath(); g.fill(); };
  const lines = (pts: [number, number, number, number][]) => { g.beginPath(); for (const [a, b, x, y] of pts) { g.moveTo(a, b); g.lineTo(x, y); } g.stroke(); };
  if (kind === "rescue") {
    canopy(-2.5, 6.5);
    lines([[-6.5, -2.5, 0, 4], [6.5, -2.5, 0, 4], [0, -2.5, 0, 4]]);
    g.beginPath(); g.arc(0, 6, 2, 0, Math.PI * 2); g.fill();
  } else if (kind === "casevac") {
    g.fillRect(-2, -7, 4, 14); g.fillRect(-7, -2, 14, 4);
  } else if (kind === "cap") {
    g.beginPath(); g.roundRect(-7.5, -4, 15, 8, 4); g.stroke();
    g.beginPath(); g.moveTo(3.5, -6.5); g.lineTo(6.5, -4); g.lineTo(3.5, -1.5); g.stroke();
  } else if (kind === "isr") {
    g.beginPath(); g.moveTo(-8, 0); g.quadraticCurveTo(0, -8, 8, 0); g.quadraticCurveTo(0, 8, -8, 0); g.stroke();
    g.beginPath(); g.arc(0, 0, 2.6, 0, Math.PI * 2); g.fill();
  } else if (kind === "aew") {
    g.beginPath(); g.arc(-4, 4, 2, 0, Math.PI * 2); g.fill();
    for (const r of [6, 10]) { g.beginPath(); g.arc(-4, 4, r, -Math.PI / 2, 0); g.stroke(); }
  } else if (kind === "strike") {
    g.beginPath(); g.arc(0, 0, 5, 0, Math.PI * 2); g.stroke();
    lines([[0, -8.5, 0, -3], [0, 3, 0, 8.5], [-8.5, 0, -3, 0], [3, 0, 8.5, 0]]);
  } else if (kind === "training") {
    g.fillRect(-6.5, -6.5, 13, 3.2); g.fillRect(-1.6, -6.5, 3.2, 13);
  } else if (kind === "airlift") {
    g.beginPath(); g.rect(-6, -5, 12, 10); g.stroke();
    lines([[-6, -1.5, 6, -1.5], [0, -5, 0, -1.5]]);
  } else if (kind === "supply") {
    canopy(-3.5, 5.5);
    lines([[-5.5, -3.5, -2.5, 2], [5.5, -3.5, 2.5, 2]]);
    g.fillRect(-3.5, 2, 7, 5.5);
  } else if (kind === "relief") {
    for (const y of [-3.5, 0.5, 4.5]) { g.beginPath(); g.moveTo(-7, y); g.quadraticCurveTo(-3.5, y - 3, 0, y); g.quadraticCurveTo(3.5, y + 3, 7, y); g.stroke(); }
  }
  return c;
}

/** A 10 px tile of 45° lines that joins seamlessly when repeated. */
function drawHatch(color: string) {
  const [c, g] = canvasRect(10, 10, 0);
  g.strokeStyle = color;
  g.lineWidth = 1.2;
  g.beginPath();
  for (const o of [-10, 0, 10]) { g.moveTo(o, 10); g.lineTo(o + 10, 0); }
  g.stroke();
  return c;
}

/** Square canvas with the origin at its centre. */
function canvas(size: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const [c, g] = canvasRect(size, size, 0);
  g.translate(size / 2, size / 2);
  return [c, g];
}

/** w × h canvas plus `pad` on every side (for glow / corner marks), origin at the content's top-left. */
function canvasRect(w: number, h: number, pad: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const r = ratio();
  const c = document.createElement("canvas");
  c.width = Math.ceil((w + 2 * pad) * r);
  c.height = Math.ceil((h + 2 * pad) * r);
  const g = c.getContext("2d")!;
  g.scale(r, r);
  g.translate(pad, pad);
  return [c, g];
}

const measure = (text: string, font: string) => {
  const g = document.createElement("canvas").getContext("2d")!;
  g.font = font;
  return g.measureText(text).width;
};

/** Aircraft silhouette in a 24-unit box centred on 0,0, pointing up. */
function planePath(g: CanvasRenderingContext2D, cls: string) {
  g.beginPath();
  if (cls === "vehicle") {   // ground vehicle seen from above, nose up, with the windscreen cut out (D82)
    g.roundRect(-5.5, -10.5, 11, 21, 3);
    g.moveTo(-4, -6.5); g.lineTo(-4, -3.2); g.lineTo(4, -3.2); g.lineTo(4, -6.5); g.closePath();
  } else if (cls === "helicopter") {
    g.arc(0, 0, 4.5, 0, Math.PI * 2);
    g.moveTo(-11, -1); g.lineTo(11, -1); g.lineTo(11, 1); g.lineTo(-11, 1); g.closePath();
    g.moveTo(-1, 3); g.lineTo(1, 3); g.lineTo(1, 11); g.lineTo(-1, 11); g.closePath();
  } else if (cls === "uav" || cls === "drone") {
    g.moveTo(0, -8); g.lineTo(10, 4); g.lineTo(3, 2); g.lineTo(0, 9); g.lineTo(-3, 2); g.lineTo(-10, 4); g.closePath();
  } else if (cls === "fighter") {
    g.moveTo(0, -11.5); g.lineTo(1.5, -6); g.lineTo(2, -1.5); g.lineTo(10, 5); g.lineTo(10, 7); g.lineTo(2.2, 5.2);
    g.lineTo(2.6, 8.5); g.lineTo(5.5, 10.6); g.lineTo(5.5, 11.6); g.lineTo(0, 10.4); g.lineTo(-5.5, 11.6); g.lineTo(-5.5, 10.6);
    g.lineTo(-2.6, 8.5); g.lineTo(-2.2, 5.2); g.lineTo(-10, 7); g.lineTo(-10, 5); g.lineTo(-2, -1.5); g.lineTo(-1.5, -6); g.closePath();
  } else {
    const w = cls === "widebody" || cls === "quadjet" ? 11.5 : cls === "light" || cls === "glider" ? 10 : 10.5;
    g.moveTo(0, -11.5); g.quadraticCurveTo(1.7, -10.5, 1.7, -7); g.lineTo(1.7, -3); g.lineTo(w, 2); g.lineTo(w, 3.6);
    g.lineTo(1.7, 1.2); g.lineTo(1.3, 7.2); g.lineTo(4.4, 9.6); g.lineTo(4.4, 11); g.lineTo(0, 10); g.lineTo(-4.4, 11);
    g.lineTo(-4.4, 9.6); g.lineTo(-1.3, 7.2); g.lineTo(-1.7, 1.2); g.lineTo(-w, 3.6); g.lineTo(-w, 2); g.lineTo(-1.7, -3);
    g.lineTo(-1.7, -7); g.quadraticCurveTo(-1.7, -10.5, 0, -11.5); g.closePath();
  }
}

function drawGlyphIn(g: CanvasRenderingContext2D, kind: string, cx: number, cy: number, s: number, color: string, bg: string) {
  g.save();
  g.translate(cx, cy);
  g.fillStyle = color;
  if (kind === "runway") {
    g.rotate(-Math.PI / 4);
    const L = s * 0.95, W = s * 0.3;
    g.fillRect(-W / 2, -L / 2, W, L);
    g.fillStyle = bg;
    for (let y = -L / 2 + L * 0.15; y < L / 2 - L * 0.1; y += L * 0.24) g.fillRect(-0.45, y, 0.9, L * 0.12);
  } else {
    g.scale(s / 24, s / 24);
    planePath(g, kind === "jet" ? "fighter" : "airliner");
    g.fill();
  }
  g.restore();
}

function drawBlock(color: string, text: string, kind: string, variant: string, size: string, code: string,
  pct: string, pctColor: string, alert: string, qra: string) {
  const bg = cssVar("--bg");
  const h = size === "l" ? 18 : size === "m" ? 15 : 12;
  const font = FONT(size === "l" ? 10.5 : 9.5);
  const full = variant === "f" && code;
  const textW = full ? Math.ceil(measure(code, font)) + 9 : 0;
  const qW = full && qra ? 12 : 0;
  const w = h + textW + qW;
  const bar = pct !== "" ? 4 : 0;
  const pad = 4;
  const [c, g] = canvasRect(w, h + bar, pad);
  // block with a soft owner-coloured glow
  g.shadowColor = color;
  g.shadowBlur = 6;
  g.fillStyle = bg;
  g.beginPath(); g.roundRect(0, 0, w, h, 3); g.fill();
  g.shadowBlur = 0;
  // glyph cell
  g.fillStyle = color;
  g.beginPath(); g.roundRect(0, 0, h, h, full ? [3, 0, 0, 3] : 3); g.fill();
  drawGlyphIn(g, kind, h / 2, h / 2, h * 0.8, bg, color);
  if (full) {
    const grad = g.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, cssVar("--surface-3"));
    grad.addColorStop(1, cssVar("--surface-1"));
    g.fillStyle = grad;
    g.fillRect(h, 0, textW, h);
    g.fillStyle = text;
    g.font = font;
    g.textBaseline = "middle";
    g.fillText(code, h + 4.5, h / 2 + 0.5);
    if (qW) {
      g.fillStyle = qra === "met" ? cssVar("--accent") : cssVar("--critical");
      g.beginPath(); g.roundRect(h + textW, 0, qW, h, [0, 3, 3, 0]); g.fill();
      g.fillStyle = qra === "met" ? cssVar("--accent-ink") : "#ffffff";
      g.font = FONT(8.5);
      g.textAlign = "center";
      g.fillText("Q", h + textW + qW / 2, h / 2 + 0.5);
      g.textAlign = "left";
    }
  }
  // border
  g.strokeStyle = color;
  g.lineWidth = 1.2;
  g.beginPath(); g.roundRect(0.6, 0.6, w - 1.2, h - 1.2, 2.6); g.stroke();
  // serviceability bar under the block
  if (bar) {
    g.fillStyle = "rgba(220, 235, 255, 0.22)";
    g.fillRect(0, h + 1.5, w, 2.5);
    g.fillStyle = pctColor;
    g.fillRect(0, h + 1.5, (w * Math.max(4, Number(pct))) / 100, 2.5);
  }
  if (alert) {  // corner status dot
    g.fillStyle = alert;
    g.strokeStyle = bg;
    g.lineWidth = 1.5;
    g.beginPath(); g.arc(w - 1, 1, 3.3, 0, Math.PI * 2); g.fill(); g.stroke();
  }
  return c;
}

function drawAirport(code: string) {
  const h = 14;
  const font = FONT(9.5);
  const textW = code ? Math.ceil(measure(code, font)) + 7 : 0;
  const w = h + textW;
  const [c, g] = canvasRect(w, h, 3);
  const ink = "#0b2545";
  g.shadowColor = "rgba(0, 0, 0, 0.55)";
  g.shadowBlur = 3;
  g.fillStyle = "#e3ecf8";
  g.beginPath(); g.roundRect(0, 0, w, h, 3); g.fill();
  g.shadowBlur = 0;
  g.save();
  g.translate(h / 2, h / 2);
  g.rotate(Math.PI / 4);
  g.scale((h * 0.78) / 24, (h * 0.78) / 24);
  g.fillStyle = ink;
  planePath(g, "airliner");
  g.fill();
  g.restore();
  if (code) {
    g.fillStyle = "rgba(11, 37, 69, 0.25)";
    g.fillRect(h, 2, 1, h - 4);
    g.fillStyle = ink;
    g.font = font;
    g.textBaseline = "middle";
    g.fillText(code, h + 3.5, h / 2 + 0.5);
  }
  return c;
}

function drawStation(color: string, size: number, major: boolean) {
  const [c, g] = canvas(size);
  const h = size / 2 - 1;
  g.fillStyle = color;
  g.strokeStyle = cssVar("--bg");
  g.lineWidth = 1.3;
  g.beginPath(); g.roundRect(-h, -h, 2 * h, 2 * h, major ? 2 : 1); g.fill(); g.stroke();
  if (major) {
    g.fillStyle = cssVar("--bg");
    g.fillRect(-h * 0.62, -0.9, h * 1.24, 1.8);
  }
  return c;
}

function drawPlace(color: string, size: number, capital: boolean) {
  const [c, g] = canvas(size);
  const r = size / 2 - 1;
  g.fillStyle = color;
  g.strokeStyle = cssVar("--bg");
  g.lineWidth = 1.2;
  if (capital) {
    g.lineWidth = 1.3;
    g.strokeStyle = color;
    g.beginPath(); g.arc(0, 0, r, 0, Math.PI * 2); g.stroke();
    g.beginPath(); g.arc(0, 0, r * 0.45, 0, Math.PI * 2); g.fill();
  } else {
    g.beginPath(); g.arc(0, 0, r, 0, Math.PI * 2); g.fill(); g.stroke();
  }
  return c;
}

function drawGlyph(cls: string, color: string, size: number) {
  const [c, g] = canvas(size + 4);
  g.scale(size / 24, size / 24);
  g.lineJoin = "round";
  planePath(g, cls);
  g.shadowColor = color;  // faint halo keeps aircraft readable over satellite imagery
  g.shadowBlur = 4;
  g.fillStyle = color;
  g.fill();
  g.shadowBlur = 0;
  g.strokeStyle = "rgba(5, 11, 22, 0.9)";
  g.lineWidth = 1.4;
  g.stroke();
  g.fill();
  return c;
}

/** Build the image for an icon id; null for ids we don't own. */
export function iconImage(id: string): { data: ImageData; pixelRatio: number } | null {
  const p = id.split("|");
  const cv = p[0] === "bb" ? drawBlock(p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8], p[9], p[10])
    : p[0] === "ap" ? drawAirport(p[1])
    : p[0] === "rs" ? drawStation(p[1], Number(p[2]), p[3] === "1")
    : p[0] === "pd" ? drawPlace(p[1], Number(p[2]), p[3] === "1")
    : p[0] === "gl" ? drawGlyph(p[1], p[2], Number(p[3]))
    : p[0] === "site" ? drawSite(p[1])
    : p[0] === "hatch" ? drawHatch(p[1])
    : p[0] === "mi" ? drawMission(p[1], p[2])
    : null;
  if (!cv) return null;
  return { data: cv.getContext("2d")!.getImageData(0, 0, cv.width, cv.height), pixelRatio: ratio() };
}
