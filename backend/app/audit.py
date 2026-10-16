"""Audit helper: one row per change, inside the caller's transaction (FR-INV-05, FR-SIM-09)."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from .models import AuditLog


def jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def diff(before: dict | None, after: dict | None) -> tuple[dict | None, dict | None]:
    """For updates keep only the changed fields."""
    if before is None or after is None:
        return jsonable(before), jsonable(after)
    keys = [k for k in after if before.get(k) != after.get(k)]
    return jsonable({k: before.get(k) for k in keys}), jsonable({k: after[k] for k in keys})


def audit(db: Session, user: dict | None, action: str, entity_type: str | None, entity_id: int | None,
          base_id: int | None, before: dict | None, after: dict | None, *, request_id: str | None = None,
          ip: str | None = None, actor_user=None) -> None:
    """user=None and actor_user=None means the simulator is the actor."""
    b, a = diff(before, after) if action in ("UPDATE", "SIM_TRANSITION") else (jsonable(before), jsonable(after))
    uid = (user or {}).get("id") or (actor_user.id if actor_user else None)
    role = (user or {}).get("role") or (actor_user.role if actor_user else None)
    db.add(AuditLog(actor_type="USER" if uid else "SIMULATOR", actor_user_id=uid, actor_role=role, action=action,
                    entity_type=entity_type, entity_id=entity_id, base_id=base_id, before=b, after=a,
                    request_id=request_id, ip=ip))
