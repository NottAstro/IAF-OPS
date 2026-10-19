"""Inventory transfers (ARCHITECTURE D56): recommended moves of fuel, weapons and spares between bases, approving them,
and the Ops map lines. Logic lives in decide/logistics.py (recommend) and services/transfers.py (write)."""
import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..decide import logistics as LG
from ..decide import scenarios as SV
from ..decide import store
from ..rbac import require
from ..services import transfers as TR

router = APIRouter(prefix="/ops/transfers", tags=["transfers"])
PLANNERS = ("ADMIN", "COMMAND_HQ")


def _recommended(db: Session) -> dict:
    plan = store.under_review(db)
    return LG.recommend(db, SV.snapshot(db), plan.id if plan is not None else None, SV.scenario_bases(db, plan))


@router.get("")
def transfers(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return {"recommended": _recommended(db), "items": [dict(r) for r in db.execute(text(
        """SELECT t.id, t.kind, t.category, t.qty, t.unit, t.status, t.eta, t.depart_ts, t.delivered_at, t.distance_km, t.reason,
                  fb.code AS from_code, tb.code AS to_code FROM inventory_transfer t
           JOIN base fb ON fb.id = t.from_base_id JOIN base tb ON tb.id = t.to_base_id ORDER BY t.id DESC LIMIT 50""")).mappings()],
            "simulated": True}


@router.get("/geo")
def transfers_geo(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    """Ops map: convoys on the road (solid) and recommended moves (dashed), base to base."""
    pts = {r.id: (r.lon, r.lat) for r in db.execute(text("SELECT id, ST_X(geom) lon, ST_Y(geom) lat FROM base WHERE side = 'OWN'"))}
    feats = []
    for r in db.execute(text("""SELECT id, kind, category, qty, unit, from_base_id, to_base_id, eta FROM inventory_transfer
                                WHERE status = 'IN_TRANSIT'""")):
        feats.append(_line(pts, r.from_base_id, r.to_base_id, {"id": r.id, "state": "in_transit", "label": _qty(r.kind, r.qty, r.unit, r.category),
                                                                "eta": r.eta.isoformat()}))
    for m in _recommended(db)["moves"]:
        feats.append(_line(pts, m["from_base"]["id"], m["to_base"]["id"], {"id": m["key"], "state": "recommended",
                                                                          "label": _qty(m["kind"], m["qty"], m["unit"], m["category"])}))
    return {"type": "FeatureCollection", "features": [f for f in feats if f]}


def _qty(kind: str, qty: float, unit: str, cat: str) -> str:
    return f"{qty / 1000:.0f} kL ATF" if kind == "FUEL" else f"{qty:.0f} {LG.label(cat).lower()}"


def _line(pts: dict, a: int, b: int, props: dict) -> dict | None:
    if a not in pts or b not in pts:
        return None
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [list(pts[a]), list(pts[b])]}, "properties": props}


class MoveIn(BaseModel):
    kind: str
    category: str
    qty: float = Field(gt=0)
    from_base_id: int
    to_base_id: int
    needed_by: datetime | None = None
    reason: str | None = None


class ApproveIn(BaseModel):
    moves: list[MoveIn] = Field(min_length=1, max_length=50)
    run_id: int | None = None


@router.post("")
async def approve(body: ApproveIn, request: Request, user: dict = Depends(require(*PLANNERS)), db: Session = Depends(get_db)):
    plan = store.under_review(db)
    made = []
    try:
        for m in body.moves:
            t = TR.approve(db, user, m.kind, m.category, m.qty, m.from_base_id, m.to_base_id, m.needed_by, m.reason,
                           plan.id if plan is not None else None, body.run_id, request.state.request_id)
            made.append({"id": t.id, "eta": t.eta})
    except TR.TransferError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    db.commit()
    SV.invalidate_snapshot()             # the planner must count the stock now on the road
    from ..ws import hub
    await hub.broadcast("entity.changed", {"types": ["transfer", "fuel_storage", "stock_level"]}, None)
    from .scenarios import _check_now
    asyncio.get_running_loop().create_task(_check_now(user, "Re-planned after inventory transfers were approved"))   # what was short may now be flyable
    return {"ok": True, "transfers": made}
