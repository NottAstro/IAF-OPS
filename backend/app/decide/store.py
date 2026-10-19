"""Plan lifecycle: read, approve, reject, override, commit (PHASE2_IMPLEMENTATION_PLAN §4–§5).

Commit is the only path from a recommendation to the sortie tables. It re-validates against a fresh snapshot, then
diffs the plan against the committed one mission by mission: KEPT (sortie untouched), SWAP (same slot, tails or crew
changed in place), MOVED / NEW (old sortie cancelled, new one created), DIVERT (airborne package recovers elsewhere),
and dropped (sortie cancelled, mission back to APPROVED). Weapons are reserved on creation and released on cancel.
Every step is audited in the same transaction.
"""
from datetime import datetime, timedelta

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import LineString
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import models as M
from ..audit import audit
from ..services import sorties as SV
from . import config as D
from . import snapshot as S
from .planner import item_spec_from_row, specs_from_row
from .validate import validate

LIVE = ("PLANNED", "CREWED", "READY")
AIRBORNE = ("AIRBORNE", "ON_STATION", "RTB")


class PlanError(Exception):
    def __init__(self, status: int, message: str, details=None):
        super().__init__(message)
        self.status, self.message, self.details = status, message, details


def current_committed(db: Session) -> M.Plan | None:
    return db.scalars(select(M.Plan).where(M.Plan.status == "COMMITTED", M.Plan.kind != "WHATIF")
                      .order_by(M.Plan.id.desc())).first()


def under_review(db: Session) -> M.Plan | None:
    """The plan the situation view shows (D56): a proposal waiting for a decision (full plan or re-task), else the
    committed one."""
    p = db.scalars(select(M.Plan).where(M.Plan.kind.in_(("PLAN", "RETASK")), M.Plan.status.in_(("PROPOSED", "APPROVED")))
                   .order_by(M.Plan.id.desc())).first()
    return p or current_committed(db)


WHY_WORD = {"MISSION_NEW": ("new mission", "new missions"), "MISSION_CHANGED": ("mission to re-plan", "missions to re-plan"),
            "AIRCRAFT_US": ("aircraft unavailable", "aircraft unavailable"),
            "CREW_UNAVAILABLE": ("crew member unavailable", "crew members unavailable"), "RUNWAY_CLOSED": ("runway closed", "runways closed"),
            "WX_BELOW_MINIMA": ("weather below minima", "weather below minima"), "FUEL_SHORT": ("fuel short", "fuel short"),
            "STOCK_SHORT": ("weapons short", "weapons short"), "THREAT_ACTIVATED": ("route through a threat zone", "routes through threat zones"),
            "RECOVERY_UNSAFE": ("recovery base unsafe", "recovery bases unsafe")}


def why_text(ds: list) -> str | None:
    """[(kind, message, scenario name | None)] -> one plain line, scenarios first: "Western sector air attack: 3 new
    missions · Routine: 5 missions to re-plan". A single disruption keeps its own message."""
    if not ds:
        return None
    if len(ds) == 1:
        k, msg, sc, *mname = ds[0]
        if mname and mname[0] and k in WHY_WORD:            # plain words, no codes: "Routine: crew member unavailable for Training near Jodhpur"
            return f"{sc or 'Routine'}: " + (f"new mission, {mname[0]}" if k == "MISSION_NEW" else f"{WHY_WORD[k][0]} for {mname[0]}")
        msg = msg.replace("SIM-", "")
        return f"{sc}: {msg}" if sc else msg
    groups: dict = {}
    for k, _, sc, *_ in ds:
        g = groups.setdefault(sc or "Routine", {})
        g[k] = g.get(k, 0) + 1
    def part(k, n):
        one, many = WHY_WORD.get(k, ("change", "changes"))
        return f"{n} {one if n == 1 else many}"
    return " · ".join(f"{s}: " + ", ".join(part(k, n) for k, n in groups[s].items()) for s in sorted(groups, key=lambda s: s == "Routine"))


def why(db: Session, p: M.Plan) -> str:
    """One plain sentence: what made this plan (Planner context line and history)."""
    if p.kind == "WHATIF":
        return "What-if on a copy: nothing was written"
    ds = db.execute(text("""SELECT d.kind, d.message, er.name, m.name FROM disruption d
                            LEFT JOIN exercise_run er ON er.id = d.exercise_run_id
                            LEFT JOIN mission m ON m.id = (d.payload ->> 'mission_id')::bigint
                            WHERE d.proposal_plan_id = :p OR d.id = :t ORDER BY d.id"""),
                    {"p": p.id, "t": p.trigger_disruption_id or 0}).all()
    return why_text([tuple(r) for r in ds]) or (p.kpis or {}).get("why") or \
        ("Re-plan of every package still to fly" if p.kind == "RETASK" else "Full plan for the next 24 hours")


def _rows(db: Session, sql: str, **p) -> list[dict]:
    return [dict(r) for r in db.execute(text(sql), p).mappings()]


def items_of(db: Session, pid: int) -> list[dict]:
    return _rows(db, """SELECT pi.*, ST_AsGeoJSON(pi.route_geom, 4)::json -> 'coordinates' AS route
                        FROM plan_item pi WHERE pi.plan_id = :p ORDER BY pi.launch_ts, pi.id""", p=pid)


