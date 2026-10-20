"""The Planner's live scenario view (ARCHITECTURE D55): for one scenario run, what it broke, what the engine recommends
for each impact, and what those recommendations need from which base.

Nothing here decides anything. Impacts are the run's disruptions (exercise.owner tags them) plus the effects it applied;
recommendations are the re-task proposal's changed packages and checked fixes; requirements are counted with
resources.py against a snapshot, so "free" means the same thing as in the planner.
"""
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import models as M
from . import config as DC
from . import exercise as EX
from . import logistics as LG
from . import snapshot as S
from . import store
from .optimiser import launch_capacity, slot_of
from .resources import Req, aircraft_free, crew_eligible, crew_free

FIRST = {"AIRCRAFT_LOST": "Crash", "RUNWAY_CLOSED": "Runway closed", "MISSION_POPUP": "Call for help", "WX_FRONT": "Front arrives",
         "FUEL_DELAY": "Convoys delayed", "AIRCRAFT_GROUNDING": "Fleet grounded", "RADAR_DOWN": "Radars offline",
         "BASE_STRIKE": "Strike", "THREAT_ZONE": "Threat zone up"}
END = {"RUNWAY_CLOSED": "Runway opens", "WX_FRONT": "Front clears", "FUEL_DELAY": "Resupply", "AIRCRAFT_GROUNDING": "Fleet back",
       "RADAR_DOWN": "Radars back", "THREAT_ZONE": "Zone clears", "MISSION_POPUP": "Deadline"}
LIVE = ("AIRBORNE", "ON_STATION", "RTB")
SEV = {"P1": "c", "P2": "w", "P3": "y", "P4": "y"}
IST = timezone(timedelta(hours=5, minutes=30))

_snap: dict = {"t": 0.0, "st": None}
_snap_lock = threading.Lock()


def snapshot(db: Session) -> S.OpsState:
    """ponytail: a 30 s cached snapshot (a build takes seconds); counts can lag the world by that much. Upgrade path: have
    the monitor publish the snapshot it already builds every 12 s."""
    with _snap_lock:
        if _snap["st"] is None or time.monotonic() - _snap["t"] > 30:
            _snap["st"], _snap["t"] = S.build(db), time.monotonic()
        return _snap["st"]


def _short(name: str | None) -> str:
    return (name or "").replace("Air Force Station ", "").replace("Air Force Academy ", "")


def _now(db: Session) -> datetime:
    return db.execute(text("SELECT sim_now()")).scalar()


def _bases(db: Session) -> dict:
    return {r.code: _short(r.name) for r in db.execute(text("SELECT code, name FROM base WHERE side = 'OWN'"))}


def lead(sc: M.Scenario, run: M.ExerciseRun, names: dict) -> str:
    p = dict(run.params or {})
    for k, v in list(p.items()):          # {base} -> code, {base_name} -> "Bidar"; lists of bases joined
        if isinstance(v, str) and v in names:
            p[f"{k}_name"] = names[v]
        elif isinstance(v, list) and v and all(isinstance(x, str) and x in names for x in v):
            p[f"{k}_name"] = ", ".join(names[x] for x in v)
    return str(EX.fill(sc.lead or sc.description or "", p))


# ---------------------------------------------------------------- attribution
def _missions_of(db: Session, run: M.ExerciseRun) -> set:
    ids = {r[0] for r in db.execute(text("""SELECT (payload->>'mission_id')::bigint FROM disruption
                                            WHERE exercise_run_id = :r AND payload->>'mission_id' IS NOT NULL
                                            UNION SELECT id FROM mission WHERE exercise_run_id = :r"""), {"r": run.id})}
    return ids | set((run.footprint or {}).get("missions", []))


def _plans(db: Session, run: M.ExerciseRun) -> tuple[list[M.Plan], M.Plan | None]:
    """Plans committed since the run started (oldest first: full plans and re-tasks) and the proposal waiting for a
    decision (D56: a full plan when nothing was committed, else a re-task)."""
    done = list(db.scalars(select(M.Plan).where(M.Plan.kind.in_(("PLAN", "RETASK")), M.Plan.committed_at.is_not(None),
                                                M.Plan.committed_at >= run.started_real).order_by(M.Plan.id)))
    pending = db.scalars(select(M.Plan).where(M.Plan.kind.in_(("PLAN", "RETASK")), M.Plan.status.in_(("PROPOSED", "APPROVED")))
                         .order_by(M.Plan.id.desc())).first()
    return done, pending if run.status == "RUNNING" else None


CAUSE = {"RUNWAY_CLOSED": "RUNWAY_CLOSED", "WX_LAUNCH": "WX_BELOW_MINIMA", "WX_RECOVERY": "WX_BELOW_MINIMA", "FUEL_SHORT": "FUEL_SHORT",
         "NOT_ENOUGH_AIRCRAFT": "AIRCRAFT_US", "THREAT_TOO_HIGH": "THREAT_ACTIVATED"}
