// Time, coordinate and vocabulary formatting (docs/DESIGN_SYSTEM.md §13).

const IST = "Asia/Kolkata";

export function istTime(d: Date | string | null | undefined, withDate = false): string {
  if (!d) return "—";
  const date = typeof d === "string" ? new Date(d) : d;
  return date.toLocaleString("en-GB", {
    timeZone: IST, hour: "2-digit", minute: "2-digit", hour12: false,
    ...(withDate ? { day: "2-digit", month: "short" } : {}),
  }) + " IST";
}

export function zulu(d: Date | string | null | undefined): string {
  if (!d) return "—";
  const date = typeof d === "string" ? new Date(d) : d;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(date.getUTCHours())}${p(date.getUTCMinutes())}Z`;
}

export function dtg(d: Date | string): string {
  const date = typeof d === "string" ? new Date(d) : d;
  const p = (n: number) => String(n).padStart(2, "0");
  const mon = date.toLocaleString("en-GB", { month: "short", timeZone: "UTC" }).toUpperCase();
  return `${p(date.getUTCDate())}${p(date.getUTCHours())}${p(date.getUTCMinutes())}Z ${mon} ${String(date.getUTCFullYear()).slice(2)}`;
}

export function dms(lat: number, lon: number): string {
  const f = (v: number, pos: string, neg: string) => {
    const a = Math.abs(v);
    const d = Math.floor(a);
    const m = Math.floor((a - d) * 60);
    const s = Math.round(((a - d) * 60 - m) * 60);
    return `${d}°${String(m).padStart(2, "0")}'${String(s).padStart(2, "0")}"${v >= 0 ? pos : neg}`;
  };
  return `${f(lat, "N", "S")} ${f(lon, "E", "W")}`;
}

export const num = (v: unknown, digits = 0): string =>
  typeof v === "number" && Number.isFinite(v) ? v.toLocaleString("en-IN", { maximumFractionDigits: digits }) : "—";

/** Calendar date, e.g. "06 Sep 2026" (IST). */
export const day = (d: string | null | undefined) =>
  d ? new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric", timeZone: "Asia/Kolkata" }) : "—";
export const feet = (m: number | null | undefined) => (m == null ? "—" : `${Math.round(m * 3.28084).toLocaleString("en-IN")} ft`);
export const kl = (l: number | null | undefined) => (l == null ? "—" : `${(l / 1000).toLocaleString("en-IN", { maximumFractionDigits: 0 })} kL`);

export const RANK: Record<string, string> = {
  FG_OFFR: "Fg Offr", FLT_LT: "Flt Lt", SQN_LDR: "Sqn Ldr", WG_CDR: "Wg Cdr", GP_CAPT: "Gp Capt", AIR_CMDE: "Air Cmde",
};

const UPPER = /\b(qra|hq|ad|sam|alg|aog|iaf|atf|gse|uav|uas|wso|rpa|qfi|nvg|aar|isr|cas|hadr|fbsu|vhf|uhf|hf|gs|c2|mpr|lltr|lllr|lr|mr|sr|vshorads|ifr|vfr|mvfr|lifr|wx|ext|ac|gpu|atc|c-uas|uas)\b/gi;
export const label = (s: string | null | undefined): string =>
  s ? s.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase()).replace(UPPER, (m) => m.toUpperCase()) : "—";

/** Status vocabulary -> (word, tone, glyph). Tone maps to .s-* classes; glyph keeps status readable without colour. */
const TONE: Record<string, [string, string]> = {
  AVAILABLE: ["S", "ok"], STANDBY: ["Standby", "info"], QRA: ["QRA", "ok"], AIRBORNE: ["Airborne", "info"],
  TURNAROUND: ["Turnaround", "neutral"], MAINT_SCHEDULED: ["Maint (sched)", "caution"],
  MAINT_UNSCHEDULED: ["U/S", "warning"], AOG: ["AOG", "critical"], DEPOT: ["Depot", "neutral"], RETIRED: ["Retired", "neutral"],
  OPERATIONAL: ["Operational", "ok"], DEGRADED: ["Degraded", "caution"], MAINTENANCE: ["Maintenance", "caution"],
  OFFLINE: ["Offline", "critical"], UP: ["Up", "ok"], DOWN: ["Down", "critical"], SERVICEABLE: ["S", "ok"],
  UNSERVICEABLE: ["U/S", "critical"], UNDER_REPAIR: ["Under repair", "caution"], OPEN: ["Open", "ok"],
  CLOSED: ["Closed", "critical"], RESTRICTED: ["Restricted", "caution"],
  ON_DUTY: ["On duty", "ok"], BRIEFED: ["Briefed", "info"], CREW_REST: ["Crew rest", "neutral"],
  OFF_DUTY: ["Off duty", "neutral"], LEAVE: ["Leave", "neutral"], SICK: ["Sick", "warning"], COURSE: ["Course", "neutral"],
  FIT_FULL: ["Fit", "ok"], FIT_RESTRICTED: ["Fit (restricted)", "caution"], TEMP_UNFIT: ["Temp unfit", "warning"],
  GROUNDED: ["Grounded", "critical"], CURRENT: ["Current", "ok"], LAPSING: ["Lapsing", "caution"], LAPSED: ["Lapsed", "warning"],
  VFR: ["VFR", "ok"], MVFR: ["MVFR", "info"], IFR: ["IFR", "warning"], LIFR: ["LIFR", "critical"],
  CRITICAL: ["Critical", "critical"], WARNING: ["Warning", "warning"], CAUTION: ["Caution", "caution"], INFO: ["Info", "info"],
  LIVE: ["Live", "ok"], STALE: ["Stale", "caution"], OFF: ["Off", "critical"], LIMITED: ["Limited", "caution"],
  PLANNED: ["Planned", "neutral"], CREWED: ["Crewed", "info"], READY: ["Ready", "info"], ON_STATION: ["On station", "info"],
  RTB: ["RTB", "info"], LANDED: ["Landed", "ok"], COMPLETED: ["Completed", "ok"], CANCELLED: ["Cancelled", "neutral"],
  ABORTED: ["Aborted", "warning"], ACKNOWLEDGED: ["Acknowledged", "info"],
};
const GLYPH: Record<string, string> = { ok: "●", info: "○", caution: "▲", warning: "◆", critical: "■", neutral: "—" };

export function tone(status: string | null | undefined): { word: string; tone: string; glyph: string } {
  const [word, t] = TONE[status ?? ""] ?? [label(status), "neutral"];
  return { word, tone: t, glyph: GLYPH[t] };
}

export function sevTone(pct: number | null | undefined, ok = 70, warn = 60, crit = 45): string {
  if (pct == null) return "neutral";
  return pct < crit ? "critical" : pct < warn ? "warning" : pct < ok ? "caution" : "ok";
}
