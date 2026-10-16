let ctx2d: CanvasRenderingContext2D | null = null;

/** Normalise any CSS colour (incl. CSS4 `rgb(r g b / a)`) to "#rrggbb" / "rgba(...)" via the browser's own parser. */
function normalise(raw: string): string {
  ctx2d ??= document.createElement("canvas").getContext("2d");
  if (!ctx2d) return raw;
  ctx2d.fillStyle = "#ffffff";
  ctx2d.fillStyle = raw;
  return String(ctx2d.fillStyle);
}

/** Read a CSS token (DESIGN_SYSTEM §14). Map code never hard-codes hex. Optional alpha → rgba(). */
export function cssVar(token: string, alpha?: number): string {
  const c = normalise(getComputedStyle(document.documentElement).getPropertyValue(token).trim() || "#ffffff");
  if (alpha === undefined || !c.startsWith("#")) return c;
  const n = parseInt(c.slice(1), 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

export const SEVERITY_TOKEN: Record<string, string> = {
  CRITICAL: "--critical", WARNING: "--warning", CAUTION: "--caution", INFO: "--info",
};
export const FLIGHT_CAT_TOKEN: Record<string, string> = { VFR: "--ok", MVFR: "--info", IFR: "--warning", LIFR: "--critical" };
