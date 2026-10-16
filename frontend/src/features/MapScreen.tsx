import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { User } from "../api/types";
import { useStore } from "../store";
import { BasePanel } from "./BasePanel";
import { Hud } from "./Hud";
import { InfoCard } from "./InfoCard";
import { LayerRail } from "./LayerRail";

/** Overlays on the always-mounted map (the map itself lives in the shell). */
export function MapScreen({ user }: { user: User }) {
  const s = useStore();
  const sel = s.selection;
  return (
    <>
      <LayerRail liveTracks={s.liveTracks} />
      {!(sel?.kind === "base") && <Search />}
      {sel?.kind === "base" && <BasePanel baseId={sel.id} user={user} />}
      {sel && sel.kind !== "base" && <InfoCard sel={sel} liveTracks={s.liveTracks} />}
      <Hud />
    </>
  );
}

interface Hit { kind: string; id: number; title: string; subtitle: string; lat: number; lon: number; side?: string; base_id?: number }

function Search() {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const set = useStore((s) => s.set);
  const fly = useStore((s) => s.requestFly);
  const r = useQuery({ queryKey: ["search", q], queryFn: () => api<Hit[]>(`/search?q=${encodeURIComponent(q)}`), enabled: q.trim().length >= 2 });
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === "/" && !(e.target as HTMLElement).closest("input, textarea, select")) {
        e.preventDefault();
        input.current?.focus();
      }
    };
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, []);
  const go = (h: Hit) => {
    if (h.kind === "base") set({ selection: { kind: h.side === "OWN" ? "base" : "public-base", id: h.id }, panelTab: useStore.getState().mode === "INFRA" ? "Bw" : "Ov" });
    else if (h.kind === "aircraft" && h.base_id) set({ selection: { kind: "base", id: h.base_id }, panelTab: "Eq" });
    else if (h.kind === "aircrew") location.assign(`/pilots/${h.id}`);
    fly(h.lat, h.lon, 9);
    setQ("");
  };
  const hits = q.trim().length >= 2 ? r.data ?? [] : [];
  return (
    <div className="search">
      <input ref={input} className="input" placeholder="Search base, ICAO, tail no., aircrew  ( / )" value={q}
        aria-label="Search" onChange={(e) => { setQ(e.target.value); setActive(0); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setActive(Math.min(active + 1, hits.length - 1));
          if (e.key === "ArrowUp") setActive(Math.max(active - 1, 0));
          if (e.key === "Enter" && hits[active]) go(hits[active]);
          if (e.key === "Escape") setQ("");
        }} />
      {hits.length > 0 && (
        <div className="search-results" role="listbox">
          {hits.map((h, i) => (
            <div key={`${h.kind}${h.id}`} role="option" aria-selected={i === active} className={`search-item${i === active ? " active" : ""}`} onMouseDown={() => go(h)}>
              <div>{h.title} <span className="dim" style={{ fontSize: 11 }}>{h.kind}</span></div>
              <div className="muted" style={{ fontSize: 12 }}>{h.subtitle}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
