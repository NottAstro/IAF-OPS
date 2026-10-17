"""Exercise control and after-action report (PHASE2_IMPLEMENTATION_PLAN §8). ADMIN acts as directing staff."""
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import models as M
from ..auth import current_user
from ..db import get_db
from ..decide import exercise as EX
from ..rbac import require

router = APIRouter(prefix="/ops/exercise", tags=["exercise"])


@router.get("/state")
def state(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    run = EX.current(db)
    st = db.get(M.SimState, 1)
    from .. import config
    return {"run": {"id": run.id, "name": run.name, "started_sim": run.started_sim, "injects": run.injects,
                    "kpi_timeline": run.kpi_timeline[-48:]} if run else None,
            "sim": {"enabled": config.SIM_ENABLED, "sim_now": st.sim_now, "speed": st.speed, "paused": st.paused,
                    "tick_no": st.tick_no} if st else None,
            "kinds": EX.KINDS,
            "scenarios": [{"id": s.id, "name": s.name, "description": s.description, "speed": s.speed, "injects": s.injects}
                          for s in db.scalars(select(M.Scenario).order_by(M.Scenario.id))],
            "runs": [dict(r) for r in db.execute(text("""SELECT id, name, status, started_sim, ended_sim FROM exercise_run
                                                         ORDER BY id DESC LIMIT 10""")).mappings()]}


class StartIn(BaseModel):
    scenario_id: int | None = None
    name: str | None = None
    speed: float | None = None


@router.post("/start")
def start(body: StartIn, user: dict = Depends(require("ADMIN")), db: Session = Depends(get_db)):
    if body.speed is not None and body.speed not in (1, 10, 60):
        raise HTTPException(422, "Speed must be 1, 10 or 60.")
    run = EX.start(db, user, body.scenario_id, body.name, body.speed)
    db.commit()
    return {"ok": True, "run_id": run.id}


@router.post("/stop")
def stop(user: dict = Depends(require("ADMIN")), db: Session = Depends(get_db)):
    EX.stop(db, user)
    db.commit()
    return {"ok": True}


class InjectIn(BaseModel):
    kind: str
    params: dict = {}
    label: str | None = None


@router.post("/inject")
async def inject(body: InjectIn, request: Request, user: dict = Depends(require("ADMIN")), db: Session = Depends(get_db)):
    if body.kind not in EX.KINDS:
        raise HTTPException(422, "Unknown inject")
    try:
        msg = EX.inject(db, user, body.kind, body.params, body.label, request.app.state.sim)
    except (ValueError, KeyError) as e:
        db.rollback()
        raise HTTPException(422, f"Check the inject: {e}")
    db.commit()
    from ..ws import hub
    await hub.broadcast("exercise.inject", {"kind": body.kind, "message": msg}, None)
    await hub.broadcast("entity.changed", {"types": ["aircraft", "runway", "fuel_storage", "radar_site", "mission"]}, None)
    return {"ok": True, "message": msg}


@router.get("/runs/{run_id}/aar")
def aar(run_id: int, user: dict = Depends(require("ADMIN", "COMMAND_HQ", "BASE_COMMANDER")), db: Session = Depends(get_db)):
    try:
        return EX.aar(db, run_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/runs/{run_id}/aar.csv")
def aar_csv(run_id: int, user: dict = Depends(require("ADMIN", "COMMAND_HQ", "BASE_COMMANDER")), db: Session = Depends(get_db)):
    try:
        a = EX.aar(db, run_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    buf = io.StringIO()
    buf.write("# SIMULATED DATA — SIH 2026 DEMO — NOT REAL\n")
    w = csv.writer(buf)
    w.writerow(["section", "sim_time_utc", "kind", "detail", "proposal_ms", "decision_s", "status"])
    for i in a["injects"]:
        w.writerow(["inject", i.get("applied_at"), i.get("kind"), i.get("result") or i.get("label"), "", "", ""])
    for d in a["disruptions"]:
        w.writerow(["disruption", d["ts"], d["kind"], d["message"], d["proposal_ms"], d["decision_s"], d["status"]])
    for m in a["missions"]:
        w.writerow(["mission", m["window_start"], m["priority"], f"{m['code']} {m['name']}", "", "", f"{m['status']} / {m['outcome']}"])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=aar-run-{run_id}.csv"})