# which uncovered-mission reasons each scenario effect can cause
EFFECT_REASONS = {"RUNWAY_CLOSED": {"RUNWAY_CLOSED"}, "WX_FRONT": {"WX_LAUNCH", "WX_RECOVERY"}, "FUEL_DELAY": {"FUEL_SHORT"},
                  "AIRCRAFT_LOST": {"NOT_ENOUGH_AIRCRAFT"}, "AIRCRAFT_GROUNDING": {"NOT_ENOUGH_AIRCRAFT"}, "THREAT_ZONE": {"THREAT_TOO_HIGH"}}


def _cause(u: dict, codes: dict, allowed: set | None = None) -> dict | None:
    """A routine mission left uncovered because of this scenario (D59): a reason this scenario's own effects produce
    (allowed: a runway closure -> "runway closed", a front -> weather, ...) names a base the scenario hit, e.g.
    "Runway closed: VOBR at 09:13Z". -> a disruption-like {"kind", "base_id"} for the wording, else None."""
    for r in u.get("reasons") or []:
        if r.get("code") in CAUSE and (allowed is None or r["code"] in allowed):
            for bid, code in codes.items():
                if any(code in x for x in r.get("examples") or []):
                    return {"kind": CAUSE[r["code"]], "base_id": bid, "message": r.get("text", "")}
    return None


def _attributed(db: Session, run: M.ExerciseRun) -> tuple[dict, dict, M.Plan | None, dict]:
    """mission id -> (item view, plan status) and mission id -> (unmet view, plan status) for this run, latest plan wins;
    plus the pending proposal and the source items of changed packages."""
    mine = _missions_of(db, run)
    others = set()
    for r in EX.running(db):
        if r.id != run.id:
            others |= _missions_of(db, r)
    bases = set((run.footprint or {}).get("bases", []))
    codes = {r.id: r.code for r in db.execute(text("SELECT id, code FROM base WHERE id = ANY(:i)"), {"i": list(bases) or [0]})}
    allowed = set().union(*[EFFECT_REASONS.get(e.get("kind"), set()) for e in (run.footprint or {}).get("effects", [])] or [set()])
    done, pending = _plans(db, run)
    items, unmet = {}, {}
    for p in done + ([pending] if pending else []):
        view = store.serialise(db, p.id)
        status = "proposed" if p.status in ("PROPOSED", "APPROVED") else "in"
        for it in view["items"]:
            mid = it["mission"]["id"] if it["mission"] else None
            if mid is None or (p.kind == "RETASK" and (not it["change"] or it["change"] == "KEPT")):
                continue
            if p.kind == "PLAN" and mid not in mine:      # a full plan: only this scenario's own missions
                continue
            knock_on = mid not in others and ((it["base"] or {}).get("id") in bases or (it["recovery_base"] or {}).get("id") in bases)
            if mid in mine or knock_on:
                items[mid] = (it, status)
                unmet.pop(mid, None)
        for u in view["unmet"]:
            mid = u["mission"]["id"] if u["mission"] else None
            cause = None if mid in mine or mid in others or not allowed else _cause(u, codes, allowed)
            if mid in mine or cause:
                unmet[mid] = ({**u, "_cause": cause} if cause else u, status)
                items.pop(mid, None)
    src_ids = [it["source_item_id"] for it, _ in items.values() if it.get("source_item_id")]
    src = {r.id: r for r in db.execute(text("""SELECT pi.id, b.code, b.name, pi.launch_ts FROM plan_item pi JOIN base b ON b.id = pi.base_id
                                              WHERE pi.id = ANY(:i)"""), {"i": src_ids or [0]})}
    return items, unmet, pending, src


# ---------------------------------------------------------------- rows
def _when(it: dict) -> dict:
    s = (it.get("sortie") or {}).get("status")
    if s in ("AIRBORNE", "RTB"):
        return {"kind": "airborne", "a": it["launch_ts"], "b": it["recovery_ts"]}
    if s == "ON_STATION":
        return {"kind": "on_station", "a": it["on_station_ts"], "b": it["recovery_ts"]}
    if s in ("LANDED", "COMPLETED"):
        return {"kind": "done", "a": it["launch_ts"], "b": it["recovery_ts"]}
    return {"kind": "window", "a": it["launch_ts"], "b": it["recovery_ts"]}


def _rec(it: dict, src) -> str:
    n, ty, base = it["n_aircraft"], (it["type"] or {}).get("name", "aircraft"), _short((it["base"] or {}).get("name"))
    ch = it["change"]
    if ch == "DIVERT":
        return f"Divert to {_short((it['recovery_base'] or {}).get('name'))}"
    if ch == "SWAP":
        return f"Other tails or crew at {base}"
    if ch == "REROLE":
        return f"Re-role {n} airborne {ty}"
    if ch == "MOVED" and src is not None and src.code == (it["base"] or {}).get("code"):
        return f"Move to {_hm(it['launch_ts'])}"
    return f"{n} {ty} from {base}"


def _hm(ts) -> str:
    """HH:MM in IST for text the engine writes into sentences (the UI formats structured times itself)."""
    t = _ts(ts)
    return (t.astimezone(IST) if t.tzinfo else t + timedelta(hours=5, minutes=30)).strftime("%H:%M")


