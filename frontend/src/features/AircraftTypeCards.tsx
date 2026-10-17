import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { AircraftTypeCount, Row } from "../api/types";
import { ErrorText, Loading } from "../components/ui";
import { EquipmentPicture } from "../equipment/Picture";
import { num } from "../lib/format";

/** Counts per aircraft type for Inventory → Aircraft. `filters` is the list's base / command query string. */
export const useAircraftTypeCounts = (filters: string) =>
  useQuery({
    queryKey: ["inv", "aircraft", "by-type", filters], // under ["inv", "aircraft"]: every aircraft mutation refreshes it
    queryFn: () => api<AircraftTypeCount[]>(`/inv/aircraft/by-type?${filters}`),
  });

const GROUPS: [string, string[]][] = [
  ["Aircraft", ["FIXED_WING"]], ["Helicopters", ["ROTARY_WING"]], ["UAVs & drones", ["UAV_FIXED_WING", "UAV_ROTARY_SMALL"]],
];
export const ROLE: Record<string, string> = {
  FIGHTER_MULTIROLE: "Multirole fighter", AIR_SUPERIORITY: "Air superiority fighter", STRIKE: "Strike aircraft",
  TRAINER_BASIC: "Basic trainer", TRAINER_INTERMEDIATE: "Intermediate jet trainer", TRAINER_ADVANCED: "Advanced jet trainer",
  TRANSPORT_STRATEGIC: "Strategic airlifter", TRANSPORT_TACTICAL: "Tactical transport", TRANSPORT_LIGHT: "Light transport",
  VIP_TRANSPORT: "VIP transport", TANKER: "Air-to-air refueller", AEW_C: "Airborne early warning and control",
  ISR: "Surveillance and reconnaissance", UTILITY_HELO: "Utility helicopter", ATTACK_HELO: "Attack helicopter",
  HEAVY_LIFT_HELO: "Heavy-lift helicopter", LIGHT_HELO: "Light utility helicopter", UAV_MALE: "Medium-altitude long-endurance UAV",
  UAV_TACTICAL: "Tactical UAV", SMALL_UAS: "Small drone",
};
const plural = (n: number, word: string) => `${num(n)} ${word}${n === 1 ? "" : "s"}`;

/** Glyph + word + colour, never colour alone (DESIGN_SYSTEM §12). Serviceable here excludes QRA so the bar adds up. */
function parts(t: AircraftTypeCount) {
  return [
    { key: "svc", word: "Serviceable", n: t.serviceable, bar: t.serviceable - t.qra, color: "ok", glyph: "●" },
    { key: "qra", word: "QRA", n: t.qra, bar: t.qra, color: "qra", glyph: "◉" },
    { key: "mnt", word: "Maintenance", n: t.maintenance, bar: t.maintenance, color: "caution", glyph: "▲" },
    { key: "us", word: "U/S", n: t.unserviceable, bar: t.unserviceable, color: "warning", glyph: "◆" },
    { key: "dep", word: "Depot", n: t.depot, bar: t.depot, color: "neutral", glyph: "—" },
  ];
}

function StatusBar({ t }: { t: AircraftTypeCount }) {
  const p = parts(t);
  const said = p.filter((x) => x.n > 0).map((x) => `${x.n} ${x.word.toLowerCase()}`).join(", ");
  return (
    <span className="ac-bar" role="img" aria-label={said || "No aircraft"}>
      {t.total > 0 && p.map((x) => x.bar > 0 && <i key={x.key} style={{ width: `${(100 * x.bar) / t.total}%`, background: `var(--${x.color})` }} />)}
    </span>
  );
}

function StatusCounts({ t }: { t: AircraftTypeCount }) {
  return (
    <span className="ac-stats">
      {parts(t).filter((x) => x.key !== "dep" || x.n > 0).map((x) => (
        <span key={x.key} className={x.n ? "" : "zero"}>
          <span className="ac-stat-word"><span aria-hidden style={{ color: `var(--${x.color})` }}>{x.glyph} </span>{x.word}</span>
          <b className="mono" style={x.n ? { color: `var(--${x.color})` } : undefined}>{num(x.n)}</b>
        </span>
      ))}
    </span>
  );
}

