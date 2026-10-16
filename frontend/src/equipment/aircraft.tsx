// Original top-down blueprint drawings, generated from per-type parameters (metres, nose at y = 0, x = 0 on the
// centreline). Dimensions are approximate public figures; shapes are simplified planforms, not engineering data.
import type { ReactNode } from "react";

type Wing = { x0: number; root: number; tip: number; sweep: number; kink?: number };
type Tail = { x0: number; root: number; tip: number; span: number; sweep: number };
type Pods = { at: number[]; x: number; len: number; dia: number; prop?: number };

export interface JetSpec {
  L: number; S: number; fus: number; nose: number;
  wing: Wing; tail?: Tail; canard?: Tail; fins: 1 | 2;
  canopy: { x0: number; len: number; w: number };
  engines: "single" | "twin" | "nacelles" | Pods;
  nacelles?: { off: number; w: number; y0: number };   // fighter engine nacelles (Su-30, MiG-29)
  prop?: number;                                       // nose propeller diameter
  lerx?: boolean; tipRails?: boolean; winglets?: boolean; ttail?: boolean;
  rotodome?: number; beam?: boolean; refuelPods?: boolean; glassNose?: boolean; rearEngines?: Pods;
}
export interface HeliSpec { heli: true; L: number; D: number; fusL: number; fusW: number; blades: number; tailD: number; stubs?: boolean; tandem?: boolean; slim?: boolean }
export interface UavSpec { uav: "boom" | "quad"; L: number; S: number; podL?: number; podW?: number; prop?: number }
export type AircraftSpec = JetSpec | HeliSpec | UavSpec;

