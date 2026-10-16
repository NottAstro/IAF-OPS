"""Pilot / aircrew profiles (FR-PIL), users admin (FR-AUTH-06), search (FR-MAP-10)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..audit import audit
from ..auth import current_user, user_dict
from ..db import get_db
from ..models import ROLES, AppUser
from ..rbac import require
from ..security import hash_password

router = APIRouter(tags=["people"])


def rows(db, sql, **p):
    return [dict(r._mapping) for r in db.execute(text(sql), p)]


@router.get("/aircrew/{crew_id}/profile")
def profile(crew_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    head = rows(db, """SELECT c.*, s.number AS squadron, b.code AS base_code, b.name AS base_name, t.name AS current_type,
                              f.sorties_24h, f.hours_24h, f.hours_7d, f.hours_30d, f.rest_hours, f.fatigued,
                              v.available
                       FROM aircrew c LEFT JOIN squadron s ON s.id = c.squadron_id JOIN base b ON b.id = c.base_id
                       LEFT JOIN aircraft_type t ON t.id = s.aircraft_type_id
                       LEFT JOIN v_aircrew_fatigue f ON f.aircrew_id = c.id
                       LEFT JOIN v_aircrew_availability v ON v.aircrew_id = c.id WHERE c.id = :id""", id=crew_id)
    if not head:
        raise HTTPException(404, "Aircrew not found")
    p = {"id": crew_id}
    return {
        "person": {**head[0], "simulated": True},
        "type_hours": rows(db, """SELECT t.name AS type, t.category, h.hours, h.captain_hours, h.night_hours, h.instrument_hours,
                                         h.last_flown_at, cur.currency, cur.expires_at, cur.window_days
                                  FROM aircrew_type_hours h JOIN aircraft_type t ON t.id = h.aircraft_type_id
                                  LEFT JOIN v_aircrew_currency cur ON cur.aircrew_id = h.aircrew_id AND cur.aircraft_type_id = h.aircraft_type_id
                                  WHERE h.aircrew_id = :id ORDER BY h.last_flown_at DESC NULLS LAST""", **p),
        "recent_hours": rows(db, """SELECT
              coalesce(sum(sc.hours_logged) FILTER (WHERE s.actual_launch_ts > sim_now() - interval '30 days'), 0) AS d30,
              coalesce(sum(sc.hours_logged) FILTER (WHERE s.actual_launch_ts > sim_now() - interval '90 days'), 0) AS d90,
              coalesce(sum(sc.hours_logged) FILTER (WHERE s.actual_launch_ts > sim_now() - interval '365 days'), 0) AS d365,
              count(*) FILTER (WHERE s.actual_launch_ts > sim_now() - interval '30 days') AS sorties_30d
            FROM sortie_crew sc JOIN sortie s ON s.id = sc.sortie_id WHERE sc.aircrew_id = :id""", **p)[0],
        "qualifications": rows(db, """SELECT q.code, q.awarded_on, q.expires_on, t.name AS type FROM aircrew_qualification q
                                      LEFT JOIN aircraft_type t ON t.id = q.aircraft_type_id WHERE q.aircrew_id = :id
                                      ORDER BY q.code""", **p),
        "postings": rows(db, """SELECT p.from_date, p.to_date, p.appointment, b.code AS base_code, b.name AS base_name,
                                       s.number AS squadron, t.name AS type
                                FROM aircrew_posting p LEFT JOIN base b ON b.id = p.base_id
                                LEFT JOIN squadron s ON s.id = p.squadron_id LEFT JOIN aircraft_type t ON t.id = p.aircraft_type_id
                                WHERE p.aircrew_id = :id ORDER BY p.from_date""", **p),
    }


@router.get("/aircrew/{crew_id}/sorties")
def crew_sorties(crew_id: int, page: int = 1, page_size: int = 25, user: dict = Depends(current_user),
                 db: Session = Depends(get_db)):
    page_size = min(max(page_size, 1), 100)
    items = rows(db, """SELECT s.code, s.mission_type, s.status, s.actual_launch_ts, s.actual_recovery_ts, sc.position,
                               sc.hours_logged, sc.night_hours, a.tail_no, t.name AS type, b.code AS base
                        FROM sortie_crew sc JOIN sortie s ON s.id = sc.sortie_id JOIN aircraft a ON a.id = sc.aircraft_id
                        JOIN aircraft_type t ON t.id = a.aircraft_type_id JOIN base b ON b.id = s.departure_base_id
                        WHERE sc.aircrew_id = :id ORDER BY s.actual_launch_ts DESC NULLS LAST LIMIT :lim OFFSET :off""",
                 id=crew_id, lim=page_size, off=(max(page, 1) - 1) * page_size)
    total = db.execute(text("SELECT count(*) FROM sortie_crew WHERE aircrew_id = :id"), {"id": crew_id}).scalar()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/search")
def search(q: str, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    q = q.strip()
    if len(q) < 2:
        return []
    like = f"%{q}%"
    out = rows(db, """SELECT 'base' AS kind, id, code AS title, name AS subtitle, ST_Y(geom) lat, ST_X(geom) lon, side
                      FROM base WHERE code ILIKE :like OR name ILIKE :like ORDER BY side, code LIMIT 8""", like=like)
    out += rows(db, """SELECT 'aircraft' AS kind, a.id, a.tail_no AS title, t.name || ' · ' || b.code AS subtitle,
                              ST_Y(b.geom) lat, ST_X(b.geom) lon, b.id AS base_id
                       FROM aircraft a JOIN aircraft_type t ON t.id = a.aircraft_type_id JOIN base b ON b.id = a.home_base_id
                       WHERE a.tail_no ILIKE :like LIMIT 6""", like=like)
    out += rows(db, """SELECT 'aircrew' AS kind, c.id, c.first_name || ' ' || c.last_name AS title,
                              replace(c.rank, '_', ' ') || ' · ' || b.code AS subtitle, ST_Y(b.geom) lat, ST_X(b.geom) lon
                       FROM aircrew c JOIN base b ON b.id = c.base_id
                       WHERE c.first_name || ' ' || c.last_name ILIKE :like OR c.service_no ILIKE :like OR c.callsign ILIKE :like
                       LIMIT 6""", like=like)
    return out


class NewUser(BaseModel):
    username: str
    display_name: str
    password: str
    role: str
    base_id: int | None = None
    command_id: int | None = None


@router.get("/users")
def users(user: dict = Depends(require("ADMIN")), db: Session = Depends(get_db)):
    return rows(db, """SELECT u.id, u.username, u.display_name, u.role, u.is_active, u.last_login_at, u.locked_until,
                              b.code AS base_code, c.code AS command_code, u.base_id, u.command_id
                       FROM app_user u LEFT JOIN base b ON b.id = u.base_id LEFT JOIN command c ON c.id = u.command_id
                       ORDER BY u.role, u.username""")


@router.post("/users", status_code=201)
def create_user(body: NewUser, request: Request, user: dict = Depends(require("ADMIN")), db: Session = Depends(get_db)):
    if body.role not in ROLES:
        raise HTTPException(422, "Unknown role")
    if body.role == "BASE_COMMANDER" and not body.base_id:
        raise HTTPException(422, "A Base Commander needs a base.")
    if len(body.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters.")
    u = AppUser(username=body.username.strip().lower(), display_name=body.display_name, role=body.role,
                password_hash=hash_password(body.password), base_id=body.base_id, command_id=body.command_id,
                is_simulated=False)
    db.add(u)
    db.flush()
    audit(db, user, "USER_ADMIN", "app_user", u.id, None, None, {"username": u.username, "role": u.role},
          request_id=request.state.request_id)
    db.commit()
    return user_dict(u, db)


class UserPatch(BaseModel):
    is_active: bool | None = None
    password: str | None = None
    role: str | None = None
    base_id: int | None = None
    command_id: int | None = None


@router.patch("/users/{uid}")
def patch_user(uid: int, body: UserPatch, request: Request, user: dict = Depends(require("ADMIN")),
               db: Session = Depends(get_db)):
    u = db.get(AppUser, uid)
    if not u:
        raise HTTPException(404, "User not found")
    before = {"is_active": u.is_active, "role": u.role, "base_id": u.base_id, "command_id": u.command_id}
    for k in ("is_active", "role", "base_id", "command_id"):
        v = getattr(body, k)
        if v is not None:
            setattr(u, k, v)
    if body.password:
        u.password_hash, u.failed_logins, u.locked_until = hash_password(body.password), 0, None
    after = {"is_active": u.is_active, "role": u.role, "base_id": u.base_id, "command_id": u.command_id,
             "password_reset": bool(body.password)}
    audit(db, user, "USER_ADMIN", "app_user", u.id, None, before, after, request_id=request.state.request_id)
    db.commit()
    return user_dict(u, db)