def serialise(db: Session, pid: int) -> dict:
    p = db.get(M.Plan, pid)
    if not p:
        raise PlanError(404, "Plan not found")
    items = items_of(db, pid)
    unmet = _rows(db, "SELECT * FROM plan_unmet WHERE plan_id = :p ORDER BY id", p=pid)
    mids = {i["mission_id"] for i in items} | {u["mission_id"] for u in unmet}
    missions = {r["id"]: r for r in _rows(db, """SELECT m.id, m.code, m.name, m.mission_type, m.priority, m.status, m.window_start,
            m.window_end, m.required_aircraft, m.on_station_min, m.max_risk, c.code AS command, ST_X(m.target_geom) AS lon,
            ST_Y(m.target_geom) AS lat, m.exercise_run_id, coalesce(er.name, 'Routine') AS tag FROM mission m
            LEFT JOIN command c ON c.id = m.requesting_command_id LEFT JOIN exercise_run er ON er.id = m.exercise_run_id
            WHERE m.id = ANY(:ids)""", ids=list(mids) or [0])}
    bases = {r["id"]: r for r in _rows(db, "SELECT id, code, name FROM base WHERE side = 'OWN'")}
    types = {r["id"]: r for r in _rows(db, "SELECT id, name, role, category FROM aircraft_type")}
    sups = [i["support"] for i in items if i.get("support")]
    ac_ids = sorted({a for i in items for a in (i["aircraft_ids"] or [])} | {a for s in sups for a in s["aircraft_ids"]})
    cr_ids = sorted({c for i in items for c in (i["aircrew_ids"] or [])} | {c[0] for s in sups for c in s["crew_positions"]})
    tails = {r["id"]: r["tail_no"] for r in _rows(db, "SELECT id, tail_no FROM aircraft WHERE id = ANY(:i)", i=ac_ids or [0])}
    crew = {r["id"]: r for r in _rows(db, """SELECT id, rank, first_name || ' ' || last_name AS name, callsign, aircrew_role
                                             FROM aircrew WHERE id = ANY(:i)""", i=cr_ids or [0])}
    sorties = {r["id"]: r for r in _rows(db, "SELECT id, code, status FROM sortie WHERE id = ANY(:i)",
                                         i=[i["sortie_id"] for i in items if i["sortie_id"]] +
                                           [s["sortie_id"] for s in sups if s.get("sortie_id")] or [0])}

    def support_view(s):
        if not s:
            return None
        return {"kind": s["kind"], "base": bases.get(s["base_id"]), "type": types.get(s["type_id"]), "launch_ts": s["launch"],
                "recovery_ts": s["recovery"], "rv": s["rv"], "rv_start": s["rv_start"], "rv_end": s["rv_end"],
                "fuel_l": s["fuel_l"], "transit_min": s.get("transit_min"),
                "aircraft": [{"id": a, "tail_no": tails.get(a)} for a in s["aircraft_ids"]],
                "crew": [{"id": c, "position": pos, **{k: crew[c][k] for k in ("rank", "name", "callsign")}}
                         for c, _, pos in s["crew_positions"] if c in crew],
                "sortie": sorties.get(s.get("sortie_id"))}
    out_items = []
    for i in items:
        out_items.append({
            "id": i["id"], "status": i["status"], "change": i["change"], "mission": missions.get(i["mission_id"]),
            "base": bases.get(i["base_id"]), "recovery_base": bases.get(i["recovery_base_id"]),
            "type": types.get(i["aircraft_type_id"]), "loadout_code": i["loadout_code"], "n_aircraft": i["n_aircraft"],
            "launch_ts": i["launch_ts"], "on_station_ts": i["on_station_ts"], "recovery_ts": i["recovery_ts"],
            "aircraft": [{"id": a, "tail_no": tails.get(a)} for a in (i["aircraft_ids"] or [])],
            "crew": [{"id": c, "aircraft_id": aid, "position": pos, **{k: crew[c][k] for k in ("rank", "name", "callsign")}}
                     for c, aid, pos in (i["crew_positions"] or []) if c in crew],
            "risk": i["risk"], "fuel_l": i["fuel_l"], "score": i["score"], "explanation": i["explanation"],
            "alternatives": i["alternatives"], "route": i["route"], "sortie": sorties.get(i["sortie_id"]),
            "source_item_id": i["source_item_id"], "support": support_view(i.get("support"))})
    return {
        "plan": {"id": p.id, "kind": p.kind, "status": p.status, "scope": p.scope, "preset": p.preset, "version": p.version,
                 "created_at": p.created_at, "horizon_start": p.horizon_start, "horizon_end": p.horizon_end,
                 "solver_status": p.solver_status, "solve_ms": p.solve_ms, "kpis": p.kpis, "summary": p.summary,
                 "parent_plan_id": p.parent_plan_id, "approved_by": p.approved_by, "approved_at": p.approved_at,
                 "committed_at": p.committed_at, "trigger_disruption_id": p.trigger_disruption_id, "why": why(db, p),
                 "simulated": True},
        "items": out_items,
        "unmet": [{"id": u["id"], "mission": missions.get(u["mission_id"]), "reasons": u["reasons"], "fixes": u["fixes"],
                   "dropped_item_id": u["dropped_item_id"]} for u in unmet],
    }


