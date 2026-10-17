// Air tasking order (ARCHITECTURE D46): a plan as the order the bases fly from, one briefing card per package. Print view
// and CSV. Built from existing classes (page, card, table, pills); the print stylesheet hides the chrome.
import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Priority, User } from "../api/types";
import { ErrorText, Loading, Sim } from "../components/ui";
import { PrioPill, hhmm } from "../features/ops";
import { RANK, istTime, label, num } from "../lib/format";

interface Wp { n: number; pos: string; near: string | null }
interface Pkg {
  serial: string; mission: string; name: string | null; priority: Priority; task: string; base: string; recovery: string; type: string;
  n: number; callsigns: string[]; sortie: string | null; tails: string[]; crew: { position: string; rank: string; name: string; callsign: string | null }[];
  loadout: string | null; brief: string; launch: string; on_station: string | null; off_station: string | null; land: string;
  waypoints: Wp[]; fuel_l: number | null; risk: number | null;
  tanker: { base: string | null; type: string | null; tails: string[]; rv: string; rv_start: string; rv_end: string; launch: string; callsigns: string[] } | null;
  notes: { label: string; value: string; note: string }[];
}
interface AtoView { plan: { id: number; kind: string; status: string; horizon_start: string; horizon_end: string; committed_at: string | null };
  draft: boolean; scope: string; issued: string; packages: Pkg[]; uncovered: { mission: string; priority: Priority; reason: string | null }[] }

const z = (d: string | null) => (d ? new Date(d).toISOString().slice(11, 16) + "Z" : "—");

export function Ato({ user }: { user: User }) {
  const { pid } = useParams();
  const [params, setParams] = useSearchParams();
  const base = params.get("base") ?? "";
  const q = useQuery({ queryKey: ["ato", pid, base], queryFn: () => api<AtoView>(`/ops/plans/${pid}/ato${base ? `?base_id=${base}` : ""}`) });
  const bases = useQuery({ queryKey: ["bases-own"], queryFn: () => api<{ id: number; code: string; side: string }[]>("/bases"), staleTime: Infinity });
  if (q.isLoading) return <div className="page"><Loading /></div>;
  if (q.error) return <div className="page"><ErrorText error={q.error} /></div>;
  const a = q.data!;
  return (
    <div className="page ato">
      <h1 className="page-title">Air tasking order <Sim title="Simulated order" />
        {a.draft && <span className="pill s-caution" style={{ marginLeft: 8 }}><span aria-hidden>▲</span>DRAFT · plan not committed</span>}
        <span className="topbar-spacer" />
        {user.role !== "BASE_COMMANDER" && <select className="select no-print" aria-label="Base" value={base} style={{ width: 160 }}
          onChange={(e) => setParams(e.target.value ? { base: e.target.value } : {})}>
          <option value="">Theatre</option>
          {(bases.data ?? []).filter((b) => b.side === "OWN").map((b) => <option key={b.id} value={b.id}>{b.code}</option>)}
        </select>}
        <a className="btn btn-sm no-print" href={`/api/v1/ops/plans/${pid}/ato?format=csv${base ? `&base_id=${base}` : ""}`}>Download CSV</a>
        <button className="btn btn-sm no-print" onClick={() => print()}>Print</button>
        <a className="btn btn-sm no-print" href={`/planner?plan=${pid}`}>Back to plan</a></h1>
      <div className="muted" style={{ marginBottom: 12 }}>
        {a.scope} · plan #{a.plan.id} ({label(a.plan.kind)}, {label(a.plan.status)}) · valid {istTime(a.plan.horizon_start, true)} – {istTime(a.plan.horizon_end, true)} ·
        issued {istTime(a.issued, true)} (simulated time) · {a.packages.length} packages. SIMULATED: synthetic data, not for operational use.
      </div>
      {a.packages.map((p) => (
        <section key={p.serial} className="card ato-card" style={{ marginBottom: 12, breakInside: "avoid" }} aria-label={`Package ${p.serial} ${p.mission}`}>
          <div className="card-title"><span><span className="mono">{p.serial}</span> <PrioPill p={p.priority} /> <span className="mono">{p.mission}</span>{" "}
            <span className="muted" style={{ fontWeight: 400 }}>{p.name}</span></span>
            <span className="mono">{p.n} × {p.type} · {p.base}{p.recovery !== p.base ? ` → ${p.recovery}` : ""}</span></div>
          <div className="grid-2" style={{ marginTop: 8 }}>
            <table className="table" style={{ fontSize: 12 }}>
              <tbody>
                <tr><td>Task</td><td>{label(p.task)}{p.loadout ? ` · ${p.loadout}` : ""}</td></tr>
                <tr><td>Callsigns</td><td className="mono">{p.callsigns.length ? p.callsigns.join(", ") : "on crew-up"}{p.sortie ? ` · ${p.sortie}` : ""}</td></tr>
                <tr><td>Tails</td><td className="mono">{p.tails.join(", ")}</td></tr>
                <tr><td>Crew</td><td style={{ whiteSpace: "normal" }}>{p.crew.map((c) => `${label(c.position)} ${RANK[c.rank] ?? c.rank} ${c.name}${c.callsign ? ` (${c.callsign})` : ""}`).join(" · ")}</td></tr>
                <tr><td>Times (Zulu / IST)</td><td className="mono">brief {z(p.brief)} · launch {z(p.launch)} · on station {z(p.on_station)}–{z(p.off_station)} · land {z(p.land)}
                  <span className="dim"> ({hhmm(p.launch)}–{hhmm(p.land)} IST)</span></td></tr>
                {p.fuel_l != null && <tr><td>Fuel / route risk</td><td className="mono">{num(p.fuel_l, 0)} L · peak {num(p.risk, 2)}</td></tr>}
                {p.tanker && <tr><td>Tanker</td><td style={{ whiteSpace: "normal" }}>{p.tanker.type} from <span className="mono">{p.tanker.base}</span>
                  {p.tanker.tails.length ? <span className="mono"> ({p.tanker.tails.join(", ")})</span> : null} · meet <span className="mono">{p.tanker.rv}</span> {z(p.tanker.rv_start)}–{z(p.tanker.rv_end)}</td></tr>}
              </tbody>
            </table>
            <table className="table" style={{ fontSize: 12 }}>
              <thead><tr><th>Waypoint</th><th>Position</th><th>Near</th></tr></thead>
              <tbody>{p.waypoints.map((w) => <tr key={w.n}><td className="mono">{w.n === 1 ? "DEP" : w.n === p.waypoints.length ? "ARR" : `WP${w.n - 1}`}</td>
                <td className="mono">{w.pos}</td><td className="dim">{w.near ?? "—"}</td></tr>)}</tbody>
            </table>
          </div>
          {p.notes.length > 0 && <div style={{ marginTop: 6, fontSize: 12 }}>{p.notes.map((n) => (
            <div key={n.label}><b>{n.label}:</b> {n.value}{n.note ? <span className="dim"> · {n.note}</span> : null}</div>))}</div>}
        </section>
      ))}
      {a.uncovered.length > 0 && <>
        <h3 className="section-h">Not tasked</h3>
        {a.uncovered.map((u) => <div key={u.mission} style={{ fontSize: 12, margin: "2px 0" }}><PrioPill p={u.priority} /> <span className="mono">{u.mission}</span>
          <span className="dim"> · {u.reason}</span></div>)}
      </>}
    </div>
  );
}
