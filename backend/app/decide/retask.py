"""Dynamic re-tasking (PHASE2_IMPLEMENTATION_PLAN §7.4).

detect(): re-validate the committed plan's future packages against live data; check airborne packages can still
recover; pick up missions approved after the plan was committed.
propose(): repair with the cheapest rung that restores coverage —
  1. local swap: other tails / crew at the same base, same slot (no other package moves);
  2. partial re-solve: only the affected and new missions, every other package frozen;
  3. full re-solve of all movable packages with a stability bonus for their committed slots;
then store a RETASK plan whose items carry KEPT / SWAP / MOVED / NEW / DIVERT, and dropped packages as unmet.
"""
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..geo import dist_km
from ..sim.routes import position
from . import routing
from . import config as D
from . import planner as P
from . import snapshot as S
from . import store
from . import weather_impact as W
from .assign import Assignment, Ledger, assign
from .feasibility import Candidate
from .resources import Req
from .validate import RULE_TEXT, Violation, validate

log = logging.getLogger("decide.retask")
SWAPPABLE = {"AIRCRAFT_STATE", "AIRCRAFT_OVERLAP", "AIRCRAFT_HOURS", "CREW_STATE", "CREW_OVERLAP"}
KIND = {"AIRCRAFT_STATE": "AIRCRAFT_US", "AIRCRAFT_OVERLAP": "AIRCRAFT_US", "AIRCRAFT_HOURS": "AIRCRAFT_US",
        "CREW_STATE": "CREW_UNAVAILABLE", "CREW_OVERLAP": "CREW_UNAVAILABLE", "RUNWAY": "RUNWAY_CLOSED",
        "WX": "WX_BELOW_MINIMA", "FUEL": "FUEL_SHORT", "WEAPONS": "STOCK_SHORT", "QRA": "AIRCRAFT_US",
        "ROUTE": "THREAT_ACTIVATED", "THREAT": "THREAT_ACTIVATED"}


@dataclass
class Detection:
    plan_id: int
    st: S.OpsState
    items: list
    frozen: list
    movable: list
    violations: list
    new_missions: list
    diverts: list
    issues: list = field(default_factory=list)   # [(dedup key, kind, message, base_id, entity_type, entity_id, mission_id)]


def _sorties(db: Session, ids: list[int]) -> dict:
    return {r.id: r for r in db.execute(text("""SELECT id, code, status, actual_launch_ts, planned_launch_ts, planned_recovery_ts,
                                                recovery_base_id, reroute_ts, ST_AsGeoJSON(route_geom, 5)::json -> 'coordinates' AS route
                                                FROM sortie WHERE id = ANY(:i)"""), {"i": ids or [0]})}


def _where_now(s, now: datetime) -> tuple | None:
    """Current position of an airborne sortie, the way the simulator computes it."""
    route = [tuple(c) for c in (s.route or [])]
    if len(route) < 2 or not s.actual_launch_ts:
        return None
    t0 = s.reroute_ts or s.actual_launch_ts
    frac = (now - t0).total_seconds() / max(60, (s.planned_recovery_ts - t0).total_seconds())
    x, y, _ = position(route, frac)
    return round(x, 4), round(y, 4)


