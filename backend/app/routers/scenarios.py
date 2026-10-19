"""Scenarios (ARCHITECTURE D55, D56): the library, starting and ending runs (directing staff: ADMIN or Air HQ), the live list and each
run's response for the Planner. Logic lives in decide/exercise.py and decide/scenarios.py."""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as M
from ..auth import current_user
from ..db import get_db
from ..decide import exercise as EX
from ..decide import scenarios as SV
from ..decide import store
from ..rbac import require

router = APIRouter(prefix="/ops/scenarios", tags=["scenarios"])
RUNS = ("ADMIN", "COMMAND_HQ")      # who may start and end scenarios: directing staff and Air HQ (one-operator demos)
log = logging.getLogger("scenarios")


@router.get("")
def catalogue(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return SV.catalogue(db)


@router.get("/live")
def live(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return SV.live(db)


@router.get("/situation")
def situation(run: int | None = None, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    """D56: the Planner's one screen for the current situation (all live scenarios, or one)."""
    return SV.situation(db, run)


@router.get("/effects/geo")
def effects_geo(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return SV.effects_geo(db)


@router.get("/runs/{run_id}/response")
def response(run_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    try:
        return SV.response(db, run_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


class StartIn(BaseModel):
    params: dict = {}
    intensity: str | None = None


async def _check_now(user: dict | None = None, why: str | None = None) -> None:
    """Answer the new situation straight away (D56): with nothing committed, plan it from scratch (replacing a full plan
    still waiting for a decision, D59, so it never misses a scenario that started or ended after it was made); else run
    one re-tasking check so the re-task proposal shows without waiting for the next cycle."""
    from ..db import SessionLocal
    from ..decide import monitor
    from ..ws import hub

    def work():
        with SessionLocal() as db:
            in_force = store.current_committed(db) is not None
        if not in_force and user is not None:
            if not monitor.LOCK.acquire(timeout=60):
                return {}
            try:
                out = store.generate_plan(user, why=why)          # replaces a full plan still waiting
            finally:
                monitor.LOCK.release()
            return {"plan": out}
        return monitor.check_once()
    try:
        out = await asyncio.to_thread(work)
    except Exception:
        log.exception("scenario: planning the new situation failed")
        return
    if out.get("plan"):
        await hub.broadcast("plan.ready", {"plan_id": out["plan"]["plan_id"], "kpis": out["plan"]["kpis"]}, None)
    if out.get("proposal"):
        await hub.broadcast("retask.proposal", out["proposal"], None)
    await hub.broadcast("entity.changed", {"types": ["plan", "disruption", "scenario", "mission"]}, None)


@router.post("/{code}/start")
async def start(code: str, body: StartIn, request: Request, user: dict = Depends(require(*RUNS)), db: Session = Depends(get_db)):
    sc = db.scalars(select(M.Scenario).where(M.Scenario.code == code)).first()
    if not sc:
        raise HTTPException(404, "Scenario not found")
    before = SV.snapshot(db).clone()           # D62: the world just before the scenario, for its impact assessment
    try:
        run = EX.start(db, user, sc.id, None, None, body.params, body.intensity)
        EX.apply_due(db, run, EX.sim_now(db), getattr(request.app.state, "sim", None))
    except ValueError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    db.commit()
    from ..ws import hub
    await hub.broadcast("exercise.inject", {"kind": "SCENARIO", "message": f"{sc.name} started"}, None)
    await hub.broadcast("entity.changed", {"types": ["aircraft", "runway", "fuel_storage", "radar_site", "mission", "scenario"]}, None)
    asyncio.get_running_loop().create_task(_answer_and_assess(user, run.id, run.name, before))
    return {"ok": True, "run_id": run.id}


async def _answer_and_assess(user: dict, run_id: int, name: str, before) -> None:
    """The planner answers the new situation first; then the scenario's impact is assessed (before vs with, D62)."""
    from ..db import SessionLocal
    from ..decide import impact as IM
    from ..decide import monitor
    from ..ws import hub
    await _check_now(user, f"Made when {name} started")

    def work():
        if not monitor.LOCK.acquire(timeout=120):
            return
        try:
            with SessionLocal() as db:
                IM.save(db, run_id, before)
                db.commit()
        finally:
            monitor.LOCK.release()
    try:
        await asyncio.to_thread(work)
    except Exception:
        log.exception("scenario: impact assessment failed")
        return
    await hub.broadcast("entity.changed", {"types": ["scenario"]}, None)


@router.post("/runs/{run_id}/end")
async def end(run_id: int, user: dict = Depends(require(*RUNS)), db: Session = Depends(get_db)):
    run = db.get(M.ExerciseRun, run_id)
    try:
        EX.stop(db, user, run_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    name = run.name if run is not None else "the scenario"
    db.commit()
    from ..ws import hub
    await hub.broadcast("entity.changed", {"types": ["scenario", "mission", "sortie"]}, None)
    asyncio.get_running_loop().create_task(_check_now(user, f"Made when {name} ended"))   # the withdrawn missions free their resources
    return {"ok": True}
