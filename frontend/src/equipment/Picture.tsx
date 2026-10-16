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

/** Aircraft: top view (recognise the type by its planform). Ground equipment, air defence, radars: 3D-style illustration. */
export function EquipmentPicture({ art, className }: { art: ArtRef; className?: string }) {
  const svg = art.kind === "aircraft"
    ? <AircraftTop spec={AIRCRAFT[art.type] ?? AIRCRAFT[FALLBACK[art.category ?? ""] ?? "Hawk 132"]} label={art.type} />
    : equipmentSvg(art.type);
  return <div className={`equip-pic ${art.kind}${className ? ` ${className}` : ""}`}>{svg}</div>;
}
