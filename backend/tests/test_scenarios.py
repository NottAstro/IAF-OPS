"""Scenarios (ARCHITECTURE D55): one incident each, several live at once, disruptions owned by the scenario that caused
them, a Planner response built from the engine, and commit tolerating the minutes a decision takes. Needs a seeded
database with a committed plan (test_decide.py commits one) and the dev server stopped."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import config
from app import models as M
from app.db import SessionLocal
from app.decide import config as D
from app.decide import exercise as EX
from app.decide import planner as P
from app.decide import snapshot as S
from app.main import app

ADMIN = {"id": 1, "role": "ADMIN"}


def login(username: str) -> TestClient:
    c = TestClient(app)
    assert c.post("/api/v1/auth/login", json={"username": username, "password": config.DEMO_PASSWORD}).status_code == 200
    return c


def test_fill_keeps_types_and_resolve_layers_defaults_preset_and_form():
    sc = M.Scenario(params=[{"key": "base", "kind": "base", "default": "VOBR"}, {"key": "hours", "kind": "choice", "default": 4}],
                    intensity="LOW", intensity_presets={"HIGH": {"hours": 8}})
    assert EX.resolve(sc, None, "HIGH") == ({"base": "VOBR", "hours": 8}, "HIGH")
    assert EX.resolve(sc, {"hours": 6, "junk": 1}, None) == ({"base": "VOBR", "hours": 6}, "LOW")   # unknown keys dropped
    assert EX.fill({"bases": "{b}", "t": "closed {h} h", "n": "{n}", "k": ["{n}"]}, {"b": ["VIHX", "VISA"], "h": 4, "n": 2}) == \
        {"bases": ["VIHX", "VISA"], "t": "closed 4 h", "n": 2, "k": [2]}
    with pytest.raises(ValueError):
        EX.resolve(sc, None, "EXTREME")


def test_two_scenarios_live_together_and_each_owns_its_disruptions():
    with SessionLocal() as db:
        a = M.Scenario(code="t-rwy", name="t runway", intensity="LOW", intensity_presets={},
                       params=[{"key": "base", "kind": "base", "default": "VIHX"}],
                       injects=[{"offset_min": 0, "kind": "RUNWAY_CLOSED", "params": {"base": "{base}", "hours": 2}}])
        b = M.Scenario(code="t-grd", name="t grounding", intensity="LOW", intensity_presets={}, params=[],
                       injects=[{"offset_min": 0, "kind": "AIRCRAFT_GROUNDING",
                                 "params": {"type": "Su-30MKI", "bases": ["VIHX"], "count": 2, "hours": 2}}])
        db.add_all([a, b])
        db.flush()
        ra = EX.start(db, ADMIN, a.id, None, None)
        EX.apply_due(db, ra, EX.sim_now(db))
        rb = EX.start(db, ADMIN, b.id, None, None)
        EX.apply_due(db, rb, EX.sim_now(db))
        with pytest.raises(ValueError):                       # one live run per scenario
            EX.start(db, ADMIN, a.id, None, None)
        hx = db.execute(text("SELECT id FROM base WHERE code = 'VIHX'")).scalar()
        assert {ra.id, rb.id} <= {r.id for r in EX.running(db)}
        assert hx in ra.footprint["bases"] and hx in rb.footprint["bases"] and len(rb.footprint["aircraft"]) == 2
        # both touched Halwara: the runway disruption belongs to the runway scenario, a grounded tail to the grounding
        assert EX.owner(db, hx, None, None, None, "RUNWAY_CLOSED") == ra.id
        assert EX.owner(db, hx, "aircraft", rb.footprint["aircraft"][0], None, "AIRCRAFT_US") == rb.id
        EX.stop(db, ADMIN, rb.id)                            # ending one leaves the other live
        assert [r.id for r in EX.running(db) if r.id in (ra.id, rb.id)] == [ra.id]
        db.rollback()                                         # leave the world as it was


def test_scenario_start_is_for_air_hq_and_admin_audited_and_answers_in_the_planner():
    adm, air, viewer = login("admin"), login("airhq"), login("viewer")
    assert viewer.post("/api/v1/ops/scenarios/trainer-crash/start", json={}).status_code == 403
    with SessionLocal() as db:
        before = db.execute(text("SELECT count(*) FROM audit_log WHERE action = 'SIM_CONTROL'")).scalar()
    assert login("cdr.viax").post("/api/v1/ops/scenarios/trainer-crash/start", json={}).status_code == 403
    r = air.post("/api/v1/ops/scenarios/trainer-crash/start", json={"intensity": "LOW"})   # Air HQ may start them
    assert r.status_code == 200, r.text
    run = r.json()["run_id"]
    try:
        with SessionLocal() as db:
            assert db.execute(text("SELECT count(*) FROM audit_log WHERE action = 'SIM_CONTROL'")).scalar() == before + 1
            fp = db.get(M.ExerciseRun, run).footprint
        assert {e["kind"] for e in fp["effects"]} == {"AIRCRAFT_LOST", "RUNWAY_CLOSED", "MISSION_POPUP"}
        assert air.post("/api/v1/ops/disruptions/check").status_code == 200        # the monitor's next cycle, now
        live = air.get("/api/v1/ops/scenarios/live").json()
        assert any(x["id"] == run for x in live)
        resp = air.get(f"/api/v1/ops/scenarios/runs/{run}/response").json()
        assert "Bidar" in resp["lead"] and resp["timeline"][0]["label"] == "Crash"
        assert any(i["status"] == "info" and "lost at Bidar" in i["what"] for i in resp["impacts"])
        # the pilot pickup is the scenario's own pop-up: it gets a package or a reason, never silence
        assert any("casualty evacuation" in i["what"].lower() for i in resp["impacts"])
        assert all(q["status"] in ("met", "approve", "wait") for q in resp["requirements"])
    finally:
        assert adm.post(f"/api/v1/ops/scenarios/runs/{run}/end").status_code == 200


def test_commit_slips_a_package_whose_preparation_time_passed_while_deciding():
    """At ×10 a minute of thought is ten simulated minutes: a package at its earliest launch must not be skipped for it."""
    from app.decide import store
    with SessionLocal() as db:
        st0 = S.build(db)
        pid = P.store(db, P.plan(st0, workers=1, seed=0), preset="BALANCED", user={"id": 2})
        db.flush()
        rows = [r for r in store.items_of(db, pid) if r["mission_id"] in st0.missions and r["on_station_ts"] + timedelta(
            minutes=20 + st0.missions[r["mission_id"]].on_station_min) <= st0.missions[r["mission_id"]].window_end]
        r = min(rows, key=lambda x: x["launch_ts"])
        launch0 = r["launch_ts"]
        # the decision took long enough that this package's preparation should have started 10 minutes ago
        db.execute(text("UPDATE sim_state SET sim_now = :t WHERE id = 1"), {"t": launch0 - timedelta(minutes=D.PREP_MIN - 10)})
        repaired, _ = store._repair(db, S.build(db), [(r, None, None, "NEW")])
        assert r["launch_ts"] > launch0 and any("slipped" in x for x in repaired), repaired
        assert db.get(M.PlanItem, r["id"]).launch_ts == r["launch_ts"]
        db.rollback()                                         # clock, plan and items as they were


def test_a_scenario_tags_the_missions_it_demands_and_ending_it_withdraws_them():
    """D56: the situation is the starting point: a scenario's missions carry its run, and ending it cancels the ones not
    yet flying (audited) so the planner frees what they held."""
    with SessionLocal() as db:
        sc = M.Scenario(code="t-pop", name="t pop-up", intensity="LOW", intensity_presets={}, params=[],
                        injects=[{"offset_min": 0, "kind": "MISSION_POPUP", "params": {"mission_type": "CASEVAC", "priority": "P1",
                                                                                       "near_base": "VI57", "offset_km": 20, "bearing": 120}}])
        db.add(sc)
        db.flush()
        run = EX.start(db, ADMIN, sc.id, None, None)
        EX.apply_due(db, run, EX.sim_now(db))
        m = db.scalars(select(M.Mission).where(M.Mission.exercise_run_id == run.id)).one()
        assert m.priority == "P1" and m.status == "APPROVED" and "MOUNTAIN_FLYING" in (m.min_quals or [])   # Thoise is high
        EX.stop(db, ADMIN, run.id)
        db.flush()
        assert m.status == "CANCELLED"
        assert db.execute(text("SELECT count(*) FROM audit_log WHERE entity_type = 'mission' AND entity_id = :i"), {"i": m.id}).scalar() >= 1
        db.rollback()


def test_the_plan_under_review_is_the_newest_proposal_else_the_committed_one():
    from app.decide import store
    with SessionLocal() as db:
        pid = P.store(db, P.plan(S.build(db), workers=1, seed=0), preset="BALANCED", user={"id": 2})
        db.flush()
        assert store.under_review(db).id == pid                   # the newest proposal
        db.execute(text("UPDATE plan SET status = 'REJECTED' WHERE id = :p"), {"p": pid})
        db.execute(text("UPDATE plan SET status = 'SUPERSEDED' WHERE status IN ('PROPOSED', 'APPROVED') AND id <> :p"), {"p": pid})
        committed = store.current_committed(db)
        assert (store.under_review(db) or M.Plan()).id == (committed.id if committed else None)   # else the committed one
        db.rollback()


def test_situation_answers_with_plan_missions_impacts_requirements_and_transfers():
    s = login("airhq").get("/api/v1/ops/scenarios/situation").json()
    assert {"runs", "plan", "decision", "missions", "impacts", "requirements", "transfers", "scenarios", "in_force"} <= set(s)
    assert {"moves", "unmet", "in_transit"} <= set(s["transfers"])
    if s["plan"]:                                   # D60: the Planner's sentence says why the plan exists
        assert s["plan"]["why"] and s["plan"]["created_at"]
    for b in s["scenarios"]:                        # D59/D60: one box per live scenario, with its timeline
        assert {"run", "lead", "timeline", "impacts"} <= set(b)
    for m in s["missions"]:
        assert m["tag"] and m["status"] in ("in", "proposed", "uncovered")


def test_a_routine_mission_is_linked_to_the_scenario_that_left_it_uncovered():
    """D57: "Runway closed: VOBR …" under a scenario that closed VOBR links the mission to it; a range reason that only
    happens to name the base does not."""
    from app.decide.scenarios import _cause
    rw = {"reasons": [{"code": "RUNWAY_CLOSED", "text": "Runway closed at launch or recovery", "examples": ["VOBR at 09:13Z"]}]}
    assert _cause(rw, {5: "VOBR"}) == {"kind": "RUNWAY_CLOSED", "base_id": 5, "message": "Runway closed at launch or recovery"}
    assert _cause(rw, {6: "VOHK"}) is None
    far = {"reasons": [{"code": "OUT_OF_RANGE", "text": "Out of range or endurance", "examples": ["VOBR Hawk 132 · needs 3 h"]}]}
    assert _cause(far, {5: "VOBR"}) is None
    risk = {"reasons": [{"code": "THREAT_TOO_HIGH", "text": "Route risk above the mission's limit", "examples": ["VOBR Su-30MKI: 0.9"]}]}
    assert _cause(risk, {5: "VOBR"}, {"RUNWAY_CLOSED"}) is None            # a runway closure doesn't make routes risky


def test_a_plan_says_why_it_exists_in_plain_words():
    """D60: the reason behind a proposal names the scenario (or routine tasking) and the mission, not codes."""
    from app.decide.store import why_text
    assert why_text([("CREW_UNAVAILABLE", "TRG-SWAC-016: aircrew 3780: unavailable", None, "Training near Pune")]) == \
        "Routine: crew member unavailable for Training near Pune"
    assert why_text([("MISSION_NEW", "x", "Air attack", "a"), ("MISSION_NEW", "y", "Air attack", "b"),
                     ("RUNWAY_CLOSED", "z", None, "c")]) == "Air attack: 2 new missions · Routine: 1 runway closed"