def _hm_day(ts, now: datetime) -> str:
    """As _hm, with the day when it isn't the simulated today ("tomorrow 01:09", "22 Oct 01:09")."""
    t, n = _ts(ts).astimezone(IST), now.astimezone(IST)
    if t.date() == n.date():
        return t.strftime("%H:%M")
    return f"tomorrow {t:%H:%M}" if t.date() == n.date() + timedelta(days=1) else f"{t:%d %b %H:%M}"


def _what(d: dict | None, m: dict, it: dict | None, src, dbase: str = "") -> tuple[str, str]:
    """What it broke, in words: from the disruption kind, else from the change."""
    name, base = m["name"], _short((it or {}).get("base", {}).get("name") if it else "")
    srcb = _short(src.name) if src is not None else (base or dbase)
    k = (d or {}).get("kind")
    if k == "RUNWAY_CLOSED":
        return (f"{name}: {srcb} runway closed" if srcb and srcb in name else f"{name} can't launch from {srcb}"), ""
    if k == "RECOVERY_UNSAFE":
        return f"{it['n_aircraft'] if it else 'Aircraft'} {(it or {}).get('type', {}).get('name', '')} in the air can't land as planned".replace("  ", " "), d["message"]
    if k == "AIRCRAFT_US":
        return f"{name} lost its aircraft", ""
    if k == "CREW_UNAVAILABLE":
        return f"{name} lost its crew", ""
    if k == "WX_BELOW_MINIMA":
        return f"{name}: weather below minima at {srcb}", ""
    if k == "FUEL_SHORT":
        return f"{name}: not enough fuel at {srcb}", ""
    if k == "THREAT_ACTIVATED":
        return f"{name}: route crosses the threat zone", ""
    if k == "MISSION_NEW":
        return f"New {m['priority']}: {name}", f"needed by {_hm(m['window_end'])}"
    if it and it.get("change") == "DIVERT":
        return f"{it['n_aircraft']} {it['type']['name']} in the air can't land as planned", ""
    return (f"Knock-on: {name}" if not d else d["message"]), ""


def _named(t: str, cn: dict) -> str:
    """Base codes in the engine's fix text become names ("the runway at VOBR" -> "the runway at Bidar")."""
    return re.sub(r"\b[A-Z]{4}\b", lambda x: cn.get(x.group(0), x.group(0)), t)


def _effect_row(e: dict, now: datetime) -> dict:
    k, until = e["kind"], e.get("until")
    u = f" until {_hm_day(until, now)}" if until else ""
    radars = f"{e.get('count')} radar{'' if e.get('count') == 1 else 's'}"
    what, rec = {
        "AIRCRAFT_LOST": (f"{e.get('count', 1)} {e.get('type')} lost at {e.get('base_name')}", "Written off; out of every plan"),
        "AIRCRAFT_GROUNDING": (f"{e.get('count')} {e.get('type')} grounded", f"Out of the plan{u}"),
        "RUNWAY_CLOSED": (f"{e.get('base_name')} runway closed", f"Reopens{u.replace(' until', '')}"),
        "WX_FRONT": (f"{', '.join(e.get('bases', []))} below flying minima", f"Front clears{u.replace(' until', '')}"),
        "FUEL_DELAY": (f"{', '.join(e.get('bases', []))} fuel down {e.get('loss_pct', 0):.0f}%", f"Resupply{u.replace(' until', '')}"),
        "RADAR_DOWN": (f"{radars} offline at {e.get('base_name')}", f"Back{u.replace(' until', '')}"),
        "THREAT_ZONE": (f"Threat zone, risk {e.get('risk', 0):.1f}", f"Routes avoid it{u}"),
    }.get(k, (None, None))
    return {"sev": "n", "what": what, "sub": e.get("left") is not None and f"{e['left']} left there" or "", "rec": rec,
            "alts": [], "when": None, "status": "info"} if what else {}