export const AIRCRAFT: Record<string, AircraftSpec> = {
  "Su-30MKI": { L: 21.9, S: 14.7, fus: 2.0, nose: 4.6, fins: 2, lerx: true, tipRails: true, engines: "nacelles",
    nacelles: { off: 1.45, w: 1.35, y0: 8.8 }, wing: { x0: 8.2, root: 7.6, tip: 1.6, sweep: 42 },
    tail: { x0: 17.6, root: 3.0, tip: 1.0, span: 9.9, sweep: 45 }, canard: { x0: 6.3, root: 1.5, tip: 0.5, span: 6.4, sweep: 50 },
    canopy: { x0: 3.0, len: 3.9, w: 0.9 } },
  "MiG-29": { L: 17.3, S: 11.4, fus: 1.8, nose: 3.6, fins: 2, lerx: true, tipRails: true, engines: "nacelles",
    nacelles: { off: 1.15, w: 1.15, y0: 6.4 }, wing: { x0: 7.6, root: 5.1, tip: 1.4, sweep: 42 },
    tail: { x0: 13.7, root: 2.6, tip: 0.9, span: 7.8, sweep: 50 }, canopy: { x0: 2.6, len: 3.1, w: 0.85 } },
  "Rafale": { L: 15.3, S: 10.9, fus: 1.7, nose: 3.4, fins: 1, engines: "twin", tipRails: true,
    wing: { x0: 6.0, root: 8.3, tip: 1.0, sweep: 48 }, canard: { x0: 4.8, root: 1.7, tip: 0.6, span: 6.0, sweep: 45 },
    canopy: { x0: 2.3, len: 3.0, w: 0.8 } },
  "Tejas Mk1": { L: 13.2, S: 8.2, fus: 1.3, nose: 3.0, fins: 1, engines: "single", tipRails: true,
    wing: { x0: 4.4, root: 7.9, tip: 0.8, sweep: 50, kink: 0.45 }, canopy: { x0: 2.0, len: 2.4, w: 0.7 } },
  "Mirage 2000": { L: 14.4, S: 9.1, fus: 1.5, nose: 3.2, fins: 1, engines: "single",
    wing: { x0: 5.3, root: 8.2, tip: 0.6, sweep: 58 }, canopy: { x0: 2.2, len: 2.6, w: 0.75 } },
  "MiG-21 Bison": { L: 15.8, S: 7.2, fus: 1.25, nose: 3.6, fins: 1, engines: "single",
    wing: { x0: 7.2, root: 6.4, tip: 0.4, sweep: 57 }, tail: { x0: 12.9, root: 1.6, tip: 0.5, span: 3.7, sweep: 55 },
    canopy: { x0: 3.2, len: 2.0, w: 0.6 } },
  "MiG-27": { L: 17.1, S: 13.97, fus: 1.6, nose: 3.4, fins: 1, engines: "single",
    wing: { x0: 7.4, root: 3.6, tip: 1.2, sweep: 18 }, tail: { x0: 13.5, root: 2.4, tip: 0.9, span: 5.8, sweep: 55 },
    canopy: { x0: 3.0, len: 2.3, w: 0.7 } },
  "Jaguar": { L: 16.8, S: 8.7, fus: 1.55, nose: 3.4, fins: 1, engines: "twin",
    wing: { x0: 7.0, root: 3.7, tip: 1.1, sweep: 40 }, tail: { x0: 13.0, root: 2.3, tip: 0.7, span: 4.5, sweep: 45 },
    canopy: { x0: 2.5, len: 2.6, w: 0.7 } },
  "Hawk 132": { L: 12.4, S: 9.9, fus: 1.3, nose: 2.4, fins: 1, engines: "single", tipRails: true,
    wing: { x0: 4.9, root: 2.8, tip: 1.0, sweep: 26 }, tail: { x0: 10.0, root: 1.6, tip: 0.7, span: 4.4, sweep: 30 },
    canopy: { x0: 2.0, len: 3.4, w: 0.75 } },
  "Kiran": { L: 10.6, S: 10.7, fus: 1.25, nose: 1.8, fins: 1, engines: "single",
    wing: { x0: 4.2, root: 2.3, tip: 1.2, sweep: 4 }, tail: { x0: 8.9, root: 1.3, tip: 0.7, span: 3.8, sweep: 10 },
    canopy: { x0: 1.9, len: 2.0, w: 1.1 } },
  "PC-7 Mk II": { L: 10.2, S: 10.2, fus: 1.1, nose: 1.6, fins: 1, engines: "single", prop: 2.4,
    wing: { x0: 3.0, root: 2.3, tip: 1.0, sweep: 6 }, tail: { x0: 8.5, root: 1.3, tip: 0.7, span: 3.8, sweep: 12 },
    canopy: { x0: 2.6, len: 2.6, w: 0.7 } },
  "HTT-40": { L: 11.0, S: 11.0, fus: 1.15, nose: 1.7, fins: 1, engines: "single", prop: 2.5,
    wing: { x0: 3.4, root: 2.3, tip: 1.1, sweep: 5 }, tail: { x0: 9.2, root: 1.4, tip: 0.7, span: 4.0, sweep: 12 },
    canopy: { x0: 2.8, len: 2.8, w: 0.72 } },
  "HPT-32": { L: 7.7, S: 9.5, fus: 1.1, nose: 1.2, fins: 1, engines: "single", prop: 1.9,
    wing: { x0: 2.3, root: 1.7, tip: 1.1, sweep: 2 }, tail: { x0: 6.5, root: 1.0, tip: 0.6, span: 3.2, sweep: 8 },
    canopy: { x0: 2.1, len: 1.6, w: 1.0 } },
  "An-32": { L: 23.8, S: 29.2, fus: 2.9, nose: 2.6, fins: 1, engines: { at: [0.3], x: 7.6, len: 6.0, dia: 1.3, prop: 4.7 },
    wing: { x0: 9.2, root: 3.9, tip: 1.3, sweep: 7 }, tail: { x0: 20.0, root: 2.6, tip: 1.0, span: 10.0, sweep: 15 },
    canopy: { x0: 1.4, len: 1.4, w: 1.8 } },
  "Do-228": { L: 16.6, S: 17.0, fus: 1.6, nose: 2.0, fins: 1, engines: { at: [0.3], x: 5.4, len: 3.6, dia: 0.8, prop: 2.7 },
    wing: { x0: 6.3, root: 2.0, tip: 1.2, sweep: 2 }, tail: { x0: 14.2, root: 1.6, tip: 0.8, span: 6.5, sweep: 10 },
    canopy: { x0: 1.6, len: 1.2, w: 1.1 } },
  "C-295W": { L: 24.5, S: 25.8, fus: 2.9, nose: 2.6, fins: 1, winglets: true, engines: { at: [0.32], x: 8.4, len: 5.0, dia: 1.1, prop: 3.9 },
    wing: { x0: 9.6, root: 3.6, tip: 1.2, sweep: 4 }, tail: { x0: 20.6, root: 2.6, tip: 1.1, span: 10.5, sweep: 18 },
    canopy: { x0: 1.5, len: 1.4, w: 1.8 } },
  "C-130J-30": { L: 34.4, S: 40.4, fus: 4.3, nose: 3.4, fins: 1, engines: { at: [0.22, 0.45], x: 11.0, len: 5.6, dia: 1.2, prop: 4.1 },
    wing: { x0: 12.6, root: 4.9, tip: 2.4, sweep: 3 }, tail: { x0: 29.4, root: 3.4, tip: 1.6, span: 16.1, sweep: 12 },
    canopy: { x0: 1.8, len: 1.6, w: 2.6 } },
  "C-17A": { L: 53.0, S: 51.8, fus: 6.9, nose: 5.6, fins: 1, ttail: true, winglets: true,
    engines: { at: [0.26, 0.49], x: 16.8, len: 6.4, dia: 2.6 }, wing: { x0: 20.0, root: 10.6, tip: 3.0, sweep: 28 },
    tail: { x0: 46.0, root: 4.6, tip: 2.2, span: 20.0, sweep: 32 }, canopy: { x0: 2.6, len: 2.2, w: 3.6 } },
  "Il-76MD": { L: 46.6, S: 50.5, fus: 4.8, nose: 4.4, fins: 1, ttail: true, glassNose: true,
    engines: { at: [0.24, 0.46], x: 15.6, len: 6.0, dia: 1.9 }, wing: { x0: 18.0, root: 9.2, tip: 2.6, sweep: 27 },
    tail: { x0: 41.4, root: 4.2, tip: 1.8, span: 17.4, sweep: 34 }, canopy: { x0: 3.2, len: 2.0, w: 3.0 } },
  "Netra EMB-145I": { L: 29.9, S: 20.0, fus: 2.3, nose: 3.0, fins: 1, ttail: true, beam: true, engines: "single",
    rearEngines: { at: [], x: 20.8, len: 4.6, dia: 1.4 }, wing: { x0: 11.6, root: 4.3, tip: 1.4, sweep: 23 },
    tail: { x0: 25.6, root: 2.3, tip: 1.2, span: 7.6, sweep: 30 }, canopy: { x0: 1.6, len: 1.4, w: 1.6 } },
  "Mi-17V-5": { heli: true, L: 25.3, D: 21.3, fusL: 18.4, fusW: 2.5, blades: 5, tailD: 3.9, stubs: true },
  "Cheetah/Chetak": { heli: true, L: 12.9, D: 11.0, fusL: 10.2, fusW: 1.6, blades: 3, tailD: 1.9 },
  "Dhruv": { heli: true, L: 15.9, D: 13.2, fusL: 12.9, fusW: 2.0, blades: 4, tailD: 2.55 },
  "Rudra": { heli: true, L: 15.9, D: 13.2, fusL: 12.9, fusW: 2.0, blades: 4, tailD: 2.55, stubs: true },
  "AH-64E": { heli: true, L: 17.7, D: 14.6, fusL: 15.5, fusW: 1.4, blades: 4, tailD: 2.8, stubs: true, slim: true },
  "Mi-35": { heli: true, L: 21.4, D: 17.3, fusL: 17.5, fusW: 1.9, blades: 5, tailD: 3.9, stubs: true, slim: true },
  "Prachand LCH": { heli: true, L: 15.8, D: 13.3, fusL: 15.8, fusW: 1.25, blades: 4, tailD: 2.05, stubs: true, slim: true },
  "CH-47F": { heli: true, L: 30.1, D: 18.3, fusL: 15.9, fusW: 3.8, blades: 3, tailD: 0, tandem: true },
  "Heron Mk II": { uav: "boom", L: 8.5, S: 16.6, podL: 6.0, podW: 0.95, prop: 1.9 },
  "Searcher Mk II": { uav: "boom", L: 5.85, S: 8.5, podL: 4.2, podW: 0.7, prop: 1.3 },
  "Small UAS (generic)": { uav: "quad", L: 1.0, S: 1.0 },
};
for (const k of ["Il-78MKI", "A-50EI"]) AIRCRAFT[k] = { ...(AIRCRAFT["Il-76MD"] as JetSpec), ...(k === "A-50EI" ? { rotodome: 10.8 } : { refuelPods: true }) };