def _check(p: M.Plan | None, *ok: str) -> M.Plan:
    if not p:
        raise PlanError(404, "Plan not found")
    if p.status not in ok:
        raise PlanError(409, f"This plan is {p.status.lower()}; it can't be changed now.")
    return p


def approve(db: Session, pid: int, user: dict, item_ids: list[int] | None = None, request_id: str | None = None) -> None:
    p = _check(db.get(M.Plan, pid), "PROPOSED")
    for it in db.scalars(select(M.PlanItem).where(M.PlanItem.plan_id == pid)):
        it.status = "APPROVED" if item_ids is None or it.id in item_ids else "REJECTED"
    p.status, p.approved_by, p.approved_at = "APPROVED", user["id"], datetime.now().astimezone()
    p.version += 1
    audit(db, user, "PLAN_APPROVE", "plan", pid, None, {"status": "PROPOSED"},
          {"status": "APPROVED", "items": item_ids or "all"}, request_id=request_id)


def reject(db: Session, pid: int, user: dict, request_id: str | None = None) -> None:
    p = _check(db.get(M.Plan, pid), "PROPOSED", "APPROVED")
    p.status = "REJECTED"
    p.version += 1
    db.execute(text("UPDATE disruption SET status = 'OPEN', proposal_plan_id = NULL WHERE proposal_plan_id = :p"), {"p": pid})
    audit(db, user, "PLAN_REJECT", "plan", pid, None, None, {"status": "REJECTED"}, request_id=request_id)


def override_item(db: Session, pid: int, iid: int, user: dict, aircraft_ids: list[int] | None,
                  crew_positions: list | None, request_id: str | None = None) -> dict:
    """Base commander / admin swaps tails or crew inside a package. Re-validated before it is accepted."""
    p = _check(db.get(M.Plan, pid), "PROPOSED", "APPROVED")
    it = db.get(M.PlanItem, iid)
    if not it or it.plan_id != pid:
        raise PlanError(404, "Plan item not found")
    from ..rbac import assert_edit_base
    assert_edit_base(user, it.base_id)
    before = {"aircraft_ids": list(it.aircraft_ids), "crew_positions": it.crew_positions}
    row = {c.name: getattr(it, c.name) for c in M.PlanItem.__table__.columns}
    row["route"] = [list(c) for c in to_shape(it.route_geom).coords] if it.route_geom is not None else []
    if aircraft_ids is not None:
        if len(aircraft_ids) != it.n_aircraft:
            raise PlanError(422, f"Pick exactly {it.n_aircraft} aircraft.")
        row["aircraft_ids"] = aircraft_ids
    if crew_positions is not None:
        row["crew_positions"] = crew_positions
    others = [item_spec_from_row(r) for r in items_of(db, pid) if r["id"] != iid and r["status"] != "REJECTED"]
    st = S.build(db, release_sortie_ids=_releasable(db))
    v = validate(st, others + [item_spec_from_row(row)])
    mine = [x.as_dict() for x in v if x.key == str(iid)]
    if mine:
        raise PlanError(422, "That change breaks a rule: " + mine[0]["detail"], mine)
    it.aircraft_ids, it.crew_positions = row["aircraft_ids"], row["crew_positions"]
    it.aircrew_ids = [c[0] for c in row["crew_positions"]]
    p.version += 1
    audit(db, user, "PLAN_OVERRIDE", "plan_item", iid, it.base_id, before,
          {"aircraft_ids": it.aircraft_ids, "crew_positions": it.crew_positions}, request_id=request_id)
    return {"ok": True}


def _releasable(db: Session) -> set:
    cp = current_committed(db)
    if not cp:
        return set()
    return {r[0] for r in db.execute(text("""SELECT s.id FROM plan_item pi JOIN sortie s
                                              ON s.id = pi.sortie_id OR s.id = (pi.support ->> 'sortie_id')::bigint
                                              WHERE pi.plan_id = :p AND s.status IN ('PLANNED','CREWED','READY')"""), {"p": cp.id})}


def own_sorties(db: Session, rows: list, pre_launch_only: bool = True) -> set:
    """The sorties a package flies itself: its own and its tanker's. Re-checking or re-planning the package frees both,
    so it never clashes with its own tanker. pre_launch_only: a tanker already airborne stays busy (re-planning)."""
    ids = {s for r in rows for s in (r.get("sortie_id"), (r.get("support") or {}).get("sortie_id")) if s}
    if not pre_launch_only or not ids:
        return ids
    return {r[0] for r in db.execute(text("SELECT id FROM sortie WHERE id = ANY(:i) AND status IN ('PLANNED','CREWED','READY')"),
                                     {"i": list(ids)})}


def _cancel_sortie(db: Session, s: M.Sortie, user: dict | None, reason: str, request_id: str | None) -> None:
    before = {"status": s.status}
    for c in db.scalars(select(M.Aircrew).join(M.SortieCrew, M.SortieCrew.aircrew_id == M.Aircrew.id)
                        .where(M.SortieCrew.sortie_id == s.id, M.Aircrew.duty_status == "BRIEFED")):
        c.duty_status = "ON_DUTY"
    SV.adjust_stock(db, s.departure_base_id, SV.sortie_weapons(db, s), reserve=-1)
    s.status, s.cancel_reason = "CANCELLED", reason
    s.version += 1
    audit(db, user, "UPDATE", "sortie", s.id, s.departure_base_id, before, {"status": "CANCELLED", "cancel_reason": reason},
          request_id=request_id)