def response(db: Session, run_id: int) -> dict:
    run = db.get(M.ExerciseRun, run_id)
    if not run:
        raise ValueError("Scenario run not found")
    sc = db.get(M.Scenario, run.scenario_id) if run.scenario_id else None
    now = _now(db)
    names = _bases(db)
    by_id, cn = {}, {}
    for r in db.execute(text("SELECT id, code, name FROM base WHERE side = 'OWN'")):
        by_id[r.id] = cn[r.code] = _short(r.name)
    items, unmet, pending, src = _attributed(db, run)
    dis = {r["mid"]: r for r in db.execute(text("""SELECT DISTINCT ON ((payload->>'mission_id')::bigint)
                                                      (payload->>'mission_id')::bigint AS mid, kind, message, ts, base_id
                                                   FROM disruption WHERE exercise_run_id = :r ORDER BY (payload->>'mission_id')::bigint, ts"""),
                                         {"r": run.id}).mappings()}
    fp = run.footprint or {}

    # ---------------------------------------------------------- impacts
    own = {r[0] for r in db.execute(text("SELECT id FROM mission WHERE exercise_run_id = :r"), {"r": run.id})}
    new = {"kind": "MISSION_NEW", "message": ""}
    rows = []
    for mid, (it, st) in items.items():
        s = src.get(it.get("source_item_id"))
        what, sub = _what(dis.get(mid) or (new if mid in own else None), it["mission"], it, s)
        alts = [f"{a['base']} {a['type']}: {a['why_not']}" for a in (it.get("alternatives") or [])[:2]]
        rows.append({"sev": SEV.get(it["mission"]["priority"], "y"), "what": what, "sub": sub, "rec": _rec(it, s), "alts": alts,
                     "when": _when(it), "status": st, "mission_id": it["mission"]["id"], "mission": it["mission"]["code"],
                     "priority": it["mission"]["priority"]})
    for mid, (u, st) in unmet.items():
        m = u["mission"]
        d = dis.get(mid) or u.get("_cause")
        what, sub = _what(d or (new if mid in own else None), m, None, None, by_id.get(d["base_id"]) if d else "")
        reason = (u.get("reasons") or [{}])[0].get("text", "")
        fixes = u.get("fixes") or []
        f0 = fixes[0] if fixes else None
        rows.append({"sev": SEV.get(m["priority"], "y"), "what": what, "sub": sub or reason,
                     "rec": _named(f0["text"], cn) if f0 else "Not covered", "alts": [_named(f["text"], cn) for f in fixes[1:3]], "when": None,
                     "status": "apply" if f0 and f0["kind"].startswith("SPLIT_") else "uncovered",
                     "fix": f0, "mission_id": m["id"], "mission": m["code"], "priority": m["priority"]})
    for mid in set(fp.get("missions", [])) - set(items) - set(unmet):      # a pop-up the monitor hasn't picked up yet
        m = db.execute(text("SELECT code, name, priority, window_end FROM mission WHERE id = :m"), {"m": mid}).mappings().first()
        if m and _ts(m["window_end"]) <= now:            # nobody committed a plan before it was needed
            rows.append({"sev": SEV.get(m["priority"], "y"), "what": f"New {m['priority']}: {m['name']}",
                         "sub": f"needed by {_hm(m['window_end'])}", "rec": "Window passed before a plan was committed", "alts": [],
                         "when": None, "status": "uncovered", "mission_id": mid, "mission": m["code"], "priority": m["priority"]})
        elif m:
            rows.append({"sev": SEV.get(m["priority"], "y"), "what": f"New {m['priority']}: {m['name']}",
                         "sub": f"needed by {_hm(m['window_end'])}", "rec": "The planner is looking for a package", "alts": [],
                         "when": None, "status": "waiting", "mission": m["code"], "priority": m["priority"]})
    rows.sort(key=lambda r: ("cwyn".index(r["sev"]), r.get("priority", "P9")))
    rows += [r for r in (_effect_row(e, now) for e in fp.get("effects", [])) if r]

    # ---------------------------------------------------------- decision
    decision = None
    if pending and any(st == "proposed" for _, st in list(items.values()) + list(unmet.values())):
        also = [r.name for r in EX.running(db) if r.id != run.id and db.execute(text(
            "SELECT 1 FROM disruption WHERE exercise_run_id = :r AND proposal_plan_id = :p LIMIT 1"), {"r": r.id, "p": pending.id}).first()]
        decision = {"plan_id": pending.id, "summary": pending.summary, "also": also}

    # ---------------------------------------------------------- timeline
    ends = [(e["until"], END.get(e["kind"], "Ends")) for e in fp.get("effects", []) if e.get("until")]
    steps = [{"ts": run.started_sim, "label": FIRST.get(next((i["kind"] for i in run.injects or []), ""), "Started")}]
    first_d = min((d["ts"] for d in dis.values()), default=None)
    if decision:
        steps.append({"ts": first_d or now, "label": "Plan ready"})
    elif items or unmet:
        steps.append({"ts": first_d or run.started_sim, "label": "Plan updated"})
    airborne = sum(it["n_aircraft"] for it, _ in items.values() if (it.get("sortie") or {}).get("status") in LIVE)
    now_label = "Your decision" if decision else f"{airborne} airborne" if airborne else \
        "Planner checking" if not (items or unmet) else "Waiting"
    steps.append({"ts": now, "label": now_label, "now": True})
    nxt = []
    for it, _ in items.values():
        s = (it.get("sortie") or {}).get("status")
        if s in LIVE and it["recovery_ts"] and _ts(it["recovery_ts"]) > now:
            nxt.append((_ts(it["recovery_ts"]), f"Lands at {_short((it['recovery_base'] or it['base'] or {}).get('name'))}"))
        elif _ts(it["launch_ts"]) > now:
            nxt.append((_ts(it["launch_ts"]), f"{it['n_aircraft']} {it['type']['name']} launch"))
    if nxt:
        steps.append(dict(zip(("ts", "label"), min(nxt))))
    if ends:
        steps.append(dict(zip(("ts", "label"), max(ends, key=lambda x: x[0]))))
    for s in steps:
        s["ts"] = _ts(s["ts"]).isoformat()
        s["state"] = "now" if s.pop("now", False) else ("done" if _ts(s["ts"]) <= now else "next")

    reqs = requirements(db, items, run)
    need = sum(1 for r in rows if r["status"] in ("proposed", "apply") or (decision and r["status"] == "uncovered"))
    # D62: a scenario is over once its effects have ended and none of its own missions is still to fly
    effect_ends = [_ts(e["until"]) for e in fp.get("effects", []) if e.get("until") and e.get("kind") != "MISSION_POPUP"]
    open_own = db.execute(text("""SELECT count(*) FROM mission WHERE exercise_run_id = :r AND window_end > :n
                                  AND status NOT IN ('CANCELLED', 'COMPLETED')"""), {"r": run.id, "n": now}).scalar()
    over = run.status == "RUNNING" and bool(effect_ends) and max(effect_ends) <= now and not open_own
    over_since = max(effect_ends).isoformat() if over else None
    return {"run": {"id": run.id, "name": run.name, "code": sc.code if sc else None, "category": sc.category if sc else None,
                    "intensity": run.intensity, "status": run.status, "started_sim": run.started_sim,
                    "elapsed_min": round((now - run.started_sim).total_seconds() / 60)},
            "bases": sorted(set(fp.get("bases", [])) | {it["base"]["id"] for it, _ in items.values() if it.get("base")}),
            "analysis": fp.get("analysis"), "over": over, "over_since": over_since,
            "lead": lead(sc, run, names) if sc else run.name, "state": "ended" if run.status != "RUNNING" else
            ("decision" if decision else "live"), "timeline": steps, "decision": decision, "impacts": rows, "need": need,
            "requirements": reqs, "counts": {k: sum(1 for r in reqs if r["status"] == k) for k in ("met", "approve", "wait")},
            "simulated": True}


