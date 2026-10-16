// Tiny 3D illustration engine: parallel 3/4 projection, lit flat faces, shaded cylinders, wheels, glass and soft
// ground shadows, painted back to front. Units are metres; x = length (front at +x), y = width (near side at +y), z = up.
import type { ReactNode } from "react";

export type V3 = [number, number, number];
const add = (a: V3, b: V3): V3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const sub = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const mul = (a: V3, k: number): V3 => [a[0] * k, a[1] * k, a[2] * k];
const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
export const norm = (a: V3): V3 => mul(a, 1 / (Math.hypot(...a) || 1));

// Projection rows (screen x, screen y-down). Length axis 18° below horizontal, width axis 40° the other way, foreshortened.
const RA = (18 * Math.PI) / 180, RB = (40 * Math.PI) / 180;
const SX: V3 = [Math.cos(RA), -0.78 * Math.cos(RB), 0];
const SY: V3 = [Math.sin(RA), 0.78 * Math.sin(RB), -0.93];
let VIEW = norm(cross(SX, SY));
if (VIEW[2] < 0) VIEW = mul(VIEW, -1);
const LIGHT = norm([-0.25, 0.6, 1]);
const light = (n: V3) => 0.5 + 0.62 * Math.max(0, dot(n, LIGHT)) + 0.06 * Math.max(0, dot(n, VIEW));
const facing = (n: V3) => dot(n, VIEW) > 1e-4;
/** Paint order: distance toward the camera, plus height (we look down, so what sits on top is drawn later). */
const depth = (p: V3) => dot(p, VIEW) + 0.45 * p[2];

export function shade(hex: string, k: number): string {
  const n = parseInt(hex.slice(1), 16);
  const ch = [n >> 16, (n >> 8) & 255, n & 255].map((c) => Math.round(k <= 1 ? c * k : c + (255 - c) * Math.min(1, k - 1)));
  return `rgb(${ch.join(",")})`;
}