const FILL = "var(--bp-fill)", INK = "var(--bp-ink)", LINE = "var(--bp-line)", DARK = "var(--bp-dark)", GLASS = "url(#bp-glass)";
const tan = (d: number) => Math.tan((d * Math.PI) / 180);
const pts = (p: number[][]) => p.map(([a, b]) => `${a.toFixed(3)},${b.toFixed(3)}`).join(" ");
const both = (p: number[][], props: Record<string, unknown> = {}) => (
  <>{[1, -1].map((s) => <polygon key={s} points={pts(p.map(([a, b]) => [a * s, b]))} {...props} />)}</>
);

function planform(w: Wing, half: number, semi: number) {
  const tipY = w.x0 + (semi - half) * tan(w.sweep);
  if (w.kink) {  // cranked delta (Tejas): steeper inboard leading edge
    const kx = half + (semi - half) * w.kink, ky = w.x0 + (kx - half) * tan(w.sweep + 12);
    const ty = ky + (semi - kx) * tan(w.sweep - 8);
    return [[half, w.x0], [kx, ky], [semi, ty], [semi, ty + w.tip], [half, w.x0 + w.root]];
  }
  return [[half, w.x0], [semi, tipY], [semi, tipY + w.tip], [half, w.x0 + w.root]];
}
const surf = (t: Tail, half: number) => planform({ x0: t.x0, root: t.root, tip: t.tip, sweep: t.sweep }, half, t.span / 2);