def _ts(v) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


# ---------------------------------------------------------------- requirements
def requirements(db: Session, items: dict, run: M.ExerciseRun) -> list[dict]:
    if not items and not (run.footprint or {}).get("effects"):
        return []
    st = snapshot(db)
    out, fuel = [], {}
    for mid, (it, status) in items.items():
        if (it.get("sortie") or {}).get("status") in ("LANDED", "COMPLETED"):
            continue
        state = "met" if status == "in" else "approve"
        b, ty = it["base"] or {}, it["type"] or {}
        a0, a1 = _ts(it["launch_ts"]), _ts(it["recovery_ts"])
        short = it["mission"]["name"].split(" (")[0]
        own = {a["id"] for a in it["aircraft"]}
        n = it["n_aircraft"]
        win = {"kind": "window", "a": it["launch_ts"], "b": it["recovery_ts"]}
        if it["change"] == "DIVERT":
            rb = it["recovery_base"] or {}
            out.append({"label": f"Runway to land {n} {ty.get('name')}", "need": f"{n} landing slot{'s' if n > 1 else ''}",
                        "from": _short(rb.get("name")), "have": "runway open", "when": {"kind": "at", "a": it["recovery_ts"]},
                        "status": state, "q": None})
            continue
        free = sum(1 for a in st.by_base_type.get((b.get("id"), ty.get("id")), [])
                   if a not in own and a in st.aircraft and aircraft_free(st, st.aircraft[a], a0, a1))
        out.append({"label": f"Aircraft for {short.lower()}", "need": f"{n} {ty.get('name')}", "from": _short(b.get("name")),
                    "have": f"{free + n} free", "when": win, "status": state, "q": [n, free + n]})
        crew_n = len(it["crew"]) or n
        tinfo = st.types.get(ty.get("id"))
        mi = st.missions.get(mid)
        req = Req(quals=frozenset(mi.min_quals) if mi else frozenset())
        mine = {c["id"] for c in it["crew"]}
        free_c = sum(1 for c in st.crew_by_base.get(b.get("id"), []) if c not in mine and c in st.crew and tinfo
                     and crew_eligible(st.crew[c], tinfo, req, a0) and crew_free(st, st.crew[c], a0, a1))
        out.append({"label": "Aircrew", "need": f"{crew_n}" + (" (mountain)" if "MOUNTAIN_FLYING" in req.quals else ""),
                    "from": _short(b.get("name")), "have": f"{free_c + crew_n} rested", "when": win, "status": state,
                    "q": [crew_n, free_c + crew_n]})
        bi = st.bases.get(b.get("id"))
        if bi is not None:
            ok = bi.runway_ok(a0)
            cap = launch_capacity(st, bi.id, slot_of(a0)) + (n if status == "in" else 0)
            out.append({"label": f"Runway at {_short(b.get('name'))}", "need": f"{n} launch{'es' if n > 1 else ''}",
                        "from": _short(b.get("name")), "have": f"{cap} slots at {_hm(slot_of(a0))}" if ok else "closed then",
                        "when": {"kind": "at", "a": it["launch_ts"]}, "status": state if ok else "wait", "q": [n, max(cap, n)] if ok else None})
        sup = it.get("support")
        if sup and sup.get("base"):
            tk = sup["type"] or {}
            tfree = sum(1 for a in st.by_base_type.get((sup["base"]["id"], tk.get("id")), [])
                        if a in st.aircraft and aircraft_free(st, st.aircraft[a], _ts(sup["launch_ts"]), _ts(sup["recovery_ts"])))
            out.append({"label": "Tanker", "need": f"1 {tk.get('name')} · {sup.get('fuel_l', 0) / 1000:.0f} kL",
                        "from": _short(sup["base"].get("name")), "have": f"{tfree + 1} free",
                        "when": {"kind": "window", "a": sup["launch_ts"], "b": sup["recovery_ts"]}, "status": state, "q": [1, tfree + 1]})
        f = fuel.setdefault(b.get("id"), {"name": _short(b.get("name")), "l": 0.0, "state": state})
        f["l"] += float(it.get("fuel_l") or 0)
        if state == "approve":
            f["state"] = "approve"
    for bid, f in fuel.items():
        fb = st.fuel.get(bid)
        if fb and f["l"]:
            out.append({"label": f"Fuel at {f['name']}", "need": f"{f['l'] / 1000:.1f} kL", "from": f["name"],
                        "have": f"{fb['current_l'] / 1000:.0f} kL in stock, reserve {fb['reserve_l'] / 1000:.0f}",
                        "when": None, "status": f["state"], "q": [f["l"], max(fb["current_l"], 1.0)]})
    for e in (run.footprint or {}).get("effects", []):
        if e["kind"] == "RUNWAY_CLOSED" and e.get("until") and _ts(e["until"]) > _now(db):
            out.append({"label": f"{e['base_name']} runway open again", "need": "repair", "from": e["base_name"],
                        "have": "closed", "when": {"kind": "at", "a": e["until"]}, "status": "wait", "q": None})
    return out