def reroles(db: Session, st: S.OpsState, det: Detection, mission_ids: list[int]) -> dict:
    """In-flight re-role (FR-RTK-05): an airborne package on a LOWER-priority mission takes an urgent new one if its
    type and load fit, it can reach the area inside the window, hold on station and still recover with reserve fuel at
    a base whose runway and weather are workable. -> {new mission id: (item dict, old item, old mission row)}."""
    from . import feasibility as F
    from . import risk as R
    out, taken = {}, set()
    srt = _sorties(db, [i["sortie_id"] for i in det.frozen if i["sortie_id"]])
    air = [(i, srt[i["sortie_id"]]) for i in det.frozen if i["sortie_id"] in srt and srt[i["sortie_id"]].status in ("AIRBORNE", "ON_STATION")]
    olds = {r.id: r for r in db.execute(text("SELECT id, code, priority, mission_type FROM mission WHERE id = ANY(:i)"),
                                        {"i": [i["mission_id"] for i, _ in air] or [0]})}
    now = st.now
    for mid in sorted(mission_ids, key=lambda k: (st.missions[k].priority, st.missions[k].window_start)):
        m = st.missions.get(mid)
        if m is None or m.priority not in ("P1", "P2"):
            continue
        best = None
        for i, s in air:
            old = olds.get(i["mission_id"])
            t = st.types.get(i["aircraft_type_id"])
            if i["id"] in taken or not old or old.priority <= m.priority or not t or t.role not in m.roles or i["n_aircraft"] < m.required:
                continue
            need = st.loadouts.get(F.choose_loadout(m, t) or "", {}).get("items", {})
            have = st.loadouts.get(i["loadout_code"] or "", {}).get("items", {})
            if any(have.get(k, 0) < v for k, v in need.items()):
                continue                                   # loads can't change in flight
            pos = _where_now(s, now)
            out_leg = routing.leg(st.G, pos, m.target) if pos else None
            if not out_leg:
                continue
            speed = t.cruise_kt * 1.852
            arrive = now + timedelta(hours=F.length_km(out_leg) / speed, minutes=5)
            start = max(arrive, m.window_start)
            if start + timedelta(minutes=m.on_station_min) > m.window_end:
                continue
            off = start + timedelta(minutes=m.on_station_min)
            refuelled = (i.get("support") or {}).get("rv_end")
            endurance = t.endurance_h * (1 + (D.AAR_TOP_UP if refuelled and datetime.fromisoformat(refuelled) < now else 0))
            left_h = endurance * (1 - D.FUEL_RESERVE_FRACTION) - (now - s.actual_launch_ts).total_seconds() / 3600
            rating = ((i["score"] or {}).get("req") or {}).get("rating", "WHITE")
            for b in sorted(st.bases.values(), key=lambda b: (b.id != s.recovery_base_id, F.dist_km(m.target, (b.lon, b.lat)))):
                back = routing.leg(st.G, m.target, (b.lon, b.lat))
                if not back:
                    continue
                eta = off + timedelta(hours=F.length_km(back) / speed + D.OVERHEAD_H / 2)
                need_h = (eta - now).total_seconds() / 3600
                wx, _ = W.rating_needed(st.wx_at(b.id, eta), t.family, b.runway_heading)
                if need_h <= left_h and b.runway_ok(eta) and wx is not None and D.RATING_ORDER.index(wx) <= D.RATING_ORDER.index(rating):
                    if best is None or start < best["on_station_ts"]:
                        route = out_leg + back[1:]
                        peak, _, zname = R.route_risk(st, route, now, eta)
                        if peak > D.RISK_LEVELS[m.max_risk]:
                            break
                        best = dict(i, mission_id=m.id, recovery_base_id=b.id, launch_ts=now, on_station_ts=start, recovery_ts=eta,
                                    route=[list(p) for p in route], risk=round(peak, 3), fuel_l=0, support=None, alternatives=[],
                                    score={**(i["score"] or {}), "weapons": {}, "expended": {}, "off_station": off.isoformat(),
                                           "duration_h": round(need_h, 2)},
                                    explanation={"rows": [
                                        {"label": "Re-roled in flight", "value": f"{s.code} leaves {old.code} ({old.priority})",
                                         "note": f"{i['n_aircraft']} × {t.name}, already airborne", "tone": "warning"},
                                        {"label": "Reaches the area", "value": f"{start:%H:%M}Z", "note": f"{F.length_km(out_leg):.0f} km from its position"},
                                        {"label": "Recovers at", "value": st.bases[b.id].code, "note": f"{eta:%H:%M}Z, {left_h - need_h:.1f} h fuel to spare"},
                                        {"label": "Route risk", "value": f"peak {peak:.2f}", "note": zname or "outside threat zones"}],
                                        "binding": [], "notes": [], "impact": {}, "cost": {}},
                                    _old=(i, old))
                    break
        if best:
            taken.add(best["_old"][0]["id"])
            out[mid] = best
    return out