function Jet({ s }: { s: JetSpec }) {
  const half = s.fus / 2, semi = s.S / 2, L = s.L;
  const wing = planform(s.wing, half * 0.92, semi);
  const out: ReactNode[] = [];
  // engines in pods under the wing (drawn first so the wing sits over the pylons)
  if (typeof s.engines === "object")
    for (const f of s.engines.at) for (const sg of [1, -1]) {
      const cx = sg * semi * f, e = s.engines as Pods;
      out.push(<rect key={`n${f}${sg}`} x={cx - e.dia / 2} y={e.x} width={e.dia} height={e.len} rx={e.dia / 2} fill={FILL} stroke={INK} strokeWidth={0.08} />);
      out.push(<rect key={`i${f}${sg}`} x={cx - e.dia / 2 + 0.08} y={e.x} width={e.dia - 0.16} height={0.35} rx={0.15} fill={DARK} />);
      if (e.prop) out.push(<line key={`p${f}${sg}`} x1={cx - e.prop / 2} y1={e.x - 0.25} x2={cx + e.prop / 2} y2={e.x - 0.25} stroke={INK} strokeWidth={0.18} strokeLinecap="round" />);
    }
  // fighter engine nacelles + nozzles
  if (s.nacelles) {
    const n = s.nacelles;
    for (const sg of [1, -1]) {
      out.push(<rect key={`na${sg}`} x={sg * n.off - n.w / 2} y={n.y0} width={n.w} height={L * 0.95 - n.y0} rx={0.45} fill={FILL} stroke={INK} strokeWidth={0.08} />);
      out.push(<rect key={`nz${sg}`} x={sg * n.off - n.w * 0.42} y={L * 0.95 - 0.1} width={n.w * 0.84} height={0.9} rx={0.2} fill={DARK} stroke={INK} strokeWidth={0.06} />);
    }
  }
  out.push(both(wing, { fill: FILL, stroke: INK, strokeWidth: 0.09, strokeLinejoin: "round" }));
  if (s.tail) out.push(both(surf(s.tail, half * 0.6), { fill: FILL, stroke: INK, strokeWidth: 0.08, strokeLinejoin: "round" }));
  // fuselage: ogive nose, parallel body, tapered tail
  const tailHalf = s.nacelles ? half * 0.45 : s.engines === "twin" ? half * 0.85 : half * 0.55;
  const nb = s.nose;
  const fusPath = `M0,0 Q${half * 0.95},${nb * 0.18} ${half},${nb} L${half},${L * 0.78} L${tailHalf},${L * 0.97} L${-tailHalf},${L * 0.97} L${-half},${L * 0.78} L${-half},${nb} Q${-half * 0.95},${nb * 0.18} 0,0 Z`;
  if (s.lerx) out.push(both([[half * 0.9, s.canopy.x0 + s.canopy.len * 0.6], [half * 0.92 + 0.9, s.wing.x0 - 0.4], [half * 0.92 + 1.4, s.wing.x0 + 0.6], [half * 0.9, s.wing.x0 + 0.6]],
    { fill: FILL, stroke: INK, strokeWidth: 0.07 }));
  out.push(<path key="fus" d={fusPath} fill={FILL} stroke={INK} strokeWidth={0.1} strokeLinejoin="round" />);
  if (s.canard) out.push(both(surf(s.canard, half * 0.9), { fill: FILL, stroke: INK, strokeWidth: 0.07 }));
  // nozzles
  if (s.engines === "single") out.push(<rect key="nz" x={-tailHalf * 0.8} y={L * 0.97 - 0.15} width={tailHalf * 1.6} height={0.7} rx={0.2} fill={DARK} />);
  if (s.engines === "twin") for (const sg of [1, -1]) out.push(<rect key={`tz${sg}`} x={sg * tailHalf * 0.5 - tailHalf * 0.42} y={L * 0.97 - 0.15} width={tailHalf * 0.84} height={0.7} rx={0.2} fill={DARK} />);
  if (s.rearEngines) for (const sg of [1, -1]) {
    const e = s.rearEngines;
    out.push(<rect key={`re${sg}`} x={sg * (half + e.dia / 2 + 0.15) - e.dia / 2} y={e.x} width={e.dia} height={e.len} rx={e.dia / 2} fill={FILL} stroke={INK} strokeWidth={0.08} />);
    out.push(<rect key={`ri${sg}`} x={sg * (half + e.dia / 2 + 0.15) - e.dia / 2 + 0.08} y={e.x} width={e.dia - 0.16} height={0.3} rx={0.12} fill={DARK} />);
  }
  // vertical fins seen from above
  const finLen = L * 0.2;
  if (s.fins === 2 && s.nacelles) for (const sg of [1, -1]) {
    const fx = sg * s.nacelles.off;
    out.push(<polygon key={`f${sg}`} points={pts([[fx - 0.12, L * 0.72], [fx + 0.12, L * 0.72], [fx + sg * 0.25 + 0.1, L * 0.72 + finLen], [fx + sg * 0.25 - 0.1, L * 0.72 + finLen]])} fill={DARK} stroke={INK} strokeWidth={0.05} />);
  } else out.push(<polygon key="f" points={pts([[-0.12, L * (s.ttail ? 0.8 : 0.74)], [0.12, L * (s.ttail ? 0.8 : 0.74)], [0.1, L * 0.99], [-0.1, L * 0.99]])} fill={DARK} />);
  if (s.ttail && s.tail) out.push(both(surf({ ...s.tail, x0: s.tail.x0 + 0.6 }, 0.15), { fill: FILL, stroke: INK, strokeWidth: 0.08 }));
  // panel lines: centreline, flap / aileron hinge lines, fuselage frames
  const tipLE = wing[wing.length - 3];
  out.push(<line key="cl" x1={0} y1={s.canopy.x0 + s.canopy.len} x2={0} y2={L * 0.95} stroke={LINE} strokeWidth={0.06} />);
  for (const sg of [1, -1]) {
    const [rx, ry] = wing[wing.length - 1], [tx, ty] = wing[wing.length - 2];
    const k = 0.78;
    out.push(<line key={`fl${sg}`} x1={sg * rx} y1={ry - s.wing.root * 0.22} x2={sg * (rx + (tx - rx) * k)} y2={ry - s.wing.root * 0.22 + (ty - ry) * k} stroke={LINE} strokeWidth={0.06} />);
    out.push(<line key={`sl${sg}`} x1={sg * (half * 0.95)} y1={s.wing.x0 + 0.35} x2={sg * tipLE[0]} y2={tipLE[1] + 0.25} stroke={LINE} strokeWidth={0.05} strokeDasharray="0.4 0.25" />);
  }
  for (const f of [0.35, 0.5, 0.62]) out.push(<line key={`fr${f}`} x1={-half * 0.98} y1={L * f} x2={half * 0.98} y2={L * f} stroke={LINE} strokeWidth={0.05} />);
  if (s.tipRails) for (const sg of [1, -1]) {
    const [tx, ty] = wing[wing.length - 3];
    out.push(<rect key={`tr${sg}`} x={sg * tx - 0.13} y={ty - 1.2} width={0.26} height={3.2} rx={0.12} fill={FILL} stroke={INK} strokeWidth={0.06} />);
  }
  if (s.winglets) for (const sg of [1, -1]) {
    const [tx, ty] = wing[wing.length - 2];
    out.push(<line key={`wl${sg}`} x1={sg * tx} y1={ty - s.wing.tip} x2={sg * tx} y2={ty} stroke={INK} strokeWidth={0.35} />);
  }
  if (s.refuelPods) for (const sg of [1, -1]) out.push(<rect key={`rp${sg}`} x={sg * semi * 0.72 - 0.4} y={s.wing.x0 + semi * 0.72 * tan(s.wing.sweep) - 0.5} width={0.8} height={4.2} rx={0.4} fill={DARK} stroke={INK} strokeWidth={0.06} />);
  if (s.beam) out.push(<rect key="beam" x={-0.45} y={L * 0.27} width={0.9} height={L * 0.47} rx={0.2} fill={DARK} stroke={INK} strokeWidth={0.06} />);
  if (s.rotodome) {
    out.push(<circle key="rd" cx={0} cy={L * 0.6} r={s.rotodome / 2} fill={FILL} stroke={INK} strokeWidth={0.12} />);
    out.push(<circle key="rd2" cx={0} cy={L * 0.6} r={s.rotodome / 2 - 0.9} fill="none" stroke={LINE} strokeWidth={0.08} />);
    out.push(<line key="rd3" x1={-s.rotodome / 2} y1={L * 0.6} x2={s.rotodome / 2} y2={L * 0.6} stroke={LINE} strokeWidth={0.08} />);
  }
  // cockpit glazing and nose propeller
  const c = s.canopy;
  out.push(<ellipse key="cp" cx={0} cy={c.x0 + c.len / 2} rx={c.w / 2} ry={c.len / 2} fill={GLASS} stroke={INK} strokeWidth={0.08} />);
  if (c.len > 2.4 && c.w < 0.9) out.push(<line key="cpf" x1={-c.w / 2} y1={c.x0 + c.len / 2} x2={c.w / 2} y2={c.x0 + c.len / 2} stroke={INK} strokeWidth={0.06} />);
  if (s.glassNose) out.push(<ellipse key="gn" cx={0} cy={1.1} rx={half * 0.45} ry={0.9} fill={GLASS} stroke={INK} strokeWidth={0.06} />);
  if (s.prop) {
    out.push(<line key="pr" x1={-s.prop / 2} y1={-0.15} x2={s.prop / 2} y2={-0.15} stroke={INK} strokeWidth={0.12} strokeLinecap="round" />);
    out.push(<circle key="sp" cx={0} cy={0.05} r={0.22} fill={DARK} />);
  }
  return <>{out}</>;
}