# ---------------------------------------------------------------- lists
def catalogue(db: Session) -> dict:
    now = _now(db)
    live = {r.scenario_id: r for r in EX.running(db) if r.scenario_id}
    st = db.get(M.SimState, 1)
    from .. import config
    out = []
    for sc in db.scalars(select(M.Scenario).order_by(M.Scenario.id)):
        r = live.get(sc.id)
        adds = [{"priority": i["params"].get("priority", "P1"), "label": DC.MISSION_LABEL[i["params"].get("mission_type", "CASEVAC")][1]}
                for i in sc.injects or [] if i.get("kind") == "MISSION_POPUP"]
        out.append({"id": sc.id, "code": sc.code, "name": sc.name, "category": sc.category, "intensity": sc.intensity,
                    "summary": sc.summary, "description": sc.description, "params": sc.params or [], "adds": adds,
                    "intensity_presets": sc.intensity_presets or {},
                    "run": {"id": r.id, "started_sim": r.started_sim, "intensity": r.intensity, "params": r.params,
                            "elapsed_min": round((now - r.started_sim).total_seconds() / 60)} if r else None})
    ended = [dict(x) for x in db.execute(text("""SELECT id, name, started_sim, ended_sim FROM exercise_run WHERE status = 'ENDED'
                                                ORDER BY id DESC LIMIT 5""")).mappings()]
    return {"scenarios": out, "ended": ended, "committed_plan_id": (store.current_committed(db) or M.Plan()).id,
            "sim": {"enabled": config.SIM_ENABLED, "sim_now": st.sim_now, "speed": st.speed, "paused": st.paused} if st else None,
            "bases": [{"code": r.code, "name": _short(r.name)} for r in db.execute(text(
                "SELECT code, name FROM base WHERE side = 'OWN' AND base_type <> 'ALG' ORDER BY name"))],
            "types": [r[0] for r in db.execute(text("SELECT name FROM aircraft_type ORDER BY name"))]}


def live(db: Session) -> list[dict]:
    now = _now(db)
    pending = db.scalars(select(M.Plan).where(M.Plan.kind == "RETASK", M.Plan.status == "PROPOSED").order_by(M.Plan.id.desc())).first()
    out = []
    for r in EX.running(db):
        sc = db.get(M.Scenario, r.scenario_id) if r.scenario_id else None
        need = db.execute(text("SELECT count(*) FROM disruption WHERE exercise_run_id = :r AND proposal_plan_id = :p"),
                          {"r": r.id, "p": pending.id if pending else 0}).scalar()
        out.append({"id": r.id, "name": r.name, "code": sc.code if sc else None, "intensity": r.intensity, "started_sim": r.started_sim,
                    "elapsed_min": round((now - r.started_sim).total_seconds() / 60), "need": need})
    return out


# ---------------------------------------------------------------- the situation view (D56)
CHANGE_WORD = {"MOVED": "moved", "SWAP": "tails / crew swapped", "NEW": "new", "DIVERT": "divert", "REROLE": "re-roled in flight"}


