import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { AlertItem, Page, User } from "../api/types";
import { ErrorText, Loading, Pill, Sim } from "../components/ui";
import { istTime, label, num } from "../lib/format";
import { useStore } from "../store";

export function Alerts() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const st = useStore();
  const [f, setF] = useState({ status: "OPEN,ACKNOWLEDGED", severity: "", command: "" });
  const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
  const q = useQuery({ queryKey: ["alerts", p.toString()], queryFn: () => api<{ items: AlertItem[]; open_counts: Record<string, number> }>(`/alerts?${p}`), refetchInterval: 15000 });
  const ack = useMutation({
    mutationFn: (id: number) => api(`/alerts/${id}/ack`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
    onError: (e) => alert(e instanceof ApiError ? e.message : "Failed"),
  });
  return (
    <div className="page">
      <h1 className="page-title">Alerts <Sim title="Alert thresholds are simulated policy" /></h1>
      <div className="toolbar">
        <select className="select" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} aria-label="Status">
          <option value="OPEN,ACKNOWLEDGED">Open and acknowledged</option><option value="OPEN">Open</option><option value="CLEARED">Cleared</option>
        </select>
        <select className="select" value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })} aria-label="Severity">
          <option value="">Any severity</option>{["CRITICAL", "WARNING", "CAUTION"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </select>
        <select className="select" value={f.command} onChange={(e) => setF({ ...f, command: e.target.value })} aria-label="Command">
          <option value="">All commands</option>{["WAC", "SWAC", "CAC", "EAC", "SAC", "TC", "MC"].map((c) => <option key={c}>{c}</option>)}
        </select>
        <span className="muted">Open: {Object.entries(q.data?.open_counts ?? {}).map(([k, v]) => `${label(k)} ${v}`).join(" · ") || "none"}</span>
      </div>
      {q.error && <ErrorText error={q.error} />}
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Severity</th><th>Alert</th><th>Base</th><th>Cmd</th><th>Raised</th><th>Status</th><th /></tr></thead>
          <tbody>{q.data?.items.map((a) => (
            <tr key={a.id}>
              <td><Pill status={a.severity} /></td>
              <td style={{ maxWidth: 520, whiteSpace: "normal" }}>{a.message} <span className="dim" style={{ fontSize: 11 }}>{label(a.kind)}</span></td>
              <td>{a.base_code ? <a href="#" onClick={(e) => { e.preventDefault(); st.set({ selection: { kind: "base", id: a.base_id! }, panelTab: "Ov" }); nav("/map"); }}>{a.base_code}</a> : "—"}</td>
              <td>{a.command_code ?? "—"}</td><td className="mono">{istTime(a.raised_at, true)}</td>
              <td><Pill status={a.status} />{a.ack_by_name && <span className="dim" style={{ fontSize: 11 }}> by {a.ack_by_name}</span>}</td>
              <td>{a.can_ack && <button className="btn btn-sm" onClick={() => ack.mutate(a.id)}>Acknowledge</button>}</td>
            </tr>))}
          </tbody>
        </table>
        {q.isLoading && <Loading />}
        {q.data?.items.length === 0 && <div className="empty" style={{ padding: 16 }}>No alerts match these filters.</div>}
      </div>
    </div>
  );
}

interface AuditRow { id: number; ts: string; actor_type: string; actor_name: string | null; actor_role: string | null; action: string; entity_type: string | null;
  entity_id: number | null; base_code: string | null; before: Record<string, unknown> | null; after: Record<string, unknown> | null; request_id: string | null }

export function Audit({ user }: { user: User }) {
  const [f, setF] = useState({ actor: "USER", entity: "", action: "" });
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  const p = new URLSearchParams({ ...Object.fromEntries(Object.entries(f).filter(([, v]) => v)), page: String(page), page_size: "50" });
  const q = useQuery({ queryKey: ["audit", p.toString()], queryFn: () => api<Page<AuditRow>>(`/audit?${p}`), placeholderData: keepPreviousData, refetchInterval: 15000 });
  return (
    <div className="page">
      <h1 className="page-title">Audit log</h1>
      {user.role === "BASE_COMMANDER" && <div className="notice" style={{ marginBottom: 8 }}>Showing entries for your base only.</div>}
      <div className="toolbar">
        <select className="select" value={f.actor} onChange={(e) => { setF({ ...f, actor: e.target.value }); setPage(1); }} aria-label="Actor">
          <option value="">Everyone</option><option value="USER">People</option><option value="SIMULATOR">Simulator</option>
        </select>
        <select className="select" value={f.action} onChange={(e) => { setF({ ...f, action: e.target.value }); setPage(1); }} aria-label="Action">
          <option value="">Any action</option>{["CREATE", "UPDATE", "DELETE", "RETIRE", "LOGIN", "LOGIN_FAILED", "ALERT_ACK", "SIM_CONTROL", "USER_ADMIN", "SIM_TRANSITION"].map((a) => <option key={a} value={a}>{label(a)}</option>)}
        </select>
        <input className="input" placeholder="Entity (e.g. aircraft)" value={f.entity} onChange={(e) => { setF({ ...f, entity: e.target.value }); setPage(1); }} />
      </div>
      {q.error && <ErrorText error={q.error} />}
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Entity</th><th>Base</th><th>Change</th></tr></thead>
          <tbody>{q.data?.items.map((r) => (
            <Fragment key={r.id}>
              <tr onClick={() => setOpen(open === r.id ? null : r.id)} style={{ cursor: "pointer" }}>
                <td className="mono">{istTime(r.ts, true)}</td>
                <td>{r.actor_type === "SIMULATOR" ? <span className="sim-badge">SIMULATOR</span> : `${r.actor_name ?? "?"} (${label(r.actor_role)})`}</td>
                <td>{label(r.action)}</td><td>{r.entity_type ?? "—"} {r.entity_id && <span className="mono dim">#{r.entity_id}</span>}</td>
                <td>{r.base_code ?? "—"}</td>
                <td className="dim" style={{ maxWidth: 360 }}>{Object.keys(r.after ?? r.before ?? {}).slice(0, 4).join(", ")}</td>
              </tr>
              {open === r.id && (
                <tr><td colSpan={6} style={{ whiteSpace: "normal", background: "var(--surface-1)" }}>
                  <div className="grid-2" style={{ fontSize: 12 }}>
                    <div><div className="muted">Before</div><pre className="mono" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(r.before, null, 2)}</pre></div>
                    <div><div className="muted">After</div><pre className="mono" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(r.after, null, 2)}</pre></div>
                  </div>
                  <div className="dim" style={{ fontSize: 11 }}>request {r.request_id ?? "—"}</div>
                </td></tr>
              )}
            </Fragment>
          ))}</tbody>
        </table>
      </div>
      {q.data && <div className="pager"><span className="mono">{num(q.data.total)} entries</span>
        <button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Newer</button>
        <button className="btn btn-sm" disabled={page * 50 >= q.data.total} onClick={() => setPage(page + 1)}>Older</button></div>}
    </div>
  );
}