def cancel_mission(db: Session, m: M.Mission, user: dict | None, request_id: str | None = None) -> None:
    """Withdraw a mission: CANCELLED, its sorties not yet flying cancelled (weapons released), audited. Used by the
    Missions page and when a scenario ends (D56); the monitor's next check frees what the packages held."""
    before = {"status": m.status}
    m.status = "CANCELLED"
    for s in db.scalars(select(M.Sortie).where(M.Sortie.mission_id == m.id, M.Sortie.status.in_(LIVE))):
        _cancel_sortie(db, s, user, "TASKING_CHANGE", request_id)
    m.version += 1
    audit(db, user, "UPDATE", "mission", m.id, None, before, {"status": "CANCELLED"}, request_id=request_id)


def commit(db: Session, pid: int, user: dict, request_id: str | None = None) -> dict:
    p = _check(db.get(M.Plan, pid), "PROPOSED", "APPROVED")
    if p.kind == "WHATIF":
        raise PlanError(409, "What-if results can't be committed.")
    old = current_committed(db)
    new_items = [r for r in items_of(db, pid) if r["status"] != "REJECTED"]
    old_items = [r for r in items_of(db, old.id) if r["status"] == "COMMITTED"] if old else []
    old_sortie = {r["id"]: db.get(M.Sortie, r["sortie_id"]) if r["sortie_id"] else None for r in old_items}
    old_by_mission = {r["mission_id"]: r for r in old_items}
    old_by_id = {r["id"]: r for r in old_items}

    # ---- decide what each new item does to the sortie tables
    actions = []
    for r in new_items:
        src = old_by_id.get(r["source_item_id"]) or old_by_mission.get(r["mission_id"])
        s = old_sortie.get(src["id"]) if src else None
        if s and s.status in AIRBORNE + ("LANDED", "COMPLETED"):
            act = "REROLE" if r["change"] == "REROLE" and s.status in AIRBORNE else \
                "DIVERT" if r["change"] == "DIVERT" and s.status in AIRBORNE and r["recovery_base_id"] != s.recovery_base_id else "KEPT"
        elif s and s.status in LIVE:
            same_slot = r["base_id"] == src["base_id"] and r["aircraft_type_id"] == src["aircraft_type_id"] \
                and abs((r["launch_ts"] - src["launch_ts"]).total_seconds()) < 60
            same_people = sorted(r["aircraft_ids"]) == sorted(src["aircraft_ids"]) and \
                sorted(map(tuple, r["crew_positions"] or [])) == sorted(map(tuple, src["crew_positions"] or []))
            act = ("KEPT" if same_people else "SWAP") if same_slot else "MOVED"
        else:
            act = "NEW"
        actions.append((r, src, s, act))

    # ---- re-validate everything that will create or change a sortie against a fresh snapshot. The simulated world
    # keeps moving between "generate" and "commit": a package whose tails or crew went unavailable is repaired with
    # others at the same base and slot; one that can't be repaired, or whose launch time has passed, is skipped.
    st = S.build(db, release_sortie_ids=_releasable(db))
    # a kept package whose tanker changed is validated like a swap
    repaired, skipped = _repair(db, st, [(r, src, s, "SWAP" if act == "KEPT" and not _support_same(r, src) else act)
                                         for r, src, s, act in actions])
    actions = [a for a in actions if a[0]["id"] not in skipped]
    if not actions:
        raise PlanError(409, "Nothing in this plan can still be committed: " + "; ".join(list(skipped.values())[:3]) +
                        ". Generate a new plan.", [{"item_id": k, "reason": v} for k, v in skipped.items()])

    counts = {"KEPT": 0, "SWAP": 0, "MOVED": 0, "NEW": 0, "DIVERT": 0, "REROLE": 0, "DROPPED": 0, "TANKERS": 0}
    used_old = set()
    for r, src, s, act in actions:
        it = db.get(M.PlanItem, r["id"])
        counts[act] += 1
        if src:
            used_old.add(src["id"])
        mission = db.get(M.Mission, r["mission_id"])
        if act == "REROLE":
            _reroll(db, user, r, src, s, mission, request_id)
            it.sortie_id = s.id
        elif act in ("KEPT", "DIVERT"):
            it.sortie_id = s.id if s else None
            if s:
                s.plan_item_id = it.id
            if act == "DIVERT":
                before = {"recovery_base_id": s.recovery_base_id}
                s.recovery_base_id = r["recovery_base_id"]
                if r["route"]:
                    s.route_geom = from_shape(LineString([tuple(c) for c in r["route"]]), srid=4326)
                s.version += 1
                audit(db, user, "UPDATE", "sortie", s.id, s.departure_base_id, before,
                      {"recovery_base_id": s.recovery_base_id, "reason": "divert (re-task)"}, request_id=request_id)
        elif act == "SWAP":
            before = {"aircraft": [x for x in db.scalars(select(M.SortieAircraft.aircraft_id).where(M.SortieAircraft.sortie_id == s.id))]}
            db.execute(text("DELETE FROM sortie_crew WHERE sortie_id = :s"), {"s": s.id})
            sas = list(db.scalars(select(M.SortieAircraft).where(M.SortieAircraft.sortie_id == s.id).order_by(M.SortieAircraft.formation_pos)))
            for sa, aid in zip(sas, r["aircraft_ids"]):
                sa.aircraft_id = aid
            for cid, aid, pos in r["crew_positions"] or []:
                db.add(M.SortieCrew(sortie_id=s.id, aircrew_id=cid, aircraft_id=aid, position=pos))
                if s.status in ("CREWED", "READY"):
                    db.get(M.Aircrew, cid).duty_status = "BRIEFED"
            s.plan_item_id, s.version = it.id, s.version + 1
            it.sortie_id = s.id
            audit(db, user, "UPDATE", "sortie", s.id, s.departure_base_id, before,
                  {"aircraft": r["aircraft_ids"], "crew": [c[0] for c in r["crew_positions"] or []], "reason": "swap (re-task)"},
                  request_id=request_id)
        else:   # MOVED or NEW
            if act == "MOVED" and s:
                _cancel_sortie(db, s, user, "TASKING_CHANGE", request_id)
            base = db.get(M.AirBase, r["base_id"])
            t = db.get(M.AircraftType, r["aircraft_type_id"])
            ac = [db.get(M.Aircraft, a) for a in r["aircraft_ids"]]
            sc = r["score"] or {}
            new = SV.create(db, user=user, origin="PLAN", mission_type=mission.mission_type, priority=mission.priority,
                            base=base, recovery_base_id=r["recovery_base_id"] or base.id, launch=r["launch_ts"],
                            recovery=r["recovery_ts"], route=[tuple(c) for c in r["route"] or []], aircraft=ac,
                            crew=[tuple(c) for c in r["crew_positions"] or []], fuel_kg=r["fuel_l"] * 0.8,
                            family=SV.family_of(t), mission_id=mission.id, loadout_code=r["loadout_code"],
                            plan_item_id=it.id, tag="P", request_id=request_id)
            SV.adjust_stock(db, base.id, sc.get("weapons", {}), reserve=1)
            it.sortie_id = new.id
        if _commit_support(db, user, r, src, it, mission, request_id) == "NEW":
            counts["TANKERS"] += 1
        it.status = "COMMITTED"
        if mission.status in ("APPROVED", "PLANNED", "TASKED"):
            mission.status = "TASKED"
    for o in old_items:     # dropped: still-live sorties of the old plan nobody carried over
        if o["id"] in used_old:
            continue
        s = old_sortie.get(o["id"])
        if p.scope == "COMMAND" and db.get(M.Mission, o["mission_id"]).requesting_command_id != p.command_id:
            continue
        osup = (o.get("support") or {}).get("sortie_id")
        if osup and (ss := db.get(M.Sortie, osup)) and ss.status in LIVE:
            _cancel_sortie(db, ss, user, "TASKING_CHANGE", request_id)     # its tanker too
        if s and s.status in LIVE:
            _cancel_sortie(db, s, user, "TASKING_CHANGE", request_id)
            counts["DROPPED"] += 1
            m = db.get(M.Mission, o["mission_id"])
            if m.status == "TASKED":
                m.status = "APPROVED"
    if old:
        old.status = "SUPERSEDED"
        db.execute(text("UPDATE plan_item SET status = 'SUPERSEDED' WHERE plan_id = :p AND status = 'COMMITTED'"), {"p": old.id})
    p.status, p.committed_at = "COMMITTED", datetime.now().astimezone()
    if not p.approved_by:
        p.approved_by, p.approved_at = user["id"], p.committed_at
    p.version += 1
    db.execute(text("""UPDATE disruption SET status = 'RESOLVED', resolved_at = now()
                       WHERE proposal_plan_id = :p OR (status IN ('OPEN','ASSESSED') AND :retask)"""),
               {"p": pid, "retask": p.kind == "RETASK"})
    for iid in skipped:
        it = db.get(M.PlanItem, iid)
        it.status, it.change = "REJECTED", "SKIPPED"     # the monitor re-proposes skipped missions (retask.detect)
        m = db.get(M.Mission, it.mission_id)
        if m.status == "PLANNED":
            m.status = "APPROVED"
    counts["REPAIRED"], counts["SKIPPED"] = len(repaired), len(skipped)
    audit(db, user, "PLAN_COMMIT", "plan", pid, None, None,
          {"kind": p.kind, **counts, "repaired": repaired, "skipped": list(skipped.values())}, request_id=request_id)
    counts["notes"] = repaired + list(skipped.values())
    return counts