def situation(db: Session, run_id: int | None = None) -> dict:
    """One screen for the current situation: the live scenarios, the plan under review (a proposal waiting for a
    decision, else the committed plan), its missions tagged Routine / scenario, the impacts, the requirements and the
    inventory moves that make it flyable. run_id narrows it to one scenario."""
    now = _now(db)
    runs = live(db)
    plan = store.under_review(db)
    pending = plan if plan is not None and plan.status in ("PROPOSED", "APPROVED") else None
    view = store.serialise(db, plan.id) if plan is not None else {"items": [], "unmet": []}
    tag = {r.id: (r.run, r.tag) for r in db.execute(text("""SELECT m.id, m.exercise_run_id AS run, coalesce(er.name, 'Routine') AS tag
                                                           FROM mission m LEFT JOIN exercise_run er ON er.id = m.exercise_run_id
                                                           WHERE m.window_end > :n - interval '12 hours'
                                                              OR m.exercise_run_id IS NOT NULL"""), {"n": now})}   # a scenario's own mission keeps its tag
    one = response(db, run_id) if run_id else None
    mine = {m for m, (r, _) in tag.items() if r == run_id} if run_id else set()
    if run_id:
        run = db.get(M.ExerciseRun, run_id)
        items, unmet, _, _ = _attributed(db, run) if run else ({}, {}, None, {})
        mine |= set(items) | set(unmet)

    rows, routine_same = [], 0
    for it in view["items"]:
        m = it["mission"]
        if not m:
            continue
        r_id, t = tag.get(m["id"], (None, "Routine"))
        changed = bool(it["change"]) and it["change"] != "KEPT"
        st = "proposed" if pending is not None and (plan.kind == "PLAN" or changed) else "in"
        show = (m["id"] in mine) if run_id else (r_id is not None or changed)
        if not show:
            routine_same += 0 if run_id else 1
            continue
        rows.append({"mission_id": m["id"], "code": m["code"], "name": m["name"], "priority": m["priority"],
                     "mission_type": m["mission_type"], "tag": t, "run_id": r_id,
                     "package": f"{it['n_aircraft']} × {(it['type'] or {}).get('name', '')} from {_short((it['base'] or {}).get('name'))}",
                     "base": (it["base"] or {}).get("code"), "when": _when(it), "status": st,
                     "change": CHANGE_WORD.get(it["change"] or "") if changed else None, "reason": None})
    for u in view["unmet"]:
        m = u["mission"]
        if not m:
            continue
        r_id, t = tag.get(m["id"], (None, "Routine"))
        if run_id and m["id"] not in mine:
            continue
        rows.append({"mission_id": m["id"], "code": m["code"], "name": m["name"], "priority": m["priority"],
                     "mission_type": m["mission_type"], "tag": t, "run_id": r_id, "package": None, "base": None, "when": None,
                     "status": "uncovered", "change": "dropped" if u.get("dropped_item_id") else None,
                     "reason": (u.get("reasons") or [{}])[0].get("text")})
    rows.sort(key=lambda r: (r["tag"] == "Routine", r["priority"], r["status"] != "uncovered", r["code"]))

    # impacts: the selected scenario's, or every live scenario's plus the routine missions left uncovered
    resp = {} if one else {r["id"]: response(db, r["id"]) for r in runs}
    if one:
        impacts = one["impacts"]
    else:
        impacts = []
        for r in runs:
            for x in resp[r["id"]]["impacts"]:
                impacts.append({**x, "scenario": r["name"]})
        taken = {x.get("mission_id") for r in resp.values() for x in r["impacts"]}   # already under the scenario that caused it
        for u in view["unmet"]:
            m = u["mission"]
            if m and tag.get(m["id"], (None,))[0] is None and m["id"] not in taken:
                fixes = u.get("fixes") or []
                impacts.append({"sev": SEV.get(m["priority"], "y"), "what": f"{m['name']} not covered", "scenario": "Routine",
                                "sub": (u.get("reasons") or [{}])[0].get("text", ""), "rec": fixes[0]["text"] if fixes else "Not covered",
                                "alts": [f["text"] for f in fixes[1:3]], "when": None,
                                "status": "apply" if fixes and fixes[0]["kind"].startswith("SPLIT_") else "uncovered",
                                "fix": fixes[0] if fixes else None, "mission_id": m["id"], "mission": m["code"],
                                "priority": m["priority"]})

    # requirements and inventory moves
    if one:
        reqs = one["requirements"]
    else:
        seen, reqs = set(), []
        for r in runs:
            for q in resp[r["id"]]["requirements"]:
                k = (q["label"], q["from"], q["need"])
                if k not in seen:
                    seen.add(k)
                    reqs.append({**q, "scenario": r["name"], "run_id": r["id"]})   # the All view groups them by scenario
    moves = LG.recommend(db, snapshot(db), plan.id if plan is not None else None, scenario_bases(db, plan)) \
        if plan is not None or runs else {"moves": [], "unmet": []}
    transit = [dict(x) for x in db.execute(text("""SELECT t.id, t.kind, t.category, t.qty, t.unit, t.status, t.eta, t.distance_km,
                                                         t.reason, fb.code AS from_code, tb.code AS to_code,
                                                         replace(fb.name, 'Air Force Station ', '') AS from_name,
                                                         replace(tb.name, 'Air Force Station ', '') AS to_name
                                                  FROM inventory_transfer t JOIN base fb ON fb.id = t.from_base_id
                                                  JOIN base tb ON tb.id = t.to_base_id
                                                  WHERE t.status = 'IN_TRANSIT' OR t.delivered_at > :n - interval '6 hours'
                                                  ORDER BY t.status = 'DELIVERED', t.eta"""), {"n": now}).mappings()]
    for x in transit:
        x["label"] = LG.label(x["category"])

    decision = None
    if pending is not None:
        also = [r["name"] for r in runs if r["id"] != run_id and r["need"]] if run_id else []
        decision = {"plan_id": pending.id, "kind": pending.kind, "summary": pending.summary, "also": also}
    k = plan.kpis if plan is not None else {}
    # the All view shows one box per scenario (D59): what happened, then "because of this -> our plan for it"
    blocks = [{"run": resp[r["id"]]["run"], "lead": resp[r["id"]]["lead"], "state": resp[r["id"]]["state"],
               "timeline": resp[r["id"]]["timeline"], "impacts": resp[r["id"]]["impacts"], "need": resp[r["id"]]["need"],
               "bases": resp[r["id"]]["bases"], "analysis": resp[r["id"]]["analysis"], "over": resp[r["id"]]["over"],
               "over_since": resp[r["id"]]["over_since"]}
              for r in runs] if not one else []
    # the Planner's step strip and its one sentence (D60): the plan in force, and what is flying under it
    cp = store.current_committed(db)
    kc = cp.kpis if cp is not None else {}
    flying = db.execute(text("""SELECT coalesce(sum(s.n), 0) FROM (SELECT count(*) AS n FROM sortie s JOIN plan_item pi ON pi.id = s.plan_item_id
                                 JOIN sortie_aircraft sa ON sa.sortie_id = s.id
                                 WHERE pi.plan_id = :p AND s.status IN ('AIRBORNE', 'ON_STATION', 'RTB')) s"""),
                        {"p": cp.id if cp is not None else 0}).scalar()
    return {"runs": runs, "selected": run_id, "now": now, "scenarios": blocks,
            "plan": {"id": plan.id, "kind": plan.kind, "status": plan.status, "summary": plan.summary,
                     "covered": k.get("covered"), "missions": k.get("missions"), "why": store.why(db, plan),
                     "created_at": plan.created_at, "committed_at": plan.committed_at} if plan is not None else None,
            "in_force": {"id": cp.id, "since": cp.committed_at, "covered": kc.get("covered"), "missions": kc.get("missions"),
                         "flying": int(flying or 0)} if cp is not None else None,
            "decision": decision, "run": one["run"] if one else None, "lead": one["lead"] if one else None,
            "timeline": one["timeline"] if one else [], "state": one["state"] if one else ("decision" if pending else "live"),
            "missions": rows, "routine_unchanged": routine_same, "impacts": impacts,
            "need": sum(1 for x in impacts if x["status"] in ("proposed", "apply")) + (1 if pending is not None else 0),
            "requirements": reqs, "counts": {c: sum(1 for q in reqs if q["status"] == c) for c in ("met", "approve", "wait")},
            "transfers": {**moves, "in_transit": transit}, "simulated": True}


