// Portions derived from God's Eye View (src/layers/wind/model.js, src/layers/wind/source.js),
// Copyright (c) 2026 Bilawal Sidhu, MIT License. See THIRD_PARTY_NOTICES.md.
// Renderer simplified: CPU particles on a 2D canvas over the map (God's Eye uses a GPU streamline pass).
import type { Map as MlMap } from "maplibre-gl";
import { useEffect } from "react";
import { useStore } from "../store";

interface WindField { u: Float32Array; v: Float32Array; nx: number; ny: number; lo1: number; la1: number; dx: number; dy: number; validIso?: string }

const norm = (lon: number) => ((((lon + 180) % 360) + 360) % 360) - 180;

function sampleWind(f: WindField, lon: number, lat: number): [number, number] {
  const x = ((norm(lon - f.lo1) + 360) % 360) / f.dx;
  const y = Math.max(0, Math.min(f.ny - 1, (f.la1 - lat) / f.dy));
  const x0 = Math.floor(x), tx = x - x0, y0 = Math.floor(y), y1 = Math.min(f.ny - 1, y0 + 1), ty = y - y0;
  const l = ((x0 % f.nx) + f.nx) % f.nx, r = (l + 1) % f.nx;
  const a = y0 * f.nx + l, b = y0 * f.nx + r, c = y1 * f.nx + l, d = y1 * f.nx + r;
  const lerp = (arr: Float32Array) => (arr[a] * (1 - tx) + arr[b] * tx) * (1 - ty) + (arr[c] * (1 - tx) + arr[d] * tx) * ty;
  return [lerp(f.u), lerp(f.v)];
}

// speed ramp in m/s: calm steel blue → white → amber → red (windy-style, tuned for the navy map)
const RAMP: [number, string][] = [[0, "rgba(130,175,235,0.55)"], [4, "rgba(165,210,255,0.75)"], [8, "rgba(225,240,255,0.9)"],
  [13, "rgba(253,230,138,0.95)"], [18, "rgba(251,191,36,1)"], [25, "rgba(249,115,22,1)"], [32, "rgba(239,68,68,1)"]];
const bucket = (speed: number) => {
  let i = 0;
  while (i < RAMP.length - 1 && speed >= RAMP[i + 1][0]) i++;
  return i;
};

const cache = new Map<string, Promise<WindField>>();
function loadField(model: string): Promise<WindField> {
  if (!cache.has(model)) {
    cache.set(model, (async () => {
      const m = await (await fetch(`/api/v1/wind/manifest?model=${model}`, { credentials: "same-origin" })).json();
      if (m.unavailable || !m.grid) throw new Error(m.reason ?? "Wind unavailable");
      const buf = await (await fetch(String(m.gridUrl).replace("/api/wind/", "/api/v1/wind/"), { credentials: "same-origin" })).arrayBuffer();
      const vals = new Float32Array(buf);
      const n = m.grid.nx * m.grid.ny;
      return { ...m.grid, u: vals.slice(0, n), v: vals.slice(n, 2 * n), validIso: m.cycle?.validIso };
    })().catch((e) => {
      cache.delete(model);
      throw e;
    }));
  }
  return cache.get(model)!;
}

/** Animated wind flow (FR-WX-04): particles advected through the GFS / IFS 10 m wind field, with fading trails.
 * Paused under prefers-reduced-motion: draws a short static set of streaks. */
export function useWind(map: MlMap | null, enabled: boolean, model: string) {
  useEffect(() => {
    if (!enabled || !map) return;
    const canvas = document.createElement("canvas");
    canvas.style.cssText = "position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:1";
    map.getContainer().appendChild(canvas);
    const g = canvas.getContext("2d")!;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0, stop = false, moving = false, field: WindField | null = null, w = 0, h = 0;
    type P = { x: number; y: number; age: number; life: number };
    let parts: P[] = [];
    const spawn = (p: P) => {
      p.x = Math.random() * w;
      p.y = Math.random() * h;
      p.age = 0;
      p.life = 40 + Math.random() * 80;
      return p;
    };
    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      w = map.getCanvas().clientWidth;
      h = map.getCanvas().clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      const n = Math.min(7000, Math.round((w * h) / 260)); // density independent of screen size
      parts = Array.from({ length: n }, () => spawn({ x: 0, y: 0, age: 0, life: 0 }));
    };
    const clear = () => g.clearRect(0, 0, w, h);
    const onStart = () => { moving = true; clear(); };
    const onEnd = () => { moving = false; parts.forEach(spawn); if (reduce) for (let i = 0; i < 14; i++) frame(true); };
    map.on("movestart", onStart);
    map.on("moveend", onEnd);
    map.on("resize", resize);

    const frame = (once = false) => {
      if (stop || !field) return;
      if (!moving) {
        g.globalCompositeOperation = "destination-in";
        g.fillStyle = "rgba(0,0,0,0.93)"; // trail fade per frame
        g.fillRect(0, 0, w, h);
        g.globalCompositeOperation = "source-over";
        const paths = RAMP.map(() => new Path2D());
        for (const p of parts) {
          const ll = map.unproject([p.x, p.y]);
          const [u, v] = sampleWind(field, ll.lng, ll.lat);
          const nx = p.x + u * 0.2, ny = p.y - v * 0.2; // screen-space step: ~2 px per frame for 10 m/s at any zoom
          const path = paths[bucket(Math.hypot(u, v))];
          path.moveTo(p.x, p.y);
          path.lineTo(nx, ny);
          p.x = nx;
          p.y = ny;
          if (++p.age > p.life || nx < 0 || ny < 0 || nx > w || ny > h) spawn(p);
        }
        g.lineCap = "round";
        paths.forEach((path, i) => {
          g.strokeStyle = RAMP[i][1];
          g.lineWidth = 0.9 + i * 0.18;
          g.stroke(path);
        });
      }
      if (!reduce && !once) raf = requestAnimationFrame(() => frame());
    };
    resize();
    loadField(model).then((f) => {
      field = f;
      const st = useStore.getState();
      st.set({ feeds: { ...st.feeds, wind: { state: "LIVE", last_ok: Date.now() / 1000, error: `${model.toUpperCase()} valid ${f.validIso ?? ""}`, count: 0 } } });
      if (reduce) for (let i = 0; i < 14; i++) frame(true);
      else frame();
    }).catch((e) => useStore.getState().toast(`Wind layer unavailable: ${e.message}. Start the wind service (wind/).`, "WARNING"));
    return () => {
      stop = true;
      cancelAnimationFrame(raf);
      map.off("movestart", onStart);
      map.off("moveend", onEnd);
      map.off("resize", resize);
      canvas.remove();
      const { wind: _, ...feeds } = useStore.getState().feeds;
      useStore.getState().set({ feeds });
    };
  }, [enabled, model, map]);
}