def _reroll(db: Session, user: dict, r: dict, src: dict, s: M.Sortie, mission: M.Mission, request_id: str | None) -> None:
    """In-flight re-role: the airborne sortie takes the new mission from where it is; its old mission is released with
    the time on station it got (the simulator flies the new route from reroute_ts)."""
    now = db.execute(text("SELECT sim_now()")).scalar()
    old_m = db.get(M.Mission, src["mission_id"])
    if s.status == "ON_STATION" and src.get("on_station_ts"):
        old_m.on_station_achieved_min = round((old_m.on_station_achieved_min or 0) + max(0.0, (now - src["on_station_ts"]).total_seconds() / 60), 1)
    if old_m.window_end > now + timedelta(minutes=30):
        old_m.status = "APPROVED"                          # still open: the next plan can cover the rest
        old_m.outcome = "PARTIAL" if old_m.on_station_achieved_min else old_m.outcome
    else:
        old_m.status, old_m.outcome = "COMPLETED", "PARTIAL" if old_m.on_station_achieved_min else "MISSED"
    before = {"mission_id": s.mission_id, "mission_type": s.mission_type, "recovery_base_id": s.recovery_base_id}
    s.mission_id, s.mission_type, s.priority = mission.id, mission.mission_type, mission.priority
    s.recovery_base_id, s.planned_recovery_ts, s.reroute_ts = r["recovery_base_id"], r["recovery_ts"], now
    s.route_geom = from_shape(LineString([tuple(c) for c in r["route"]]), srid=4326)
    s.status, s.version = "AIRBORNE", s.version + 1
    mission.status = "ACTIVE"
    audit(db, user, "UPDATE", "sortie", s.id, s.departure_base_id, before,
          {"mission_id": mission.id, "mission_type": mission.mission_type, "recovery_base_id": s.recovery_base_id,
           "reason": f"re-roled in flight from {old_m.code} to {mission.code}"}, request_id=request_id)