def detect(db: Session) -> Detection | None:
    cp = store.current_committed(db)
    if not cp:
        return None
    items = [i for i in store.items_of(db, cp.id) if i["status"] == "COMMITTED"]
    sorties = _sorties(db, [i["sortie_id"] for i in items if i["sortie_id"]])
    now = db.execute(text("SELECT sim_now()")).scalar()
    frozen, movable = [], []
    for i in items:
        s = sorties.get(i["sortie_id"])
        if s and s.status == "PLANNED" and i["launch_ts"] >= now + timedelta(minutes=D.FREEZE_MIN):
            movable.append(i)
        elif not s or s.status not in ("CANCELLED", "ABORTED", "COMPLETED", "LANDED"):
            frozen.append(i)
    st = S.build(db, release_sortie_ids={i["sortie_id"] for i in movable})
    viol = validate(st, [x for i in movable for x in P.specs_from_row(i)])
    det = Detection(cp.id, st, items, frozen, movable, viol, [], [])
    by_id = {str(i["id"]): i for i in movable}
    for v in viol:
        it = by_id[v.key.partition("#")[0]]                 # "<item>#AAR" = the package's tanker leg
        det.issues.append((f"m{it['mission_id']}:{v.rule}:{v.entity_type or ''}{v.entity_id or ''}", KIND.get(v.rule, "INJECT"),
                           f"{st.missions[it['mission_id']].code if it['mission_id'] in st.missions else 'Mission'}: {v.detail}",
                           it["base_id"], v.entity_type, v.entity_id, it["mission_id"]))
    # planned sorties the simulator had to cancel (aircraft U/S at crew-up, crew unavailable, weather)
    for r in db.execute(text("""SELECT pi.mission_id, pi.base_id, s.id, s.code, s.cancel_reason FROM plan_item pi
                                JOIN sortie s ON s.id = pi.sortie_id WHERE pi.plan_id = :p AND s.status = 'CANCELLED'
                                AND s.cancel_reason <> 'TASKING_CHANGE'"""), {"p": cp.id}):
        if r.mission_id in st.missions:
            det.new_missions.append(r.mission_id)
            det.issues.append((f"m{r.mission_id}:CANCELLED", {"AIRCRAFT_US": "AIRCRAFT_US", "CREW_UNAVAILABLE": "CREW_UNAVAILABLE",
                                                              "WX": "WX_BELOW_MINIMA", "FUEL": "FUEL_SHORT"}.get(r.cancel_reason, "INJECT"),
                               f"{r.code} cancelled at crew-up ({(r.cancel_reason or 'other').replace('_', ' ').lower()})",
                               r.base_id, "sortie", r.id, r.mission_id))
    # packages commit had to skip (their tails or crew went unavailable in between): try again once
    for r in db.execute(text("""SELECT pi.mission_id, pi.base_id, m.code, m.priority FROM plan_item pi JOIN mission m ON m.id = pi.mission_id
                                WHERE pi.plan_id = :p AND pi.status = 'REJECTED' AND pi.change = 'SKIPPED'
                                  AND m.status = 'APPROVED'"""), {"p": cp.id}):
        if r.mission_id in st.missions and r.mission_id not in det.new_missions:
            det.new_missions.append(r.mission_id)
            det.issues.append((f"m{r.mission_id}:SKIPPED", "MISSION_CHANGED", f"{r.priority} {r.code} was skipped at commit: still uncovered",
                               r.base_id, "mission", r.mission_id, r.mission_id))
    # a tanker sortie the simulator had to cancel leaves its receivers without fuel: re-plan the package
    for i in items:
        sid = (i.get("support") or {}).get("sortie_id")
        if sid and i["mission_id"] in st.missions:
            r = db.execute(text("SELECT code, cancel_reason FROM sortie WHERE id = :s AND status = 'CANCELLED'"), {"s": sid}).first()
            if r and r.cancel_reason != "TASKING_CHANGE":
                det.issues.append((f"m{i['mission_id']}:TANKER", "AIRCRAFT_US", f"Tanker {r.code} cancelled at crew-up",
                                   i["base_id"], "sortie", sid, i["mission_id"]))
                if i in movable:
                    det.violations.append(Violation(str(i["id"]), i["mission_id"], "TANKER", f"tanker {r.code} cancelled"))
    covered = {i["mission_id"] for i in items}
    for r in db.execute(text("""SELECT id, code, priority FROM mission WHERE status = 'APPROVED' AND
                                (created_at > :c OR approved_at > :c)"""), {"c": cp.committed_at}):
        if r.id in st.missions and r.id not in covered:
            det.new_missions.append(r.id)
            det.issues.append((f"m{r.id}:NEW", "MISSION_NEW", f"New {r.priority} mission {r.code}", None, "mission", r.id, r.id))
    for i in frozen:
        s = sorties.get(i["sortie_id"])
        if s and s.status in ("AIRBORNE", "ON_STATION", "RTB"):
            d = _divert(st, i, s, now)
            if d:
                det.diverts.append(d)
                det.issues.append((f"m{i['mission_id']}:RECOVERY:{i['recovery_base_id']}", "RECOVERY_UNSAFE", d["why"],
                                   i["recovery_base_id"], "sortie", s.id, i["mission_id"]))
    return det