/** Inventory → Aircraft: one card per aircraft type that has aircraft, grouped like the base panel's equipment tiles. */
export function AircraftTypeCards({ filters, search }: { filters: string; search: string }) {
  const q = useAircraftTypeCounts(filters);
  if (q.error) return <ErrorText error={q.error} />;
  if (q.isLoading || !q.data) return <Loading />;
  const s = search.trim().toLowerCase();
  const shown = q.data.filter((t) => (t.total > 0 || t.retired > 0) && (!s || `${t.name} ${ROLE[t.role] ?? ""}`.toLowerCase().includes(s)));
  if (!shown.length) return <div className="empty">{s ? `No aircraft type matches "${search.trim()}".` : "No aircraft match these filters."}</div>;
  const all = shown.reduce((a, t) => a + t.total, 0), svc = shown.reduce((a, t) => a + t.serviceable, 0);
  return (
    <>
      <div className="ac-summary muted">
        {plural(shown.length, "type")} · <b className="mono">{num(all)}</b> aircraft · <b className="mono">{num(svc)}</b> serviceable
      </div>
      {GROUPS.map(([title, cats]) => {
        const types = shown.filter((t) => cats.includes(t.category)).sort((a, b) => b.total - a.total || a.name.localeCompare(b.name));
        if (!types.length) return null;
        return (
          <section key={title} className="ac-group" aria-label={title}>
            <h2 className="ac-group-title">{title}<span className="mono">{num(types.reduce((a, t) => a + t.total, 0))}</span></h2>
            <div className="ac-grid">
              {types.map((t) => (
                <Link key={t.id} to={`/inventory/aircraft/${t.id}`} className="ac-card" aria-label={`${t.name}: ${num(t.total)} aircraft. View aircraft`}>
                  <EquipmentPicture art={{ kind: "aircraft", type: t.name, category: t.category }} className="pic-type ac-pic" />
                  <span className="ac-head">
                    <span className="ac-name">{t.name}</span>
                    <span className="ac-total mono" title="Aircraft (not counting retired)">{num(t.total)}</span>
                  </span>
                  <span className="ac-sub">{ROLE[t.role] ?? t.role} · {plural(t.squadrons, "squadron")}</span>
                  <StatusBar t={t} />
                  <StatusCounts t={t} />
                  <span className="ac-foot">
                    {t.retired > 0 ? <span className="dim">{num(t.retired)} retired</span> : <span />}
                    <span className="ac-view">View aircraft ›</span>
                  </span>
                </Link>
              ))}
            </div>
          </section>
        );
      })}
    </>
  );
}

/** Header of one type's aircraft list: breadcrumb, back, picture, name and the same counts as its card. */
export function AircraftTypeHeader({ typeId, filters }: { typeId: string; filters: string }) {
  const type = useQuery({ queryKey: ["aircraft-type", typeId], queryFn: () => api<Row>(`/inv/aircraft-types/${typeId}`), staleTime: Infinity });
  const counts = useAircraftTypeCounts(filters);
  const name = type.data ? String(type.data.name) : "…";
  const t = counts.data?.find((x) => String(x.id) === typeId);
  return (
    <div className="ac-detail-head">
      <div className="ac-crumbs-row">
        <nav className="crumbs" aria-label="Breadcrumb">
          <Link to="/inventory/aircraft">Inventory</Link><span aria-hidden> › </span>
          <Link to="/inventory/aircraft">Aircraft</Link><span aria-hidden> › </span>
          <span aria-current="page">{name}</span>
        </nav>
        <Link to="/inventory/aircraft" className="btn">‹ Back to aircraft types</Link>
      </div>
      {type.error && <ErrorText error={type.error} />}
      {type.data && (
        <div className="ac-detail">
          <EquipmentPicture art={{ kind: "aircraft", type: name, category: String(type.data.category) }} className="pic-type ac-detail-pic" />
          <div className="ac-detail-text">
            <div className="ac-detail-title">
              <h2>{name}</h2>
              <span className="ac-total mono">{t ? `${num(t.total)} aircraft` : "0 aircraft"}</span>
            </div>
            <div className="ac-sub">
              {ROLE[String(type.data.role)] ?? String(type.data.role)}
              {t && ` · ${plural(t.squadrons, "squadron")}`}
              {t && t.retired > 0 && ` · ${num(t.retired)} retired`}
            </div>
            {t && <><StatusBar t={t} /><StatusCounts t={t} /></>}
          </div>
        </div>
      )}
    </div>
  );
}
