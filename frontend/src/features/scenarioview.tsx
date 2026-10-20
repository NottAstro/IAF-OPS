// The Planner (ARCHITECTURE D61, D65, D66). The landing page is one card per situation (each live scenario and routine
// tasking). Opening a card walks that one situation through four steps, with nothing else on screen:
//   1 Situation: what happened and the missions it affects
//   2 Plan: for each mission the planner's recommendation and why, two other options, Keep / Keep all
//   3 Decide: only what you decided
//   4 Mission: approve it and watch the missions fly (also on Map → Ops)
// D66: the content is scripted per scenario (features/scripts.ts) so every scenario reads the same way, and approval is
// demo state in this browser. Nothing here writes sorties; Planner → Details & tools stays on the real planner.
import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Intensity, LiveScenario, User } from "../api/types";
import { Loading, Sim } from "../components/ui";
import { istTime } from "../lib/format";
import { useStore } from "../store";
import { type Decision, type DemoRun, type Kind, type Pkg, ROUTINE, type Script, type ScriptMission, type Status, baseName, chosen,
  isGround, routineStart, scriptFor, statusAt, statusWord, timesOf, validRun } from "./scripts";

export const INT_COLOUR: Record<Intensity, string> = { LOW: "var(--ok)", MEDIUM: "var(--caution)", HIGH: "var(--warning)", SEVERE: "var(--critical)" };
const INT_N: Record<Intensity, number> = { LOW: 1, MEDIUM: 2, HIGH: 3, SEVERE: 4 };

