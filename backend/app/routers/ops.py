"""Phase 2 decision support API (PHASE2_IMPLEMENTATION_PLAN §9): missions, plans, re-tasking, what-if, forecasts,
operational zones. Routers stay thin; the logic is in app/decide."""
import asyncio
import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from geoalchemy2.shape import from_shape
from pydantic import BaseModel, Field
from shapely.geometry import Point
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import models as M
from ..audit import audit
from ..auth import current_user
from ..db import SessionLocal, get_db
from ..decide import config as D
from ..decide import forecast as FC
from ..decide import predict as PR
from ..decide import monitor, planner as P, snapshot as S, store, whatif as WI
from ..rbac import require

router = APIRouter(prefix="/ops", tags=["decision support"])
PLANNERS = ("ADMIN", "COMMAND_HQ")


def _err(e: store.PlanError):
    raise HTTPException(e.status, {"message": e.message, "details": e.details})


def _theatre_ok(user: dict) -> bool:
    return user["role"] == "ADMIN" or (user["role"] == "COMMAND_HQ" and user["command_id"] is None)


def _q(db: Session, sql: str, **p) -> list[dict]:
    return [dict(r) for r in db.execute(text(sql), p).mappings()]


# ================================================================== missions
MISSION_SQL = """SELECT m.id, m.code, m.name, m.mission_type, m.priority, m.status, m.window_start, m.window_end, m.version,
       m.required_aircraft, m.eligible_roles, m.loadout_code, m.on_station_min, m.min_quals, m.max_risk, m.notes, m.outcome,
       m.on_station_achieved_min, m.requesting_command_id, c.code AS command, ST_X(m.target_geom) AS lon,
       ST_Y(m.target_geom) AS lat, tb.code AS target_base, m.target_base_id, m.created_at, m.approved_at,
       pi.id AS item_id, pi.plan_id, b.code AS tasked_base, t.name AS tasked_type, pi.n_aircraft AS tasked_n,
       pi.launch_ts AS tasked_launch, s.code AS sortie_code, s.status AS sortie_status, m.is_simulated AS simulated,
       m.depends_on_id, dm.code AS depends_on, m.parent_mission_id, pm.code AS parent_code, m.part_no, m.parts, m.split_kind
FROM mission m LEFT JOIN command c ON c.id = m.requesting_command_id LEFT JOIN base tb ON tb.id = m.target_base_id
LEFT JOIN mission dm ON dm.id = m.depends_on_id LEFT JOIN mission pm ON pm.id = m.parent_mission_id
LEFT JOIN plan_item pi ON pi.mission_id = m.id AND pi.status = 'COMMITTED'
     AND pi.plan_id = (SELECT id FROM plan WHERE status = 'COMMITTED' AND kind <> 'WHATIF' ORDER BY id DESC LIMIT 1)
LEFT JOIN base b ON b.id = pi.base_id LEFT JOIN aircraft_type t ON t.id = pi.aircraft_type_id
LEFT JOIN sortie s ON s.id = pi.sortie_id"""