def invalidate_snapshot() -> None:
    """After a write the planner must see at once (an approved transfer), drop the cached snapshot."""
    with _snap_lock:
        _snap["st"] = None


def scenario_bases(db: Session, plan: M.Plan | None) -> set:
    """Bases the live scenarios touch: their effects' bases and the bases flying their missions in the plan under review.
    Spares shortages only count here, so the moves stay about the situation."""
    out = set()
    for r in EX.running(db):
        out |= set((r.footprint or {}).get("bases", []))
    if plan is not None:
        out |= {r[0] for r in db.execute(text("""SELECT pi.base_id FROM plan_item pi JOIN mission m ON m.id = pi.mission_id
                                                WHERE pi.plan_id = :p AND m.exercise_run_id IS NOT NULL"""), {"p": plan.id})}
    return out


EFFECT_WORD = {"RUNWAY_CLOSED": "runway closed", "RADAR_DOWN": "radars offline", "AIRCRAFT_LOST": "aircraft lost",
               "AIRCRAFT_GROUNDING": "fleet grounded", "FUEL_DELAY": "fuel down", "WX_FRONT": "below minima"}


def effects_geo(db: Session) -> dict:
    """Ops map (D56): one point per base a live scenario's effects hit, labelled with what happened there."""
    pts = {r.code: (r.lon, r.lat, r.id) for r in db.execute(text("SELECT id, code, ST_X(geom) lon, ST_Y(geom) lat FROM base WHERE side = 'OWN'"))}
    at: dict[str, dict] = {}
    for run in EX.running(db):
        for e in (run.footprint or {}).get("effects", []):
            word = EFFECT_WORD.get(e["kind"])
            codes = [e["base"]] if e.get("base") else list(e.get("bases") or [])
            for c in codes:
                if word and c in pts:
                    x = at.setdefault(c, {"code": c, "scenario": run.name, "what": []})
                    until = f" until {_hm(e['until'])}" if e.get("until") and e["kind"] != "AIRCRAFT_LOST" else ""
                    if f"{word}{until}" not in x["what"]:
                        x["what"].append(f"{word}{until}")
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": list(pts[c][:2])},
         "properties": {"code": c, "base_id": pts[c][2], "scenario": x["scenario"], "label": f"{c}: {', '.join(x['what'])}"}}
        for c, x in at.items()]}
