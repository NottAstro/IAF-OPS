"""Re-tasking monitor (PHASE2_IMPLEMENTATION_PLAN §7.4). Every MONITOR_S seconds while a plan is committed:
detect problems → store them as disruptions (deduplicated) → propose a re-task → raise alerts → tell the clients.

One mechanism for every source: simulator transitions, human edits, weather changes and exercise injects all show up
as rules the committed plan no longer meets. Proposal target: ≤ 15 s from the change (p95).
"""
import asyncio
import logging
import threading
import time

from sqlalchemy import select, text

from .. import models as M
from ..db import SessionLocal
from ..sim import alerts as alert_rules
from . import retask, store

log = logging.getLogger("decide.monitor")
MONITOR_S = 12
LOCK = threading.Lock()          # one solve at a time: planner, monitor and what-if share it


def check_once(user: dict | None = None, force: bool = False) -> dict:
    """-> {"disruptions": [...new], "proposal": {...} | None, "resolved": n}"""
    if not LOCK.acquire(blocking=force):
        return {"disruptions": [], "proposal": None, "resolved": 0, "busy": True}
    try:
        with SessionLocal() as db:
            det = retask.detect(db)
            if det is None:
                return {"disruptions": [], "proposal": None, "resolved": 0}
            keys = {k for k, *_ in det.issues}
            existing = {d.dedup_key: d for d in db.scalars(select(M.Disruption).where(M.Disruption.status.in_(("OPEN", "ASSESSED"))))}
            resolved = 0
            for k, d in existing.items():
                if k not in keys:
                    d.status, d.resolved_at = "RESOLVED", text("now()")
                    resolved += 1
            seen, new = set(existing), []
            for x in det.issues:                  # one disruption per key (launch + recovery of one runway = one)
                if x[0] not in seen:
                    seen.add(x[0])
                    new.append(x)
            now = db.execute(text("SELECT sim_now()")).scalar()
            rows = []
            for key, kind, msg, base_id, et, eid, mid in new:
                d = M.Disruption(ts=now, kind=kind, base_id=base_id, entity_type=et, entity_id=eid, message=msg,
                                 payload={"mission_id": mid}, dedup_key=key, status="OPEN")
                db.add(d)
                rows.append(d)
            db.flush()
            proposal = None
            if rows or (force and det.issues):
                t0 = time.perf_counter()
                proposal = retask.propose(db, det, user, [d.id for d in rows] or [existing[k].id for k in keys if k in existing])
                ms = int((time.perf_counter() - t0) * 1000)
                if proposal:
                    db.execute(text("""UPDATE plan SET status = 'SUPERSEDED' WHERE kind = 'RETASK' AND status = 'PROPOSED'
                                       AND id <> :p"""), {"p": proposal["plan_id"]})
                    for d in list(rows) + [existing[k] for k in keys if k in existing]:
                        d.status, d.proposal_plan_id, d.proposal_ms = "ASSESSED", proposal["plan_id"], ms
            _alerts(db)
            db.commit()
            return {"disruptions": [{"id": d.id, "kind": d.kind, "message": d.message, "base_id": d.base_id} for d in rows],
                    "proposal": proposal, "resolved": resolved}
    finally:
        LOCK.release()


def _alerts(db) -> list[dict]:
    """PLAN_AT_RISK per open disruption, RETASK_PROPOSED while a proposal waits for a decision."""
    desired = {}
    for d in db.scalars(select(M.Disruption).where(M.Disruption.status.in_(("OPEN", "ASSESSED")))):
        prio = db.execute(text("SELECT priority FROM mission WHERE id = :m"), {"m": (d.payload or {}).get("mission_id")}).scalar()
        desired[f"PLAN_AT_RISK:{d.dedup_key}"] = dict(
            kind="PLAN_AT_RISK", severity="CRITICAL" if prio == "P1" else "WARNING", entity_type="disruption",
            entity_id=d.id, base_id=d.base_id, command_id=None, message=f"Plan at risk: {d.message}", value=None, threshold=None)
    for p in db.scalars(select(M.Plan).where(M.Plan.kind == "RETASK", M.Plan.status == "PROPOSED")):
        desired[f"RETASK_PROPOSED:{p.id}"] = dict(
            kind="RETASK_PROPOSED", severity="WARNING", entity_type="plan", entity_id=p.id, base_id=None, command_id=None,
            message=f"Re-task proposal ready: {p.summary}", value=None, threshold=None)
    return alert_rules.reconcile(db, desired, {"PLAN_AT_RISK", "RETASK_PROPOSED"})


async def loop(hub) -> None:
    while True:
        await asyncio.sleep(MONITOR_S)
        try:
            out = await asyncio.to_thread(check_once)
        except Exception:
            log.exception("re-tasking monitor failed")
            continue
        if out.get("disruptions"):
            await hub.broadcast("disruption", out["disruptions"], None)
        if out.get("proposal"):
            await hub.broadcast("retask.proposal", out["proposal"], None)
            await hub.broadcast("alert", {"event": "raised", "severity": "WARNING", "kind": "RETASK_PROPOSED",
                                          "message": f"Re-task proposal ready: {out['proposal']['summary']}"}, None)
        if out.get("disruptions") or out.get("resolved"):
            await hub.broadcast("entity.changed", {"types": ["plan", "disruption"]}, None)