type P2 = [number, number];
function hull(ps: P2[]): P2[] {
  const p = [...ps].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cr = (o: P2, a: P2, b: P2) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo: P2[] = [], up: P2[] = [];
  for (const q of p) { while (lo.length > 1 && cr(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
  for (const q of p.reverse()) { while (up.length > 1 && cr(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); }
  return lo.slice(0, -1).concat(up.slice(0, -1));
}

export interface Item { d: number; n: ReactNode[] }
const EDGE = "rgba(6, 10, 16, 0.5)";

/** Collects primitives, then renders them sorted far → near. `id` keeps gradient ids unique per drawing. */
export class Scene {
  items: Item[] = [];
  defs: ReactNode[] = [];
  private k = 0;
  private b = [Infinity, Infinity, -Infinity, -Infinity];
  constructor(private id: string) {}

  P(p: V3): P2 {
    const x = dot(p, SX), y = dot(p, SY);
    this.b = [Math.min(this.b[0], x), Math.min(this.b[1], y), Math.max(this.b[2], x), Math.max(this.b[3], y)];
    return [x, y];
  }
  private pts(ps: V3[]) { return ps.map((p) => this.P(p).map((v) => v.toFixed(3)).join(",")).join(" "); }
  private key() { return `${this.id}${this.k++}`; }
  private push(d: number, n: ReactNode[]): Item { const it = { d, n }; this.items.push(it); return it; }

  /** Box from an origin and three edge vectors (any orientation). */
  box(o: V3, ex: V3, ey: V3, ez: V3, color: string, bias = 0): Item {
    const c = (i: number, j: number, k: number) => add(add(add(o, mul(ex, i)), mul(ey, j)), mul(ez, k));
    const faces: [V3, V3[]][] = [
      [norm(ex), [c(1, 0, 0), c(1, 1, 0), c(1, 1, 1), c(1, 0, 1)]], [mul(norm(ex), -1), [c(0, 0, 0), c(0, 1, 0), c(0, 1, 1), c(0, 0, 1)]],
      [norm(ey), [c(0, 1, 0), c(1, 1, 0), c(1, 1, 1), c(0, 1, 1)]], [mul(norm(ey), -1), [c(0, 0, 0), c(1, 0, 0), c(1, 0, 1), c(0, 0, 1)]],
      [norm(ez), [c(0, 0, 1), c(1, 0, 1), c(1, 1, 1), c(0, 1, 1)]], [mul(norm(ez), -1), [c(0, 0, 0), c(1, 0, 0), c(1, 1, 0), c(0, 1, 0)]],
    ];
    const n = faces.filter(([nv]) => facing(nv)).map(([nv, ps]) =>
      <polygon key={this.key()} points={this.pts(ps)} fill={shade(color, light(nv))} stroke={EDGE} strokeWidth={0.6} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />);
    return this.push(depth(c(0.5, 0.5, 0.5)) + bias, n);
  }
  /** Axis-aligned box. */
  ab(x: number, y: number, z: number, l: number, w: number, h: number, color: string, bias = 0) {
    return this.box([x, y, z], [l, 0, 0], [0, w, 0], [0, 0, h], color, bias);
  }

  /** Flat panel on a face: rectangle in plane x / y / z = at, lit by that face's normal (or `flat` colour). */
  dec(it: Item, axis: "x" | "y" | "z", at: number, r: [number, number, number, number], color: string, o: { flat?: boolean; opacity?: number } = {}) {
    const [a0, b0, a1, b1] = r;
    const ps: V3[] = axis === "x" ? [[at, a0, b0], [at, a1, b0], [at, a1, b1], [at, a0, b1]]
      : axis === "y" ? [[a0, at, b0], [a1, at, b0], [a1, at, b1], [a0, at, b1]] : [[a0, b0, at], [a1, b0, at], [a1, b1, at], [a0, b1, at]];
    this.poly(it, ps, axis === "x" ? [1, 0, 0] : axis === "y" ? [0, 1, 0] : [0, 0, 1], color, o);
  }
  poly(it: Item, ps: V3[], n: V3, color: string, o: { flat?: boolean; opacity?: number } = {}) {
    if (!facing(n)) return;
    it.n.push(<polygon key={this.key()} points={this.pts(ps)} fill={o.flat ? color : shade(color, light(n))} opacity={o.opacity} />);
  }
  /** Window with a soft reflection band. */
  glass(it: Item, axis: "x" | "y" | "z", at: number, r: [number, number, number, number]) {
    this.dec(it, axis, at, r, "#2d4c6b");
    const [a0, b0, a1, b1] = r;
    this.dec(it, axis, at, axis === "z" ? [a0, b0, a0 + (a1 - a0) * 0.45, b1] : [a0, b0 + (b1 - b0) * 0.62, a1, b1], "#ffffff", { flat: true, opacity: 0.16 });
  }
  /** Circle on a plane through `c` spanned by unit vectors u, v. */
  disc(it: Item, c: V3, u: V3, v: V3, r: number, color: string, flat = false) {
    const n = norm(cross(u, v));
    const ps = Array.from({ length: 24 }, (_, i) => { const t = (i / 24) * Math.PI * 2; return add(c, add(mul(u, r * Math.cos(t)), mul(v, r * Math.sin(t)))); });
    this.poly(it, ps, facing(n) ? n : mul(n, -1), color, { flat });
  }
  line(it: Item | null, a: V3, b: V3, color: string, w = 0.05) {
    const [x1, y1] = this.P(a), [x2, y2] = this.P(b);
    const el = <line key={this.key()} x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={w} strokeLinecap="round" />;
    if (it) it.n.push(el); else this.push(depth(mul(add(a, b), 0.5)), [el]);
  }

  /** Cylinder from a to b, shaded across its width; the end facing the camera is capped. */
  cyl(a: V3, b: V3, r: number, color: string, o: { r2?: number; bias?: number; cap?: string } = {}): Item {
    const u = norm(sub(b, a));
    const p = norm(cross(u, Math.abs(u[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0]));
    const q = cross(u, p);
    const r2 = o.r2 ?? r;
    const ring = (c: V3, rr: number) => Array.from({ length: 28 }, (_, i) => { const t = (i / 28) * Math.PI * 2; return add(c, add(mul(p, rr * Math.cos(t)), mul(q, rr * Math.sin(t)))); });
    const ra = ring(a, r), rb = ring(b, r2);
    const body = hull([...ra, ...rb].map((pt) => this.P(pt)));
    const [ax, ay] = this.P(a), [bx, by] = this.P(b);
    let px = -(by - ay), py = bx - ax;
    const l = Math.hypot(px, py);
    if (l < 1e-6) { px = 0; py = -1; } else { px /= l; py /= l; }
    if (py > 0) { px = -px; py = -py; }
    const cx = (ax + bx) / 2, cy = (ay + by) / 2, rs = Math.max(r, r2) * 1.02;
    const gid = this.key();
    this.defs.push(
      <linearGradient key={gid} id={gid} gradientUnits="userSpaceOnUse" x1={cx + px * rs} y1={cy + py * rs} x2={cx - px * rs} y2={cy - py * rs}>
        <stop offset="0" stopColor={shade(color, 0.92)} /><stop offset="0.22" stopColor={shade(color, 1.16)} />
        <stop offset="0.55" stopColor={shade(color, 0.84)} /><stop offset="1" stopColor={shade(color, 0.48)} />
      </linearGradient>,
    );
    const n: ReactNode[] = [<polygon key={this.key()} points={body.map((v) => v.map((z) => z.toFixed(3)).join(",")).join(" ")} fill={`url(#${gid})`}
      stroke={EDGE} strokeWidth={0.6} vectorEffect="non-scaling-stroke" />];
    const capB = facing(u), cap = capB ? rb : ra, cn = capB ? u : mul(u, -1);
    if (facing(cn)) n.push(<polygon key={this.key()} points={this.pts(cap)} fill={o.cap ?? shade(color, light(cn))} stroke={EDGE} strokeWidth={0.5} vectorEffect="non-scaling-stroke" />);
    return this.push(depth(mul(add(a, b), 0.5)) + (o.bias ?? 0), n);
  }

  /** Wheel with its axle along y: tyre, steel hub and centre cap on the side facing the camera. */
  wheel(c: V3, r: number, w: number, hub = "#9aa6b2") {
    const a = sub(c, [0, w / 2, 0]), b = add(c, [0, w / 2, 0]);
    const it = this.cyl(a, b, r, "#202328");
    const face = facing([0, 1, 0]) ? b : a;
    this.disc(it, face, [1, 0, 0], [0, 0, 1], r * 0.58, hub);
    this.disc(it, face, [1, 0, 0], [0, 0, 1], r * 0.2, "#3a4048");
    return it;
  }

  /** Ellipsoid (aerostat envelope): screen ellipse with a soft highlight. */
  blob(c: V3, ax: V3, r: number, color: string) {
    const [x0, y0] = this.P(c), [x1, y1] = this.P(add(c, ax)), [, y2] = this.P(add(c, [0, 0, r]));
    this.P(sub(c, ax)); this.P(add(c, [0, r, 0])); this.P(sub(c, [0, 0, r]));
    const rx = Math.hypot(x1 - x0, y1 - y0), ry = Math.abs(y2 - y0) * 1.05, ang = (Math.atan2(y1 - y0, x1 - x0) * 180) / Math.PI;
    const gid = this.key();
    this.defs.push(<radialGradient key={gid} id={gid} cx="0.38" cy="0.3" r="0.75"><stop offset="0" stopColor={shade(color, 1.12)} />
      <stop offset="0.6" stopColor={shade(color, 0.86)} /><stop offset="1" stopColor={shade(color, 0.5)} /></radialGradient>);
    return this.push(depth(c), [<ellipse key={this.key()} cx={x0} cy={y0} rx={rx} ry={ry} transform={`rotate(${ang} ${x0} ${y0})`} fill={`url(#${gid})`}
      stroke={EDGE} strokeWidth={0.6} vectorEffect="non-scaling-stroke" />]);
  }

  /** Soft contact shadow under a footprint at ground level. */
  shadow(x0: number, y0: number, x1: number, y1: number) {
    const fid = this.key(), m = 0.25;
    const size = Math.max(x1 - x0, y1 - y0);
    this.defs.push(<filter key={fid} id={fid} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation={size * 0.035} /></filter>);
    this.push(-1e9, [<polygon key={this.key()} points={this.pts([[x0 - m, y0 - m, 0], [x1 + m, y0 - m, 0], [x1 + m, y1 + m * 2, 0], [x0 - m, y1 + m * 2, 0]])}
      fill="#000" opacity={0.5} filter={`url(#${fid})`} />]);
  }

  render(label: string) {
    const [x0, y0, x1, y1] = this.b;
    const m = Math.max(x1 - x0, y1 - y0) * 0.07;
    return (
      <svg viewBox={`${x0 - m} ${y0 - m} ${x1 - x0 + 2 * m} ${y1 - y0 + 2 * m}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label={label}>
        <defs>{this.defs}</defs>
        {[...this.items].sort((a, b) => a.d - b.d).flatMap((it) => it.n)}
      </svg>
    );
  }
}
