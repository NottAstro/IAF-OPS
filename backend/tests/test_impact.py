"""Scenario impact assessment (ARCHITECTURE D62): planning the same moment without and with a scenario shows what it
does; a package that can't stay where it was says why in plain words; the brief is built from those facts. Needs a
seeded database. Every test rolls back."""
from sqlalchemy import select

from app import models as M
from app.db import SessionLocal
from app.decide import exercise as EX
from app.decide import impact as IM
from app.decide import snapshot as S

AIRHQ = {"id": 2, "role": "COMMAND_HQ", "username": "airhq", "command_id": None}


def _start(db, code):
    before = S.build(db)
    sc = db.scalars(select(M.Scenario).where(M.Scenario.code == code)).first()
    run = EX.start(db, AIRHQ, sc.id, None, None, {}, None)
    EX.apply_due(db, run, EX.sim_now(db), None)
    db.flush()
    return run, before


def test_a_runway_closure_moves_or_drops_what_was_planned_there_and_says_why():
    with SessionLocal() as db:
        live = {r.scenario_id for r in EX.running(db)}
        code = next(c for c in ("runway-closure", "trainer-crash")            # whichever runway scenario isn't running
                    if db.scalars(select(M.Scenario).where(M.Scenario.code == c)).first().id not in live)
        run, before = _start(db, code)
        a = IM.assess(db, run, before)
        assert a["brief"] and a["before"]["missions"] and a["with"]["missions"]
        assert a["bases"] and a["aircraft_there"] > 0
        there = [c for c in a["changes"] if c["kind"] in ("moved", "dropped") and c["before"]["base_id"] in run.footprint["bases"]]
        if a["flights_there_before"]:            # something was planned from the closed base in the window
            assert there or a["kept_there"], a
        for c in there:
            assert c["reason"] and c["reason_code"], c
            if c["reason_code"] == "RUNWAY_CLOSED":
                assert "runway" in c["reason"] and "closed" in c["reason"]
        db.rollback()


def test_a_scenario_that_adds_missions_lists_them_with_their_package_or_why_not():
    with SessionLocal() as db:
        run, before = _start(db, "air-attack")
        a = IM.assess(db, run, before)
        added = [c for c in a["changes"] if c["kind"] == "added"]
        assert len(added) == len(run.footprint.get("missions", [])) > 0
        for c in added:
            assert c["after"] or c["reason"], c
        assert any("adds" in x for x in a["brief"])
        db.rollback()
