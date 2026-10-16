import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Base, Page, User } from "../api/types";
import { ErrorText, Kpi, Loading, Pill, Row, Sim, ToneText } from "../components/ui";
import { RANK, istTime, label, num } from "../lib/format";

interface CrewRow { id: number; rank: string; first_name: string; last_name: string; callsign: string; aircrew_role: string; stream: string;
  duty_status: string; medical_status: string; ops_category: string; total_hours: number; base_id: number; squadron_id: number | null; service_no: string }

export function Pilots({ user }: { user: User }) {
  const nav = useNavigate();
  const [f, setF] = useState({ base_id: user.role === "BASE_COMMANDER" ? String(user.base_id) : "", aircrew_role: "PILOT", duty_status: "", medical_status: "", rank: "", q: "" });
  const [page, setPage] = useState(1);
  const bases = useQuery({ queryKey: ["bases"], queryFn: () => api<Base[]>("/bases"), staleTime: Infinity });
  const p = new URLSearchParams({ page: String(page), page_size: "50", sort: "rank", order: "desc" });
  Object.entries(f).forEach(([k, v]) => v && p.set(k, v));
  const q = useQuery({ queryKey: ["inv", "aircrew", p.toString()], queryFn: () => api<Page<CrewRow>>(`/inv/aircrew?${p}`), placeholderData: keepPreviousData });
  const sel = (k: keyof typeof f, opts: string[], all: string) => (
    <select className="select" value={f[k]} onChange={(e) => { setF({ ...f, [k]: e.target.value }); setPage(1); }} aria-label={all}>
      <option value="">{all}</option>{opts.map((o) => <option key={o} value={o}>{label(o)}</option>)}
    </select>
  );
  return (
    <div className="page">
      <h1 className="page-title">Aircrew <Sim title="All aircrew are fictional" /></h1>
      <div className="toolbar">
        <input className="input" placeholder="Search name, service no., callsign" value={f.q} onChange={(e) => { setF({ ...f, q: e.target.value }); setPage(1); }} />
        <select className="select" value={f.base_id} onChange={(e) => { setF({ ...f, base_id: e.target.value }); setPage(1); }} aria-label="Base">
          <option value="">All bases</option>{(bases.data ?? []).filter((b) => b.side === "OWN").map((b) => <option key={b.id} value={b.id}>{b.code} {b.name.replace("Air Force Station ", "")}</option>)}
        </select>
        {sel("aircrew_role", ["PILOT", "WSO", "NAVIGATOR", "FLIGHT_ENGINEER", "LOADMASTER", "RPA_PILOT", "PAYLOAD_OPERATOR"], "All roles")}
        {sel("rank", ["FG_OFFR", "FLT_LT", "SQN_LDR", "WG_CDR", "GP_CAPT"], "All ranks")}
        {sel("duty_status", ["ON_DUTY", "STANDBY", "QRA", "BRIEFED", "AIRBORNE", "CREW_REST", "OFF_DUTY", "LEAVE", "SICK", "COURSE"], "Any duty")}
        {sel("medical_status", ["FIT_FULL", "FIT_RESTRICTED", "TEMP_UNFIT", "GROUNDED"], "Any medical")}
      </div>
      {q.error && <ErrorText error={q.error} />}
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Name</th><th>Rank</th><th>Callsign</th><th>Role</th><th>Category</th><th className="right">Total hours</th><th>Duty</th><th>Medical</th></tr></thead>
          <tbody>{q.data?.items.map((c) => (
            <tr key={c.id} onClick={() => nav(`/pilots/${c.id}`)} style={{ cursor: "pointer" }}>
              <td>{c.first_name} {c.last_name} <span className="dim mono" style={{ fontSize: 11 }}>{c.service_no}</span></td>
              <td>{RANK[c.rank]}</td><td className="mono">{c.callsign}</td><td>{label(c.aircrew_role)}</td><td>{label(c.ops_category)}</td>
              <td className="num">{num(c.total_hours)}</td><td><Pill status={c.duty_status} /></td><td><Pill status={c.medical_status} /></td>
            </tr>))}
          </tbody>
        </table>
        {q.isLoading && <Loading />}
      </div>
      {q.data && <div className="pager"><span className="mono">{num(q.data.total)} aircrew</span>
        <button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
        <button className="btn btn-sm" disabled={page * 50 >= q.data.total} onClick={() => setPage(page + 1)}>Next</button></div>}
    </div>
  );
}

