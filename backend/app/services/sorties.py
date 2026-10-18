"""Sortie creation and weapons reservation, shared by the human sortie route and plan commit (one place for the
rules, PHASE2_IMPLEMENTATION_PLAN §9)."""
from datetime import datetime

from geoalchemy2.shape import from_shape
from shapely.geometry import LineString
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from generator import config as GC

from .. import models as M
from ..audit import audit

CRUISE_ALT = {"fighter": 7500, "transport": 7500, "helo": 1500, "uav": 5500, "uas": 120, "trainer": 3000}
CALLSIGNS = ["VAJRA", "GARUDA", "TEJAS", "AGNI", "VAYU", "MEGH", "NEEL", "SHER", "BAAZ", "TOOFAN", "KIRAN", "TRISHUL"]


def next_code(db: Session, base_code: str, tag: str) -> str:
    seq = db.execute(text("SELECT coalesce(max(id), 0) + 1 FROM sortie")).scalar()
    return f"SIM-{base_code}-{tag}{seq:05d}"


def create(db: Session, *, user: dict | None, origin: str, mission_type: str, priority: str, base: M.AirBase,
           recovery_base_id: int, launch: datetime, recovery: datetime, route: list, aircraft: list[M.Aircraft],
           crew: list[tuple[int, int, str]], fuel_kg: float, family: str, mission_id: int | None = None,
           loadout_code: str | None = None, plan_item_id: int | None = None, tag: str = "U",
           request_id: str | None = None) -> M.Sortie:
    s = M.Sortie(code=next_code(db, base.code, tag), origin=origin, mission_type=mission_type, priority=priority,
                 mission_id=mission_id, departure_base_id=base.id, recovery_base_id=recovery_base_id, status="PLANNED",
                 planned_launch_ts=launch, planned_recovery_ts=recovery,
                 route_geom=from_shape(LineString(route), srid=4326) if len(route) > 1 else None,
                 cruise_alt_m=CRUISE_ALT.get(family, 3000), fuel_planned_kg=round(fuel_kg), loadout_code=loadout_code,
                 plan_item_id=plan_item_id, is_simulated=True)
    db.add(s)
    db.flush()
    word = CALLSIGNS[s.id % len(CALLSIGNS)]
    for i, ac in enumerate(aircraft):
        db.add(M.SortieAircraft(sortie_id=s.id, aircraft_id=ac.id, callsign=f"{word}{(s.id % 90) + 10}{i + 1}",
                                formation_pos=i + 1))
    for cid, aid, pos in crew:
        db.add(M.SortieCrew(sortie_id=s.id, aircrew_id=cid, aircraft_id=aid, position=pos))
    db.flush()
    audit(db, user, "CREATE", "sortie", s.id, base.id, None,
          {"code": s.code, "origin": origin, "mission_type": mission_type, "priority": priority, "launch": launch,
           "aircraft": [a.tail_no for a in aircraft], "crew": [c for c, _, _ in crew], "plan_item_id": plan_item_id},
          request_id=request_id)
    return s


def sortie_weapons(db: Session, s: M.Sortie) -> dict:
    """Generic armament a sortie carries: its loadout's items × aircraft."""
    if not s.loadout_code:
        return {}
    items = db.scalar(select(M.LoadoutConfig.items).where(M.LoadoutConfig.code == s.loadout_code)) or {}
    n = db.scalar(select(func.count()).select_from(M.SortieAircraft).where(M.SortieAircraft.sortie_id == s.id)) or 0
    return {k: v * n for k, v in items.items()}


def adjust_stock(db: Session, base_id: int, weapons: dict, reserve: float = 0, consume: float = 0) -> None:
    """reserve > 0 reserves, < 0 releases; consume > 0 takes stock off the shelf (and the matching reservation)."""
    for cat, qty in weapons.items():
        left = qty
        rows = db.execute(text("""SELECT l.id, l.qty_on_hand, l.qty_reserved FROM stock_level l
                                  JOIN stock_item i ON i.id = l.stock_item_id JOIN warehouse w ON w.id = l.warehouse_id
                                  WHERE w.base_id = :b AND i.category = :c ORDER BY l.id"""), {"b": base_id, "c": cat}).all()
        for r in rows:
            if left <= 0:
                break
            if reserve > 0:
                take = min(left, max(0.0, r.qty_on_hand - r.qty_reserved)) if r is not rows[-1] else left
                db.execute(text("UPDATE stock_level SET qty_reserved = qty_reserved + :q, version = version + 1 WHERE id = :id"),
                           {"q": take, "id": r.id})
            elif reserve < 0:
                take = min(left, r.qty_reserved)
                db.execute(text("UPDATE stock_level SET qty_reserved = qty_reserved - :q, version = version + 1 WHERE id = :id"),
                           {"q": take, "id": r.id})
            else:
                take = min(left, r.qty_on_hand)
                db.execute(text("""UPDATE stock_level SET qty_on_hand = qty_on_hand - :q,
                                   qty_reserved = greatest(0, qty_reserved - :q), version = version + 1 WHERE id = :id"""),
                           {"q": take, "id": r.id})
            left -= take


def family_of(t: M.AircraftType) -> str:
    return GC.ROLE_FAMILY[t.role][0]
