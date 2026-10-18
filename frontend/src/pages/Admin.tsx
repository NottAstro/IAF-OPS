import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { Base, SnagModelCard } from "../api/types";
import { ErrorText, Pill, Row, Sim, ToneText } from "../components/ui";
import { istTime, label, num } from "../lib/format";

/** D38: the snag-risk model card (metrics on held-out sorties, coefficients, calibration) and a retrain button. */
function ModelCard() {
  const qc = useQueryClient();
  const card = useQuery({ queryKey: ["model-card"], queryFn: () => api<SnagModelCard>("/ops/models/snag-risk") });
  const train = useMutation({
    mutationFn: () => api<SnagModelCard>("/ops/models/snag-risk/train", { method: "POST" }),
    onSuccess: (c) => { qc.setQueryData(["model-card"], c); qc.invalidateQueries({ queryKey: ["snag-risk"] }); },
  });
  const c = card.data, m = c?.metrics;
  return (
    <>
      <h2 className="section-h" style={{ marginTop: 18 }}>Snag-risk model <Sim /></h2>
      <div className="muted" style={{ marginBottom: 8 }}>
        Predicts the chance a tail develops a defect on a sortie, from the maintenance log. Used to give priority packages
        their most reliable tails, in package explanations and in expected-defect forecasts.
      </div>
      {card.error && <ErrorText error={card.error} />}
      {c && !c.trained && <div className="empty">Not trained yet: there isn't enough maintenance history.</div>}
      {m && <>
        <Row label="Held-out sorties" value={`${num(m.test.n, 0)} · ${num(m.test.defects, 0)} defects (${num(100 * m.test.base_rate, 1)}%)`}
          extra={<span className="dim" style={{ fontSize: 11 }}>newest 20 %, from {istTime(m.split.test_from, true)}</span>} />
        <Row label="Ranking (AUC)" value={num(m.test.auc, 2)} extra={<span className="dim" style={{ fontSize: 11 }}>0.5 = guessing · train {num(m.train.auc, 2)}</span>} />
        <Row label="Top 10 % riskiest" value={`${num(m.test.top_decile_lift, 1)} × the average defect rate`} />
        <Row label="Brier score" value={`${num(m.test.brier, 4)}`} extra={<span className="dim" style={{ fontSize: 11 }}>
          base rate alone {num(m.test.brier_base_rate, 4)} · skill {num(m.test.brier_skill, 2)}</span>} />
        <h4 className="section-h" style={{ fontSize: 13 }}>Calibration <span className="muted" style={{ fontSize: 11, fontWeight: 400 }}>predicted vs seen, by tenth of risk</span></h4>
        <div className="table-wrap"><table className="table" style={{ fontSize: 12 }}>
          <thead><tr><th>Tenth</th><th className="right">Predicted</th><th className="right">Seen</th></tr></thead>
          <tbody>{m.test.calibration.map((d, i) => (
            <tr key={i}><td>{i + 1}</td><td className="num">{num(100 * d.predicted, 1)}%</td>
              <td className="num">{Math.abs(d.observed - d.predicted) > 0.03 ? <ToneText toneName="caution">{`${num(100 * d.observed, 1)}%`}</ToneText> : `${num(100 * d.observed, 1)}%`}</td></tr>
          ))}</tbody>
        </table></div>
        <h4 className="section-h" style={{ fontSize: 13 }}>What drives it <span className="muted" style={{ fontSize: 11, fontWeight: 400 }}>log-odds per unit</span></h4>
        {Object.entries(m.coefficients).map(([k, v]) => (
          <Row key={k} label={m.labels[k] ?? label(k)} value={<span className="mono">{v > 0 ? "+" : ""}{num(v, 2)}</span>} />
        ))}
        <div className="dim" style={{ fontSize: 11, margin: "6px 0" }}>{c?.method} {c?.limits}</div>
      </>}
      <div className="toolbar">
        <button className="btn" disabled={train.isPending} onClick={() => train.mutate()}>{train.isPending ? "Training…" : "Retrain on the latest log"}</button>
        {c?.trained_at && <span className="muted" style={{ fontSize: 12 }}>model #{c.id} · trained {istTime(c.trained_at, true)}</span>}
      </div>
      {train.error && <ErrorText error={train.error} />}
    </>
  );
}

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
          <ModelCard />
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
