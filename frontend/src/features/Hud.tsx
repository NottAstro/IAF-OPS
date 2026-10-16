import { useEffect, useState } from "react";
import { dms } from "../lib/format";
import { MODES, type Mode, useStore } from "../store";
import { ToneText } from "../components/ui";

/** HUD strip: cursor position, zoom and feed health. Keys 1–4 switch map views (FR-MAP-09, FR-MAP-11). */
export function Hud() {
  const s = useStore();
  const [dd, setDd] = useState(false);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select")) return;
      const m = MODES[Number(e.key) - 1]?.id as Mode | undefined;
      if (m && !useStore.getState().selection) useStore.getState().set({ mode: m });
    };
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, []);
  const c = s.cursor;
  const feedTone = (st: string) => (st === "LIVE" ? "ok" : st === "STALE" ? "caution" : "critical");
  return (
    <div className="hud" role="status">
      <span className="hud-item" onClick={() => setDd(!dd)} style={{ cursor: "pointer" }} title="Toggle DMS / decimal">
        {c ? <b>{dd ? `${c.lat.toFixed(4)}, ${c.lon.toFixed(4)}` : dms(c.lat, c.lon)}</b> : "—"}
        {c?.elev != null && <> · elev <b>{Math.round(c.elev).toLocaleString("en-IN")} m</b> / <b>{Math.round(c.elev * 3.28084).toLocaleString("en-IN")} ft</b></>}
      </span>
      <span className="hud-item">zoom <b>{s.camera ? s.camera.zoom.toFixed(1) : "—"}</b></span>
      <span style={{ flex: 1 }} />
      {Object.entries(s.feeds).filter(([name]) => (s.mode === "WX" ? name === "wind" : s.mode === "LIVE" && name !== "wind")).map(([name, f]) => (
        <span key={name} className="feed" title={f.error ?? ""}>
          <ToneText toneName={feedTone(f.state)}>{name}</ToneText>
        </span>
      ))}
    </div>
  );
}
