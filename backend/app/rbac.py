"""Role checks (PRD §4.2). The server is authoritative; the UI only hides what it can't do."""
from fastapi import Depends, HTTPException

from .auth import current_user


def require(*roles: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, "Your role can't do this.")
        return user
    return dep


def can_edit_base(user: dict, base_id: int | None) -> bool:
    """Inventory create/update/delete: Admin anywhere, Base Commander only at their own base."""
    if user["role"] == "ADMIN":
        return True
    return user["role"] == "BASE_COMMANDER" and base_id is not None and base_id == user["base_id"]


def assert_edit_base(user: dict, base_id: int | None) -> None:
    if not can_edit_base(user, base_id):
        raise HTTPException(403, "You can only change records at your own base." if user["role"] == "BASE_COMMANDER"
                            else "Your role can't change inventory.")


def can_ack(user: dict, alert_base_id: int | None, alert_command_id: int | None) -> bool:
    role = user["role"]
    if role == "ADMIN":
        return True
    if role == "COMMAND_HQ":
        return user["command_id"] is None or user["command_id"] == alert_command_id
    if role == "BASE_COMMANDER":  # proposed default (PRD §4.2)
        return alert_base_id is not None and alert_base_id == user["base_id"]
    return False