@router.get("/missions")
def missions(status: str = "", priority: str = "", command: str = "", mission_type: str = "", q: str = "",
             horizon_h: float = 0, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    where, p = ["true"], {}
    for col, val in (("m.status", status), ("m.priority", priority), ("c.code", command), ("m.mission_type", mission_type)):
        if val:
            where.append(f"{col} = ANY(:{col.replace('.', '_')})")
            p[col.replace(".", "_")] = val.split(",")
    if q:
        where.append("(m.code ILIKE :q OR m.name ILIKE :q)")
        p["q"] = f"%{q}%"
    if horizon_h:
        where.append("m.window_end > sim_now() AND m.window_start < sim_now() + :h * interval '1 hour'")
        p["h"] = horizon_h
    rows = _q(db, MISSION_SQL + " WHERE " + " AND ".join(where) + " ORDER BY m.window_start, m.priority, m.id", **p)
    counts = {r["status"]: r["n"] for r in _q(db, "SELECT status, count(*) n FROM mission GROUP BY 1")}
    return {"items": rows, "counts": counts, "now": db.execute(text("SELECT sim_now()")).scalar(), "simulated": True}


@router.get("/missions/meta")
def missions_meta(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return {"templates": {k: {"label": D.MISSION_LABEL[k][1], "roles": v[1], "required": v[2][0], "on_station_min": v[3],
                              "priority_weights": v[0]} for k, v in D.MISSION_TEMPLATES.items()},
            "types": list(M.MISSION_TYPES), "priorities": list(D.PRIORITIES), "risk": list(D.RISK_LEVELS),
            "roles": sorted({r for v in D.MISSION_TEMPLATES.values() for r in v[1]}),
            "quals": ["NIGHT", "NVG", "MOUNTAIN_FLYING", "AAR_RECEIVER", "LOW_LEVEL", "SAR", "PARA_DROP"],
            "loadouts": [{"code": c, "name": v[0], "families": v[1], "items": v[2]} for c, v in D.LOADOUTS.items()],
            "bases": _q(db, "SELECT id, code, name FROM base WHERE side = 'OWN' ORDER BY code"),
            "commands": _q(db, "SELECT id, code, name FROM command WHERE is_operational ORDER BY id")}


class MissionIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    mission_type: str
    priority: str = "P2"
    window_start: datetime
    window_end: datetime
    lon: float | None = None
    lat: float | None = None
    target_base_id: int | None = None
    required_aircraft: int | None = None
    eligible_roles: list[str] | None = None
    loadout_code: str | None = None
    on_station_min: int | None = None
    min_quals: list[str] = []
    max_risk: str = "MED"
    notes: str | None = None
    command_id: int | None = None
    depends_on_id: int | None = None          # D41: e.g. the AEW&C orbit this CAP needs


def _check_dependency(db: Session, dep_id: int | None, self_id: int | None, errs: dict) -> None:
    if not dep_id:
        return
    d = db.get(M.Mission, dep_id)
    if not d or d.id == self_id or d.status in ("CANCELLED", "COMPLETED"):
        errs["depends_on_id"] = "Pick a live mission"
    elif d.depends_on_id:
        errs["depends_on_id"] = "That mission depends on another one itself (one level only)"


def _validate_mission(db: Session, body: MissionIn) -> tuple:
    errs = {}
    _check_dependency(db, body.depends_on_id, None, errs)
    if body.mission_type not in D.MISSION_TEMPLATES and body.mission_type not in M.MISSION_TYPES:
        errs["mission_type"] = "Choose a mission type"
    if body.priority not in D.PRIORITIES:
        errs["priority"] = "P1–P4"
    if body.max_risk not in D.RISK_LEVELS:
        errs["max_risk"] = "LOW, MED or HIGH"
    if body.window_end <= body.window_start + timedelta(minutes=15):
        errs["window_end"] = "Window must be at least 15 minutes long"
    lon, lat = body.lon, body.lat
    if body.target_base_id:
        b = db.get(M.AirBase, body.target_base_id)
        if not b or b.side != "OWN":
            errs["target_base_id"] = "Pick an IAF base"
        else:
            r = db.execute(text("SELECT ST_X(geom), ST_Y(geom) FROM base WHERE id = :i"), {"i": b.id}).one()
            lon, lat = r[0], r[1]
    if lon is None or lat is None:
        errs["lon"] = "Pick a point on the map or a destination base"
    else:
        G = S.india(db)
        if not G.ok(lon, lat):
            errs["lon"] = f"The area must be inside India and at least {D_buffer()} km from the boundary (and this side of the LoC / LAC)"
    if errs:
        raise HTTPException(422, {"message": "Check the highlighted fields.", "fields": errs})
    return lon, lat


def D_buffer():
    from .. import config
    return config.BORDER_BUFFER_KM


@router.post("/missions", status_code=201)
def create_mission(body: MissionIn, request: Request, user: dict = Depends(require(*PLANNERS)), db: Session = Depends(get_db)):
    lon, lat = _validate_mission(db, body)
    tpl = D.MISSION_TEMPLATES.get(body.mission_type)
    cmd = body.command_id if _theatre_ok(user) and body.command_id else user["command_id"]
    if cmd is None:
        cmd = db.execute(text("""SELECT b.command_id FROM base b WHERE b.side = 'OWN' AND b.command_id IN
                                 (SELECT id FROM command WHERE is_operational) ORDER BY b.geom <-> ST_SetSRID(ST_Point(:x, :y), 4326)
                                 LIMIT 1"""), {"x": lon, "y": lat}).scalar()
    short = D.MISSION_LABEL.get(body.mission_type, ("MSN", ""))[0]
    ccode = db.get(M.Command, cmd).code
    n = db.execute(text("SELECT count(*) FROM mission WHERE code LIKE :p"), {"p": f"SIM-{short}-{ccode}-U%"}).scalar() + 1
    approved = _theatre_ok(user)
    m = M.Mission(code=f"SIM-{short}-{ccode}-U{n:02d}", name=body.name, mission_type=body.mission_type, priority=body.priority,
                  window_start=body.window_start, window_end=body.window_end, status="APPROVED" if approved else "REQUESTED",
                  requesting_command_id=cmd, target_geom=from_shape(Point(lon, lat), srid=4326), target_base_id=body.target_base_id,
                  required_aircraft=body.required_aircraft or (tpl[2][0] if tpl else 2),
                  eligible_roles=body.eligible_roles or (tpl[1] if tpl else None), loadout_code=body.loadout_code,
                  on_station_min=body.on_station_min or (tpl[3] if tpl else 60), min_quals=body.min_quals, max_risk=body.max_risk,
                  notes=body.notes, depends_on_id=body.depends_on_id,
                  requested_by=user["id"], approved_by=user["id"] if approved else None,
                  approved_at=datetime.now().astimezone() if approved else None, is_simulated=True, source="SYNTHETIC")
    db.add(m)
    db.flush()
    audit(db, user, "CREATE", "mission", m.id, None, None,
          {"code": m.code, "type": m.mission_type, "priority": m.priority, "status": m.status}, request_id=request.state.request_id)
    db.commit()
    return {"id": m.id, "code": m.code, "status": m.status}


class MissionPatch(BaseModel):
    version: int
    name: str | None = None
    priority: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    required_aircraft: int | None = None
    on_station_min: int | None = None
    max_risk: str | None = None
    notes: str | None = None
    depends_on_id: int | None = None          # 0 removes the dependency


def _mission_scope(user: dict, m: M.Mission) -> None:
    if user["role"] == "ADMIN" or (user["role"] == "COMMAND_HQ" and user["command_id"] in (None, m.requesting_command_id)):
        return
    raise HTTPException(403, "You can only change your own command's missions.")


@router.patch("/missions/{mid}")
def patch_mission(mid: int, body: MissionPatch, request: Request, user: dict = Depends(require(*PLANNERS)),
                  db: Session = Depends(get_db)):
    m = db.get(M.Mission, mid, with_for_update=True)
    if not m:
        raise HTTPException(404, "Mission not found")
    _mission_scope(user, m)
    if body.version != m.version:
        raise HTTPException(409, "This mission was changed by someone else. Reload it.")
    if m.status in ("COMPLETED", "CANCELLED"):
        raise HTTPException(409, "Finished missions can't be changed.")
    fields = {k: v for k, v in body.model_dump(exclude={"version"}).items() if v is not None}
    if "priority" in fields and fields["priority"] not in D.PRIORITIES or "max_risk" in fields and fields["max_risk"] not in D.RISK_LEVELS:
        raise HTTPException(422, "Invalid priority or risk level")
    if "depends_on_id" in fields:
        errs: dict = {}
        _check_dependency(db, fields["depends_on_id"] or None, m.id, errs)
        if errs:
            raise HTTPException(422, {"message": "Check the highlighted fields.", "fields": errs})
        fields["depends_on_id"] = fields["depends_on_id"] or None
    before = {k: getattr(m, k) for k in fields}
    for k, v in fields.items():
        setattr(m, k, v)
    if (m.window_end - m.window_start) < timedelta(minutes=15):
        raise HTTPException(422, {"message": "Window must be at least 15 minutes long", "fields": {"window_end": "Too short"}})
    m.version += 1
    if m.status in ("PLANNED", "TASKED") and set(fields) & {"window_start", "window_end", "required_aircraft", "on_station_min",
                                                             "priority", "max_risk", "depends_on_id"}:
        m.approved_at = datetime.now().astimezone()      # the monitor re-checks the committed package against it
    audit(db, user, "UPDATE", "mission", m.id, None, before, fields, request_id=request.state.request_id)
    db.commit()
    return {"ok": True, "version": m.version}


class SplitIn(BaseModel):
    kind: str                                  # SPLIT_RELIEF / SPLIT_BASES (the fix kinds)
    parts: int
    t0: datetime
    sizes: list[int] | None = None


@router.post("/missions/{mid}/split")
def split_mission(mid: int, body: SplitIn, request: Request, user: dict = Depends(require(*PLANNERS)), db: Session = Depends(get_db)):
    """D42: cover one mission with several packages (reliefs in time, or parts from different bases). Audited."""
    from ..decide import split as SP
    m = db.get(M.Mission, mid, with_for_update=True)
    if not m:
        raise HTTPException(404, "Mission not found")
    _mission_scope(user, m)
    if m.status not in ("APPROVED", "PLANNED") or m.parent_mission_id:
        raise HTTPException(409, "Only an approved mission that isn't tasked (and isn't itself a part) can be split.")
    if body.kind not in ("SPLIT_RELIEF", "SPLIT_BASES") or not 2 <= body.parts <= D.SPLIT_MAX_PARTS:
        raise HTTPException(422, f"Split into 2–{D.SPLIT_MAX_PARTS} reliefs or base parts.")
    t0 = body.t0 if body.t0.tzinfo else body.t0.replace(tzinfo=m.window_start.tzinfo)
    if t0 < m.window_start or t0 + timedelta(minutes=m.on_station_min) > m.window_end:
        raise HTTPException(422, "The covered period must sit inside the mission's window.")
    if body.kind == "SPLIT_BASES" and (body.sizes and (sum(body.sizes) != m.required_aircraft or len(body.sizes) != body.parts)
                                       or m.required_aircraft < body.parts):
        raise HTTPException(422, "The parts must add up to the aircraft the mission needs.")
    parts = SP.apply(db, user, m, body.kind, body.parts, t0, body.sizes, request_id=request.state.request_id)
    db.commit()
    return {"ok": True, "parts": [{"id": p.id, "code": p.code} for p in parts]}


@router.post("/missions/{mid}/{action}")
def mission_action(mid: int, action: str, request: Request, user: dict = Depends(require(*PLANNERS)), db: Session = Depends(get_db)):
    m = db.get(M.Mission, mid, with_for_update=True)
    if not m:
        raise HTTPException(404, "Mission not found")
    _mission_scope(user, m)
    before = {"status": m.status}
    if action == "approve":
        if m.status != "REQUESTED":
            raise HTTPException(409, "Only requested missions can be approved.")
        m.status, m.approved_by, m.approved_at = "APPROVED", user["id"], datetime.now().astimezone()
        audit(db, user, "APPROVE", "mission", m.id, None, before, {"status": "APPROVED"}, request_id=request.state.request_id)
    elif action == "cancel":
        if m.status in ("COMPLETED", "CANCELLED", "ACTIVE"):
            raise HTTPException(409, "Active or finished missions can't be cancelled here.")
        m.status = "CANCELLED"
        for s in db.scalars(select(M.Sortie).where(M.Sortie.mission_id == m.id, M.Sortie.status.in_(("PLANNED", "CREWED", "READY")))):
            store._cancel_sortie(db, s, user, "TASKING_CHANGE", request.state.request_id)
        audit(db, user, "UPDATE", "mission", m.id, None, before, {"status": "CANCELLED"}, request_id=request.state.request_id)
    else:
        raise HTTPException(404, "Unknown action")
    m.version += 1
    db.commit()
    return {"ok": True, "status": m.status}


@router.get("/missions/geo")
def missions_geo(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    rows = _q(db, MISSION_SQL + """ WHERE m.status IN ('REQUESTED','APPROVED','PLANNED','TASKED','ACTIVE')
                                    AND m.window_end > sim_now() AND m.window_start < sim_now() + interval '24 hours'""")
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
         "properties": {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()
                        if k in ("id", "code", "name", "mission_type", "priority", "status", "command", "tasked_base",
                                 "tasked_type", "window_start", "window_end", "sortie_status")}}
        for r in rows if r["lon"] is not None]}


