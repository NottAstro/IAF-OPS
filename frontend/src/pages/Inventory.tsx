import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Base, ColumnMeta, EntityMeta, Page, Row, User } from "../api/types";
import { ErrorText, Loading, Modal, Pill, Sim } from "../components/ui";
import { type ArtRef, EquipmentPicture } from "../equipment/Picture";
import { AircraftTypeCards, AircraftTypeHeader } from "../features/AircraftTypeCards";
import { istTime, label, num } from "../lib/format";

const ENTITIES: [string, string][] = [
  ["aircraft", "Aircraft"], ["aircrew", "Aircrew"], ["sorties", "Sorties"], ["fuel-storage", "Fuel storage"], ["fuel-transactions", "Fuel transactions"],
  ["ground-assets", "Vehicles & GSE"], ["ground-crew", "Ground crew"], ["warehouses", "Warehouses"], ["stock-levels", "Stock levels"],
  ["ad-batteries", "AD batteries"], ["radars", "Radars"], ["comms-nodes", "Comms nodes"], ["runways", "Runways"], ["parking", "Parking"],
  ["qra-posture", "QRA posture"], ["squadrons", "Squadrons"], ["missions", "Missions"], ["bases", "Bases"], ["aircraft-types", "Aircraft types"],
  ["stock-items", "Stock catalogue"], ["ad-system-types", "AD system types"], ["radar-types", "Radar types"],
];
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
const HIDE = new Set(["created_at", "updated_at", "version", "is_simulated", "source", "source_ref", "simulated", "password_hash"]);
const STATUS_COLS = ["status", "duty_status", "medical_status", "ops_status"];

function canWrite(user: User, meta: EntityMeta, baseId: unknown): boolean {
  if (meta.readonly) return false;
  if (user.role === "ADMIN") return true;
  if (meta.admin_only || (!meta.scope && meta.entity !== "fuel-transactions" && meta.entity !== "stock-levels")) return false;
  return user.role === "BASE_COMMANDER" && (baseId === undefined || baseId === user.base_id);
}

function cell(c: ColumnMeta, v: unknown, labels?: Record<string, Record<string, string>>) {
  if (v === null || v === undefined || v === "") return <span className="dim">—</span>;
  if (c.fk && labels?.[c.name]?.[String(v)]) return labels[c.name][String(v)];
  if (STATUS_COLS.includes(c.name)) return <Pill status={String(v)} />;
  if (c.type === "bool") return v ? "Yes" : "No";
  if (c.type === "datetime") return <span className="mono">{istTime(String(v), true)}</span>;
  if (c.type === "float" || c.type === "int") return num(v, c.type === "float" ? 1 : 0);
  if (c.type === "enum") return label(String(v));
  if (Array.isArray(v)) return v.join(", ");
  return String(v);
}

