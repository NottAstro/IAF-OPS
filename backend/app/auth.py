"""Login, JWT session cookie, current-user dependency (FR-AUTH-01..05, 07, 08)."""
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .audit import audit
from .db import get_db
from .models import AppUser, Command
from .security import verify_password

COOKIE = "airops_session"
LOCK_AFTER, LOCK_MINUTES = 5, 15
router = APIRouter(prefix="/auth", tags=["auth"])


def user_dict(u: AppUser, db: Session) -> dict:
    from .models import AirBase
    base = db.get(AirBase, u.base_id) if u.base_id else None
    cmd = db.get(Command, u.command_id) if u.command_id else None
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role,
            "base_id": u.base_id, "base_code": base.code if base else None, "base_name": base.name if base else None,
            "command_id": u.command_id, "command_code": cmd.code if cmd else None}


def decode(token: str | None) -> int | None:
    if not token:
        return None
    try:
        return int(jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def current_user(request: Request, db: Session = Depends(get_db)) -> dict:
    uid = decode(request.cookies.get(COOKIE))
    u = db.get(AppUser, uid) if uid else None
    if not u or not u.is_active:
        raise HTTPException(401, "Not signed in")
    return user_dict(u, db)


class Login(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    u = db.scalar(select(AppUser).where(AppUser.username == body.username.strip().lower()))
    now = datetime.now(timezone.utc)
    ip = request.client.host if request.client else None
    if u and u.locked_until and u.locked_until > now:
        raise HTTPException(423, f"Account locked after {LOCK_AFTER} failed attempts. Try again after "
                                 f"{u.locked_until.astimezone(timezone(timedelta(hours=5, minutes=30))):%H:%M} IST.")
    if not u or not u.is_active or not verify_password(u.password_hash, body.password):
        if u:
            u.failed_logins += 1
            if u.failed_logins >= LOCK_AFTER:
                u.locked_until, u.failed_logins = now + timedelta(minutes=LOCK_MINUTES), 0
            audit(db, None, "LOGIN_FAILED", "app_user", u.id, None, None, {"username": u.username}, ip=ip, actor_user=u)
            db.commit()
        raise HTTPException(401, "Username or password is incorrect.")
    u.failed_logins, u.locked_until, u.last_login_at = 0, None, now
    audit(db, None, "LOGIN", "app_user", u.id, None, None, None, ip=ip, actor_user=u)
    db.commit()
    token = jwt.encode({"sub": str(u.id), "role": u.role, "exp": now + timedelta(hours=config.JWT_TTL_HOURS)},
                       config.JWT_SECRET, algorithm="HS256")
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=config.JWT_TTL_HOURS * 3600)
    return user_dict(u, db)


@router.post("/logout")
def logout(response: Response, request: Request, db: Session = Depends(get_db)):
    uid = decode(request.cookies.get(COOKIE))
    if uid and (u := db.get(AppUser, uid)):
        audit(db, None, "LOGOUT", "app_user", u.id, None, None, None, actor_user=u)
        db.commit()
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return user
