import type { ReactNode } from "react";
import { Pill } from "../components/ui";
import { type ArtRef, EquipmentPicture } from "../equipment/Picture";
import { tone } from "../lib/format";

export interface GalleryItem { id: number; title: string; status: string; facts: [string, ReactNode][]; actions?: ReactNode }
export interface GalleryType { key: string; name: string; desc?: string; art: ArtRef; items: GalleryItem[]; ready: (status: string) => boolean }
export interface GalleryGroup { title: string; types: GalleryType[] }

/** Status in plain words, for people who don't read S / U/S. */
const PLAIN: Record<string, string> = {
  SERVICEABLE: "ready", AVAILABLE: "ready", OPERATIONAL: "ready", UP: "working", QRA: "on quick reaction alert", STANDBY: "on standby",
  AIRBORNE: "airborne", TURNAROUND: "being turned round", MAINT_SCHEDULED: "in scheduled maintenance", MAINT_UNSCHEDULED: "out of service",
  UNSERVICEABLE: "out of service", UNDER_REPAIR: "under repair", AOG: "grounded (AOG)", DEGRADED: "degraded", OFFLINE: "offline",
  MAINTENANCE: "in maintenance", DEPOT: "at depot", DOWN: "down",
};
const plain = (st: string) => PLAIN[st] ?? st.replace(/_/g, " ").toLowerCase();
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const readyCount = (t: GalleryType) => t.items.filter((i) => t.ready(i.status)).length;

/** Every equipment type at the base as compact tiles, grouped; `onOpen` shows one type's items. */
export function EquipmentTiles({ groups, onOpen }: { groups: GalleryGroup[]; onOpen: (key: string) => void }) {
  return (
    <>
      {groups.filter((g) => g.types.length).map((g) => {
        const ok = g.types.reduce((a, t) => a + readyCount(t), 0), total = g.types.reduce((a, t) => a + t.items.length, 0);
        return (
          <section key={g.title} className="eq-group">
            <div className="eq-head"><span>{g.title}</span><span className="eq-head-count"><b>{ok}</b> of {total} ready</span></div>
            <div className="eq-tiles">
              {g.types.map((t) => {
                const r = readyCount(t), pct = t.items.length ? (100 * r) / t.items.length : 0;
                const tn = pct >= 70 ? "ok" : pct >= 45 ? "caution" : "critical";
                return (
                  <button key={t.key} className="eq-tile" onClick={() => onOpen(t.key)} title={`Show each ${t.name}`}>
                    <EquipmentPicture art={t.art} className="pic-thumb" />
                    <span className="eq-name">{t.name}</span>
                    <span className={`eq-count s-${r === t.items.length ? "ok" : tn}`}><b>{r}</b>/{t.items.length}</span>
                    <span className="eq-bar"><i style={{ width: `${pct}%`, background: `var(--${tn})` }} /></span>
                  </button>
                );
              })}
            </div>
          </section>
        );
      })}
    </>
  );
}

/** One equipment type: what it is, how many are ready, and a card for each individual item. */
export function EquipmentDetail({ t, backLabel, onBack }: { t: GalleryType; backLabel: string; onBack: () => void }) {
  const ok = readyCount(t);
  const notReady = new Map<string, number>();
  for (const i of t.items) if (!t.ready(i.status)) notReady.set(i.status, (notReady.get(i.status) ?? 0) + 1);
  return (
    <section className="gallery">
      <button className="gallery-back" onClick={onBack}>‹ {backLabel}</button>
      <div className="gallery-head">
        <div>
          <div className="gallery-title">{t.name}</div>
          {t.desc && <div className="muted" style={{ fontSize: 12.5 }}>{t.desc}</div>}
          {notReady.size > 0 && <div className="type-status" style={{ marginTop: 4 }}>
            {[...notReady.entries()].map(([st, n]) => <span key={st} className={`s-${tone(st).tone}`}>{n} {plain(st)}</span>)}
          </div>}
        </div>
        <div className="count-big"><b>{ok}</b> of {t.items.length}<span>ready</span></div>
      </div>
      <div className="item-grid">
        {t.items.map((i) => (
          <article key={i.id} className={`item-card tone-${tone(i.status).tone}`}>
            <EquipmentPicture art={t.art} className="pic-item" />
            <div className="item-title"><span className="mono">{i.title}</span><Pill status={i.status} text={cap(plain(i.status))} /></div>
            {i.facts.length > 0 && <dl className="item-facts">{i.facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>}
            {i.actions && <div className="item-actions">{i.actions}</div>}
          </article>
        ))}
      </div>
    </section>
  );
}