export function Inventory({ user }: { user: User }) {
  const { entity = "aircraft", typeId: typeParam } = useParams();
  const typeId = entity === "aircraft" ? typeParam : undefined;
  const typeCards = entity === "aircraft" && !typeId; // Aircraft opens on one card per type; a card opens that type's table
  const nav = useNavigate();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("id");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [search, setSearch] = useState("");
  const [baseFilter, setBaseFilter] = useState(user.role === "BASE_COMMANDER" && user.base_id ? String(user.base_id) : "");
  const [statusFilter, setStatusFilter] = useState("");
  const [command, setCommand] = useState("");
  const [typeSearch, setTypeSearch] = useState("");
  const [editing, setEditing] = useState<Row | "new" | null>(null);
  useEffect(() => { setPage(1); setSearch(""); setStatusFilter(""); }, [typeId]);
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
  const cols = useMemo(() => (meta.data?.columns ?? []).filter((c) => !HIDE.has(c.name) && c.type !== "geometry").slice(0, 12), [meta.data]);
  const remove = useMutation({
    mutationFn: ({ row, kind }: { row: Row; kind: "retire" | "delete" }) =>
      api(`/inv/${entity}/${row.id}${kind === "retire" ? "/retire" : ""}`, { method: kind === "retire" ? "POST" : "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["inv", entity] }),
    onError: (e) => alert(e instanceof ApiError ? e.message : "Failed"),
  });
  const exportCsv = async () => {
    const all = await api<Page<Row>>(`/inv/${entity}?${new URLSearchParams({ ...Object.fromEntries(params), page: "1", page_size: "500" })}`);
    const head = cols.map((c) => c.name);
    const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = ["# SIMULATED DATA — SIH 2026 DEMO — NOT REAL", head.join(","), ...all.items.map((r) => head.map((h) => esc(r[h])).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `${entity}${typeId ? `-type-${typeId}` : ""}.csv`;
    a.click();
  };
  const scopeVal = (r: Row) => (meta.data?.scope ? r[meta.data.scope] : undefined);
  return (
    <div className="page">
      <h1 className="page-title">Inventory <Sim /></h1>
      <div className="tabs" role="tablist">
        {ENTITIES.map(([k, n]) => (
          <button key={k} role="tab" aria-selected={k === entity} className={`tab${k === entity ? " on" : ""}`}
            onClick={() => { nav(`/inventory/${k}`); setPage(1); setSort("id"); setStatusFilter(""); }}>{n}</button>
        ))}
      </div>
      {meta.error && <ErrorText error={meta.error} />}
      {meta.data && (
        <>
          {typeId && <AircraftTypeHeader typeId={typeId} filters={typeFilters.toString()} />}
          <div className="toolbar">
            {typeCards && <input className="input" placeholder="Search aircraft type" value={typeSearch}
              onChange={(e) => setTypeSearch(e.target.value)} aria-label="Search aircraft type" />}
            {!typeCards && meta.data.search.length > 0 && <input className="input" placeholder={`Search ${meta.data.search.join(", ")}`} value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }} aria-label="Search" />}
            {meta.data.scope && (
              <select className="select" value={baseFilter} onChange={(e) => { setBaseFilter(e.target.value); setPage(1); }} aria-label="Base">
                <option value="">All bases</option>
                {(bases.data ?? []).filter((b) => b.side === "OWN").map((b) => <option key={b.id} value={b.id}>{b.code} {b.name.replace("Air Force Station ", "")}</option>)}
              </select>
            )}
            {meta.data.scope && (
              <select className="select" value={command} onChange={(e) => { setCommand(e.target.value); setPage(1); }} aria-label="Command">
                <option value="">All commands</option>{["WAC", "SWAC", "CAC", "EAC", "SAC", "TC", "MC"].map((c) => <option key={c}>{c}</option>)}
              </select>
            )}
            {statusCol && !typeCards && (
              <select className="select" value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }} aria-label="Status">
                <option value="">Any {label(statusCol.name).toLowerCase()}</option>{statusCol.values?.map((v) => <option key={v} value={v}>{label(v)}</option>)}
              </select>
            )}
            <span style={{ flex: 1 }} />
            <button className="btn" onClick={exportCsv} disabled={user.role === "VIEWER"} title={user.role === "VIEWER" ? "Viewers can't export" : "Export the filtered view (max 500 rows)"}>Export CSV</button>
            {canWrite(user, meta.data, undefined) && <button className="btn btn-primary" onClick={() => setEditing("new")}>New {meta.data.label.toLowerCase().replace(/s$/, "")}</button>}
          </div>
          {typeCards ? <AircraftTypeCards filters={typeFilters.toString()} search={typeSearch} /> : <>
          {meta.data.readonly && <div className="notice" style={{ marginBottom: 8 }}>{meta.data.label} are maintained by the system{entity === "sorties" ? "; create sorties from a base panel" : ""}.</div>}
          <div className="table-wrap">
            <table className="table">
              <thead><tr>
                {ART[entity] && <th aria-label="Top view" />}
                {cols.map((c) => (
                  <th key={c.name} className={c.type === "int" || c.type === "float" ? "right" : ""} aria-sort={sort === c.name ? (order === "asc" ? "ascending" : "descending") : "none"}
                    onClick={() => { if (sort === c.name) setOrder(order === "asc" ? "desc" : "asc"); else { setSort(c.name); setOrder("asc"); } }}>
                    {label(c.name.replace(/_id$/, ""))}{sort === c.name ? (order === "asc" ? " ▲" : " ▼") : ""}
                  </th>
                ))}
                <th />
              </tr></thead>
              <tbody>
                {list.data?.items.map((r) => (
                  <tr key={r.id}>
                    {ART[entity] && <td className="tv-cell">{(() => { const a = ART[entity](r, list.data?.labels); return a && <EquipmentPicture art={a} className="pic-thumb" />; })()}</td>}
                    {cols.map((c) => <td key={c.name} className={c.type === "int" || c.type === "float" ? "num" : ""}>{cell(c, r[c.name], list.data?.labels)}</td>)}
                    <td style={{ whiteSpace: "nowrap" }}>
                      {canWrite(user, meta.data, scopeVal(r)) && (
                        <>
                          <button className="btn btn-sm" onClick={() => setEditing(r)}>Edit</button>{" "}
                          {meta.data.retire && <button className="btn btn-sm btn-ghost" onClick={() => confirm(`Retire this record?`) && remove.mutate({ row: r, kind: "retire" })}>Retire</button>}
                          <button className="btn btn-sm btn-ghost" onClick={() => confirm("Delete this record? This can't be undone.") && remove.mutate({ row: r, kind: "delete" })}>Delete</button>
                        </>
                      )}
                      {entity === "aircrew" && <button className="btn btn-sm btn-ghost" onClick={() => nav(`/pilots/${r.id}`)}>Profile</button>}
                    </td>
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