def _divert(st: S.OpsState, item: dict, s, now: datetime) -> dict | None:
    rb = st.bases.get(s.recovery_base_id)
    eta = s.planned_recovery_ts
    t = st.types.get(item["aircraft_type_id"])
    if not rb or not t:
        return None
    rating = ((item["score"] or {}).get("req") or {}).get("rating", "WHITE")
    need, why = W.rating_needed(st.wx_at(rb.id, eta), t.family, rb.runway_heading)
    ok = rb.runway_ok(eta) and need is not None and D.RATING_ORDER.index(need) <= D.RATING_ORDER.index(rating)
    if ok:
        return None
    reason = f"{rb.code} runway closed at {eta:%H:%M}Z" if not rb.runway_ok(eta) else f"{rb.code} at {eta:%H:%M}Z: {why}"
    x, y = _where_now(s, now) or (rb.lon, rb.lat)
    left_km = dist_km((x, y), (rb.lon, rb.lat)) * 1.3 + 150
    best = None
    for b in st.bases.values():
        if b.id == rb.id or not b.runway_ok(eta):
            continue
        n2, _ = W.rating_needed(st.wx_at(b.id, eta), t.family, b.runway_heading)
        if n2 is None or D.RATING_ORDER.index(n2) > D.RATING_ORDER.index(rating):
            continue
        if not st.by_base_type.get((b.id, item["aircraft_type_id"])) and b.base_type == "ALG":
            continue
        d = dist_km((x, y), (b.lon, b.lat))
        if d <= left_km and (best is None or d < best[1]):
            best = (b, d)
    if not best:
        return {"item": item, "why": f"{reason}; no alternate within fuel range", "to": None}
    return {"item": item, "why": f"{reason}: divert to {best[0].code} ({best[1]:.0f} km)", "to": best[0].id,
            "route": [[round(x, 4), round(y, 4)], [best[0].lon, best[0].lat]]}


_cand = P.cand_from_row


def _same(a: dict, b: dict) -> str:
    if a["base_id"] != b["base_id"] or a["aircraft_type_id"] != b["aircraft_type_id"] or \
            abs((a["launch_ts"] - b["launch_ts"]).total_seconds()) >= 60:
        return "MOVED"
    same = sorted(a["aircraft_ids"]) == sorted(b["aircraft_ids"]) and \
        sorted(map(tuple, a["crew_positions"] or [])) == sorted(map(tuple, b["crew_positions"] or []))
    return "KEPT" if same else "SWAP"


def _coverage(res: P.PlanResult) -> tuple:
    by = res.kpis["by_priority"]
    return tuple(by[p]["covered"] for p in D.PRIORITIES)