def _support_same(r: dict, src: dict | None) -> bool:
    """Same tanker slot and the same people as the committed package's support leg (or neither has one)."""
    a, b = r.get("support"), (src or {}).get("support")
    if not a or not b:
        return not a and not b
    same_slot = a["base_id"] == b["base_id"] and a["type_id"] == b["type_id"] and a["launch"] == b["launch"]
    return same_slot and sorted(a["aircraft_ids"]) == sorted(b["aircraft_ids"]) and \
        sorted(map(tuple, a["crew_positions"])) == sorted(map(tuple, b["crew_positions"]))


def _commit_support(db: Session, user: dict, r: dict, src: dict | None, it: M.PlanItem, mission: M.Mission,
                    request_id: str | None) -> str | None:
    """The package's support leg (tanker, D36) as its own sortie: kept, swapped in place, or cancelled and recreated.
    Returns "NEW" when a tanker sortie was created."""
    from sqlalchemy.orm.attributes import flag_modified
    made = None
    new, old = r.get("support"), (src or {}).get("support")
    old_s = db.get(M.Sortie, old["sortie_id"]) if old and old.get("sortie_id") else None
    if old_s and old_s.status in AIRBORNE + ("LANDED", "COMPLETED") and new:
        new["sortie_id"] = old_s.id                        # already flying: carried as it is
    elif old_s and old_s.status in LIVE and new and _support_same(r, src):
        new["sortie_id"] = old_s.id
    elif old_s and old_s.status in LIVE and new and new["base_id"] == old["base_id"] and new["launch"] == old["launch"]:
        db.execute(text("DELETE FROM sortie_crew WHERE sortie_id = :s"), {"s": old_s.id})
        for sa, aid in zip(db.scalars(select(M.SortieAircraft).where(M.SortieAircraft.sortie_id == old_s.id)), new["aircraft_ids"]):
            sa.aircraft_id = aid
        for cid, aid, pos in new["crew_positions"]:
            db.add(M.SortieCrew(sortie_id=old_s.id, aircrew_id=cid, aircraft_id=aid, position=pos))
        old_s.version += 1
        new["sortie_id"] = old_s.id
        audit(db, user, "UPDATE", "sortie", old_s.id, old_s.departure_base_id, None,
              {"aircraft": new["aircraft_ids"], "reason": "tanker swap (re-task)"}, request_id=request_id)
    else:
        if old_s and old_s.status in LIVE:
            _cancel_sortie(db, old_s, user, "TASKING_CHANGE", request_id)
        if new:
            base = db.get(M.AirBase, new["base_id"])
            t = db.get(M.AircraftType, new["type_id"])
            s = SV.create(db, user=user, origin="PLAN", mission_type="AAR_SUPPORT", priority=mission.priority, base=base,
                          recovery_base_id=base.id, launch=datetime.fromisoformat(new["launch"]),
                          recovery=datetime.fromisoformat(new["recovery"]), route=[tuple(c) for c in new["route"]],
                          aircraft=[db.get(M.Aircraft, a) for a in new["aircraft_ids"]],
                          crew=[tuple(c) for c in new["crew_positions"]], fuel_kg=new["fuel_l"] * 0.8, family=SV.family_of(t),
                          mission_id=mission.id, plan_item_id=it.id, tag="T", request_id=request_id)
            new["sortie_id"] = s.id
            made = "NEW"
    if new:
        if new.get("sortie_id") and (ts := db.get(M.Sortie, new["sortie_id"])):
            ts.plan_item_id = it.id                       # carried / swapped tankers follow their package
        it.support = dict(new)
        flag_modified(it, "support")
    return made


