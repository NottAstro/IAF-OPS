"""Simulator controls (FR-SIM-01) and human sortie planning (FR-INV-10)."""
import asyncio
import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from geoalchemy2.shape import from_shape, to_shape
from pydantic import BaseModel
from shapely.geometry import LineString
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import models as M
from ..audit import audit
from ..auth import current_user
from ..db import SessionLocal, get_db
from ..rbac import assert_edit_base, require
from ..sim.engine import family
from ..sim.routes import plan

router = APIRouter(tags=["simulator"])


def sim_now(db: Session) -> datetime:
    return db.scalar(text("SELECT sim_now()"))


@router.get("/sim/state")
def state(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    st = db.get(M.SimState, 1)
    if not st:
        raise HTTPException(404, "Simulator not seeded")
    return {"sim_now": st.sim_now, "speed": st.speed, "paused": st.paused, "tick_no": st.tick_no, "seed": st.seed}


class SpeedBody(BaseModel):
    speed: float


@router.post("/sim/{action}")
async def control(action: str, request: Request, body: SpeedBody | None = None, user: dict = Depends(require("ADMIN")),
                  db: Session = Depends(get_db)):
    sim = request.app.state.sim
    st = db.get(M.SimState, 1, with_for_update=True)
    before = {"speed": st.speed, "paused": st.paused}
    if action == "pause":
        st.paused = True
    elif action == "resume":
        st.paused = False
    elif action == "speed":
        if not body or body.speed not in (1, 10, 60):
            raise HTTPException(422, "Speed must be 1, 10 or 60.")
        st.speed = body.speed
    elif action == "step":
        db.commit()
        await sim.step(force=True)
        return {"ok": True}
    elif action == "reseed":
        st.paused = True
        db.commit()
        from generator.__main__ import main as generate
        async with sim.lock:
            await asyncio.to_thread(generate)
            sim.routes.clear()
            sim.unknowns.clear()
        with SessionLocal() as s2:
            audit(s2, user, "SIM_CONTROL", "sim_state", 1, None, None, {"action": "reseed"}, request_id=request.state.request_id)
            s2.commit()
        return {"ok": True, "reseeded": True}
    else:
        raise HTTPException(404, "Unknown action")
    audit(db, user, "SIM_CONTROL", "sim_state", 1, None, before, {"speed": st.speed, "paused": st.paused, "action": action},
          request_id=request.state.request_id)
    db.commit()
    return {"ok": True, "speed": st.speed, "paused": st.paused}


class SortieIn(BaseModel):
    departure_base_id: int
    destination_base_id: int | None = None
    mission_type: str = "TRAINING"
    priority: str = "P3"
    planned_launch_ts: datetime
    duration_h: float = 1.0
    aircraft_ids: list[int]
    aircrew_ids: list[int] = []
    mission_id: int | None = None


@router.post("/sorties", status_code=201)
def create_sortie(body: SortieIn, request: Request, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    assert_edit_base(user, body.departure_base_id)
    if body.mission_type not in M.MISSION_TYPES or body.mission_type in ("QRA_SCRAMBLE", "INTERCEPT"):
        raise HTTPException(422, {"message": "Choose a valid mission type.", "fields": {"mission_type": "Invalid"}})
    if body.priority not in ("P1", "P2", "P3", "P4"):
        raise HTTPException(422, {"message": "Priority must be P1–P4.", "fields": {"priority": "Invalid"}})
    if not body.aircraft_ids:
        raise HTTPException(422, {"message": "Pick at least one aircraft.", "fields": {"aircraft_ids": "Required"}})
    if not 0.2 <= body.duration_h <= 24:
        raise HTTPException(422, {"message": "Duration must be between 0.2 and 24 hours.", "fields": {"duration_h": "0.2–24 h"}})
    now = sim_now(db)
    launch = body.planned_launch_ts if body.planned_launch_ts.tzinfo else body.planned_launch_ts.replace(tzinfo=now.tzinfo)
    if launch < now + timedelta(minutes=20):
        raise HTTPException(422, {"message": "Launch must be at least 20 minutes after the current simulator time.",
                                  "fields": {"planned_launch_ts": "Too early"}})
    base = db.get(M.AirBase, body.departure_base_id)
    if not base or base.side != "OWN":
        raise HTTPException(422, "Sorties depart only from IAF bases.")
    busy = set(db.scalars(select(M.SortieAircraft.aircraft_id).join(M.Sortie, M.Sortie.id == M.SortieAircraft.sortie_id)
                          .where(M.Sortie.status.in_(("PLANNED", *M.ACTIVE_SORTIE)))))
    aircraft = []
    for aid in body.aircraft_ids:
        ac = db.get(M.Aircraft, aid)
        if not ac or ac.current_base_id != base.id or ac.status not in ("AVAILABLE", "STANDBY"):
            raise HTTPException(422, {"message": f"Aircraft {ac.tail_no if ac else aid} isn't serviceable at {base.code}.",
                                      "fields": {"aircraft_ids": "Pick available aircraft at the departure base"}})
        if ac.id in busy:
            raise HTTPException(409, f"{ac.tail_no} is already assigned to another sortie.")
        aircraft.append(ac)
    crew_busy = set(db.scalars(select(M.SortieCrew.aircrew_id).join(M.Sortie, M.Sortie.id == M.SortieCrew.sortie_id)
                               .where(M.Sortie.status.in_(("PLANNED", *M.ACTIVE_SORTIE)))))
    crew = []
    for cid in body.aircrew_ids:
        c = db.get(M.Aircrew, cid)
        if not c or c.base_id != base.id or c.medical_status not in ("FIT_FULL", "FIT_RESTRICTED") \
                or c.duty_status in ("LEAVE", "SICK", "AIRBORNE", "COURSE") or c.id in crew_busy:
            raise HTTPException(422, {"message": f"{(c.first_name + ' ' + c.last_name) if c else cid} isn't available to fly.",
                                      "fields": {"aircrew_ids": "Pick available aircrew at the departure base"}})
        crew.append(c)
    t = db.get(M.AircraftType, aircraft[0].aircraft_type_id)
    sim = request.app.state.sim
    if sim.G is None:
        from ..geo import load_india
        sim.G = load_india(db)
    home = (to_shape(base.geom).x, to_shape(base.geom).y)
    dest = None
    if body.destination_base_id:
        d = db.get(M.AirBase, body.destination_base_id)
        if not d or d.side != "OWN":
            raise HTTPException(422, "Destination must be an IAF base.")
        dest = (to_shape(d.geom).x, to_shape(d.geom).y)
        if not sim.G.route_ok([home, dest]):
            raise HTTPException(422, {"message": "That route would come within 25 km of the border.",
                                      "fields": {"destination_base_id": "Pick another destination"}})
    rng = random.Random(f"human:{base.id}:{launch.isoformat()}")
    pts, dur = plan(sim.G, rng, family(t), body.mission_type, home, dest, t.cruise_kt, body.duration_h)
    seq = db.execute(text("SELECT coalesce(max(id), 0) + 1 FROM sortie")).scalar()
    s = M.Sortie(code=f"SIM-{base.code}-U{seq:05d}", origin="HUMAN", mission_type=body.mission_type, priority=body.priority,
                 mission_id=body.mission_id, departure_base_id=base.id, recovery_base_id=base.id, status="PLANNED",
                 planned_launch_ts=launch, planned_recovery_ts=launch + timedelta(hours=dur),
                 route_geom=from_shape(LineString(pts), srid=4326), cruise_alt_m=7000 if family(t) == "fighter" else 3000,
                 fuel_planned_kg=round(t.burn_kg_per_h * dur * len(aircraft)), is_simulated=True)
    db.add(s)
    db.flush()
    for i, ac in enumerate(aircraft):
        db.add(M.SortieAircraft(sortie_id=s.id, aircraft_id=ac.id, callsign=f"{base.code}{i + 1}", formation_pos=i + 1))
    positions = {"PILOT": ["CAPTAIN", "CO_PILOT"], "WSO": ["WSO"], "NAVIGATOR": ["NAVIGATOR"],
                 "FLIGHT_ENGINEER": ["FLIGHT_ENGINEER"], "LOADMASTER": ["LOADMASTER"], "RPA_PILOT": ["RPA_PILOT"],
                 "PAYLOAD_OPERATOR": ["PAYLOAD_OPERATOR"], "FLIGHT_GUNNER": ["FLIGHT_GUNNER"]}
    used: dict[str, int] = {}
    for i, c in enumerate(crew):
        role = c.aircrew_role
        opts = positions.get(role, ["CO_PILOT"])
        pos = opts[min(used.get(role, 0), len(opts) - 1)]
        used[role] = used.get(role, 0) + 1
        db.add(M.SortieCrew(sortie_id=s.id, aircrew_id=c.id, aircraft_id=aircraft[min(i, len(aircraft) - 1)].id, position=pos))
    db.flush()
    audit(db, user, "CREATE", "sortie", s.id, base.id, None,
          {"code": s.code, "mission_type": s.mission_type, "priority": s.priority, "launch": launch,
           "aircraft": [a.tail_no for a in aircraft], "crew": [c.service_no for c in crew]},
          request_id=request.state.request_id)
    db.commit()
    return {"id": s.id, "code": s.code, "status": s.status, "planned_launch_ts": s.planned_launch_ts,
            "planned_recovery_ts": s.planned_recovery_ts, "route": [list(p) for p in pts]}


class SortiePatch(BaseModel):
    version: int
    planned_launch_ts: datetime | None = None
    priority: str | None = None


@router.patch("/sorties/{sid}")
def patch_sortie(sid: int, body: SortiePatch, request: Request, user: dict = Depends(current_user),
                 db: Session = Depends(get_db)):
    s = db.get(M.Sortie, sid, with_for_update=True)
    if not s:
        raise HTTPException(404, "Sortie not found")
    assert_edit_base(user, s.departure_base_id)
    if s.status != "PLANNED":
        raise HTTPException(409, "Only planned sorties can be changed.")
    if body.version != s.version:
        raise HTTPException(409, "This sortie was changed by the simulator or another user. Reload it.")
    before = {"planned_launch_ts": s.planned_launch_ts, "priority": s.priority}
    if body.planned_launch_ts:
        if body.planned_launch_ts < sim_now(db) + timedelta(minutes=20):
            raise HTTPException(422, "Launch must be at least 20 minutes after the current simulator time.")
        dur = s.planned_recovery_ts - s.planned_launch_ts
        s.planned_launch_ts, s.planned_recovery_ts = body.planned_launch_ts, body.planned_launch_ts + dur
    if body.priority:
        s.priority = body.priority
    s.version += 1
    audit(db, user, "UPDATE", "sortie", s.id, s.departure_base_id, before,
          {"planned_launch_ts": s.planned_launch_ts, "priority": s.priority}, request_id=request.state.request_id)
    db.commit()
    return {"ok": True, "version": s.version}


@router.post("/sorties/{sid}/cancel")
def cancel_sortie(sid: int, request: Request, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(M.Sortie, sid, with_for_update=True)
    if not s:
        raise HTTPException(404, "Sortie not found")
    assert_edit_base(user, s.departure_base_id)
    if s.status not in ("PLANNED", "CREWED", "READY"):
        raise HTTPException(409, "Airborne or finished sorties can't be cancelled.")
    before = {"status": s.status}
    s.status, s.cancel_reason = "CANCELLED", "USER_CANCELLED"
    s.version += 1
    for c in db.scalars(select(M.Aircrew).join(M.SortieCrew, M.SortieCrew.aircrew_id == M.Aircrew.id)
                        .where(M.SortieCrew.sortie_id == s.id, M.Aircrew.duty_status == "BRIEFED")):
        c.duty_status = "ON_DUTY"
    audit(db, user, "UPDATE", "sortie", s.id, s.departure_base_id, before, {"status": "CANCELLED"},
          request_id=request.state.request_id)
    db.commit()
    return {"ok": True}


@router.get("/sorties/{sid}/detail")
def sortie_detail(sid: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    r = db.execute(text("""SELECT s.*, ST_AsGeoJSON(s.route_geom, 5)::json -> 'coordinates' AS route, d.code AS departure,
                                  m.name AS mission_name
                           FROM sortie s JOIN base d ON d.id = s.departure_base_id LEFT JOIN mission m ON m.id = s.mission_id
                           WHERE s.id = :id"""), {"id": sid}).mappings().first()
    if not r:
        raise HTTPException(404, "Sortie not found")
    out = {k: v for k, v in r.items() if k not in ("route_geom", "orbit_geom")}
    out["aircraft"] = [dict(x._mapping) for x in db.execute(text(
        """SELECT a.id, a.tail_no, t.name AS type, sa.callsign FROM sortie_aircraft sa JOIN aircraft a ON a.id = sa.aircraft_id
           JOIN aircraft_type t ON t.id = a.aircraft_type_id WHERE sa.sortie_id = :id"""), {"id": sid})]
    out["crew"] = [dict(x._mapping) for x in db.execute(text(
        """SELECT c.id, c.rank, c.first_name, c.last_name, c.callsign, sc.position, sc.hours_logged
           FROM sortie_crew sc JOIN aircrew c ON c.id = sc.aircrew_id WHERE sc.sortie_id = :id"""), {"id": sid})]
    return out