def propose(db: Session, det: Detection, user: dict | None = None, disruption_ids: list[int] | None = None) -> dict | None:
    t0 = time.perf_counter()
    st = det.st
    bad = {}
    for v in det.violations:
        iid, _, leg = v.key.partition("#")
        bad.setdefault(int(iid), []).append(v if not leg else Violation(v.key, v.mission_id, "TANKER", v.detail))
    if not bad and not det.new_missions and not det.diverts:
        return None
    movable = {i["id"]: i for i in det.movable}
    keep_rows = {iid: r for iid, r in movable.items() if iid not in bad}
    new_rows: list[dict] = []          # item dicts for planner.store
    changes: dict[int, dict] = {}
    rung = "swap"

    # ---------------------------------------------------------------- rung 1: local swap
    led = Ledger()
    for r in keep_rows.values():
        led.take(_cand(st, r, 0), P.assignment_from_row(r))
    unresolved = []
    for iid, vs in bad.items():
        r = movable[iid]
        if {v.rule for v in vs} <= SWAPPABLE:
            c = _cand(st, r, iid)
            a = assign(st, c, led, Assignment(r["aircraft_ids"], [tuple(x) for x in r["crew_positions"] or []]))
            if not isinstance(a, str):
                a.support = P.assignment_from_row(r).support          # the tanker leg is unaffected by a receiver swap
                led.take(c, a)
                new_rows.append(_row_from(r, a, vs, st))
                changes[r["mission_id"]] = {"change": "SWAP", "source_item_id": iid}
                continue
        unresolved.append(iid)
    scope = {movable[i]["mission_id"] for i in unresolved} | set(det.new_missions)
    res = None
    if scope:
        # ------------------------------------------------------------ rung 2: partial re-solve of the affected missions
        rung = "partial"
        release = {movable[i]["sortie_id"] for i in unresolved}
        st2 = S.build(db, release_sortie_ids=release)
        # packages swapped in rung 1 now hold different people: model them as busy for this solve
        for row in new_rows:
            c = _cand(st2, row | {"route": row["route"]}, 0)
            for aid in row["aircraft_ids"]:
                st2.busy_aircraft.setdefault(aid, []).append((*c.ac_iv, -1))
            for cid, _, _ in row["crew_positions"]:
                st2.busy_crew.setdefault(cid, []).append((*c.cr_iv, -1))
        stability = {movable[i]["mission_id"]: (movable[i]["base_id"], movable[i]["aircraft_type_id"], movable[i]["launch_ts"])
                     for i in unresolved}
        fixed = set(st2.missions) - scope
        res = P.plan(st2, "BALANCED", stability=stability, fixed_missions=fixed)
        lost = [u for u in res.unmet if st2.missions[u["mission_id"]].priority in ("P1", "P2")]
        if lost:
            # -------------------------------------------------------- rung 3: full re-solve of every movable package
            st3 = S.build(db, release_sortie_ids={i["sortie_id"] for i in det.movable})
            frozen_m = {i["mission_id"] for i in det.frozen}
            stab3 = {r["mission_id"]: (r["base_id"], r["aircraft_type_id"], r["launch_ts"]) for r in det.movable}
            keep3 = {r["mission_id"]: P.assignment_from_row(r) for r in det.movable}
            mine = {r["mission_id"] for r in det.movable} | set(det.new_missions) | scope
            res3 = P.plan(st3, "BALANCED", stability=stab3, keep=keep3, fixed_missions=(set(st3.missions) - mine) | frozen_m)
            held = list(keep_rows.values()) + new_rows            # covered without moving in rung 2
            cov2 = tuple(_coverage(res)[k] + sum(1 for r in held if st.missions.get(r["mission_id"])
                                                 and st.missions[r["mission_id"]].priority == p)
                         for k, p in enumerate(D.PRIORITIES))
            if _coverage(res3) > cov2:                            # lexicographic: more P1 first, then P2, ...
                rung, res, new_rows, changes, keep_rows = "full", res3, [], {}, {}
        old_by_m = {r["mission_id"]: r for r in det.movable}
        for it in res.items:
            src = old_by_m.get(it["mission_id"])
            ch = _same(it, src) if src else "NEW"
            new_rows.append(it)
            changes[it["mission_id"]] = {"change": ch, "source_item_id": src["id"] if src else None}
        for u in res.unmet:
            src = old_by_m.get(u["mission_id"])
            if src or u["mission_id"] in det.new_missions:
                changes[u["mission_id"]] = {"change": "DROPPED", "source_item_id": src["id"] if src else None}
    # in-flight re-role: urgent new missions the ground can't cover in time take a lower-priority airborne package
    urgent = [u["mission_id"] for u in (res.unmet if res else []) if u["mission_id"] in det.new_missions]
    rerolled = []
    for mid, it in reroles(db, st, det, urgent).items():
        old_item, old = it.pop("_old")
        new_rows.append(it)
        rerolled.append((it, old_item))
        changes[mid] = {"change": "REROLE", "source_item_id": old_item["id"]}
        changes[old_item["mission_id"]] = {"change": "DROPPED", "source_item_id": old_item["id"]}
        res.unmet = [u for u in res.unmet if u["mission_id"] != mid] + [{
            "mission_id": old_item["mission_id"], "fixes": [{"kind": "REPLAN", "text": "Generate a plan to cover the rest of it with another package"}],
            "reasons": [{"code": "REROLED", "text": f"Package re-roled in flight to {st.missions[mid].code} ({st.missions[mid].priority})",
                         "count": 1, "examples": []}]}]
        if rung in ("swap", "partial", "full"):
            rung = f"{rung} + re-role"
    unmet = [u for u in (res.unmet if res else []) if u["mission_id"] in changes]
    # diverts: an airborne package whose recovery base went bad
    divert_rows = []
    for d in det.diverts:
        if d.get("to"):
            r = dict(d["item"])
            r["recovery_base_id"], r["route"] = d["to"], d["route"]
            r["explanation"] = {"rows": [{"label": "Divert", "value": d["why"], "note": "airborne package"}], "binding": [],
                                "impact": {}, "notes": [], "cost": {}}
            divert_rows.append(r)
            changes[r["mission_id"]] = {"change": "DIVERT", "source_item_id": r["id"]}
            rerolled.append((r, d["item"]))
    if rerolled:                                   # re-roled / diverted packages land later or elsewhere
        _knock_on(st, rerolled, keep_rows, new_rows, changes)
    ms = int((time.perf_counter() - t0) * 1000)
    counts = {k: sum(1 for c in changes.values() if c["change"] == k) for k in ("SWAP", "MOVED", "NEW", "DROPPED", "DIVERT", "REROLE")}
    counts["KEPT"] = len(keep_rows) + len(det.frozen) - len(divert_rows) + sum(1 for c in changes.values() if c["change"] == "KEPT")
    summary = ", ".join(f"{v} {k.lower()}" for k, v in counts.items() if v and k != "KEPT") or "no change needed"
    kp = res.kpis if res else {}
    kpis = {"rung": rung, "changes": counts, "proposal_ms": ms, "missions": len(det.items) + len(det.new_missions),
            "covered": len(det.items) + counts["NEW"] - counts["DROPPED"],
            "solve_ms": kp.get("solve_ms", 0), "solver_status": kp.get("solver_status", "SWAP"),
            "by_priority": kp.get("by_priority", {}), "issues": [x[2] for x in det.issues][:12]}
    shell = P.PlanResult(st, items=new_rows + divert_rows, unmet=unmet, kpis=kpis, solver_status=kpis["solver_status"],
                         solve_ms=kpis["solve_ms"])
    pid = P.store(db, shell, preset="STABILITY", user=user, kind="RETASK", parent_plan_id=det.plan_id,
                  disruption_id=(disruption_ids or [None])[0], changes=changes, summary=summary)
    carried = [i["id"] for i in det.frozen if i["mission_id"] not in changes] + \
              [iid for iid, r in keep_rows.items() if r["mission_id"] not in changes]
    store.copy_items(db, det.plan_id, pid, carried, "KEPT")
    return {"plan_id": pid, "summary": summary, "rung": rung, "ms": ms, "changes": counts}


