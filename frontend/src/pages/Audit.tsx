// Audit log (FR-ALR-06). The alert list that shared this file was removed with D69; alerts still drive the map's base
// tags, the base panel's "Needs attention", the Overview tile and the pop-ups.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { api } from "../api/client";
import type { Page, User } from "../api/types";
import { ErrorText, onActivate } from "../components/ui";
import { istTime, label, num } from "../lib/format";

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
          <option value="">Any action</option>{["CREATE", "UPDATE", "DELETE", "RETIRE", "APPROVE", "PLAN_GENERATE", "PLAN_APPROVE", "PLAN_COMMIT", "PLAN_REJECT", "PLAN_OVERRIDE", "INJECT",
            "LOGIN", "LOGIN_FAILED", "ALERT_ACK", "SIM_CONTROL", "USER_ADMIN", "SIM_TRANSITION"].map((a) => <option key={a} value={a}>{label(a)}</option>)}
        </select>
        <input className="input" placeholder="Entity (e.g. aircraft)" value={f.entity} onChange={(e) => { setF({ ...f, entity: e.target.value }); setPage(1); }} />
      </div>
      {q.error && <ErrorText error={q.error} />}
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Entity</th><th>Base</th><th>Change</th></tr></thead>
          <tbody>{q.data?.items.map((r) => (
            <Fragment key={r.id}>
              <tr onClick={() => setOpen(open === r.id ? null : r.id)} style={{ cursor: "pointer" }} tabIndex={0} aria-expanded={open === r.id}
                onKeyDown={onActivate(() => setOpen(open === r.id ? null : r.id))}>
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
