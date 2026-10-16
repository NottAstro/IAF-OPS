"""Alerts + audit log (FR-ALR)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..audit import audit
from ..auth import current_user
from ..db import get_db
from ..models import Alert
from ..rbac import can_ack, require

router = APIRouter(tags=["alerts"])


@router.get("/alerts")
def alerts(status: str = "OPEN,ACKNOWLEDGED", severity: str = "", kind: str = "", command: str = "", base_id: int | None = None,
           limit: int = 200, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    where, p = ["a.status = ANY(:st)"], {"st": status.split(","), "lim": min(limit, 500)}
    if severity:
        where.append("a.severity = ANY(:sev)")
        p["sev"] = severity.split(",")
    if kind:
        where.append("a.kind = ANY(:kind)")
        p["kind"] = kind.split(",")
    if command:
        where.append("c.code = :cmd")
        p["cmd"] = command
    if base_id:
        where.append("a.base_id = :bid")
        p["bid"] = base_id
    items = [dict(r._mapping) for r in db.execute(text(f"""
        SELECT a.*, b.code AS base_code, b.name AS base_name, c.code AS command_code, u.username AS ack_by_name
        FROM alert a LEFT JOIN base b ON b.id = a.base_id LEFT JOIN command c ON c.id = a.command_id
        LEFT JOIN app_user u ON u.id = a.ack_by
        WHERE {' AND '.join(where)}
        ORDER BY CASE a.severity WHEN 'CRITICAL' THEN 0 WHEN 'WARNING' THEN 1 WHEN 'CAUTION' THEN 2 ELSE 3 END, a.raised_at DESC
        LIMIT :lim"""), p)]
    for it in items:
        it["can_ack"] = it["status"] == "OPEN" and can_ack(user, it["base_id"], it["command_id"])
    counts = dict(db.execute(text("SELECT severity, count(*) FROM alert WHERE status = 'OPEN' GROUP BY 1")).all())
    return {"items": items, "open_counts": counts}


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: int, request: Request, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id, with_for_update=True)
    if not a:
        raise HTTPException(404, "Alert not found")
    if not can_ack(user, a.base_id, a.command_id):
        raise HTTPException(403, "You can't acknowledge this alert.")
    if a.status != "OPEN":
        return {"ok": True, "status": a.status}
    a.status, a.ack_by, a.ack_at = "ACKNOWLEDGED", user["id"], datetime.now(timezone.utc)
    audit(db, user, "ALERT_ACK", "alert", a.id, a.base_id, {"status": "OPEN"}, {"status": "ACKNOWLEDGED"},
          request_id=request.state.request_id)
    db.commit()
    return {"ok": True, "status": a.status}


@router.get("/audit")
def audit_log(actor: str = "", entity: str = "", action: str = "", base_id: int | None = None, page: int = 1,
              page_size: int = 50, user: dict = Depends(require("ADMIN", "COMMAND_HQ", "BASE_COMMANDER")),
              db: Session = Depends(get_db)):
    where, p = ["true"], {"lim": min(max(page_size, 1), 200)}
    p["off"] = (max(page, 1) - 1) * p["lim"]
    if user["role"] == "BASE_COMMANDER":  # proposed default: own base only (PRD §4.2)
        where.append("l.base_id = :own")
        p["own"] = user["base_id"]
    if actor == "SIMULATOR":
        where.append("l.actor_type = 'SIMULATOR'")
    elif actor == "USER":
        where.append("l.actor_type = 'USER'")
    elif actor:
        where.append("u.username = :actor")
        p["actor"] = actor
    if entity:
        where.append("l.entity_type = :entity")
        p["entity"] = entity
    if action:
        where.append("l.action = :action")
        p["action"] = action
    if base_id:
        where.append("l.base_id = :bid")
        p["bid"] = base_id
    sql = f"""FROM audit_log l LEFT JOIN app_user u ON u.id = l.actor_user_id LEFT JOIN base b ON b.id = l.base_id
              WHERE {' AND '.join(where)}"""
    items = [dict(r._mapping) for r in db.execute(text(
        f"SELECT l.*, u.username AS actor_name, b.code AS base_code {sql} ORDER BY l.id DESC LIMIT :lim OFFSET :off"), p)]
    total = db.execute(text(f"SELECT count(*) {sql}"), p).scalar()
    return {"items": items, "total": total, "page": page, "page_size": p["lim"]}