def _repair(db: Session, st: S.OpsState, actions: list) -> tuple[list[str], dict]:
    """Commit-time repair. Returns (sentences for repaired packages, {item id: reason} for skipped ones)."""
    from datetime import timedelta as td
    from sqlalchemy.orm.attributes import flag_modified
    from .assign import Assignment, Ledger, assign
    from .planner import assignment_from_row, cand_from_row, support_from_row
    skipped, repaired = {}, []
    live = [r for r, _, _, act in actions if act in ("NEW", "MOVED", "SWAP")]
    # the clock ran while a person decided: a new or moved package whose preparation should already have started slips
    # by that delay, if its mission window still holds (the validator below re-checks everything at the new time)
    for r, _, _, act in actions:
        m = st.missions.get(r["mission_id"])
        need = st.now + td(minutes=D.PREP_MIN + 2)
        if act not in ("NEW", "MOVED") or m is None or r["launch_ts"] >= need:
            continue
        slip = need - r["launch_ts"]
        if r["on_station_ts"] + slip + td(minutes=m.on_station_min) <= m.window_end:
            _shift(db, r, slip)
            repaired.append(f"{m.code}: launch slipped {round(slip.total_seconds() / 60)} min while the decision was taken")
    for r in live:
        if r["launch_ts"] < st.now + td(minutes=5):
            skipped[r["id"]] = f"{st.missions[r['mission_id']].code if r['mission_id'] in st.missions else r['mission_id']}: launch time has passed"
    todo = [r for r in live if r["id"] not in skipped]
    swappable = {"AIRCRAFT_STATE", "AIRCRAFT_OVERLAP", "AIRCRAFT_HOURS", "CREW_STATE", "CREW_OVERLAP"}
    for _ in range(2):
        bad = validate(st, [x for r in todo for x in specs_from_row(r)])
        if not bad:
            break
        by, sup_bad = {}, {}
        for v in bad:
            iid, _, leg = v.key.partition("#")
            (sup_bad if leg else by).setdefault(int(iid), []).append(v)
        led = Ledger()
        for r in todo:
            if r["id"] not in by and r["id"] not in sup_bad:
                led.take(cand_from_row(st, r, 0), assignment_from_row(r))
        for r in todo:
            vs = sup_bad.get(r["id"])
            if vs and r["id"] not in by:              # only the tanker broke: re-crew the tanker
                code = st.missions[r["mission_id"]].code if r["mission_id"] in st.missions else str(r["mission_id"])
                c = cand_from_row(st, r, r["id"])
                led.take(c, Assignment(r["aircraft_ids"], [tuple(x) for x in r["crew_positions"] or []]))
                s = support_from_row(st, r)
                a = assign(st, s, led, assignment_from_row(r).support) if {v.rule for v in vs} <= swappable else "not swappable"
                if not isinstance(a, str):
                    led.take(s, a)
                    r["support"] = {**r["support"], "aircraft_ids": list(a.aircraft), "crew_positions": [list(x) for x in a.crew]}
                    it = db.get(M.PlanItem, r["id"])
                    it.support = dict(r["support"])
                    flag_modified(it, "support")
                    repaired.append(f"{code}: tanker {vs[0].detail}; repaired with another tanker or crew")
                else:
                    skipped[r["id"]] = f"{code}: tanker {vs[0].detail}"
        for r in todo:
            vs = by.get(r["id"])
            if not vs:
                continue
            code = st.missions[r["mission_id"]].code if r["mission_id"] in st.missions else str(r["mission_id"])
            if {v.rule for v in vs} <= swappable:
                c = cand_from_row(st, r, r["id"])
                a = assign(st, c, led, Assignment(r["aircraft_ids"], [tuple(x) for x in r["crew_positions"] or []]))
                if not isinstance(a, str):
                    led.take(c, a)
                    r["aircraft_ids"], r["crew_positions"] = list(a.aircraft), [list(x) for x in a.crew]
                    it = db.get(M.PlanItem, r["id"])
                    it.aircraft_ids, it.crew_positions = r["aircraft_ids"], r["crew_positions"]
                    it.aircrew_ids = [x[0] for x in a.crew]
                    repaired.append(f"{code}: {vs[0].detail}; repaired with other tails / crew at the same base")
                    continue
            skipped[r["id"]] = f"{code}: {vs[0].detail}"
        todo = [r for r in todo if r["id"] not in skipped]
    return repaired, skipped


def _shift(db: Session, r: dict, d: timedelta) -> None:
    """Move a package (and its tanker leg) later by d, in the row and in the stored plan item."""
    from sqlalchemy.orm.attributes import flag_modified
    it = db.get(M.PlanItem, r["id"])
    for k in ("launch_ts", "on_station_ts", "recovery_ts"):
        r[k] = r[k] + d
        setattr(it, k, r[k])
    if r.get("support"):
        sup = dict(r["support"])
        for k in ("launch", "recovery", "rv_start", "rv_end"):
            if sup.get(k):
                sup[k] = (datetime.fromisoformat(sup[k]) + d).isoformat()
        r["support"] = it.support = sup
        flag_modified(it, "support")


ITEM_COLS = ("mission_id", "base_id", "recovery_base_id", "aircraft_type_id", "loadout_code", "launch_ts", "on_station_ts",
             "recovery_ts", "n_aircraft", "aircraft_ids", "aircrew_ids", "crew_positions", "route_geom", "risk", "fuel_l",
             "score", "explanation", "alternatives", "support")


