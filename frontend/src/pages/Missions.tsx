// Missions (PHASE2_IMPLEMENTATION_PLAN §10.3): the tasking list the planner works from. Requests, approval, tasking
// status and outcome. All missions are simulated; every area is inside India and clear of the border buffer.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { MissionRow, Priority, User } from "../api/types";
import { ErrorText, Loading, Modal, Pill, Sim, ToneText } from "../components/ui";
import { PrioPill, hhmm } from "../features/ops";
import { istTime, label } from "../lib/format";
import { useStore } from "../store";

interface Meta {
  templates: Record<string, { label: string; roles: string[]; required: number; on_station_min: number }>;
  priorities: Priority[]; risk: string[]; quals: string[]; bases: { id: number; code: string; name: string }[];
  commands: { id: number; code: string; name: string }[];
}
const STATUS_TONE: Record<string, string> = { REQUESTED: "PLANNED", APPROVED: "CAUTION", PLANNED: "STANDBY", TASKED: "OPERATIONAL", ACTIVE: "AIRBORNE",
  COMPLETED: "COMPLETED", CANCELLED: "CANCELLED" };
const OUTCOME_TONE: Record<string, string> = { MET: "ok", PARTIAL: "caution", MISSED: "critical" };

export function Missions({ user }: { user: User }) {
  const qc = useQueryClient();
  const toast = useStore((s) => s.toast);
  const draft = useStore((s) => s.missionDraft);
  const [params] = useSearchParams();
  const focus = Number(params.get("focus")) || null;
  const [f, setF] = useState({ status: "", priority: "", command: "", mission_type: "", q: "", horizon_h: "24" });
  const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
  const q = useQuery({ queryKey: ["missions", p.toString()], queryFn: () => api<{ items: MissionRow[]; counts: Record<string, number>; now: string }>(`/ops/missions?${p}`),
    refetchInterval: 20000 });
  const meta = useQuery({ queryKey: ["missions", "meta"], queryFn: () => api<Meta>("/ops/missions/meta"), staleTime: Infinity });
  const canPlan = user.role === "ADMIN" || user.role === "COMMAND_HQ";
  const [open, setOpen] = useState(false);
  useEffect(() => { if (draft) setOpen(true); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const act = useMutation({
    mutationFn: ({ id, action }: { id: number; action: "approve" | "cancel" }) => api(`/ops/missions/${id}/${action}`, { method: "POST" }),
    onSuccess: (_, v) => { qc.invalidateQueries({ queryKey: ["missions"] }); toast(v.action === "approve" ? "Mission approved" : "Mission cancelled", "INFO"); },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Failed", "CRITICAL"),
  });
  const rows = q.data?.items ?? [];
  return (
    <div className="page">
      <h1 className="page-title">Missions <Sim title="Simulated tasking" />
        <span className="muted" style={{ fontSize: 13, fontWeight: 400 }}>{Object.entries(q.data?.counts ?? {}).map(([k, v]) => `${label(k)} ${v}`).join(" · ")}</span></h1>
      <div className="toolbar">
        <select className="select" aria-label="Window" value={f.horizon_h} onChange={(e) => setF({ ...f, horizon_h: e.target.value })}>
          <option value="24">Next 24 h</option><option value="48">Next 48 h</option><option value="">All</option>
        </select>
        <select className="select" aria-label="Status" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
          <option value="">Any status</option>{["REQUESTED", "APPROVED", "TASKED", "ACTIVE", "COMPLETED", "CANCELLED"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </select>
        <select className="select" aria-label="Priority" value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })}>
          <option value="">Any priority</option>{["P1", "P2", "P3", "P4"].map((x) => <option key={x}>{x}</option>)}
        </select>
        <select className="select" aria-label="Command" value={f.command} onChange={(e) => setF({ ...f, command: e.target.value })}>
          <option value="">All commands</option>{["WAC", "SWAC", "CAC", "EAC", "SAC"].map((c) => <option key={c}>{c}</option>)}
        </select>
        <select className="select" aria-label="Type" value={f.mission_type} onChange={(e) => setF({ ...f, mission_type: e.target.value })}>
          <option value="">Any type</option>{Object.entries(meta.data?.templates ?? {}).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <input className="input" placeholder="Search code or name" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        <span className="topbar-spacer" />
        {canPlan && <button className="btn btn-primary" onClick={() => setOpen(true)}>New mission request</button>}
      </div>
      {q.error && <ErrorText error={q.error} />}
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Pri.</th><th>Mission</th><th>Type</th><th>Window (IST)</th><th>Cmd</th><th className="right">Needs</th><th>Status</th><th>Tasked</th><th>Outcome</th><th /></tr></thead>
          <tbody>{rows.map((m) => (
            <tr key={m.id} className={focus === m.id ? "sel" : ""}>
              <td><PrioPill p={m.priority} /></td>
              <td style={{ maxWidth: 300 }}><span className="mono">{m.code}</span> <span className="muted">{m.name}</span></td>
              <td>{meta.data?.templates[m.mission_type]?.label ?? label(m.mission_type)}</td>
              <td className="mono">{istTime(m.window_start, true).replace(" IST", "")}–{hhmm(m.window_end)}</td>
              <td>{m.command ?? "—"}</td>
              <td className="num">{m.required_aircraft} × {m.on_station_min} min</td>
              <td><Pill status={STATUS_TONE[m.status] ?? m.status} text={label(m.status)} /></td>
              <td>{m.tasked_base ? <span>{m.tasked_n} × {m.tasked_type} <span className="mono">{m.tasked_base}</span> {hhmm(m.tasked_launch)}{m.sortie_status && <span className="dim"> · {label(m.sortie_status)}</span>}</span>
                : <span className="dim">—</span>}</td>
              <td>{m.outcome !== "NONE" ? <ToneText toneName={OUTCOME_TONE[m.outcome] ?? "neutral"}>{label(m.outcome)}</ToneText> : <span className="dim">—</span>}</td>
              <td className="nowrap">
                {canPlan && m.status === "REQUESTED" && <button className="btn btn-sm" onClick={() => act.mutate({ id: m.id, action: "approve" })}>Approve</button>}{" "}
                {canPlan && ["REQUESTED", "APPROVED", "PLANNED", "TASKED"].includes(m.status) &&
                  <button className="btn btn-sm btn-danger" onClick={() => confirm(`Cancel ${m.code}? Any planned sortie is cancelled too.`) && act.mutate({ id: m.id, action: "cancel" })}>Cancel</button>}
              </td>
            </tr>
          ))}</tbody>
        </table>
        {q.isLoading && <Loading />}
        {q.data && rows.length === 0 && <div className="empty" style={{ padding: 16 }}>No missions match these filters.</div>}
      </div>
      {open && meta.data && <NewMission meta={meta.data} user={user} onClose={() => { setOpen(false); useStore.getState().set({ missionDraft: null }); }} />}
    </div>
  );
}

const toLocal = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);

function NewMission({ meta, user, onClose }: { meta: Meta; user: User; onClose: () => void }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const st = useStore();
  const now = st.simClock ? new Date(st.simClock.sim_now) : new Date();
  const init = st.missionDraft ?? {
    name: "", mission_type: "CASEVAC", priority: "P2", window_start: toLocal(new Date(now.getTime() + 3600e3)),
    window_end: toLocal(new Date(now.getTime() + 4 * 3600e3)), target: "base", target_base_id: "", lon: "", lat: "",
    required_aircraft: String(meta.templates.CASEVAC.required), on_station_min: String(meta.templates.CASEVAC.on_station_min),
    max_risk: "MED", min_quals: [] as string[], notes: "",
  };
  const [v, setV] = useState(init);
  const [fields, setFields] = useState<Record<string, string>>({});
  const set = (k: string, x: unknown) => setV({ ...v, [k]: x });
  const pickType = (t: string) => setV({ ...v, mission_type: t, required_aircraft: String(meta.templates[t].required), on_station_min: String(meta.templates[t].on_station_min) });
  const save = useMutation({
    mutationFn: () => api<{ code: string; status: string }>("/ops/missions", { method: "POST", body: {
      name: v.name, mission_type: v.mission_type, priority: v.priority, window_start: new Date(v.window_start).toISOString(),
      window_end: new Date(v.window_end).toISOString(), target_base_id: v.target === "base" && v.target_base_id ? Number(v.target_base_id) : null,
      lon: v.target === "point" && v.lon ? Number(v.lon) : null, lat: v.target === "point" && v.lat ? Number(v.lat) : null,
      required_aircraft: Number(v.required_aircraft), on_station_min: Number(v.on_station_min), max_risk: v.max_risk, min_quals: v.min_quals,
      notes: v.notes || null } }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["missions"] }); st.toast(`${r.code} ${r.status === "APPROVED" ? "approved" : "requested"}`, "INFO"); onClose(); },
    onError: (e) => { if (e instanceof ApiError) setFields(e.fields); },
  });
  const pickOnMap = () => {
    st.set({ missionDraft: { ...v, target: "point" }, picking: "mission", mode: "OPS", selection: null });
    nav("/map");
  };
  const err = (k: string) => fields[k] && <span className="field-error">■ {fields[k]}</span>;
  return (
    <Modal title="New mission request" onClose={onClose}>
      <div className="muted" style={{ marginBottom: 10 }}>
        {user.role === "COMMAND_HQ" && user.command_id ? `Requested for ${user.command_code}; Air HQ approves it.` : "Missions created by Air HQ or the directing staff are approved at once."}
      </div>
      <div className="form-grid">
        <label className="field" style={{ gridColumn: "1 / -1" }}><span className="field-label">Name</span>
          <input className="input" value={v.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Casualty evacuation from Nyoma" />{err("name")}</label>
        <label className="field"><span className="field-label">Type</span>
          <select className="select" value={v.mission_type} onChange={(e) => pickType(e.target.value)}>
            {Object.entries(meta.templates).map(([k, t]) => <option key={k} value={k}>{t.label}</option>)}</select>{err("mission_type")}</label>
        <label className="field"><span className="field-label">Priority</span>
          <select className="select" value={v.priority} onChange={(e) => set("priority", e.target.value)}>{meta.priorities.map((x) => <option key={x}>{x}</option>)}</select></label>
        <label className="field"><span className="field-label">Window opens</span>
          <input className="input" type="datetime-local" value={v.window_start} onChange={(e) => set("window_start", e.target.value)} /></label>
        <label className="field"><span className="field-label">Window closes</span>
          <input className="input" type="datetime-local" value={v.window_end} onChange={(e) => set("window_end", e.target.value)} />{err("window_end")}</label>
        <label className="field"><span className="field-label">Aircraft</span>
          <input className="input" type="number" min={1} max={8} value={v.required_aircraft} onChange={(e) => set("required_aircraft", e.target.value)} /></label>
        <label className="field"><span className="field-label">Time on station (min)</span>
          <input className="input" type="number" min={10} max={600} value={v.on_station_min} onChange={(e) => set("on_station_min", e.target.value)} /></label>
        <label className="field"><span className="field-label">Highest acceptable route risk</span>
          <select className="select" value={v.max_risk} onChange={(e) => set("max_risk", e.target.value)}>{meta.risk.map((x) => <option key={x} value={x}>{label(x)}</option>)}</select></label>
        <div className="field"><span className="field-label">Target</span>
          <div className="toolbar" style={{ margin: 0 }}>
            <label className="check"><input type="radio" checked={v.target === "base"} onChange={() => set("target", "base")} /> Destination base</label>
            <label className="check"><input type="radio" checked={v.target === "point"} onChange={() => set("target", "point")} /> Area on the map</label>
          </div>
        </div>
        {v.target === "base" ? (
          <label className="field"><span className="field-label">Destination base</span>
            <select className="select" value={v.target_base_id} onChange={(e) => set("target_base_id", e.target.value)}>
              <option value="">Choose</option>{meta.bases.map((b) => <option key={b.id} value={b.id}>{b.code} {b.name.replace("Air Force Station ", "")}</option>)}</select>
            {err("target_base_id")}{err("lon")}</label>
        ) : (
          <div className="field"><span className="field-label">Area (lat, lon)</span>
            <div className="toolbar" style={{ margin: 0 }}>
              <input className="input" style={{ width: 90 }} placeholder="lat" value={v.lat} onChange={(e) => set("lat", e.target.value)} />
              <input className="input" style={{ width: 90 }} placeholder="lon" value={v.lon} onChange={(e) => set("lon", e.target.value)} />
              <button className="btn btn-sm" onClick={pickOnMap}>Pick on map</button>
            </div>{err("lon")}</div>
        )}
        <div className="field" style={{ gridColumn: "1 / -1" }}><span className="field-label">Crew must also hold</span>
          <div className="toolbar" style={{ margin: 0 }}>{meta.quals.map((x) => (
            <label key={x} className="check"><input type="checkbox" checked={v.min_quals.includes(x)}
              onChange={() => set("min_quals", v.min_quals.includes(x) ? v.min_quals.filter((y) => y !== x) : [...v.min_quals, x])} /> {label(x)}</label>
          ))}</div>
          <span className="dim" style={{ fontSize: 11 }}>Night and NVG are added automatically for packages that fly after dark.</span></div>
        <label className="field" style={{ gridColumn: "1 / -1" }}><span className="field-label">Notes</span>
          <input className="input" value={v.notes} onChange={(e) => set("notes", e.target.value)} /></label>
      </div>
      {save.error && !Object.keys(fields).length && <ErrorText error={save.error} />}
      <div className="modal-actions"><button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={save.isPending || v.name.length < 3} onClick={() => save.mutate()}>Submit request</button></div>
    </Modal>
  );
}
