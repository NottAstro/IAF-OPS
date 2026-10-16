import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { Base } from "../api/types";
import { ErrorText, Pill, Row, Sim } from "../components/ui";
import { label } from "../lib/format";

interface UserRow { id: number; username: string; display_name: string; role: string; is_active: boolean; last_login_at: string | null; base_code: string | null; command_code: string | null }

export function Admin() {
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<UserRow[]>("/users") });
  const bases = useQuery({ queryKey: ["bases"], queryFn: () => api<Base[]>("/bases"), staleTime: Infinity });
  const [msg, setMsg] = useState("");
  const sim = useMutation({
    mutationFn: ({ action }: { action: "reseed" }) => api(`/sim/${action}`, { method: "POST" }),
    onSuccess: () => { setMsg("Data regenerated."); qc.invalidateQueries(); },
    onError: (e) => setMsg(e instanceof ApiError ? e.message : "Failed"),
  });
  const [nu, setNu] = useState({ username: "", display_name: "", password: "", role: "VIEWER", base_id: "" });
  const create = useMutation({
    mutationFn: () => api("/users", { method: "POST", body: { ...nu, base_id: nu.base_id ? Number(nu.base_id) : null } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); setNu({ username: "", display_name: "", password: "", role: "VIEWER", base_id: "" }); },
  });
  const toggle = useMutation({
    mutationFn: (u: UserRow) => api(`/users/${u.id}`, { method: "PATCH", body: { is_active: !u.is_active } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
  return (
    <div className="page">
      <h1 className="page-title">Admin</h1>
      <div className="grid-2">
        <div>
          <h2 className="section-h">Synthetic data <Sim /></h2>
          <div className="muted" style={{ marginBottom: 8 }}>
            Regenerates every base inventory, aircrew record and 90-day history from the fixed seed. Every manual edit is lost.
          </div>
          <div className="toolbar">
            <button className="btn btn-danger" disabled={sim.isPending} onClick={() => confirm("Regenerate all synthetic data? Every edit is lost.") && sim.mutate({ action: "reseed" })}>
              {sim.isPending ? "Regenerating…" : "Regenerate data"}
            </button>
          </div>
          {msg && <div className="muted">{msg}</div>}
        </div>
        <div>
          <h2 className="section-h">Users</h2>
          {users.error && <ErrorText error={users.error} />}
          {users.data?.map((u) => (
            <Row key={u.id} label={<>{u.username} <span className="dim">{u.display_name}</span></>}
              extra={<span className="dim">{label(u.role)} {u.base_code ?? u.command_code ?? ""}</span>}
              value={<button className="btn btn-sm" onClick={() => toggle.mutate(u)}>{u.is_active ? <Pill status="OPERATIONAL" text="Active" /> : <Pill status="OFFLINE" text="Disabled" />}</button>} />
          ))}
          <h3 className="section-h">Add user</h3>
          <div className="form-grid">
            <input className="input" placeholder="Username" value={nu.username} onChange={(e) => setNu({ ...nu, username: e.target.value })} />
            <input className="input" placeholder="Display name" value={nu.display_name} onChange={(e) => setNu({ ...nu, display_name: e.target.value })} />
            <input className="input" type="password" placeholder="Password (8+ characters)" value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} />
            <select className="select" value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}>
              {["VIEWER", "BASE_COMMANDER", "COMMAND_HQ", "ADMIN"].map((r) => <option key={r} value={r}>{label(r)}</option>)}
            </select>
            {nu.role === "BASE_COMMANDER" && (
              <select className="select" value={nu.base_id} onChange={(e) => setNu({ ...nu, base_id: e.target.value })}>
                <option value="">Choose base</option>{(bases.data ?? []).filter((b) => b.side === "OWN").map((b) => <option key={b.id} value={b.id}>{b.code} {b.name}</option>)}
              </select>
            )}
          </div>
          {create.error && <ErrorText error={create.error} />}
          <div className="toolbar" style={{ marginTop: 8 }}><button className="btn btn-primary" disabled={!nu.username || !nu.password} onClick={() => create.mutate()}>Add user</button></div>
        </div>
      </div>
    </div>
  );
}