function Heli({ s }: { s: HeliSpec }) {
  const w = s.fusW, half = w / 2, out: ReactNode[] = [];
  const rotor = (cy: number, key: string) => (
    <g key={key}>
      <circle cx={0} cy={cy} r={s.D / 2} fill="var(--bp-disc)" stroke={LINE} strokeWidth={0.08} strokeDasharray="0.6 0.4" />
      {Array.from({ length: s.blades }, (_, i) => {
        const a = (i / s.blades) * 360 + 18;
        return <rect key={i} x={-0.24} y={cy - s.D / 2 + 0.2} width={0.48} height={s.D / 2 - 0.2} rx={0.2} fill={FILL} stroke={INK} strokeWidth={0.06}
          transform={`rotate(${a} 0 ${cy})`} />;
      })}
      <circle cx={0} cy={cy} r={0.55} fill={DARK} stroke={INK} strokeWidth={0.06} />
    </g>
  );
  if (s.tandem) {
    out.push(<rect key="fus" x={-half} y={0} width={w} height={s.fusL} rx={1.4} fill={FILL} stroke={INK} strokeWidth={0.1} />);
    out.push(<rect key="aft" x={-half * 0.7} y={s.fusL * 0.78} width={w * 0.7} height={s.fusL * 0.22} rx={0.6} fill={FILL} stroke={INK} strokeWidth={0.08} />);
    for (const sg of [1, -1]) out.push(<rect key={`eng${sg}`} x={sg * (half + 0.2) - 0.5} y={s.fusL * 0.7} width={1.0} height={3.6} rx={0.45} fill={DARK} />);
    out.push(<ellipse key="cp" cx={0} cy={1.2} rx={half * 0.75} ry={0.9} fill={GLASS} stroke={INK} strokeWidth={0.06} />);
    const r1 = Math.min(s.D / 2 - 1.5, 1.6), r2 = s.fusL - 1.2;
    out.push(rotor(r1, "r1"), rotor(r2, "r2"));
    return <g transform={`translate(0 ${s.D / 2 - r1})`}>{out}</g>;
  }
  const body = s.fusL * 0.62, boomEnd = s.fusL;
  out.push(<path key="boom" d={`M${-half * 0.3},${body * 0.9} L${-0.22},${boomEnd} L${0.22},${boomEnd} L${half * 0.3},${body * 0.9} Z`} fill={FILL} stroke={INK} strokeWidth={0.08} />);
  out.push(<rect key="hs" x={-1.3} y={boomEnd - 2.0} width={2.6} height={0.6} rx={0.2} fill={FILL} stroke={INK} strokeWidth={0.06} />);
  if (s.tailD) out.push(<line key="tr" x1={half * 0.3 + 0.3} y1={boomEnd - 0.6 - s.tailD / 2} x2={half * 0.3 + 0.3} y2={boomEnd - 0.6 + s.tailD / 2} stroke={INK} strokeWidth={0.22} strokeLinecap="round" />);
  if (s.stubs) {
    out.push(<rect key="stub" x={-half - 1.9} y={body * 0.52} width={w + 3.8} height={0.75} rx={0.3} fill={FILL} stroke={INK} strokeWidth={0.07} />);
    for (const sg of [1, -1]) for (const k of [0.8, 1.6]) out.push(<rect key={`py${sg}${k}`} x={sg * (half + k) - 0.18} y={body * 0.52 - 0.6} width={0.36} height={1.9} rx={0.15} fill={DARK} />);
  }
  const nose = s.slim ? 0.35 : 0.6;
  out.push(<path key="fus" d={`M0,0 Q${half},${nose} ${half},${body * 0.35} L${half},${body * 0.8} Q${half * 0.6},${body} 0,${body} Q${-half * 0.6},${body} ${-half},${body * 0.8} L${-half},${body * 0.35} Q${-half},${nose} 0,0 Z`}
    fill={FILL} stroke={INK} strokeWidth={0.1} />);
  out.push(<rect key="eng" x={-half * 0.55} y={body * 0.3} width={half * 1.1} height={body * 0.42} rx={0.35} fill={DARK} opacity={0.75} />);
  out.push(s.slim
    ? <g key="cp"><ellipse cx={0} cy={body * 0.1} rx={half * 0.75} ry={body * 0.07} fill={GLASS} stroke={INK} strokeWidth={0.05} /><ellipse cx={0} cy={body * 0.24} rx={half * 0.75} ry={body * 0.07} fill={GLASS} stroke={INK} strokeWidth={0.05} /></g>
    : <ellipse key="cp" cx={0} cy={body * 0.14} rx={half * 0.8} ry={body * 0.12} fill={GLASS} stroke={INK} strokeWidth={0.06} />);
  const hub = body * 0.42;
  out.push(rotor(hub, "rotor"));
  return <g transform={`translate(0 ${Math.max(0, s.D / 2 - hub)})`}>{out}</g>;
}

