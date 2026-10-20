import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { AircraftTypeCount, Base, ColumnMeta, EntityMeta, Page, Row, User } from "../api/types";
import { ErrorText, Gauge, Loading, Modal, Pill, Sim, ToneText } from "../components/ui";
import { type ArtRef, EquipmentPicture } from "../equipment/Picture";
import { AircraftTypeCards, AircraftTypeHeader, ROLE } from "../features/AircraftTypeCards";
import { istTime, label, num } from "../lib/format";
import "./Inventory.css";

const ic = (d: ReactNode) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>{d}</svg>;
/** Navigation groups only: records keep their existing routes, queries, forms and permissions. Each category card shows an
 * icon and one headline count, summed over `count` (D80, D81). */
const GROUPS: { label: string; icon: ReactNode; count: string[]; word: string; entities: [string, string][] }[] = [
  { label: "Fleet", count: ["aircraft"], word: "aircraft",
    icon: ic(<path fill="currentColor" stroke="none" d="M12 2.5l1.5 6.3 7.5 4.4v1.9l-7.5-2.3-.4 5.5 2.7 2v1.4L12 20.7l-3.8 1v-1.4l2.7-2-.4-5.5L3 15.1v-1.9l7.5-4.4z" />),
    entities: [["aircraft", "Aircraft"], ["squadrons", "Squadrons"], ["aircraft-types", "Specifications"]] },
  { label: "Personnel", count: ["aircrew", "ground-crew"], word: "people",
    icon: ic(<><circle cx="9" cy="8" r="3.2" /><path d="M3 20c0-3.4 2.7-6 6-6s6 2.6 6 6" /><circle cx="17" cy="9" r="2.4" /><path d="M16 14.1c2.8.3 5 2.6 5 5.9" /></>),
    entities: [["aircrew", "Aircrew"], ["ground-crew", "Ground crew"]] },
  { label: "Logistics & support", count: ["ground-assets"], word: "vehicles & GSE",
    icon: ic(<><path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z" /><path d="M3 7.5 12 12l9-4.5M12 12v9" /></>),
    entities: [["fuel-storage", "Fuel storage"], ["fuel-transactions", "Fuel activity"], ["ground-assets", "Vehicles & GSE"], ["warehouses", "Warehouses"],
      ["stock-levels", "Stock levels"], ["stock-items", "Stock catalogue"]] },
  { label: "Defence & comms", count: ["radars", "ad-batteries"], word: "radar & AD sites",
    icon: ic(<><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.5" /><path d="M12 12l6-6" /><circle cx="12" cy="12" r="1" fill="currentColor" /></>),
    entities: [["ad-batteries", "AD batteries"], ["radars", "Radars"], ["comms-nodes", "Comms nodes"], ["ad-system-types", "AD specifications"],
      ["radar-types", "Radar specifications"]] },
  { label: "Bases & infrastructure", count: ["bases?side=OWN"], word: "IAF bases",
    icon: ic(<><path d="M3 20V11.5a9 9 0 0 1 18 0V20" /><path d="M2 20h20M8.5 20v-5h7v5" /></>),
    entities: [["bases", "Bases"], ["runways", "Runways"], ["parking", "Parking"]] },
];

/** Headline totals for the category cards, kept under ["inv", entity] so every edit refreshes them. A count may carry a
 * filter ("bases?side=OWN"); aircraft come from the per-type summary, so retired airframes are left out as on the cards. */
function useGroupCounts() {
  const ids = GROUPS.flatMap((g) => g.count);
  const qs = useQueries({ queries: ids.map((e) => {
    const [entity, filter = ""] = e.split("?");
    return { queryKey: ["inv", entity, "total", filter], staleTime: 60000,
      queryFn: () => entity === "aircraft"
        ? api<AircraftTypeCount[]>("/inv/aircraft/by-type").then((ts) => ts.reduce((a, t) => a + t.total, 0))
        : api<Page<Row>>(`/inv/${entity}?${filter}${filter ? "&" : ""}page=1&page_size=1`).then((p) => p.total) };
  }) });
  const by = Object.fromEntries(ids.map((e, i) => [e, qs[i].data])) as Record<string, number | undefined>;
  return (g: (typeof GROUPS)[number]) => (g.count.some((e) => by[e] == null) ? null : g.count.reduce((a, e) => a + (by[e] ?? 0), 0));
}
/** Entities whose rows get a top-view thumbnail, and how to find the type for each row. */
type Labels = Page<Row>["labels"];
const fk = (l: Labels, col: string, r: Row) => l?.[col]?.[String(r[col])];
const ART: Record<string, (r: Row, l: Labels) => ArtRef | null> = {
  aircraft: (r, l) => (fk(l, "aircraft_type_id", r) ? { kind: "aircraft", type: fk(l, "aircraft_type_id", r)! } : null),
  "aircraft-types": (r) => ({ kind: "aircraft", type: String(r.name), category: String(r.category) }),
  "ground-assets": (r) => ({ kind: "ground", type: String(r.asset_type) }),
  "ad-batteries": (r, l) => (fk(l, "ad_system_type_id", r) ? { kind: "ground", type: fk(l, "ad_system_type_id", r)! } : null),
  radars: (r, l) => (fk(l, "radar_type_id", r) ? { kind: "ground", type: fk(l, "radar_type_id", r)! } : null),
};
/** Never shown as columns: bookkeeping, the internal id and map geometry (D81). */
const HIDE = new Set(["created_at", "updated_at", "version", "is_simulated", "source", "source_ref", "simulated", "password_hash", "id", "geom"]);
const STATUS_COLS = ["status", "duty_status", "medical_status", "ops_status"];

function canWrite(user: User, meta: EntityMeta, baseId: unknown): boolean {
  if (meta.readonly) return false;
  if (user.role === "ADMIN") return true;
  if (meta.admin_only || (!meta.scope && meta.entity !== "fuel-transactions" && meta.entity !== "stock-levels")) return false;
  return user.role === "BASE_COMMANDER" && (baseId === undefined || baseId === user.base_id);
}

/** Stock held against a maximum (D81): a gauge with reserve / reorder marks replaces four number columns, plus a state. */
interface Level { value: string; max: string; reserve?: string; reorder?: string; kl: boolean; hide: string[] }
const LEVEL: Record<string, Level> = {
  "fuel-storage": { value: "current_l", max: "capacity_l", reserve: "reserve_l", reorder: "reorder_l", kl: true,
    hide: ["current_l", "capacity_l", "reserve_l", "reorder_l"] },
  "stock-levels": { value: "qty_on_hand", max: "max_level", reorder: "reorder_level", kl: false, hide: ["qty_on_hand", "max_level", "reorder_level"] },
};
const levelState = (lv: Level, r: Row): [string, string] => {
  const v = Number(r[lv.value]);
  return lv.reserve && v < Number(r[lv.reserve]) ? ["critical", "Below reserve"] : lv.reorder && v < Number(r[lv.reorder]) ? ["caution", "Reorder"] : ["ok", "OK"];
};
const kl = (l: unknown) => num(Number(l) / 1000, 1);

/** Column headers in words, with units in brackets: "capacity_l" → "Capacity (kL)" (litres shown as kL), "ts" → "Time". */
const HEAD: Record<string, string> = { ts: "Time", iata: "IATA", icao_type: "ICAO type", country_iso3: "Country", qty_reserved: "Reserved",
  reg_or_serial: "Reg / serial", burn_kg_per_h: "Burn (kg/h)", quantity_l: "Quantity (kL)", balance_after_l: "Balance after (kL)" };
const UNIT: [RegExp, string][] = [[/_l$/, " (kL)"], [/_kg$/, " (kg)"], [/_kt$/, " (kt)"], [/_km$/, " (km)"], [/_m$/, " (m)"], [/_h$/, " (h)"], [/_pct$/, " (%)"]];
function head(name: string) {
  if (HEAD[name]) return HEAD[name];
  const u = UNIT.find(([re]) => re.test(name));
  const base = label((u ? name.replace(u[0], "") : name).replace(/_id$/, "")).replace(/\beta\b/i, "ETA");
  return u ? base + u[1] : base;
}
/** "FUEL_BOWSER" → "Fuel bowser" inside any text (labels too: "VABJ · DIESEL_HSD"); codes without an underscore stay. */
const words = (s: string) => s.replace(/\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g, (m) => label(m));
const OUTFLOW = /ISSUE|TRANSFER_OUT|DEFUEL/;
/** Text columns that hold words in capitals ("AMBULANCE", "SIMULATOR"), shown as words; codes elsewhere (VIAX) stay. */
const CAPS_TEXT = new Set(["asset_type", "actor"]);
const capsWord = (x: string) => (/^[A-Z][A-Z_]+$/.test(x) ? label(x) : x);

function cell(c: ColumnMeta, v: unknown, r: Row, labels?: Record<string, Record<string, string>>) {
  if (v === null || v === undefined || v === "") return <span className="dim">—</span>;
  if (c.fk && labels?.[c.name]?.[String(v)]) return words(labels[c.name][String(v)]);
  if (STATUS_COLS.includes(c.name)) return <Pill status={String(v)} text={label(String(v))} />;
  if (c.name === "role" && ROLE[String(v)]) return ROLE[String(v)];
  if (c.name === "quantity_l") {   // fuel activity: receipts in, issues and transfers out
    const out = OUTFLOW.test(String(r.kind));
    return <span className={out ? "" : "s-ok"}>{out ? "−" : "+"}{kl(Math.abs(Number(v)))}</span>;
  }
  if (c.type === "bool") return v ? "Yes" : "No";
  if (c.type === "datetime") return <span className="mono">{istTime(String(v), true)}</span>;
  if (/_l$/.test(c.name) && (c.type === "float" || c.type === "int")) return kl(v);
  if (c.type === "float" || c.type === "int") return num(v, c.type === "float" ? 1 : 0);
  if (c.type === "enum") return label(String(v));
  if (Array.isArray(v)) return v.map((x) => capsWord(String(x))).join(", ");
  if (CAPS_TEXT.has(c.name)) return capsWord(String(v));
  return words(String(v));
}

/** Fuel at a glance (D81): one card per grade over the filtered tanks: on hand of capacity, and how many tanks are at reorder
 * or below reserve. */
function FuelSummary({ filters }: { filters: string }) {
  const q = useQuery({ queryKey: ["inv", "fuel-storage", "summary", filters], staleTime: 30000,
    queryFn: () => api<Page<Row>>(`/inv/fuel-storage?${filters}&page=1&page_size=500`) });
  if (!q.data) return null;
  const grades = [...new Set(q.data.items.map((r) => String(r.grade)))].sort();
  const lv = LEVEL["fuel-storage"];
  return (
    <div className="fuel-sum">
      {grades.map((g) => {
        const rs = q.data.items.filter((r) => r.grade === g);
        const on = rs.reduce((a, r) => a + Number(r.current_l), 0), cap = rs.reduce((a, r) => a + Number(r.capacity_l), 0);
        const states = rs.map((r) => levelState(lv, r)[1]);
        const low = states.filter((x) => x === "Below reserve").length, re = states.filter((x) => x === "Reorder").length;
        const pct = Math.round((100 * on) / Math.max(cap, 1));
        return (
          <div key={g} className="fuel-card">
            <div className="fuel-card-top"><b>{label(g)}</b><span className="mono">{pct}%</span></div>
            <div className="fuel-bar"><i style={{ width: `${pct}%`, background: `var(--${low ? "critical" : re ? "caution" : "ok"})` }} /></div>
            <div className="fuel-card-sub"><span className="mono">{kl(on)} of {kl(cap)} kL</span>
              <span>{rs.length} tanks{re > 0 && <> · <ToneText toneName="caution">{re} at reorder</ToneText></>}
                {low > 0 && <> · <ToneText toneName="critical">{low} below reserve</ToneText></>}
                {!re && !low && <> · <span className="s-ok">all above reorder</span></>}</span></div>
          </div>
        );
      })}
    </div>
  );
}

export function Inventory({ user }: { user: User }) {
  const { entity = "aircraft", typeId: typeParam } = useParams();
  const typeId = entity === "aircraft" ? typeParam : undefined;
  const typeCards = entity === "aircraft" && !typeId; // Aircraft opens on one card per type; a card opens that type's table
  const group = GROUPS.find((g) => g.entities.some(([id]) => id === entity));
  const nav = useNavigate();
  const qc = useQueryClient();
  const countOf = useGroupCounts();
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("id");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [search, setSearch] = useState("");
  const [baseFilter, setBaseFilter] = useState(user.role === "BASE_COMMANDER" && user.base_id ? String(user.base_id) : "");
  const [statusFilter, setStatusFilter] = useState("");
  const [command, setCommand] = useState("");
  const [typeSearch, setTypeSearch] = useState("");
  const [editing, setEditing] = useState<Row | "new" | null>(null);
  useEffect(() => { setPage(1); setSearch(""); setStatusFilter(""); setSort("id"); setOrder("asc"); setEditing(null); }, [entity, typeId]);
  const selectEntity = (next: string) => {
    if (next === entity && !typeId) return;
    setPage(1); setSearch(""); setStatusFilter(""); setSort("id"); setOrder("asc"); setEditing(null);
    nav(`/inventory/${next}`);
  };
  const meta = useQuery({ queryKey: ["meta", entity], queryFn: () => api<EntityMeta>(`/inv/${entity}/meta`), staleTime: Infinity });
  const bases = useQuery({ queryKey: ["bases"], queryFn: () => api<Base[]>("/bases"), staleTime: Infinity });
  const statusCol = meta.data?.columns.find((c) => STATUS_COLS.includes(c.name) && c.type === "enum");
  const params = new URLSearchParams({ page: String(page), page_size: "50", sort, order, q: search, command });
  if (baseFilter && meta.data?.scope) params.set(meta.data.scope, baseFilter);
  if (statusFilter && statusCol) params.set(statusCol.name, statusFilter);
  const typeFilters = new URLSearchParams({ command }); // the base / command filters, shared by the cards and the type header
  if (baseFilter && meta.data?.scope) typeFilters.set(meta.data.scope, baseFilter);
  if (typeId) params.set("aircraft_type_id", typeId);
  const list = useQuery({
    queryKey: ["inv", entity, params.toString()], queryFn: () => api<Page<Row>>(`/inv/${entity}?${params}`),
    enabled: !!meta.data && !typeCards, placeholderData: keepPreviousData,
  });
  const lv = LEVEL[entity];
  const allCols = useMemo(() => (meta.data?.columns ?? []).filter((c) => !HIDE.has(c.name) && c.type !== "geometry" && c.type !== "point"
    && !lv?.hide.includes(c.name)), [meta.data, lv]);
  // columns with nothing in them on this page say nothing, so they go (D81)
  const cols = useMemo(() => {
    const items = list.data?.items ?? [];
    return (items.length ? allCols.filter((c) => items.some((r) => r[c.name] != null && r[c.name] !== "" && !(Array.isArray(r[c.name]) && !(r[c.name] as unknown[]).length)))
      : allCols).slice(0, 11);
  }, [allCols, list.data]);
  const remove = useMutation({
    mutationFn: ({ row, kind }: { row: Row; kind: "retire" | "delete" }) =>
      api(`/inv/${entity}/${row.id}${kind === "retire" ? "/retire" : ""}`, { method: kind === "retire" ? "POST" : "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["inv", entity] }),
    onError: (e) => alert(e instanceof ApiError ? e.message : "Failed"),
  });
  const exportCsv = async () => {
    const all = await api<Page<Row>>(`/inv/${entity}?${new URLSearchParams({ ...Object.fromEntries(params), page: "1", page_size: "500" })}`);
    const names = (meta.data?.columns ?? []).filter((c) => !HIDE.has(c.name) && c.type !== "geometry" && c.type !== "point").map((c) => c.name);
    const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = ["# SIMULATED DATA — SIH 2026 DEMO — NOT REAL", names.join(","), ...all.items.map((r) => names.map((h) => esc(r[h])).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `${entity}${typeId ? `-type-${typeId}` : ""}.csv`;
    a.click();
  };
  const scopeVal = (r: Row) => (meta.data?.scope ? r[meta.data.scope] : undefined);
  const sortBy = (name: string) => { if (sort === name) setOrder(order === "asc" ? "desc" : "asc"); else { setSort(name); setOrder("asc"); } };
  const thSort = (name: string, text: string, right: boolean) => (
    <th key={name} className={right ? "right" : ""} aria-sort={sort === name ? (order === "asc" ? "ascending" : "descending") : "none"} onClick={() => sortBy(name)}>
      {text}{sort === name ? (order === "asc" ? " ▲" : " ▼") : ""}</th>
  );
  const levelAt = lv ? Math.max(0, cols.findIndex((c) => c.type === "enum" || c.fk) + 1) : -1;   // the gauge sits after the leading text columns
  return (
    <div className="page">
      <h1 className="page-title">Inventory <Sim /></h1>
      {/* row 1: category tabs; row 2: the category's records, search, filters and actions (D81, D83) */}
      <nav className="inv-tabs" aria-label="Inventory categories">
        {GROUPS.map((g) => {
          const n = countOf(g);
          return (
            <button key={g.label} className={`inv-tab${g === group ? " on" : ""}`} aria-current={g === group ? "page" : undefined}
              title={n == null ? undefined : `${num(n)} ${g.word}`} onClick={() => { if (g !== group) selectEntity(g.entities[0][0]); }}>
              {g.icon}<span>{g.label}</span><span className="inv-tab-n">{n == null ? "…" : num(n)}</span>
            </button>
          );
        })}
      </nav>
      {meta.error && <ErrorText error={meta.error} />}
      <div className="inv-bar">
        {group && <nav className="inv-subs" aria-label={`${group.label} records`}>
          {group.entities.map(([id, name]) => <button key={id} className={`inv-sub${id === entity ? " on" : ""}`}
            aria-current={id === entity ? "page" : undefined} onClick={() => selectEntity(id)}>{name}</button>)}
        </nav>}
        {meta.data && <>
          <span className="inv-sep" aria-hidden />
          {(typeCards || meta.data.search.length > 0) && (
            <label className="inv-search">{ic(<><circle cx="10.5" cy="10.5" r="6" /><path d="m15 15 5 5" /></>)}
              {typeCards
                ? <input placeholder="Search aircraft type" value={typeSearch} onChange={(e) => setTypeSearch(e.target.value)} aria-label="Search aircraft type" />
                : <input placeholder={`Search ${meta.data.search.map((k) => head(k).toLowerCase()).join(", ")}`} value={search}
                    onChange={(e) => { setSearch(e.target.value); setPage(1); }} aria-label="Search" />}
            </label>
          )}
          {meta.data.scope && (
            <select className={`inv-filter${baseFilter ? " on" : ""}`} value={baseFilter} onChange={(e) => { setBaseFilter(e.target.value); setPage(1); }} aria-label="Base">
              <option value="">All bases</option>
              {(bases.data ?? []).filter((b) => b.side === "OWN").map((b) => <option key={b.id} value={b.id}>{b.code} {b.name.replace("Air Force Station ", "")}</option>)}
            </select>
          )}
          {meta.data.scope && (
            <select className={`inv-filter${command ? " on" : ""}`} value={command} onChange={(e) => { setCommand(e.target.value); setPage(1); }} aria-label="Command">
              <option value="">All commands</option>{["WAC", "SWAC", "CAC", "EAC", "SAC", "TC", "MC"].map((c) => <option key={c}>{c}</option>)}
            </select>
          )}
          {statusCol && !typeCards && (
            <select className={`inv-filter${statusFilter ? " on" : ""}`} value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }} aria-label="Status">
              <option value="">Any {label(statusCol.name).toLowerCase()}</option>{statusCol.values?.map((v) => <option key={v} value={v}>{label(v)}</option>)}
            </select>
          )}
          {(search || typeSearch || statusFilter || command || (baseFilter && user.role !== "BASE_COMMANDER")) && (
            <button className="inv-clear" onClick={() => { setSearch(""); setTypeSearch(""); setStatusFilter(""); setCommand("");
              if (user.role !== "BASE_COMMANDER") setBaseFilter(""); setPage(1); }}>× Clear</button>
          )}
          <div className="inv-actions">
          {meta.data.readonly && <span className="inv-ro" title={`${meta.data.label} are maintained by the system`}>read only</span>}
          <button className="inv-act" onClick={exportCsv} disabled={user.role === "VIEWER"} title={user.role === "VIEWER" ? "Viewers can't export" : "Export the filtered view (max 500 rows)"}>
            {ic(<path d="M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M5 19.5h14" />)}Export CSV</button>
          {canWrite(user, meta.data, undefined) && <button className="inv-act primary" onClick={() => setEditing("new")}>
            {ic(<path d="M12 5v14M5 12h14" />)}New {meta.data.label.toLowerCase().replace(/s$/, "")}</button>}
          </div>
        </>}
      </div>
      {meta.data && (
        <>
          {typeId && <AircraftTypeHeader typeId={typeId} filters={typeFilters.toString()} />}
          {entity === "fuel-storage" && <FuelSummary filters={typeFilters.toString()} />}
          {typeCards ? <AircraftTypeCards filters={typeFilters.toString()} search={typeSearch} /> : <>
          <div className="table-wrap">
            <table className="table">
              <thead><tr>
                {ART[entity] && <th aria-label="Top view" />}
                {cols.flatMap((c, i) => [
                  ...(i === levelAt && lv ? [thSort(lv.value, lv.kl ? "Level (kL)" : "Level", false), <th key="state">State</th>] : []),
                  thSort(c.name, head(c.name), !c.fk && (c.type === "int" || c.type === "float")),
                ])}
                <th />
              </tr></thead>
              <tbody>
                {list.data?.items.map((r) => (
                  <tr key={r.id}>
                    {ART[entity] && <td className="tv-cell">{(() => { const a = ART[entity](r, list.data?.labels); return a && <EquipmentPicture art={a} className="pic-thumb" />; })()}</td>}
                    {cols.flatMap((c, i) => [
                      ...(i === levelAt && lv ? [
                        <td key="level" className="lvl-cell"><div className="lvl">
                          <Gauge value={Number(r[lv.value])} max={Number(r[lv.max])} reserve={lv.reserve ? Number(r[lv.reserve]) : undefined}
                            reorder={lv.reorder ? Number(r[lv.reorder]) : undefined} />
                          <span className="mono">{lv.kl ? kl(r[lv.value]) : num(r[lv.value])} / {lv.kl ? kl(r[lv.max]) : num(r[lv.max])}</span>
                          <span className="mono dim">{Math.round((100 * Number(r[lv.value])) / Math.max(Number(r[lv.max]), 1))}%</span></div></td>,
                        <td key="state">{(() => { const [t, w] = levelState(lv, r); return <ToneText toneName={t}>{w}</ToneText>; })()}</td>] : []),
                      <td key={c.name} className={!c.fk && (c.type === "int" || c.type === "float") ? "num" : ""}>{cell(c, r[c.name], r, list.data?.labels)}</td>,
                    ])}
                    <td style={{ whiteSpace: "nowrap" }}><span className="row-act">
                      {canWrite(user, meta.data, scopeVal(r)) && (
                        <>
                          <button className="btn btn-sm" onClick={() => setEditing(r)}>Edit</button>{" "}
                          {meta.data.retire && <button className="btn btn-sm btn-ghost" onClick={() => confirm(`Retire this record?`) && remove.mutate({ row: r, kind: "retire" })}>Retire</button>}
                          <button className="btn btn-sm btn-ghost" onClick={() => confirm("Delete this record? This can't be undone.") && remove.mutate({ row: r, kind: "delete" })}>Delete</button>
                        </>
                      )}
                      {entity === "aircrew" && <button className="btn btn-sm btn-ghost" onClick={() => nav(`/pilots/${r.id}`)}>Profile</button>}
                    </span></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {list.isLoading && <Loading />}
            {list.data?.items.length === 0 && <div className="empty" style={{ padding: 16 }}>No records match these filters.</div>}
          </div>
          {list.data && (
            <div className="pager">
              <span className="mono">{num(list.data.total)} records</span>
              <button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <span className="mono">{page} / {Math.max(1, Math.ceil(list.data.total / list.data.page_size))}</span>
              <button className="btn btn-sm" disabled={page * list.data.page_size >= list.data.total} onClick={() => setPage(page + 1)}>Next</button>
            </div>
          )}
          </>}
          {editing && <EntityForm entity={entity} meta={meta.data} row={editing === "new" ? null : editing} user={user} bases={bases.data ?? []}
            preset={typeId ? { aircraft_type_id: Number(typeId) } : undefined}
            onClose={() => setEditing(null)} onSaved={() => { setEditing(null); qc.invalidateQueries({ queryKey: ["inv", entity] }); qc.invalidateQueries({ queryKey: ["summary"] }); }} />}
        </>
      )}
    </div>
  );
}

function EntityForm({ entity, meta, row, user, bases, preset, onClose, onSaved }: {
  entity: string; meta: EntityMeta; row: Row | null; user: User; bases: Base[]; preset?: Record<string, unknown>; onClose: () => void; onSaved: () => void;
}) {
  const fields = meta.columns.filter((c) => c.editable && !HIDE.has(c.name));
  const init: Record<string, unknown> = {};
  for (const c of fields) init[c.name] = row ? row[c.name] : meta.scope === c.name && user.base_id ? user.base_id : c.type === "bool" ? false : "";
  if (!row && preset) Object.assign(init, preset);
  if (meta.has_point) { init.lat = row?.lat ?? ""; init.lon = row?.lon ?? ""; }
  const [v, setV] = useState(init);
  const [err, setErr] = useState<ApiError | null>(null);
  const [conflict, setConflict] = useState(false);
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {};
      for (const [k, val] of Object.entries(v)) if (!row || val !== (k === "lat" || k === "lon" ? row[k] : row[k])) body[k] = val;
      if (meta.has_point && (body.lat !== undefined || body.lon !== undefined)) { body.lat = v.lat; body.lon = v.lon; }
      return row ? api(`/inv/${entity}/${row.id}`, { method: "PATCH", body: { ...body, version: row.version } }) : api(`/inv/${entity}`, { method: "POST", body });
    },
    onSuccess: onSaved,
    onError: (e) => {
      const ex = e instanceof ApiError ? e : new ApiError(0, "Save failed.");
      if (ex.status === 409) setConflict(true);
      setErr(ex);
    },
  });
  const ownBases = bases.filter((b) => b.side === "OWN" && (user.role === "ADMIN" || b.id === user.base_id));
  const input = (c: ColumnMeta) => {
    const val = v[c.name];
    const on = (x: unknown) => setV({ ...v, [c.name]: x });
    if (c.type === "enum") return <select className="select" value={String(val ?? "")} onChange={(e) => on(e.target.value)}>
      {c.nullable && <option value="">—</option>}{c.values?.map((o) => <option key={o} value={o}>{label(o)}</option>)}</select>;
    if (c.type === "bool") return <input type="checkbox" checked={!!val} onChange={(e) => on(e.target.checked)} />;
    if (c.fk === "base") return <select className="select" value={String(val ?? "")} onChange={(e) => on(e.target.value ? Number(e.target.value) : "")}>
      <option value="">—</option>{(c.name === meta.scope ? ownBases : bases).map((b) => <option key={b.id} value={b.id}>{b.code} {b.name.replace("Air Force Station ", "")}</option>)}</select>;
    if (c.type === "date") return <input className="input" type="date" value={String(val ?? "").slice(0, 10)} onChange={(e) => on(e.target.value)} />;
    if (c.type === "datetime") return <input className="input" type="datetime-local" value={String(val ?? "").slice(0, 16)} onChange={(e) => on(e.target.value)} />;
    if (c.type === "int" || c.type === "float") return <input className="input mono" type="number" step={c.type === "int" ? 1 : "any"} value={String(val ?? "")} onChange={(e) => on(e.target.value === "" ? "" : Number(e.target.value))} />;
    return <input className="input" value={Array.isArray(val) ? val.join(", ") : String(val ?? "")} onChange={(e) => on(e.target.value)} />;
  };
  return (
    <Modal title={`${row ? "Edit" : "New"} ${meta.label.toLowerCase().replace(/s$/, "")}${row ? ` #${row.id}` : ""}`} onClose={onClose}>
      {conflict && <div className="notice" style={{ marginBottom: 8 }}>◆ This record was changed by the simulator or another user. Close and reopen it to edit the latest version.</div>}
      <div className="form-grid">
        {fields.map((c) => (
          <label key={c.name} className="field">
            <span className="field-label">{label(c.name.replace(/_id$/, ""))}{!c.nullable && " *"}</span>
            {input(c)}
            {err?.fields[c.name] && <span className="field-error">■ {err.fields[c.name]}</span>}
          </label>
        ))}
        {meta.has_point && ["lat", "lon"].map((k) => (
          <label key={k} className="field"><span className="field-label">{k === "lat" ? "Latitude" : "Longitude"} *</span>
            <input className="input mono" type="number" step="any" value={String(v[k] ?? "")} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
            {err?.fields[k] && <span className="field-error">■ {err.fields[k]}</span>}</label>
        ))}
      </div>
      {err && <div className="error-text" style={{ marginTop: 8 }}>■ {err.message}</div>}
      <div className="modal-actions">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={save.isPending || conflict} onClick={() => { setErr(null); save.mutate(); }}>{row ? "Save changes" : "Create"}</button>
      </div>
    </Modal>
  );
}