/** Intensity as four dots (colour plus count, never colour alone). */
export const IntensityDots = ({ i }: { i: Intensity | null | undefined }) => (
  <span className="int-dots" title={i ? `${i.toLowerCase()} intensity` : undefined}>
    {[1, 2, 3, 4].map((k) => <i key={k} style={i && k <= INT_N[i] ? { background: INT_COLOUR[i] } : undefined} />)}
  </span>
);
export const mins = (m: number) => (m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`);

const MIN = 60e3;
const istDay = (d: string) => istTime(d, true).slice(0, 6);
/** HH:MM IST; a time on another simulated day says which ("tomorrow 01:09", "22 Oct 01:09"). */
const hh = (d: string | number | undefined | null) => {
  if (d == null) return "—";
  const s = typeof d === "number" ? new Date(d).toISOString() : d;
  const t = istTime(s).replace(" IST", ""), now = useStore.getState().simClock?.sim_now;
  if (!now || istDay(s) === istDay(now)) return t;
  return istDay(s) === istDay(new Date(Date.parse(now) + 864e5).toISOString()) ? `tomorrow ${t}` : `${istDay(s)} ${t}`;
};
const pkgText = (p: Pkg) => `${p.n} × ${p.type} from ${baseName(p.base)}`;
const KIND: Record<Kind, [string, string]> = { added: ["info", "added"], moved: ["warn", "moved"], "not flown": ["crit", "not flown"] };
const KIND_WORDS: Record<Kind, string> = { added: "new mission", moved: "moved to another base or time", "not flown": "can't be flown as asked" };
const STATUS: Record<Status, [string, string]> = { waiting: ["warn", "waiting"], approved: ["ok", "approved"], airborne: ["info", "airborne"],
  "on station": ["info", "on station"], returning: ["info", "returning"], landed: ["ok", "landed"], "not flown": ["crit", "not flown"] };
const TEXT_TONE: Record<string, string> = { ok: "s-ok", warn: "s-warning", info: "s-info", crit: "s-critical" };
const VERB = (m: ScriptMission, d: Decision | undefined) => typeof d === "number" ? "Your choice" : d === "accept" || (d === "keep" && !m.pkg) ? "Not flown" : "Keep";

// ---------------------------------------------------------------- situations and their demo state
export interface Sit { key: string; script: Script; started: string; runId: number | null }

/** Live scenarios with a script, then Routine tasking (Planner landing, Overview). */
export function useSituations(): { sits: Sit[]; now: string; loading: boolean } {
  const live = useQuery({ queryKey: ["scenarios", "live"], queryFn: () => api<LiveScenario[]>("/ops/scenarios/live"), refetchInterval: 5000 });
  const now = useStore((s) => s.simClock?.sim_now) ?? new Date().toISOString();
  const sits: Sit[] = (live.data ?? []).flatMap((r) => {
    const script = scriptFor(r.code);
    return script ? [{ key: String(r.id), script, started: r.started_sim, runId: r.id }] : [];
  });
  sits.push({ key: "routine", script: ROUTINE, started: routineStart(now), runId: null });
  return { sits, now, loading: live.isLoading };
}

/** The decisions and approval for one situation; a record left from an earlier run with the same id is ignored. */
function useRun(sit: Sit) {
  const rec = useStore((s) => s.demo[sit.key]);
  const setDemo = useStore((s) => s.setDemo);
  const now = useStore((s) => s.simClock?.sim_now) ?? new Date().toISOString();
  const run: DemoRun = validRun(rec, sit.started) ?? { started: sit.started, dec: {}, approvedAt: null };
  const decide = (id: string, d: Decision | null) => {
    const dec = { ...run.dec };
    if (d == null) delete dec[id]; else dec[id] = d;
    setDemo(sit.key, { ...run, dec });
  };
  return {
    run, decide,
    keepAll: (ids: string[]) => setDemo(sit.key, { ...run, dec: { ...run.dec, ...Object.fromEntries(ids.map((i) => [i, "keep" as Decision])) } }),
    approve: () => setDemo(sit.key, { ...run, approvedAt: now }),
    reject: () => setDemo(sit.key, null),
  };
}

const firstLaunch = (s: Script, run: DemoRun, now: string) => {
  const ls = s.missions.map((m) => chosen(m, run.dec[m.id])).filter((p): p is Pkg => !!p).map((p) => ({ p, t: timesOf(p, run.approvedAt, now).launch }));
  return ls.sort((a, b) => a.t - b.t)[0];
};

// ---------------------------------------------------------------- the page
export function PlannerFlow({ user }: { user: User }) {
  const [params, setParams] = useSearchParams();
  const { sits, now, loading } = useSituations();
  if (loading) return <Loading />;
  const canPlan = user.role === "ADMIN" || user.role === "COMMAND_HQ";
  const key = params.get("run");
  const cur = key ? sits.find((x) => x.key === key) : undefined;
  if (key && !cur) return <div className="live-empty"><h2>That scenario has ended</h2><p className="muted">Its missions were withdrawn.</p>
    <button className="btn" onClick={() => setParams({})}>← All situations</button></div>;
  const step = Math.min(4, Math.max(1, Number(params.get("step") ?? 1)));
  return cur
    ? <SituationFlow key={cur.key} sit={cur} now={now} step={step} canPlan={canPlan} go={(n) => setParams({ run: cur.key, step: String(n) })} back={() => setParams({})} />
    : <Landing sits={sits} now={now} canPlan={canPlan} open={(k) => setParams({ run: k, step: "1" })} />;
}

/** The landing (D70): one situation per row, those waiting for a decision first, routine tasking after the scenarios. */
function Landing({ sits, now, canPlan, open }: { sits: Sit[]; now: string; canPlan: boolean; open: (k: string) => void }) {
  const demo = useStore((s) => s.demo);
  const decided = (x: Sit) => !!validRun(demo[x.key], x.started)?.approvedAt;
  const waiting = sits.filter((x) => !decided(x)).length;
  const rows = [...sits].sort((a, b) => Number(decided(a)) - Number(decided(b)) || Number(!a.runId) - Number(!b.runId));
  return (
    <div>
      <p className="live-lead" style={{ marginTop: 0 }}>{waiting ? <><b>{waiting} situation{waiting > 1 ? "s" : ""} wait for your decision.</b> Open one to see what
        happened and what the planner recommends.</> : "Every situation is decided. Open one to watch its missions."} <Sim title="Everything here is simulated" /></p>
      <div className="sit-list">
        {rows.map((x) => <SitRow key={x.key} sit={x} now={now} onOpen={() => open(x.key)} />)}
        {canPlan && <Link className="sit-add" to="/scenarios"><span aria-hidden>+</span> Start a scenario</Link>}
      </div>
    </div>
  );
}

function SitRow({ sit, now, onOpen }: { sit: Sit; now: string; onOpen: () => void }) {
  const { run } = useRun(sit);
  const s = sit.script;
  const pkgs = s.missions.map((m) => statusAt(chosen(m, run.dec[m.id]), run.approvedAt, now));
  const flying = pkgs.filter((x) => x === "airborne" || x === "on station" || x === "returning").length;   // under way, in the air or on the road
  const landed = pkgs.filter((x) => x === "landed").length, dropped = pkgs.filter((x) => x === "not flown").length;
  const [tone, line] = !run.approvedAt ? ["warn", `◆ ${s.missions.length} recommendation${s.missions.length > 1 ? "s" : ""} wait for your decision`]
    : landed + dropped === pkgs.length ? ["ok", `✓ Done: ${landed} carried out${dropped ? `, ${dropped} not flown` : ""}`]
    : ["ok", `✓ Approved${flying ? ` · ${flying} under way` : ""}`];
  const colour = sit.runId ? INT_COLOUR[s.intensity] : "var(--text-3)";
  return (
    <button className="sit-row" style={{ borderLeftColor: colour }} onClick={onOpen}>
      <div className="sr-main">
        <h3><span className="dot" style={{ background: colour }} />{s.name}</h3>
        <div className="meta">{s.category}{sit.runId ? <><IntensityDots i={s.intensity} /><span>since {hh(sit.started)}</span></> : <span>today</span>}</div>
        <p className="lead">{s.lead}</p>
      </div>
      <ul className="sr-facts" aria-label="What happened">{s.happened.slice(0, 3).map((h, k) => <li key={k}>{h.what}</li>)}</ul>
      <div className="sr-side">
        <div className={`sit-state ${tone}`}>{line}</div>
        <div className="foot"><span className="dim">{s.missions.length} mission{s.missions.length > 1 ? "s" : ""} affected</span><span className="btn btn-sm btn-primary">Open →</span></div>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------- one situation, four steps
const STEPS: [string, string][] = [["Situation", "what happened"], ["Plan", "recommendations and options"], ["Decide", "what you decided"], ["Mission", "approve and watch"]];

function SituationFlow({ sit, now, step, canPlan, go, back }: { sit: Sit; now: string; step: number; canPlan: boolean;
  go: (n: number) => void; back: () => void }) {
  const { run, decide, keepAll, approve, reject } = useRun(sit);
  const nav = useNavigate();
  const showOnMap = (m: ScriptMission) => {   // D71: open Map → Ops framed on this package
    useStore.getState().set({ mode: "OPS", selection: { kind: "plan-mission", run: sit.key, mission: m.id, fit: Date.now() } });
    nav("/map");
  };
  const s = sit.script;
  const open = s.missions.filter((m) => run.dec[m.id] === undefined).length;
  const decided = s.missions.length - open;
  const badge = [null, open ? `${open} to decide` : "all decided", decided ? `${decided} decided` : null, run.approvedAt ? "approved" : "waiting"];
  const first = firstLaunch(s, run, now);
  const ends = Math.max(0, ...s.happened.map((h) => h.ends ?? 0));
  const timeline: [string | number, string, string][] = [
    [sit.started, sit.runId ? "Event" : "Today's tasking", "done"], [Date.parse(sit.started) + MIN, "Planner ready", "done"],
    run.approvedAt ? [run.approvedAt, "Approved", "done"] : [now, "Your decision (now)", "now"],
    ...(first ? [[first.t, `${isGround(first.p.type) ? "First out" : "First launch"}: ${first.p.n} × ${first.p.type}`, first.t <= Date.parse(now) ? "done" : "next"] as [number, string, string]] : []),
    ...(sit.runId && ends ? [[Date.parse(sit.started) + ends * MIN, "Back to normal", "next"] as [number, string, string]] : []),
  ];
  return (
    <div>
      <button className="back-link" onClick={back}>← All situations</button>
      <nav className="steps4" aria-label="Steps">
        {STEPS.map(([name, sub], i) => (
          <button key={name} className={i + 1 === step ? "on" : i + 1 < step ? "done" : ""} aria-current={i + 1 === step ? "step" : undefined} onClick={() => go(i + 1)}>
            <span className="n">{i + 1 < step ? "✓" : i + 1}</span><span><b>{name}</b><small>{sub}</small></span>
            {badge[i] && <span className={`badge${badge[i] === "waiting" || badge[i]?.includes("to decide") ? " warn" : ""}`}>{badge[i]}</span>}
          </button>
        ))}
      </nav>

      <div className="sit-head">
        <h2><span className="dot" style={{ background: sit.runId ? INT_COLOUR[s.intensity] : "var(--text-3)" }} />{s.name}
          {sit.runId ? <><span className="live-chip">● live</span><span className="muted" style={{ fontSize: 13, fontWeight: 400 }}>since {hh(sit.started)}</span></>
            : <span className="muted" style={{ fontSize: 13, fontWeight: 400 }}>today</span>}<Sim title="Everything in a scenario is simulated" /></h2>
        <p className="live-lead">{s.lead}</p>
        <div className="mini-steps">{timeline.map(([t, l, st], k) => <span key={k} className={st}><i />{hh(t)} {l}</span>)}</div>
      </div>

      {step === 1 && <>
        <section className="sbox">
          <h3 className="sbox-h">What happened</h3>
          <ul className="facts">{s.happened.map((h, k) => <li key={k}><span>{h.what}</span>
            <span>{h.ends != null ? `until ${hh(Date.parse(sit.started) + h.ends * MIN)}` : ""}</span></li>)}</ul>
        </section>
        <Missions title="Missions affected" sit={sit} run={run} now={now} col1={(m) => KIND[m.kind]}
          col4={(m) => {
            const p = chosen(m, run.dec[m.id]), st = statusAt(p, run.approvedAt, now);
            return run.approvedAt ? [TEXT_TONE[STATUS[st][0]], statusWord(st, p?.type)] : run.dec[m.id] !== undefined ? ["s-ok", "✓ decided"] : ["s-warning", "◆ recommendation ready"];
          }} />
        <NextBar note="The planner has worked out an answer for each mission. Review them in Plan." label="Plan it →" onNext={() => go(2)} />
      </>}

      {step === 2 && <div className="plan-grid">
        <section style={{ minWidth: 0 }}>
          {canPlan && open > 1 && !run.approvedAt && <NextBar note={`${open} of the planner's recommendations are not decided yet.`}
            label={`✓ Keep all ${open}`} onNext={() => keepAll(s.missions.filter((m) => run.dec[m.id] === undefined).map((m) => m.id))} />}
          {s.missions.map((m, k) => <TaskCard key={m.id} n={k + 1} m={m} d={run.dec[m.id]} run={run} now={now} canPlan={canPlan && !run.approvedAt}
            onDecide={(d) => decide(m.id, d)} />)}
          <NextBar note={open ? `${open} still to decide.` : "Everything is decided."} label="Next: decide →" onNext={() => go(3)} />
        </section>
        <Needs s={s} run={run} now={now} />
      </div>}

      {step === 3 && <>
        <Missions title="What you decided" sit={sit} run={run} now={now} only={(m) => run.dec[m.id] !== undefined}
          col1={(m) => { const v = VERB(m, run.dec[m.id]); return [v === "Not flown" ? "crit" : v === "Your choice" ? "info" : "ok", v]; }}
          col4={(m) => { const p = chosen(m, run.dec[m.id]); return ["mono dim", p ? `launch ${hh(timesOf(p, run.approvedAt, now).launch)}` : ""]; }}
          empty="Nothing decided yet." />
        {open > 0 ? <NextBar note={<span className="s-warning">◆ {open} not decided yet. Undecided missions follow the planner's recommendation.</span>}
          label="← Back to plan" onNext={() => go(2)} />
          : <NextBar note="Approving turns these decisions into missions." label="Next: mission →" onNext={() => go(4)} />}
      </>}

      {step === 4 && <>
        {!run.approvedAt ? <div className="approve-box">
          <div><b>Approve to turn your decisions into missions.</b> Undecided missions follow the planner's recommendation; the packages then fly on
            the sim clock and appear on Map → Ops.</div>
          {canPlan ? <div className="approve-act"><button className="btn btn-danger" onClick={reject}>Reject</button>
            <button className="btn btn-primary" onClick={approve}>Approve missions</button></div> : <span className="muted">waiting for Air HQ</span>}
        </div> : <div className="notice" style={{ marginBottom: "var(--s3)" }}>✓ Approved at {hh(run.approvedAt)}. The missions fly on the sim clock;
          click one to watch it on Map → Ops.</div>}
        <Missions title="Missions for this situation" sit={sit} run={run} now={now} onMap={showOnMap}
          col1={(m) => { const p = chosen(m, run.dec[m.id]), st = statusAt(p, run.approvedAt, now); return [STATUS[st][0], statusWord(st, p?.type)]; }}
          col4={(m) => {
            const p = chosen(m, run.dec[m.id]);
            if (!p) return ["dim", ""];
            const st = statusAt(p, run.approvedAt, now), { launch, back: home } = timesOf(p, run.approvedAt, now);
            const air = st === "airborne" || st === "on station" || st === "returning";
            const g = isGround(p.type);   // vehicles leave and come back; aircraft launch and land
            return [`mono${air ? " s-info" : " dim"}`, st === "landed" ? `${g ? "back" : "landed"} ${hh(home)}` : air ? `${g ? "back" : "lands"} ${hh(home)}`
              : `${g ? "leaves" : "launch"} ${hh(launch)}`];
          }} />
      </>}
    </div>
  );
}