function Uav({ s }: { s: UavSpec }) {
  if (s.uav === "quad") {
    const a = 0.36;
    return (
      <g transform="translate(0 0.5)">
        {[[1, 1], [1, -1], [-1, 1], [-1, -1]].map(([x, y]) => (
          <g key={`${x}${y}`}>
            <line x1={0} y1={0} x2={x * a} y2={y * a} stroke={INK} strokeWidth={0.06} />
            <circle cx={x * a} cy={y * a} r={0.15} fill="var(--bp-disc)" stroke={LINE} strokeWidth={0.015} strokeDasharray="0.03 0.02" />
            <circle cx={x * a} cy={y * a} r={0.035} fill={DARK} />
          </g>
        ))}
        <rect x={-0.12} y={-0.12} width={0.24} height={0.24} rx={0.05} fill={FILL} stroke={INK} strokeWidth={0.015} />
      </g>
    );
  }
  const podL = s.podL!, podW = s.podW!, semi = s.S / 2, wx = podL * 0.4, chord = s.S * 0.065, boom = podW * 1.6;
  return (
    <>
      {[1, -1].map((sg) => <rect key={`b${sg}`} x={sg * boom - 0.09} y={wx} width={0.18} height={s.L - wx - 0.2} rx={0.08} fill={FILL} stroke={INK} strokeWidth={0.04} />)}
      <rect x={-boom} y={s.L - 0.9} width={boom * 2} height={0.55} rx={0.12} fill={FILL} stroke={INK} strokeWidth={0.04} />
      {both([[podW * 0.4, wx], [semi, wx + 0.12], [semi, wx + 0.12 + chord * 0.75], [podW * 0.4, wx + chord]], { fill: FILL, stroke: INK, strokeWidth: 0.05 })}
      <path d={`M0,0 Q${podW / 2},${podL * 0.08} ${podW / 2},${podL * 0.3} L${podW * 0.4},${podL} L${-podW * 0.4},${podL} L${-podW / 2},${podL * 0.3} Q${-podW / 2},${podL * 0.08} 0,0 Z`}
        fill={FILL} stroke={INK} strokeWidth={0.05} />
      <ellipse cx={0} cy={podL * 0.18} rx={podW * 0.3} ry={podL * 0.08} fill={DARK} />
      <line x1={-s.prop! / 2} y1={podL + 0.1} x2={s.prop! / 2} y2={podL + 0.1} stroke={INK} strokeWidth={0.07} strokeLinecap="round" />
      <line x1={0} y1={podL * 0.35} x2={0} y2={podL * 0.95} stroke={LINE} strokeWidth={0.03} />
    </>
  );
}

/** Bounds in metres for framing: [width, height]. */
export function aircraftBox(s: AircraftSpec): [number, number] {
  if ("heli" in s) return s.tandem ? [s.D, s.fusL + s.D - 2.8] : [s.D, Math.max(s.D, s.fusL + Math.max(0, s.D / 2 - s.fusL * 0.62 * 0.42))];
  if ("uav" in s) return s.uav === "quad" ? [1.1, 1.1] : [s.S, s.L + 0.3];
  return [Math.max(s.S, s.tail?.span ?? 0, s.rotodome ?? 0) + 0.8, s.L + 1.0];
}

export function AircraftArt({ spec }: { spec: AircraftSpec }) {
  if ("heli" in spec) return <Heli s={spec} />;
  if ("uav" in spec) return <Uav s={spec} />;
  return <Jet s={spec} />;
}