def copy_items(db: Session, src_plan: int, dst_plan: int, item_ids: list[int], change: str = "KEPT") -> int:
    """Carry committed items into a new plan unchanged (frozen packages, other commands' packages). SQL-side so
    geometry and arrays copy exactly."""
    if not item_ids:
        return 0
    cols = ", ".join(ITEM_COLS)
    r = db.execute(text(f"""INSERT INTO plan_item (plan_id, {cols}, change, status, source_item_id)
                            SELECT :dst, {cols}, :ch, 'PROPOSED', id FROM plan_item WHERE plan_id = :src AND id = ANY(:ids)"""),
                   {"dst": dst_plan, "src": src_plan, "ids": item_ids, "ch": change})
    return r.rowcount


def routes_geojson(db: Session, pid: int) -> dict:
    feats = []
    for r in _rows(db, """SELECT pi.id, pi.status, pi.change, pi.launch_ts, pi.recovery_ts, pi.n_aircraft, m.code, m.name,
                                 m.priority, m.mission_type, b.code AS base, t.name AS type, s.status AS sortie_status,
                                 ST_AsGeoJSON(pi.route_geom, 4)::json AS g, ST_X(m.target_geom) AS tx, ST_Y(m.target_geom) AS ty,
                                 pi.support
                          FROM plan_item pi JOIN mission m ON m.id = pi.mission_id JOIN base b ON b.id = pi.base_id
                          JOIN aircraft_type t ON t.id = pi.aircraft_type_id LEFT JOIN sortie s ON s.id = pi.sortie_id
                          WHERE pi.plan_id = :p AND pi.status <> 'REJECTED' AND pi.route_geom IS NOT NULL""", p=pid):
        g = r.pop("g")
        sup = r.pop("support", None)
        props = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()}
        feats.append({"type": "Feature", "geometry": g, "properties": {**props, "support": False}})
        if sup and len(sup.get("route", [])) > 1:          # the tanker's track to the refuelling point
            feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": sup["route"]},
                          "properties": {**props, "support": True, "rv": sup["rv"], "base": props["base"], "type": "tanker"}})
    return {"type": "FeatureCollection", "features": feats}


def generate_plan(user: dict, preset: str = "BALANCED", scope: str = "THEATRE", horizon_h: float | None = None,
                  why: str | None = None) -> dict:
    """Plan the current situation (routine and scenario missions alike) and store it as a proposal. The caller holds
    monitor.LOCK (one solve at a time). Used by POST /ops/plans and when a scenario starts with nothing committed (D56)."""
    from ..db import SessionLocal
    from . import config as DC
    from . import planner as P
    horizon_h = horizon_h or DC.HORIZON_H
    with SessionLocal() as db:
        cp = current_committed(db)
        command_id = user["command_id"] if scope == "COMMAND" or user["command_id"] else None
        release, stability, keep = set(), {}, {}
        if cp:
            from .assign import Assignment
            for r in (x for x in items_of(db, cp.id) if x["status"] == "COMMITTED"):
                mine = command_id is None or db.get(M.Mission, r["mission_id"]).requesting_command_id == command_id
                s = db.get(M.Sortie, r["sortie_id"]) if r["sortie_id"] else None
                if mine and s and s.status == "PLANNED":
                    release |= {s.id} | own_sorties(db, [r])           # and its tanker, unless already airborne
                    stability[r["mission_id"]] = (r["base_id"], r["aircraft_type_id"], r["launch_ts"])
                    keep[r["mission_id"]] = Assignment(r["aircraft_ids"], [tuple(x) for x in r["crew_positions"] or []])
        st = S.build(db, horizon_h=horizon_h, release_sortie_ids=release)
        if command_id is not None:
            st.missions = {k: m for k, m in st.missions.items() if m.command_id == command_id}
        if cp:   # packages already flying or too close to launch stay as they are
            frozen = {r["mission_id"] for r in items_of(db, cp.id) if r["status"] == "COMMITTED"
                      and r["sortie_id"] and db.get(M.Sortie, r["sortie_id"]).status != "PLANNED"}
        else:
            frozen = set()
        res = P.plan(st, preset, stability=stability, keep=keep, fixed_missions=frozen)
        if why:                                           # what made it (D57), e.g. a scenario starting
            res.kpis["why"] = why
        pid = P.store(db, res, preset=preset, user=user, scope="COMMAND" if command_id else "THEATRE",
                      command_id=command_id, parent_plan_id=cp.id if cp else None,
                      summary=f"{res.kpis['covered']} of {res.kpis['missions']} missions covered")
        if cp:   # carry forward what this plan didn't touch (frozen packages, other commands)
            carry = [r["id"] for r in items_of(db, cp.id) if r["status"] == "COMMITTED" and (r["mission_id"] in frozen or
                     (command_id is not None and db.get(M.Mission, r["mission_id"]).requesting_command_id != command_id))]
            copy_items(db, cp.id, pid, carry, "KEPT")
        # one full plan waits for a decision at a time: the newest picture replaces older ones (D59)
        db.execute(text("""UPDATE plan SET status = 'SUPERSEDED' WHERE kind = 'PLAN' AND status IN ('PROPOSED', 'APPROVED')
                           AND scope = :s AND id <> :p"""), {"s": "COMMAND" if command_id else "THEATRE", "p": pid})
        audit(db, user, "PLAN_GENERATE", "plan", pid, None, None, {"preset": preset, **{k: res.kpis[k] for k in
              ("missions", "covered", "unmet", "solve_ms", "total_ms")}})
        db.commit()
        return {"plan_id": pid, "kpis": res.kpis}
