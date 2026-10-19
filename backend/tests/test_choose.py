"""A person's own choice for one mission (ARCHITECTURE D61): another option or a hand-picked base and type is checked
with the planner's rules before it replaces the planner's package; a pick that breaks a rule is refused with the reason;
only Air HQ and admin may choose, and every choice is audited. Needs a seeded database. Every test rolls back."""
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import config
from app import models as M
from app.db import SessionLocal
from app.decide import choose as CH
from app.decide import planner as P
from app.decide import snapshot as S
from app.decide import store
from app.main import app

AIRHQ = {"id": 2, "role": "COMMAND_HQ", "username": "airhq", "command_id": None}


def _proposal(db):
    """A fresh full plan waiting for a decision (in this session only)."""
    db.execute(text("UPDATE plan SET status = 'SUPERSEDED' WHERE status IN ('PROPOSED', 'APPROVED')"))
    res = P.plan(S.build(db), "BALANCED")
    return P.store(db, res, preset="BALANCED", user=AIRHQ, summary="test")


def test_another_option_replaces_the_package_after_the_rules_check_and_is_audited():
    with SessionLocal() as db:
        pid = _proposal(db)
        now = db.execute(text("SELECT sim_now()")).scalar()
        picked = None
        for r in store.items_of(db, pid):
            if not r["alternatives"] or r["launch_ts"] <= now:
                continue
            o = CH.options(db, r["mission_id"])
            for a in o["alternatives"]:
                try:
                    picked = (r, a, CH.choose(db, AIRHQ, r["mission_id"], a["base_id"], a["type_id"]))
                    break
                except store.PlanError:
                    continue
            if picked:
                break
        assert picked, "no alternative could be chosen in this seed"
        r, a, out = picked
        assert out["plan_id"] == pid
        it = db.get(M.PlanItem, out["item_id"])
        assert (it.base_id, it.aircraft_type_id) == (a["base_id"], a["type_id"]) and it.mission_id == r["mission_id"]
        assert it.explanation["rows"][0]["label"] == "Chosen by"
        assert db.get(M.PlanItem, r["id"]) is None                       # the planner's package is gone, one per mission
        assert db.execute(text("SELECT count(*) FROM audit_log WHERE action = 'PLAN_OVERRIDE' AND entity_id = :i"),
                          {"i": it.id}).scalar() == 1
        db.rollback()


def test_a_pick_that_breaks_a_rule_is_refused_with_the_reason():
    with SessionLocal() as db:
        pid = _proposal(db)
        now = db.execute(text("SELECT sim_now()")).scalar()
        refused = None
        for r in store.items_of(db, pid):
            if r["launch_ts"] <= now:
                continue
            o = CH.options(db, r["mission_id"])
            for m in o["manual"]:
                try:
                    CH.choose(db, AIRHQ, r["mission_id"], m["base_id"], m["type_id"])
                except store.PlanError as e:
                    refused = e
                    break
            if refused:
                break
        assert refused is not None and refused.status in (409, 422) and refused.message
        db.rollback()


def test_choosing_is_for_air_hq_and_admin_only():
    for who in ("viewer", "cdr.viax"):
        c = TestClient(app)
        assert c.post("/api/v1/auth/login", json={"username": who, "password": config.DEMO_PASSWORD}).status_code == 200
        r = c.post("/api/v1/ops/plans/choose", json={"mission_id": 1, "base_id": 1, "type_id": 1})
        assert r.status_code == 403, (who, r.status_code)