/** One `.r4` row per mission (D65): pill · mission · package and time · status. Steps 1, 3 and 4 differ only in the columns. */
function Missions({ title, sit, run, now, col1, col4, only, empty, onMap }: { title: string; sit: Sit; run: DemoRun; now: string;
  col1: (m: ScriptMission) => [string, string]; col4: (m: ScriptMission) => [string, string]; only?: (m: ScriptMission) => boolean; empty?: string;
  onMap?: (m: ScriptMission) => void }) {
  const ms = sit.script.missions.filter((m) => !only || only(m));
  return (
    <section className="sbox">
      <h3 className="sbox-h">{title} <span className="count">{ms.length}</span></h3>
      {ms.length === 0 && <div className="empty" style={{ padding: "12px 16px" }}>{empty}</div>}
      {ms.map((m) => {
        const p = chosen(m, run.dec[m.id]);
        const [t1, w1] = col1(m), [t4, w4] = col4(m);
        const t = p ? timesOf(p, run.approvedAt, now) : null;
        return (
          <div key={m.id} className={`r4${onMap ? " go" : ""}`} {...(onMap && { role: "button", tabIndex: 0, title: "Show on Map → Ops",
            onClick: () => onMap(m), onKeyDown: (e: React.KeyboardEvent) => (e.key === "Enter" || e.key === " ") && onMap(m) })}>
            <span><span className={`fl-pill ${t1}`}>{w1}</span></span>
            <span>{m.priority} {m.name}<small>{m.reason}</small></span>
            <span className="pkg">{p ? pkgText(p) : <span className="dim">no package</span>}{t && <small>{hh(t.launch)} – {hh(t.back)}</small>}</span>
            <span className={t4}>{w4}{onMap && <small className="go-hint">on map ›</small>}</span></div>
        );
      })}
    </section>
  );
}