def _knock_on(st: S.OpsState, rerolled: list, keep_rows: dict, new_rows: list, changes: dict) -> None:
    """A re-roled or diverted package lands later or elsewhere than planned, so a kept package that reuses its tails or
    crew may break: give it other tails / crew at its base in the same proposal (rung 1), not on the next check.
    `rerolled`: [(new item dict, old item dict)]."""
    ac, cr = set(), set()
    for it, old in rerolled:
        sid, t = old["sortie_id"], st.types[it["aircraft_type_id"]]
        for aid in it["aircraft_ids"]:
            ac.add(aid)
            if aid in st.aircraft:
                st.aircraft[aid].base_id = it["recovery_base_id"]
            st.busy_aircraft[aid] = [iv for iv in st.busy_aircraft.get(aid, []) if iv[2] != sid] + \
                [(it["launch_ts"], it["recovery_ts"] + timedelta(minutes=t.turnaround_min), sid)]
        for cid, _, _ in it["crew_positions"] or []:
            cr.add(cid)
            st.busy_crew[cid] = [iv for iv in st.busy_crew.get(cid, []) if iv[2] != sid] + \
                [(it["launch_ts"], it["recovery_ts"] + timedelta(minutes=D.DEBRIEF_MIN, hours=D.CREW_REST_H), sid)]
    st.index()                                     # tails now sit at their new recovery base
    hit = [r for r in keep_rows.values() if set(r["aircraft_ids"]) & ac or {c[0] for c in r["crew_positions"] or []} & cr]
    bad: dict[int, list] = {}
    for v in validate(st, [x for r in hit for x in P.specs_from_row(r)]):
        bad.setdefault(int(v.key.partition("#")[0]), []).append(v)
    if not bad:
        return
    led = Ledger()
    for r in [r for iid, r in keep_rows.items() if iid not in bad] + \
            [r for r in new_rows if changes.get(r["mission_id"], {}).get("change") not in ("REROLE", "DIVERT")]:   # in st already
        led.take(_cand(st, r, 0), P.assignment_from_row(r))
    for iid, vs in bad.items():
        r = keep_rows[iid]
        c = _cand(st, r, iid)
        a = assign(st, c, led, Assignment(r["aircraft_ids"], [tuple(x) for x in r["crew_positions"] or []])) \
            if {v.rule for v in vs} <= SWAPPABLE else "not swappable"
        if isinstance(a, str):
            continue                                   # the next check repairs it with the full ladder
        a.support = P.assignment_from_row(r).support
        led.take(c, a)
        new_rows.append(_row_from(r, a, vs, st))
        changes[r["mission_id"]] = {"change": "SWAP", "source_item_id": iid}
        del keep_rows[iid]


def _row_from(r: dict, a: Assignment, vs: list[Violation], st: S.OpsState) -> dict:
    """Swapped package: same slot and route, new tails / crew, explanation says what changed and why."""
    out = dict(r)
    out["aircraft_ids"], out["crew_positions"] = list(a.aircraft), [list(x) for x in a.crew]
    out["aircrew_ids"] = [x[0] for x in a.crew]
    old_t = {st.aircraft[x].tail if x in st.aircraft else str(x) for x in r["aircraft_ids"]} - \
            {st.aircraft[x].tail for x in a.aircraft if x in st.aircraft}
    new_t = {st.aircraft[x].tail for x in a.aircraft if x in st.aircraft} - \
            {st.aircraft[x].tail if x in st.aircraft else str(x) for x in r["aircraft_ids"]}
    expl = dict(r["explanation"] or {})
    rows = list(expl.get("rows", []))
    why = "; ".join(sorted({v.detail for v in vs}))[:200]
    rows.insert(0, {"label": "Change", "value": (f"{', '.join(sorted(old_t))} → {', '.join(sorted(new_t))}" if new_t else "crew changed"),
                    "note": why, "tone": "caution"})
    expl["rows"] = rows
    out["explanation"] = expl
    return out
