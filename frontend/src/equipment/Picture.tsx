import { type ReactElement, useEffect, useState } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AIRCRAFT, type AircraftSpec, AircraftArt, aircraftBox } from "./aircraft";
import { equipmentSvg } from "./models";

export type ArtRef = { kind: "aircraft"; type: string; category?: string } | { kind: "ground"; type: string };

const FALLBACK: Record<string, string> = { FIXED_WING: "Hawk 132", ROTARY_WING: "Dhruv", UAV_FIXED_WING: "Searcher Mk II", UAV_ROTARY_SMALL: "Small UAS (generic)" };

function AircraftTop({ spec, label }: { spec: AircraftSpec; label: string }) {
  const [w, h] = aircraftBox(spec);
  const m = Math.max(w, h) * 0.06;
  return (
    <svg viewBox={`${-w / 2 - m} ${-0.6 - m} ${w + 2 * m} ${h + 2 * m + 0.6}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label={`Top view of ${label}`}>
      <defs>
        <linearGradient id="bp-glass" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#7fb0dc" /><stop offset="0.45" stopColor="#2f6297" /><stop offset="1" stopColor="#163d66" />
        </linearGradient>
      </defs>
      <AircraftArt spec={spec} />
    </svg>
  );
}

// Each drawing is rasterised once per type into a PNG (with the aircraft drop shadow baked in). Inline SVG, and even
// SVG <img>, was re-rasterised on every scroll frame, which made the Inventory tables and type cards stutter.
const SIZE = 360;  // px on the long side: sharp up to the largest use (type card / header, about 2× on hi-dpi)
const done = new Map<string, string>();
const pending = new Map<string, Promise<string>>();

function rasterise(key: string, draw: () => ReactElement | null, shadow: boolean): Promise<string> {
  let p = pending.get(key);
  if (p) return p;
  p = new Promise<string>((resolve) => {
    const el = draw();
    if (!el) return resolve("");
    const css = getComputedStyle(document.documentElement);  // an image can't see the page's CSS variables
    let svg = renderToStaticMarkup(el).replace(/var\((--[\w-]+)\)/g, (_, v: string) => css.getPropertyValue(v).trim());
    const vb = /viewBox="([^"]+)"/.exec(svg)?.[1].split(/[\s,]+/).map(Number) ?? [0, 0, 4, 3];
    const k = SIZE / Math.max(vb[2], vb[3]), w = Math.round(vb[2] * k), h = Math.round(vb[3] * k);
    svg = svg.replace("<svg", `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"`);
    const img = new Image();
    img.onload = () => {
      const pad = shadow ? 14 : 0, c = document.createElement("canvas");
      c.width = w + 2 * pad; c.height = h + 2 * pad;
      const g = c.getContext("2d")!;
      if (shadow) { g.shadowColor = "rgba(0,0,0,0.5)"; g.shadowBlur = 12; g.shadowOffsetY = 5; }
      g.drawImage(img, pad, pad, w, h);
      c.toBlob((b) => resolve(b ? URL.createObjectURL(b) : ""), "image/png");
    };
    img.onerror = () => resolve("");
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  }).then((url) => { done.set(key, url); return url; });
  pending.set(key, p);
  return p;
}

/** Aircraft: top view (recognise the type by its planform). Ground equipment, air defence, radars: 3D-style illustration. */
export function EquipmentPicture({ art, className }: { art: ArtRef; className?: string }) {
  const key = art.kind === "aircraft" ? `a|${art.type}|${art.category ?? ""}` : `g|${art.type}`;
  const [url, setUrl] = useState(() => done.get(key));
  useEffect(() => {
    const ready = done.get(key);
    if (ready !== undefined) return void setUrl(ready);
    let live = true;
    rasterise(key, art.kind === "aircraft"
      ? () => <AircraftTop spec={AIRCRAFT[art.type] ?? AIRCRAFT[FALLBACK[art.category ?? ""] ?? "Hawk 132"]} label={art.type} />
      : () => equipmentSvg(art.type), art.kind === "aircraft").then((u) => live && setUrl(u));
    return () => { live = false; };
  }, [key]);  // `art` is fully described by `key`
  return (
    <div className={`equip-pic ${art.kind}${className ? ` ${className}` : ""}`}>
      {url && <img src={url} alt={art.kind === "aircraft" ? `Top view of ${art.type}` : art.type} draggable={false} />}
    </div>
  );
}