@router.get("/missions/{mid}")
def mission(mid: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    rows = _q(db, MISSION_SQL + " WHERE m.id = :id", id=mid)
    if not rows:
        raise HTTPException(404, "Mission not found")
    why = _q(db, """SELECT u.reasons, u.fixes, u.plan_id FROM plan_unmet u JOIN plan p ON p.id = u.plan_id
                    WHERE u.mission_id = :id AND p.kind <> 'WHATIF' ORDER BY u.id DESC LIMIT 1""", id=mid)
    return {**rows[0], "unmet": why[0] if why and not rows[0]["item_id"] else None}


@router.get("/plan-items/{iid}")
def plan_item(iid: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    it = db.get(M.PlanItem, iid)
    if not it:
        raise HTTPException(404, "Plan item not found")
    return next(i for i in store.serialise(db, it.plan_id)["items"] if i["id"] == iid)



# ================================================================== plans
class PlanIn(BaseModel):
    preset: str = "BALANCED"
    scope: str = "THEATRE"
    horizon_h: float = D.HORIZON_H


def _generate(user: dict, body: PlanIn) -> dict:
    with SessionLocal() as db:
        cp = store.current_committed(db)
        command_id = user["command_id"] if body.scope == "COMMAND" or user["command_id"] else None
        release, stability, keep = set(), {}, {}
        if cp:
            from ..decide.assign import Assignment
            for r in (x for x in store.items_of(db, cp.id) if x["status"] == "COMMITTED"):
                mine = command_id is None or db.get(M.Mission, r["mission_id"]).requesting_command_id == command_id
                s = db.get(M.Sortie, r["sortie_id"]) if r["sortie_id"] else None
                if mine and s and s.status == "PLANNED":
                    release.add(s.id)
                    stability[r["mission_id"]] = (r["base_id"], r["aircraft_type_id"], r["launch_ts"])
                    keep[r["mission_id"]] = Assignment(r["aircraft_ids"], [tuple(x) for x in r["crew_positions"] or []])
        st = S.build(db, horizon_h=body.horizon_h, release_sortie_ids=release)
        if command_id is not None:
            st.missions = {k: m for k, m in st.missions.items() if m.command_id == command_id}
        if cp:   # packages already flying or too close to launch stay as they are
            frozen = {r["mission_id"] for r in store.items_of(db, cp.id) if r["status"] == "COMMITTED"
                      and r["sortie_id"] and db.get(M.Sortie, r["sortie_id"]).status != "PLANNED"}
        else:
            frozen = set()
        res = P.plan(st, body.preset, stability=stability, keep=keep, fixed_missions=frozen)
        pid = P.store(db, res, preset=body.preset, user=user, scope="COMMAND" if command_id else "THEATRE",
                      command_id=command_id, parent_plan_id=cp.id if cp else None,
                      summary=f"{res.kpis['covered']} of {res.kpis['missions']} missions covered")
        if cp:   # carry forward what this plan didn't touch (frozen packages, other commands)
            carry = [r["id"] for r in store.items_of(db, cp.id) if r["status"] == "COMMITTED" and (r["mission_id"] in frozen or
                     (command_id is not None and db.get(M.Mission, r["mission_id"]).requesting_command_id != command_id))]
            store.copy_items(db, cp.id, pid, carry, "KEPT")
        audit(db, user, "PLAN_GENERATE", "plan", pid, None, None, {"preset": body.preset, **{k: res.kpis[k] for k in
              ("missions", "covered", "unmet", "solve_ms", "total_ms")}})
        db.commit()
        return {"plan_id": pid, "kpis": res.kpis}


@router.post("/plans", status_code=201)
async def generate(body: PlanIn, request: Request, user: dict = Depends(require(*PLANNERS))):
    if body.preset not in D.PRESETS:
        raise HTTPException(422, "Unknown preset")
    if body.scope == "THEATRE" and not _theatre_ok(user) and user["command_id"] is None:
        raise HTTPException(403, "Only Air HQ can plan for the whole theatre.")

    def run():
        if not monitor.LOCK.acquire(timeout=30):
            raise HTTPException(409, "A plan is being generated. Try again in a moment.")
        try:
            return _generate(user, body)
        finally:
            monitor.LOCK.release()
    out = await asyncio.to_thread(run)
    from ..ws import hub
    await hub.broadcast("plan.ready", {"plan_id": out["plan_id"], "kpis": out["kpis"]}, None)
    return out


@router.get("/plans")
def plans(kind: str = "", status: str = "", limit: int = 20, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    where = ["true"]
    p = {"lim": max(1, min(limit, 100))}
    if kind:
        where.append("p.kind = ANY(:k)")
        p["k"] = kind.split(",")
    if status:
        where.append("p.status = ANY(:s)")
        p["s"] = status.split(",")
    rows = _q(db, f"""SELECT p.id, p.kind, p.status, p.scope, p.preset, p.created_at, p.committed_at, p.solve_ms, p.kpis,
                             p.summary, p.parent_plan_id, u.username AS created_by, c.code AS command
                      FROM plan p LEFT JOIN app_user u ON u.id = p.created_by LEFT JOIN command c ON c.id = p.command_id
                      WHERE {' AND '.join(where)} ORDER BY p.id DESC LIMIT :lim""", **p)
    cp = store.current_committed(db)
    pending = db.scalars(select(M.Plan).where(M.Plan.kind == "RETASK", M.Plan.status == "PROPOSED").order_by(M.Plan.id.desc())).first()
    return {"items": rows, "committed_id": cp.id if cp else None, "pending_retask_id": pending.id if pending else None}


@router.get("/plans/current")
def current_plan(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    cp = store.current_committed(db)
    return store.serialise(db, cp.id) if cp else None


@router.get("/plans/{pid}")
def get_plan(pid: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    try:
        return store.serialise(db, pid)
    except store.PlanError as e:
        _err(e)


@router.get("/plans/{pid}/routes")
def plan_routes(pid: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return store.routes_geojson(db, pid)


def _can_decide(user: dict, p: M.Plan) -> None:
    if user["role"] == "ADMIN" or (user["role"] == "COMMAND_HQ" and (user["command_id"] is None or
                                                                       (p.scope == "COMMAND" and p.command_id == user["command_id"]))):
        return
    raise HTTPException(403, "Only Air HQ (or the command that owns a command plan) can approve this plan.")


class ApproveIn(BaseModel):
    item_ids: list[int] | None = None


@router.post("/plans/{pid}/approve")
def approve(pid: int, request: Request, body: ApproveIn | None = None, user: dict = Depends(require(*PLANNERS)),
            db: Session = Depends(get_db)):
    p = db.get(M.Plan, pid)
    if p:
        _can_decide(user, p)
    try:
        store.approve(db, pid, user, body.item_ids if body else None, request.state.request_id)
    except store.PlanError as e:
        _err(e)
    db.commit()
    return {"ok": True}


@router.post("/plans/{pid}/reject")
def reject(pid: int, request: Request, user: dict = Depends(require(*PLANNERS)), db: Session = Depends(get_db)):
    p = db.get(M.Plan, pid)
    if p:
        _can_decide(user, p)
    try:
        store.reject(db, pid, user, request.state.request_id)
    except store.PlanError as e:
        _err(e)
    db.commit()
    return {"ok": True}


@router.post("/plans/{pid}/commit")
async def commit(pid: int, request: Request, user: dict = Depends(require(*PLANNERS))):
    def run():
        with monitor.LOCK, SessionLocal() as db:
            p = db.get(M.Plan, pid)
            if p:
                _can_decide(user, p)
            try:
                counts = store.commit(db, pid, user, request.state.request_id)
            except store.PlanError as e:
                db.rollback()
                _err(e)
            db.commit()
            return counts
    counts = await asyncio.to_thread(run)
    from ..ws import hub
    await hub.broadcast("entity.changed", {"types": ["sortie", "plan", "mission", "stock_level", "aircrew"]}, None)
    return {"ok": True, "changes": counts}


class OverrideIn(BaseModel):
    aircraft_ids: list[int] | None = None
    crew_positions: list[list] | None = None


@router.patch("/plans/{pid}/items/{iid}")
def override(pid: int, iid: int, body: OverrideIn, request: Request, user: dict = Depends(current_user),
             db: Session = Depends(get_db)):
    try:
        out = store.override_item(db, pid, iid, user, body.aircraft_ids, body.crew_positions, request.state.request_id)
    except store.PlanError as e:
        _err(e)
    db.commit()
    return out


@router.get("/plans/{pid}/items/{iid}/options")
def item_options(pid: int, iid: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    """Tails and pilots a base commander could swap into a package (validated again on save)."""
    from ..decide.resources import Req, aircraft_free, crew_eligible, crew_free
    from ..decide.feasibility import Candidate
    it = db.get(M.PlanItem, iid)
    if not it or it.plan_id != pid:
        raise HTTPException(404, "Plan item not found")
    st = S.build(db, release_sortie_ids=store._releasable(db))
    rq = (it.score or {}).get("req", {})
    req = Req(frozenset(rq.get("quals", [])), rq.get("rating", "WHITE"), rq.get("ops", False))
    a0, a1 = it.launch_ts - timedelta(minutes=D.PREP_MIN), it.recovery_ts + timedelta(minutes=(it.score or {}).get("turnaround", 45))
    r0, r1 = it.launch_ts - timedelta(minutes=D.BRIEF_MIN), it.recovery_ts + timedelta(minutes=D.DEBRIEF_MIN, hours=D.CREW_REST_H)
    t = st.types[it.aircraft_type_id]
    dur = (it.score or {}).get("duration_h", 1.0)
    ac = [{"id": a.id, "tail_no": a.tail, "hours_left": round(a.hours_left, 1), "status": a.status,
           "free": aircraft_free(st, a, a0, a1) or a.id in it.aircraft_ids,
           "snag": round(PR.tail_risk(st, a, dur), 4) if st.snag else None}
          for a in (st.aircraft[i] for i in st.by_base_type.get((it.base_id, it.aircraft_type_id), ()))]
    crew = [{"id": c.id, "name": c.name, "rank": c.rank, "rating": c.rating, "quals": sorted(c.quals),
             "free": crew_free(st, c, r0, r1) or c.id in it.aircrew_ids}
            for c in (st.crew[i] for i in st.crew_by_base.get(it.base_id, ())) if crew_eligible(c, t, req, it.recovery_ts)]
    return {"aircraft": sorted(ac, key=lambda x: (not x["free"], -x["hours_left"])),
            "pilots": sorted(crew, key=lambda x: (not x["free"], x["name"])), "requirement": req.label()}


# ================================================================== what-if / COA
class WhatIfIn(BaseModel):
    deltas: list[dict] = []
    presets: list[str] = ["BALANCED"]


@router.get("/whatif/meta")
def whatif_meta(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return {"deltas": WI.DELTAS, "presets": list(D.PRESETS),
            "types": [r["name"] for r in _q(db, "SELECT name FROM aircraft_type WHERE in_service ORDER BY name")],
            "bases": [r["code"] for r in _q(db, "SELECT code FROM base WHERE side = 'OWN' ORDER BY code")]}


@router.post("/whatif")
async def whatif(body: WhatIfIn, user: dict = Depends(require(*PLANNERS))):
    if not body.presets or any(p not in D.PRESETS for p in body.presets):
        raise HTTPException(422, "Unknown preset")

    def run():
        if not monitor.LOCK.acquire(timeout=30):
            raise HTTPException(409, "The planner is busy. Try again in a moment.")
        try:
            with SessionLocal() as db:
                st = S.build(db)
            try:
                return WI.compare(st, body.deltas, body.presets[:3])
            except (ValueError, KeyError) as e:
                raise HTTPException(422, f"Check the what-if inputs: {e}")
        finally:
            monitor.LOCK.release()
    return await asyncio.to_thread(run)


# ================================================================== re-tasking
@router.get("/disruptions")
def disruptions(status: str = "", limit: int = 50, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    where, p = ["true"], {"lim": max(1, min(limit, 200))}
    if status:
        where.append("d.status = ANY(:s)")
        p["s"] = status.split(",")
    return _q(db, f"""SELECT d.id, d.ts, d.kind, d.message, d.status, d.proposal_plan_id, d.proposal_ms, d.resolved_at,
                             d.created_at, b.code AS base FROM disruption d LEFT JOIN base b ON b.id = d.base_id
                      WHERE {' AND '.join(where)} ORDER BY d.id DESC LIMIT :lim""", **p)


@router.post("/disruptions/check")
async def check_now(user: dict = Depends(require(*PLANNERS))):
    out = await asyncio.to_thread(monitor.check_once, user, True)
    from ..ws import hub
    if out.get("proposal"):
        await hub.broadcast("retask.proposal", out["proposal"], None)
    return out


@router.post("/disruptions/{did}/ignore")
def ignore(did: int, request: Request, user: dict = Depends(require(*PLANNERS)), db: Session = Depends(get_db)):
    d = db.get(M.Disruption, did)
    if not d:
        raise HTTPException(404, "Disruption not found")
    d.status = "IGNORED"
    audit(db, user, "UPDATE", "disruption", did, d.base_id, None, {"status": "IGNORED"}, request_id=request.state.request_id)
    db.commit()
    return {"ok": True}


# ================================================================== forecasts, zones, catalogue
@router.get("/forecast/bases/{base_id}")
def base_forecast(base_id: int, hours: int = 72, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    st = S.build(db, horizon_h=max(24, min(hours, 96)))
    if base_id not in st.bases:
        raise HTTPException(404, "IAF base not found")
    return FC.base(db, st, base_id, min(hours, 96))


# ================================================================== air tasking order (D46)
@router.get("/plans/{pid}/ato")
def plan_ato(pid: int, base_id: int | None = None, format: str = "json", user: dict = Depends(current_user),
             db: Session = Depends(get_db)):
    """The plan as an air tasking order: theatre-wide, or the packages one base flies (and the tankers it sends)."""
    from ..decide import ato as ATO
    if user["role"] == "BASE_COMMANDER" and base_id is None:
        base_id = user["base_id"]
    out = ATO.build(db, pid, base_id)
    if format == "csv":
        return StreamingResponse(iter([ATO.to_csv(out)]), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="ato-plan{pid}{f"-base{base_id}" if base_id else ""}.csv"'})
    return out


# ================================================================== manual planning baseline (D43, PS-8)
class ManualPicks(BaseModel):
    picks: list[dict] = []


def _manual_snapshot(db: Session):
    """The picture a full re-plan starts from: the committed plan's sorties that haven't launched are free again."""
    return S.build(db, release_sortie_ids=store._releasable(db))


@router.post("/manual", status_code=201)
def manual_start(user: dict = Depends(require(*PLANNERS)), db: Session = Depends(get_db)):
    """Start a timed manual planning session on the current snapshot."""
    from ..decide import manual as MN
    st = _manual_snapshot(db)
    ms = M.ManualSession(user_id=user["id"], sim_time=st.now, missions=len(st.missions), picks=[])
    db.add(ms)
    db.commit()
    return {"id": ms.id, "started_at": ms.started_at, "sim_time": st.now, "missions": MN.choices(st), "simulated": True}


def _manual(db: Session, sid: int, user: dict) -> M.ManualSession:
    ms = db.get(M.ManualSession, sid)
    if not ms or ms.user_id != user["id"]:
        raise HTTPException(404, "Session not found")
    if ms.finished_at:
        raise HTTPException(409, "This session is finished.")
    return ms


@router.post("/manual/{sid}/check")
def manual_check(sid: int, body: ManualPicks, user: dict = Depends(require(*PLANNERS)), db: Session = Depends(get_db)):
    """Apply the real rules to the picks so far (feasibility, assignment, validator). Counted."""
    from ..decide import manual as MN
    ms = _manual(db, sid, user)
    out = MN.evaluate(_manual_snapshot(db), body.picks)
    ms.checks, ms.picks = ms.checks + 1, body.picks
    db.commit()
    return out


@router.post("/manual/{sid}/finish")
async def manual_finish(sid: int, body: ManualPicks, request: Request, user: dict = Depends(require(*PLANNERS))):
    """Stop the clock, evaluate the picks, plan the same snapshot with the optimiser, store both."""
    from ..decide import manual as MN

    def run():
        with SessionLocal() as db:
            ms = _manual(db, sid, user)
            st = _manual_snapshot(db)
            mine = MN.evaluate(st, body.picks)
            ms.finished_at = datetime.now().astimezone()
            opt = MN.optimiser_result(st)
            ms.picks = body.picks
            ms.result = {"manual": {k: v for k, v in mine.items() if k != "rows"}, "optimiser": opt,
                         "elapsed_s": round((ms.finished_at - ms.started_at).total_seconds()), "checks": ms.checks}
            audit(db, user, "CREATE", "manual_session", ms.id, None, None,
                  {"covered": mine["covered"], "of": mine["missions"], "elapsed_s": ms.result["elapsed_s"]}, request_id=request.state.request_id)
            db.commit()
            return {**ms.result, "rows": mine["rows"]}
    return await asyncio.to_thread(run)


@router.get("/manual")
def manual_list(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return {"items": _q(db, """SELECT ms.id, ms.started_at, ms.finished_at, ms.sim_time, ms.missions, ms.checks, ms.result,
                                      u.display_name AS planner FROM manual_session ms LEFT JOIN app_user u ON u.id = ms.user_id
                               WHERE ms.finished_at IS NOT NULL ORDER BY ms.id DESC LIMIT 50"""), "simulated": True}


# ================================================================== snag-risk model (D38, FR-FCT-04)
@router.get("/models/snag-risk")
def snag_model_card(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return PR.card(db)


@router.post("/models/snag-risk/train")
async def snag_model_train(request: Request, user: dict = Depends(require(*PLANNERS))):
    """Retrain on the maintenance log as it stands now (the simulator keeps adding to it)."""
    def run():
        with SessionLocal() as db:
            try:
                m = PR.train(db, until=db.execute(text("SELECT sim_now()")).scalar())
            except ValueError as e:
                raise HTTPException(409, str(e))
            audit(db, user, "CREATE", "ml_model", m.id, None, None,
                  {"name": PR.NAME, "auc": m.metrics["test"]["auc"], "n": m.metrics["test"]["n"]}, request_id=request.state.request_id)
            db.commit()
            return PR.card(db)
    return await asyncio.to_thread(run)


@router.get("/fleet/snag-risk")
def fleet_snag_risk(base_id: int | None = None, hours: float = 1.5, limit: int = 12, user: dict = Depends(current_user),
                    db: Session = Depends(get_db)):
    """Serviceable tails ranked by predicted defect risk on a sortie of `hours` (base panel, planner)."""
    st = S.build(db, horizon_h=24)
    if st.snag is None:
        return {"items": [], "model": None, "simulated": True}
    rows = []
    for a in st.aircraft.values():
        if (base_id and a.base_id != base_id) or a.status not in ("AVAILABLE", "STANDBY"):
            continue
        rows.append({"aircraft_id": a.id, "tail_no": a.tail, "type": st.types[a.type_id].name, "base": st.bases[a.base_id].code,
                     "p": round(PR.tail_risk(st, a, hours), 4), "hours_left": round(a.hours_left, 1), "recent_defects": a.recent,
                     "why": st.snag.drivers(a.frac, a.age_y, hours, a.family, a.recent)})
    rows.sort(key=lambda r: -r["p"])
    mean = sum(r["p"] for r in rows) / len(rows) if rows else 0
    return {"items": rows[:max(1, min(limit, 50))], "fleet_mean": round(mean, 4), "n": len(rows), "hours": hours,
            "model": {"id": st.snag.id, "auc": st.snag.metrics["test"]["auc"]}, "simulated": True}


@router.get("/bases/{base_id}/tasking")
def base_tasking(base_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    """Base panel: committed packages at this base (next 24 h) and a short outlook (aircraft ready now / +6 h / +24 h)."""
    items = _q(db, """SELECT pi.id, pi.launch_ts, pi.recovery_ts, pi.n_aircraft, pi.change, m.code, m.name, m.priority, m.mission_type,
                             t.name AS type, s.code AS sortie_code, s.status AS sortie_status
                      FROM plan_item pi JOIN plan p ON p.id = pi.plan_id AND p.status = 'COMMITTED' AND p.kind <> 'WHATIF'
                      JOIN mission m ON m.id = pi.mission_id JOIN aircraft_type t ON t.id = pi.aircraft_type_id
                      LEFT JOIN sortie s ON s.id = pi.sortie_id
                      WHERE pi.base_id = :b AND pi.status = 'COMMITTED' AND pi.recovery_ts > sim_now()
                        AND pi.launch_ts < sim_now() + interval '24 hours' ORDER BY pi.launch_ts""", b=base_id)
    st = S.build(db, horizon_h=30)
    if base_id not in st.bases:
        return {"items": items, "outlook": None}
    fc = FC.base(db, st, base_id, hours=24, step=6)
    total = lambda k: round(sum(s["points"][k]["aircraft"] for s in fc["aircraft"]), 1) if fc["aircraft"] else 0  # noqa: E731
    return {"items": items, "outlook": {"now": total(0), "h6": total(1), "h24": total(-1),
                                        "fuel_breach": fc["fuel"]["reserve_breach"], "weather": fc["weather"][:5]}, "simulated": True}


@router.get("/wx-impact")
def wx_impact(hours: int = 6, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return FC.wx_impact(S.build(db, horizon_h=12), min(hours, 12))


@router.get("/zones")
def zones(kind: str = "airspace", user: dict = Depends(current_user), db: Session = Depends(get_db)):
    if kind == "threat":
        sql = """SELECT id, code, name, kind, risk_level AS risk, active_from, active_to, ST_AsGeoJSON(geom, 4)::json AS g
                 FROM threat_zone WHERE active_to IS NULL OR active_to > sim_now()"""
    else:
        sql = """SELECT id, code, name, kind, capacity_packages AS capacity, active_from, active_to, ST_AsGeoJSON(geom, 4)::json AS g
                 FROM airspace_zone WHERE (active_to IS NULL OR active_to > sim_now()) AND code NOT LIKE 'RWY-%'"""
    feats = []
    for r in _q(db, sql):
        g = r.pop("g")
        feats.append({"type": "Feature", "geometry": g, "properties": {k: (v.isoformat() if isinstance(v, datetime) else v)
                                                                       for k, v in r.items()} | {"simulated": True}})
    return {"type": "FeatureCollection", "features": feats}


@router.get("/loadouts")
def loadouts(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return _q(db, """SELECT l.code, l.name, l.role_family, l.items, l.fuel_penalty_pct, l.radius_factor, l.description,
                            array_agg(t.name ORDER BY t.name) AS types FROM loadout_config l
                     LEFT JOIN type_loadout tl ON tl.loadout_id = l.id LEFT JOIN aircraft_type t ON t.id = tl.aircraft_type_id
                     GROUP BY l.id ORDER BY l.id""")


@router.get("/summary")
def summary(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    """Mission KPIs for the overview strip: values only (FR-CMD-04)."""
    cp = store.current_committed(db)
    rows = _q(db, """SELECT c.code AS command, m.priority, count(*) AS total,
                            count(*) FILTER (WHERE m.status IN ('TASKED','ACTIVE','COMPLETED')) AS covered
                     FROM mission m LEFT JOIN command c ON c.id = m.requesting_command_id
                     WHERE m.status <> 'CANCELLED' AND m.window_end > sim_now() AND m.window_start < sim_now() + interval '24 hours'
                     GROUP BY 1, 2""")
    open_d = db.execute(text("SELECT count(*) FROM disruption WHERE status IN ('OPEN','ASSESSED')")).scalar()
    pending = db.scalars(select(M.Plan).where(M.Plan.kind == "RETASK", M.Plan.status == "PROPOSED").order_by(M.Plan.id.desc())).first()
    return {"rows": rows, "committed_plan_id": cp.id if cp else None, "committed_at": cp.committed_at if cp else None,
            "open_disruptions": open_d, "pending_retask_id": pending.id if pending else None,
            "pending_retask_summary": pending.summary if pending else None, "simulated": True}