interface Profile {
  person: CrewRow & { date_of_birth: string; commission_date: string; squadron: string | null; base_code: string; base_name: string; current_type: string | null;
    appointment: string | null; instrument_rating: string; medical_valid_until: string; night_hours: number; instrument_hours: number; version: number;
    sorties_24h: number; hours_24h: number; hours_7d: number; hours_30d: number; rest_hours: number | null; fatigued: boolean; available: boolean };
  type_hours: { type: string; category: string; hours: number; captain_hours: number; night_hours: number; last_flown_at: string | null; currency: string | null; expires_at: string | null; window_days: number }[];
  recent_hours: { d30: number; d90: number; d365: number; sorties_30d: number };
  qualifications: { code: string; awarded_on: string; expires_on: string | null; type: string | null }[];
  postings: { from_date: string; to_date: string | null; appointment: string | null; base_code: string; squadron: string | null; type: string | null }[];
}

export function PilotProfile({ user }: { user: User }) {
  const { id } = useParams();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const q = useQuery({ queryKey: ["pilot", id], queryFn: () => api<Profile>(`/aircrew/${id}/profile`) });
  const sorties = useQuery({
    queryKey: ["pilot", id, "sorties", page], placeholderData: keepPreviousData,
    queryFn: () => api<Page<{ code: string; mission_type: string; status: string; actual_launch_ts: string; position: string; hours_logged: number; night_hours: number; tail_no: string; type: string; base: string }>>(`/aircrew/${id}/sorties?page=${page}&page_size=15`),
  });
  const edit = useMutation({
    mutationFn: (body: Record<string, unknown>) => api(`/inv/aircrew/${id}`, { method: "PATCH", body: { ...body, version: q.data!.person.version } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pilot", id] }),
    onError: (e) => alert(e instanceof ApiError ? e.message : "Update failed"),
  });
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (q.error || !q.data) return <div className="page"><ErrorText error={q.error} /></div>;
  const p = q.data.person;
  const canEdit = user.role === "ADMIN" || (user.role === "BASE_COMMANDER" && user.base_id === p.base_id);
  const today = new Date();
  const expTone = (d: string | null) => !d ? "ok" : new Date(d) < today ? "warning" : (new Date(d).getTime() - today.getTime()) / 864e5 < 7 ? "caution" : "ok";
  return (
    <div className="page">
      <h1 className="page-title">{RANK[p.rank]} {p.first_name} {p.last_name} <span className="muted" style={{ fontSize: 15 }}>(fictional)</span> <Sim /></h1>
      <div className="panel-meta" style={{ marginBottom: 16, fontSize: 14 }}>
        <span className="mono">"{p.callsign}"</span><span className="mono">{p.service_no}</span><span>{label(p.aircrew_role)} · {label(p.stream)}</span>
        <span>{p.squadron ?? p.appointment} · {p.base_code}</span><span>{label(p.ops_category)}</span><span>Instrument rating {label(p.instrument_rating)}</span>
      </div>
      <div className="grid-2">
        <div>
          <h2 className="section-h">Status</h2>
          <Row label="Duty status" value={canEdit ? (
            <select className="select" value={p.duty_status} onChange={(e) => edit.mutate({ duty_status: e.target.value })} aria-label="Duty status">
              {["ON_DUTY", "STANDBY", "OFF_DUTY", "LEAVE", "SICK", "COURSE", "CREW_REST", "QRA"].map((x) => <option key={x} value={x}>{label(x)}</option>)}
            </select>) : <Pill status={p.duty_status} />} />
          <Row label="Medical" extra={<span className="mono dim">valid to {p.medical_valid_until}</span>} value={canEdit ? (
            <select className="select" value={p.medical_status} onChange={(e) => edit.mutate({ medical_status: e.target.value })} aria-label="Medical status">
              {["FIT_FULL", "FIT_RESTRICTED", "TEMP_UNFIT", "GROUNDED"].map((x) => <option key={x} value={x}>{label(x)}</option>)}
            </select>) : <Pill status={p.medical_status} />} />
          <Row label="Available to fly" value={<ToneText toneName={p.available ? "ok" : "neutral"}>{p.available ? "Yes" : "No"}</ToneText>} />
          <Row label="Fatigue" value={<ToneText toneName={p.fatigued ? "warning" : "ok"}>{p.fatigued ? "Fatigued" : "Rested"}</ToneText>}
            extra={<span className="mono dim">{num(p.hours_24h, 1)} h/24h · {num(p.hours_7d, 1)} h/7d · {num(p.hours_30d, 1)} h/30d{p.rest_hours != null ? ` · rest ${num(p.rest_hours, 1)} h` : ""}</span>} />
          <div className="kpis" style={{ marginTop: 12 }}>
            <Kpi label="Total hours" value={num(p.total_hours)} sub={`night ${num(p.night_hours)} · instr ${num(p.instrument_hours)}`} />
            <Kpi label="Last 30 / 90 days" value={`${num(q.data.recent_hours.d30, 1)} / ${num(q.data.recent_hours.d90, 1)}`} sub={`${q.data.recent_hours.sorties_30d} sorties in 30 days`} />
            <Kpi label="Last 365 days" value={num(q.data.recent_hours.d365, 1)} sub="hours" />
          </div>
          <h2 className="section-h">Hours and currency by type</h2>
          {q.data.type_hours.map((t) => (
            <Row key={t.type} label={<>{t.type} <span className="dim mono">capt {num(t.captain_hours)} · night {num(t.night_hours)}</span></>}
              extra={t.currency && t.type === p.current_type ? <span title={`Current if flown within ${t.window_days} days (simulated policy)`}><Pill status={t.currency} /></span> : <span className="dim">history</span>}
              value={`${num(t.hours)} h`} />
          ))}
          <h2 className="section-h">Qualifications</h2>
          {q.data.qualifications.length === 0 && <div className="empty">None recorded.</div>}
          {q.data.qualifications.map((x, i) => (
            <Row key={i} label={<>{label(x.code)} <span className="dim">{x.type ?? ""}</span></>} extra={<span className="mono dim">since {x.awarded_on}</span>}
              value={x.expires_on ? <ToneText toneName={expTone(x.expires_on)}>to {x.expires_on}</ToneText> : "—"} />
          ))}
        </div>
        <div>
          <h2 className="section-h">Career</h2>
          <div className="timeline">
            {q.data.postings.map((x, i) => (
              <span key={i} style={{ display: "contents" }}>
                {i > 0 && <span className="timeline-sep" />}
                <span className={`timeline-step${x.to_date ? "" : " now"}`} title={`${x.from_date} → ${x.to_date ?? "now"} · ${x.base_code}`}>{x.type ?? x.appointment} <span className="dim">{x.base_code}</span></span>
              </span>
            ))}
          </div>
          <h2 className="section-h">Sortie history</h2>
          <div className="table-wrap">
            <table className="table" style={{ fontSize: 13 }}>
              <thead><tr><th>Launch</th><th>Mission</th><th>Aircraft</th><th>Position</th><th className="right">Hours</th><th>Status</th></tr></thead>
              <tbody>{sorties.data?.items.map((x) => (
                <tr key={x.code}><td className="mono">{istTime(x.actual_launch_ts, true)}</td><td>{label(x.mission_type)}</td>
                  <td><span className="mono">{x.tail_no}</span> {x.type}</td><td>{label(x.position)}</td><td className="num">{num(x.hours_logged, 1)}</td><td><Pill status={x.status} /></td></tr>))}
              </tbody>
            </table>
          </div>
          {sorties.data && <div className="pager"><span className="mono">{sorties.data.total} sorties</span>
            <button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Newer</button>
            <button className="btn btn-sm" disabled={page * 15 >= sorties.data.total} onClick={() => setPage(page + 1)}>Older</button></div>}
        </div>
      </div>
    </div>
  );
}