const NextBar = ({ note, label, onNext }: { note: ReactNode; label: string; onNext: () => void }) => (
  <div className="next-bar"><span className="muted">{note}</span><button className="btn btn-primary" onClick={onNext}>{label}</button></div>
);

/** One mission: what the planner recommends and why, Keep, and the two other options (step 2). */
function TaskCard({ n, m, d, run, now, canPlan, onDecide }: { n: number; m: ScriptMission; d: Decision | undefined; run: DemoRun; now: string;
  canPlan: boolean; onDecide: (d: Decision | null) => void }) {
  const [more, setMore] = useState(false);
  const p = chosen(m, d);
  const t = p ? timesOf(p, run.approvedAt, now) : null;
  const word = d === undefined ? null : `✓ ${VERB(m, d) === "Keep" ? "Kept" : VERB(m, d)}`;
  return (
    <div className={`tk${d !== undefined ? " decided" : ""}`}>
      <div className="tk-top"><span className="num">{n}</span>
        <div className="prob">{m.priority} {m.name}<small>{KIND_WORDS[m.kind]} · {m.reason}</small></div>
        <span className={`fl-pill ${KIND[m.kind][0]}`}>{KIND[m.kind][1]}</span></div>
      <div className="tk-ans"><span />
        <div><div className="lbl">{typeof d === "number" ? "Your choice" : m.pkg ? "Planner's recommendation" : "Planner's answer"}</div>
          <div className="pick">{p ? pkgText(p) : "Can't be flown as asked"}{t && <span className="mono dim" style={{ fontSize: 12 }}> · {hh(t.launch)} – {hh(t.back)}</span>}</div>
          <div className="why">{typeof d === "number" ? `Trade-off: ${m.options[d].tradeoff}` : p ? `Why: ${p.why.join(" · ")}` : `Why: ${m.reason}. The other options fly it another way.`}</div></div>
        <div className="tk-act">
          {word ? <div className="done"><span className="s-ok">{word}</span>{canPlan && <button className="tog" onClick={() => onDecide(null)}>change</button>}</div>
            : canPlan && <button className="btn btn-sm" onClick={() => onDecide(m.pkg ? "keep" : "accept")}>{m.pkg ? "✓ Keep" : "✓ Accept"}</button>}
          {canPlan && <button className="btn btn-sm btn-ghost" onClick={() => setMore(!more)}>Other options ▾</button>}
        </div>
      </div>
      {more && <div className="tk-opts">
        <div className="opt-h">The planner's other options</div>
        {m.options.map((o, k) => (
          <div key={k} className="opt-row"><span>{pkgText(o.pkg)} · launch {hh(timesOf(o.pkg, run.approvedAt, now).launch)} <span className="dim">· {o.tradeoff}</span></span>
            <button className="btn btn-sm" disabled={d === k} onClick={() => { onDecide(k); setMore(false); }}>{d === k ? "Chosen" : "Use this instead"}</button></div>
        ))}
      </div>}
    </div>
  );
}

const REQ: Record<string, [string, string]> = { met: ["✓ committed", "var(--ok)"], approve: ["once approved", "var(--warning)"] };

/** Step 2 side panel: what the chosen packages need, from which base, and when. */
function Needs({ s, run, now }: { s: Script; run: DemoRun; now: string }) {
  const rows = s.missions.flatMap((m) => { const p = chosen(m, run.dec[m.id]); return p ? [{ m, p }] : []; });
  const st = run.approvedAt ? "met" : "approve";
  return (
    <aside className="req-side">
      <h2 className="needs-h">What this situation needs</h2>
      {rows.length === 0 && <div className="empty">Nothing beyond the bases' own stock.</div>}
      {rows.map(({ m, p }) => { const t = timesOf(p, run.approvedAt, now); return (
        <div key={m.id} className="req">
          <div className="a"><b style={{ fontWeight: 400 }}>{m.name}</b><span style={{ color: REQ[st][1] }}>{REQ[st][0]}</span></div>
          <div className="nf"><span className="k">Need</span><span>{p.n} × {p.type} · {p.n} crew{p.n > 1 ? "s" : ""}</span>
            <span className="k">From</span><span>{baseName(p.base)} · {p.free} free, {p.crews} rested</span>
            <span className="k">When</span><span className="mono">{hh(t.launch)} – {hh(t.back)}</span></div>
          <div className={`bar${st === "approve" ? " ap" : ""}`}><i style={{ width: `${Math.min(100, (100 * p.n) / Math.max(p.free, 1))}%` }} /></div>
        </div>); })}
    </aside>
  );
}
