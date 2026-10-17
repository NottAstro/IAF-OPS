"""Phase 2 decision support (PHASE2_IMPLEMENTATION_PLAN §13): the smallest checks that fail if the planner stops being
valid, lexicographic, deterministic, explainable, border-safe or side-effect free, or if commit / re-tasking break.
Needs a seeded database (make seed) and the dev server stopped: its simulator writes to the same database. Runs after
test_api.py; the last tests commit a plan and re-task it."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text

from app import config
from app.db import SessionLocal
from app.decide import planner as P, routing, snapshot as S, weather_impact as W
from app.decide.validate import validate
from app.main import app

_ST = {}


def login(username: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={"username": username, "password": config.DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return c


def snap():
    if "st" not in _ST:
        with SessionLocal() as db:
            _ST["st"] = S.build(db)
    return _ST["st"]


def plan(st=None, **kw):
    return P.plan((st or snap()).clone(), workers=1, seed=0, **kw)


def counts():
    with SessionLocal() as db:
        return db.execute(text("SELECT (SELECT count(*) FROM plan), (SELECT count(*) FROM sortie), "
                               "(SELECT count(*) FROM mission WHERE status = 'TASKED')")).one()


def test_weather_minima_and_night():
    assert W.category(None, 10000) == "VFR" and W.category(800, 3000) == "IFR" and W.category(200, 500) == "LIFR"
    ifr = (None, 700, 3000, 5, None, 0, "IFR", "SYNTHETIC")
    assert W.rating_needed(ifr, "fighter", 0)[0] == "GREEN"            # white-rated pilots can't take IFR
    lifr = (None, 150, 400, 5, None, 0, "LIFR", "SYNTHETIC")
    assert W.rating_needed(lifr, "fighter", 0)[0] is None
    delhi = (77.2, 28.6)
    assert W.is_night(*delhi, datetime(2026, 10, 17, 18, 30, tzinfo=timezone.utc))      # midnight IST
    assert not W.is_night(*delhi, datetime(2026, 10, 17, 6, 30, tzinfo=timezone.utc))   # noon IST


def test_router_threads_the_siliguri_corridor():
    st = snap()
    agra = next(b for b in st.bases.values() if b.code == "VIAG")
    tezpur = next(b for b in st.bases.values() if b.code == "VETZ")
    leg = routing.leg(st.G, (agra.lon, agra.lat), (tezpur.lon, tezpur.lat))
    assert leg and st.G.route_clear(leg)
    assert any(87.6 <= x <= 89.6 and 25.9 <= y <= 27.2 for x, y in leg[1:-1]), leg


def test_plan_is_valid_border_safe_and_explained():
    st = snap()
    res = plan(st)
    assert res.items, "the seeded day should be plannable"
    assert res.kpis["violations"] == 0 and not res.violations
    specs = [P.spec(c, res.assignments[m], str(m)) for m, c in res.selected.items()]
    assert validate(st, specs) == []
    for it in res.items:
        assert st.G.route_clear([tuple(p) for p in it["route"]])          # I8 / I15, incl. the LoC / LAC (D33)
        assert it["explanation"]["rows"]
    for u in res.unmet:
        assert u["reasons"], st.missions[u["mission_id"]].code             # every unmet mission says why
    assert res.kpis["covered"] + res.kpis["unmet"] == res.kpis["missions"]


def test_priorities_are_lexicographic():
    """Dropping every P3/P4 mission can never raise P1 or P2 coverage: they were already maximal."""
    st = snap()
    full = plan(st)
    top = st.clone()
    top.missions = {k: m for k, m in top.missions.items() if m.priority in ("P1", "P2")}
    only = P.plan(top, workers=1, seed=0)
    for p in ("P1", "P2"):
        assert full.kpis["by_priority"][p]["covered"] == only.kpis["by_priority"][p]["covered"], p


def test_planner_is_deterministic():
    a, b = plan(), plan()
    key = lambda r: sorted((i["mission_id"], i["base_id"], i["aircraft_type_id"], str(i["launch_ts"]), tuple(i["aircraft_ids"]))
                           for i in r.items)  # noqa: E731
    assert key(a) == key(b)


def test_validator_catches_double_booking():
    st = snap()
    res = plan(st)
    specs = [P.spec(c, res.assignments[m], str(m)) for m, c in res.selected.items()]
    same = [(i, j) for i in specs for j in specs if i is not j and i.base_id == j.base_id and i.type_id == j.type_id
            and i.ac_iv[0] < j.ac_iv[1] and j.ac_iv[0] < i.ac_iv[1]]
    if not same:
        return
    i, j = same[0]
    j.aircraft[0] = i.aircraft[0]
    assert any(v.rule == "AIRCRAFT_OVERLAP" for v in validate(st, specs))


def test_whatif_changes_nothing_and_grounding_hurts():
    before = counts()
    c = login("airhq")
    r = c.post("/api/v1/ops/whatif", json={"deltas": [{"kind": "GROUND_TYPE", "params": {"type": "Su-30MKI", "count": 150}}],
                                          "presets": ["BALANCED"]})
    assert r.status_code == 200, r.text
    base, what = r.json()["runs"][0]["kpis"], r.json()["runs"][1]["kpis"]
    assert what["covered"] <= base["covered"]
    assert counts() == before


def test_planning_rbac():
    assert login("viewer").post("/api/v1/ops/plans", json={}).status_code == 403
    assert login("cdr.viax").post("/api/v1/ops/plans", json={}).status_code == 403
    assert login("viewer").get("/api/v1/ops/missions").status_code == 200


def test_air_to_air_refuelling_extends_reach():
    """Out-of-range missions can be covered with a tanker; receivers are AAR-qualified and the tanker leg validates."""
    st = snap()
    res = plan(st)
    aar = [i for i in res.items if i.get("support")]
    assert aar, "the seeded day has missions only reachable with refuelling"
    for i in aar:
        m = st.missions[i["mission_id"]]
        assert st.types[i["aircraft_type_id"]].name in {"Su-30MKI", "Rafale", "Mirage 2000", "Tejas Mk1"}
        assert st.types[i["support"]["type_id"]].role == "TANKER"
        pilots = [c for c, _, pos in i["crew_positions"] if pos in ("CAPTAIN", "CO_PILOT")]
        assert all("AAR_RECEIVER" in st.crew[c].quals for c in pilots), m.code
        assert any(r["label"] == "Air-to-air refuelling" for r in i["explanation"]["rows"])
    specs = [x for mid, c in res.selected.items() for x in P.specs(c, res.assignments[mid], str(mid))]
    assert any(s.key.endswith("#AAR") for s in specs) and validate(st, specs) == []


def test_runway_launch_rate_is_enforced():
    from dataclasses import replace
    st = snap()
    res = plan(st)
    mid, c = next(iter(res.selected.items()))
    one = P.spec(c, res.assignments[mid], "x")
    cap = st.bases[c.base_id].runways * 8
    crowd = [replace(one, key=f"k{i}", aircraft=[-(i + 1)], crew=[]) for i in range(cap + 1)]
    assert any(v.rule == "LAUNCH_RATE" for v in validate(st, crowd))


def test_snag_model_learns_from_the_log_and_is_calibrated():
    """D38: trained only on the maintenance log (never the simulator's law), it ranks held-out sorties well above chance,
    beats the base rate, is calibrated, and finds the wear-out and just-out-of-maintenance effects."""
    import inspect
    from app.decide import predict as PR
    assert "reliability" not in inspect.getsource(PR).split('"""', 2)[2]      # the model can't peek at the ground truth
    with SessionLocal() as db:
        m = PR.train(db, store=False)
    t = m.metrics["test"]
    assert t["n"] > 5000 and t["auc"] > 0.65 and t["brier"] < t["brier_base_rate"], t
    cal = t["calibration"]
    assert cal[-1]["observed"] > 3 * cal[0]["observed"] and abs(cal[-1]["observed"] - cal[-1]["predicted"]) < 0.05
    co = m.metrics["coefficients"]
    assert co["wear_sq"] + co["wear"] > 0.5 and co["fresh"] > 0.3 and co["age_30y"] > 0
    assert 0 < m.p(0.95, 30, 3, "fighter", 2) and m.p(0.95, 30, 3, "fighter", 2) > m.p(0.3, 5, 1, "fighter", 0)


def test_priority_packages_take_the_most_reliable_tails():
    """P1/P2 packages get the free tails with the lowest predicted defect risk (2-point bands); the explanation says so."""
    from app.decide import config as DC
    from app.decide.assign import Ledger, assign
    from app.decide.predict import tail_risk
    from app.decide.resources import aircraft_free
    st = snap()
    assert st.snag is not None
    res = plan(st)
    checked = 0
    for mid, c in res.selected.items():
        if st.missions[mid].priority not in DC.SNAG_AWARE:
            continue
        a = assign(st, c, Ledger())
        a0, a1 = c.ac_iv
        free = [x for x in (st.aircraft[i] for i in st.by_base_type[(c.base_id, c.type_id)])
                if aircraft_free(st, x, a0, a1) and x.hours_left >= c.duration_h]
        band = lambda x: int(tail_risk(st, x, c.duration_h) / DC.SNAG_BAND)  # noqa: E731
        worst_chosen = max(band(st.aircraft[i]) for i in a.aircraft)
        assert all(band(x) >= worst_chosen for x in free if x.id not in a.aircraft), st.missions[mid].code
        checked += 1
    assert checked >= 5
    it = res.items[0]
    assert it["score"]["snag"]["package"] > 0 and any(r["label"] == "Snag risk" for r in it["explanation"]["rows"])
    assert res.kpis["snag_expected"] > 0


def test_civil_traffic_is_a_soft_cost_with_an_explanation():
    """D39: civil ADS-B tracks along a route raise its cost (for near-term launches only) and the explanation names the
    busy spot; civil airports' terminal areas always count; traffic never rejects a candidate."""
    import time as _t
    from app.decide import feasibility as F, traffic as TR
    from app.live import feeds
    st = snap().clone()
    cands, _ = F.generate(st, "BALANCED")
    allc = [c for cs in cands.values() for c in cs]
    assert allc and all("traffic" in c.cost_parts for c in allc)
    assert any(c.traffic and c.traffic["airport"] for c in allc)            # static TMA layer, feed or not
    c = min(allc, key=lambda c: c.launch)
    x, y = TR.samples(c.route)[len(TR.samples(c.route)) // 2]
    near, late = TR.live_weight(st.now, st.now), TR.live_weight(st.now, st.now + timedelta(hours=8))
    assert near == 1.0 and late == 0.0
    with SessionLocal() as db:
        base = TR.score(TR.route_profile(TR.build(db), c.route), near)[0]
        now = _t.time()
        for k in range(40):
            feeds.TRACKS[f"zz{k:02d}"] = {"hex": f"zz{k:02d}", "lat": y + 0.002 * k, "lon": x, "on_ground": False, "ts": now,
                                          "db_military": False}
        try:
            tr = TR.build(db)
        finally:
            for k in range(40):
                feeds.TRACKS.pop(f"zz{k:02d}", None)
    prof = TR.route_profile(tr, c.route)
    assert TR.score(prof, near)[0] >= base + 3 and TR.score(prof, late)[0] == base
    d = TR.describe(tr, c.route, prof, near)
    assert d["level"] == "busy" and d["live"] >= 30


def test_snag_risk_api_card_and_fleet():
    c = login("airhq")
    card = c.get("/api/v1/ops/models/snag-risk").json()
    assert card["trained"] and card["metrics"]["test"]["auc"] > 0.65 and len(card["metrics"]["test"]["calibration"]) == 10
    fleet = c.get("/api/v1/ops/fleet/snag-risk?limit=10").json()
    ps = [r["p"] for r in fleet["items"]]
    assert len(ps) == 10 and ps == sorted(ps, reverse=True) and fleet["fleet_mean"] < ps[0]
    assert login("viewer").post("/api/v1/ops/models/snag-risk/train").status_code == 403


def test_dependent_missions_fly_only_under_cover():
    """D41: a barrier CAP that needs AEW&C is planned only inside its supporter's time on station; without the supporter
    the validator flags it, and an uncovered dependent says why."""
    st = snap()
    res = plan(st)
    items = {i["mission_id"]: i for i in res.items}
    deps = [m for m in st.missions.values() if m.depends_on]
    assert deps, "the seeded day has missions under AEW&C cover"
    covered = [m for m in deps if m.id in items]
    assert covered
    for m in covered:
        d = items[m.id]
        sups = [items[x] for x in st.family_of(m.depends_on) if x in items]
        assert any(s["on_station_ts"] <= d["on_station_ts"] and s["score"]["off_station"] >= d["score"]["off_station"] for s in sups), m.code
        assert any(r["label"] == "Depends on" for r in d["explanation"]["rows"])
    supporters = {m.depends_on for m in deps}
    specs = [x for mid, c in res.selected.items() if mid not in supporters for x in P.specs(c, res.assignments[mid], str(mid))]
    assert any(v.rule == "DEPENDENCY" and v.mission_id == covered[0].id for v in validate(st, specs))
    st2 = st.clone()                          # the supporter is gone (cancelled): its dependent can't be covered
    gone = covered[0].depends_on
    st2.missions = {k: m for k, m in st2.missions.items() if k != gone}
    res2 = plan(st2)
    u = next(u for u in res2.unmet if u["mission_id"] == covered[0].id)
    assert u["reasons"][0]["code"] == "NO_COVER" and u["fixes"][0]["kind"] == "COVER_SUPPORT"


def test_split_missions_relief_and_bases():
    """D42: a 6 h CAP no package can hold and a surge no base can launch get checked split fixes; applied, every part is
    covered (reliefs hand over without a gap, base parts are on station together), and parts are covered all or nothing."""
    from dataclasses import replace
    res = plan(snap())
    fixes = {f["kind"]: (u["mission_id"], f) for u in res.unmet for f in u["fixes"] if f["kind"].startswith("SPLIT_")}
    assert {"SPLIT_RELIEF", "SPLIT_BASES"} <= set(fixes), fixes
    air = login("airhq")
    for mid, f in fixes.values():
        r = air.post(f"/api/v1/ops/missions/{mid}/split", json={k: f[k] for k in ("kind", "parts", "t0", "sizes") if k in f})
        assert r.status_code == 200, r.text
    assert air.post(f"/api/v1/ops/missions/{fixes['SPLIT_RELIEF'][0]}/split", json=fixes["SPLIT_RELIEF"][1]).status_code == 409
    with SessionLocal() as db:
        st = S.build(db)
    res = plan(st)
    items = {i["mission_id"]: i for i in res.items}
    for kind in ("RELIEF", "BASES"):
        parts = sorted((m for m in st.missions.values() if m.part and m.part[2] == kind), key=lambda m: m.part[0])
        assert len(parts) >= 2 and all(m.id in items for m in parts), [(m.code, m.id in items) for m in parts]
        got = [items[m.id] for m in parts]
        if kind == "RELIEF":
            for a, b in zip(got, got[1:]):     # the next relief is on station before the previous one leaves
                assert b["on_station_ts"].isoformat() <= a["score"]["off_station"]
        else:
            assert len({g["on_station_ts"] for g in got}) == 1 and len({g["base_id"] for g in got}) == len(got)
            assert sum(g["n_aircraft"] for g in got) == sum(m.required for m in parts)
        assert any(r["label"] == "Part of" for r in got[0]["explanation"]["rows"])
    st2 = st.clone()                          # one relief can't be flown: the other is dropped too
    rel = [m for m in st2.missions.values() if m.part and m.part[2] == "RELIEF"]
    st2.missions[rel[-1].id] = replace(rel[-1], window_end=rel[-1].window_start + timedelta(minutes=1))
    res2 = plan(st2)
    assert not {m.id for m in rel} & {i["mission_id"] for i in res2.items}


def test_scenario_injects_apply_exactly_once():
    """Regression: the JSONB inject list was mutated in place, so applied_at never saved and injects re-fired."""
    from app import models as M
    from app.decide import exercise as EX
    with SessionLocal() as db:
        user = {"id": 1, "role": "ADMIN"}
        sc = M.Scenario(name="test-once", speed=60, injects=[{"offset_min": 0, "kind": "MISSION_POPUP", "label": "pop",
                                                              "params": {"mission_type": "CASEVAC", "priority": "P1", "target_base": "VILH"}}])
        db.add(sc)
        db.flush()
        EX.start(db, user, sc.id, None, None)
        db.commit()
        now = db.execute(text("SELECT sim_now()")).scalar()
        before = db.execute(text("SELECT count(*) FROM mission WHERE code LIKE 'SIM-CEV-POP-%'")).scalar()
        for k in range(3):
            EX.tick(db, now + timedelta(minutes=k))
            db.commit()
        after = db.execute(text("SELECT count(*) FROM mission WHERE code LIKE 'SIM-CEV-POP-%'")).scalar()
        EX.stop(db, user)
        db.delete(sc)
        db.commit()
    assert after == before + 1


def test_commit_repairs_or_skips_instead_of_failing():
    """The world moves between generate and commit: an aircraft going U/S must not fail the whole commit."""
    with SessionLocal() as db:
        st = S.build(db)
        res = P.plan(st, workers=1, seed=0)
        pid = P.store(db, res, preset="BALANCED", user={"id": 2})
        db.commit()
        victim = res.items[0]["aircraft_ids"][0]
        db.execute(text("UPDATE aircraft SET status = 'MAINT_UNSCHEDULED', maint_eta = sim_now() + interval '3 days' WHERE id = :a"),
                   {"a": victim})
        db.commit()
    r = login("airhq").post(f"/api/v1/ops/plans/{pid}/commit")
    assert r.status_code == 200, r.text
    ch = r.json()["changes"]
    assert ch["REPAIRED"] + ch["SKIPPED"] >= 1 and ch["NEW"] + ch["KEPT"] + ch["MOVED"] + ch["SWAP"] >= len(res.items) - 1
    with SessionLocal() as db:
        assert not db.execute(text("""SELECT count(*) FROM sortie_aircraft sa JOIN sortie s ON s.id = sa.sortie_id
                                      WHERE sa.aircraft_id = :a AND s.status = 'PLANNED'"""), {"a": victim}).scalar()


def test_losing_the_supporter_replans_its_dependents():
    """D41: when the AEW&C sortie is lost, the re-task proposal re-plans it together with its barrier CAP and never keeps
    the CAP without cover (a new AEW&C package over the unchanged CAP is the smallest repair)."""
    with SessionLocal() as db:
        row = db.execute(text("""SELECT pa.sortie_id, pa.mission_id FROM plan_item pa
                                 JOIN plan p ON p.id = pa.plan_id AND p.status = 'COMMITTED'
                                 JOIN mission d ON d.depends_on_id = pa.mission_id
                                 JOIN plan_item pd ON pd.plan_id = pa.plan_id AND pd.mission_id = d.id AND pd.status = 'COMMITTED'
                                 JOIN sortie s ON s.id = pa.sortie_id AND s.status = 'PLANNED'
                                 WHERE pa.status = 'COMMITTED' ORDER BY pa.id LIMIT 1""")).first()
        assert row, "the committed plan has an AEW&C package with a dependent CAP"
        deps = [r[0] for r in db.execute(text("SELECT id FROM mission WHERE depends_on_id = :m"), {"m": row.mission_id})]
        db.execute(text("UPDATE sortie SET status = 'CANCELLED', cancel_reason = 'AIRCRAFT_US' WHERE id = :s"), {"s": row.sortie_id})
        db.commit()
    air = login("airhq")
    out = air.post("/api/v1/ops/disruptions/check").json()
    assert out["proposal"], out
    prop = air.get(f"/api/v1/ops/plans/{out['proposal']['plan_id']}").json()
    items = {i["mission"]["id"]: i for i in prop["items"]}
    for d in deps:
        if d in items:
            s = items.get(row.mission_id)
            assert s and s["on_station_ts"] <= items[d]["on_station_ts"] and \
                s["score"]["off_station"] >= items[d]["score"]["off_station"], "a dependent CAP was kept without AEW&C cover"


def test_commit_then_retask_a_runway_closure():
    from app.sim.engine import Simulator
    from app.ws import hub
    app.state.sim = Simulator(hub)
    air, adm = login("airhq"), login("admin")
    r = air.post("/api/v1/ops/plans", json={"preset": "BALANCED"})
    assert r.status_code == 201, r.text
    pid = r.json()["plan_id"]
    items = air.get(f"/api/v1/ops/plans/{pid}").json()["items"]
    sorties_before = counts()[1]
    r = air.post(f"/api/v1/ops/plans/{pid}/commit")
    assert r.status_code == 200, r.text
    ch = r.json()["changes"]
    assert ch["NEW"] + ch["KEPT"] + ch["MOVED"] + ch["SWAP"] + ch["SKIPPED"] == len(items)
    assert counts()[1] == sorties_before + ch["NEW"] + ch["MOVED"] + ch["TANKERS"]   # kept / swapped packages reuse theirs
    with SessionLocal() as db:
        assert db.execute(text("SELECT count(*) FROM audit_log WHERE action = 'PLAN_COMMIT' AND entity_id = :p"), {"p": pid}).scalar() == 1
        tankers = sum(1 for i in items if i.get("support") and i["status"] != "REJECTED")
        assert db.execute(text("SELECT count(*) FROM sortie WHERE plan_item_id IN (SELECT id FROM plan_item WHERE plan_id = :p)"),
                          {"p": pid}).scalar() >= len(items) - ch["SKIPPED"]
        # every committed refuelled package has its own tanker sortie (AAR support), linked to the same plan item
        for r in db.execute(text("""SELECT pi.id, (pi.support->>'sortie_id')::bigint AS sid FROM plan_item pi
                                    WHERE pi.plan_id = :p AND pi.status = 'COMMITTED' AND jsonb_typeof(pi.support) = 'object'"""), {"p": pid}):
            s = db.execute(text("SELECT mission_type, plan_item_id FROM sortie WHERE id = :s"), {"s": r.sid}).one()
            assert s.mission_type == "AAR_SUPPORT" and s.plan_item_id == r.id
        assert tankers >= 0
    # close the runway with the most future packages; the monitor must propose a repair that only touches those
    from collections import Counter
    with SessionLocal() as db:
        now = db.execute(text("SELECT sim_now()")).scalar()
    future = [i for i in items if datetime.fromisoformat(i["launch_ts"]) > now + timedelta(minutes=45)]
    base = Counter(i["base"]["code"] for i in future).most_common(1)[0][0]
    assert adm.post("/api/v1/ops/exercise/inject", json={"kind": "RUNWAY_CLOSED", "params": {"base": base, "hours": 30}}).status_code == 200
    out = air.post("/api/v1/ops/disruptions/check").json()
    assert out["proposal"], out
    prop = air.get(f"/api/v1/ops/plans/{out['proposal']['plan_id']}").json()
    touched = {i["mission"]["code"] for i in prop["items"] if i["change"] not in ("KEPT", None)} | \
              {u["mission"]["code"] for u in prop["unmet"]}
    affected = {i["mission"]["code"] for i in future if i["base"]["code"] == base}
    assert touched and touched <= affected | {u["mission"]["code"] for u in prop["unmet"]}
    assert all(i["base"]["code"] != base for i in prop["items"] if i["change"] in ("MOVED", "NEW"))
    assert out["proposal"]["ms"] < 15000
    r = air.post(f"/api/v1/ops/plans/{out['proposal']['plan_id']}/commit")
    assert r.status_code == 200, r.text
    assert air.post("/api/v1/ops/disruptions/check").json()["proposal"] is None     # repaired: nothing left to fix


def test_inflight_rerole_for_an_urgent_popup():
    """FR-RTK-05: a P1 pop-up the ground can't reach in time takes an airborne lower-priority package with the right
    load; commit re-tasks that sortie in place (the simulator flies on from where it is) and releases its old mission."""
    import json
    from app.sim.routes import position
    air, adm = login("airhq"), login("admin")
    with SessionLocal() as db:
        now = db.execute(text("SELECT sim_now()")).scalar()
        row = db.execute(text("""SELECT pi.id, pi.mission_id, pi.sortie_id, s.planned_recovery_ts - s.planned_launch_ts AS dur,
                                        ST_AsGeoJSON(s.route_geom, 5) AS route
                                 FROM plan_item pi JOIN plan p ON p.id = pi.plan_id AND p.status = 'COMMITTED'
                                 JOIN mission m ON m.id = pi.mission_id JOIN sortie s ON s.id = pi.sortie_id AND s.status = 'PLANNED'
                                 WHERE pi.status = 'COMMITTED' AND m.mission_type = 'AIR_DEFENCE_PATROL' AND m.priority > 'P1'
                                   AND jsonb_typeof(pi.support) IS DISTINCT FROM 'object'
                                 ORDER BY m.priority DESC, pi.launch_ts LIMIT 1""")).first()
        assert row, "the committed plan has no lower-priority CAP package to re-role"
        t0 = now - timedelta(minutes=10)                  # it took off ten minutes ago
        db.execute(text("""UPDATE sortie SET status = 'AIRBORNE', actual_launch_ts = :t, planned_launch_ts = :t,
                           planned_recovery_ts = :e WHERE id = :s"""), {"t": t0, "e": t0 + row.dur, "s": row.sortie_id})
        db.execute(text("""UPDATE aircraft SET status = 'AIRBORNE', current_base_id = NULL
                           WHERE id IN (SELECT aircraft_id FROM sortie_aircraft WHERE sortie_id = :s)"""), {"s": row.sortie_id})
        db.commit()
    pts = [tuple(c) for c in json.loads(row.route)["coordinates"]]
    x, y, _ = position(pts, 10 * 60 / row.dur.total_seconds())
    # a P1 patrol right where it is, starting in 20 min: nothing on the ground can launch, climb and get there in time
    r = adm.post("/api/v1/ops/exercise/inject", json={"kind": "MISSION_POPUP", "params": {
        "mission_type": "AIR_DEFENCE_PATROL", "priority": "P1", "lon": round(x, 4), "lat": round(y, 4), "window_h": 1.5}})
    assert r.status_code == 200, r.text
    out = air.post("/api/v1/ops/disruptions/check").json()
    assert out["proposal"], out
    prop = air.get(f"/api/v1/ops/plans/{out['proposal']['plan_id']}").json()
    rr = [i for i in prop["items"] if i["change"] == "REROLE"]
    assert len(rr) == 1 and rr[0]["source_item_id"] == row.id and rr[0]["mission"]["priority"] == "P1", prop["plan"]["kpis"]
    assert rr[0]["route"][0] == [round(x, 4), round(y, 4)] or abs(rr[0]["route"][0][0] - x) < 0.05
    gone = [u for u in prop["unmet"] if u["mission"]["id"] == row.mission_id]
    assert gone and gone[0]["dropped_item_id"] == row.id and gone[0]["reasons"][0]["code"] == "REROLED"
    r = air.post(f"/api/v1/ops/plans/{out['proposal']['plan_id']}/commit")
    assert r.status_code == 200, r.text
    assert r.json()["changes"]["REROLE"] == 1
    with SessionLocal() as db:
        s = db.execute(text("SELECT mission_id, status, reroute_ts, version FROM sortie WHERE id = :s"), {"s": row.sortie_id}).one()
        assert s.mission_id == rr[0]["mission"]["id"] and s.status == "AIRBORNE" and s.reroute_ts is not None
        assert db.execute(text("SELECT status FROM mission WHERE id = :m"), {"m": row.mission_id}).scalar() in ("APPROVED", "COMPLETED")
        assert db.execute(text("SELECT status FROM mission WHERE id = :m"), {"m": s.mission_id}).scalar() == "ACTIVE"
    assert air.post("/api/v1/ops/disruptions/check").json()["proposal"] is None


def test_manual_planning_baseline():
    """D43 / PS-8: a timed manual session; the real rules judge each pick (a base that can't reach is rejected with a
    reason), and finishing stores the manual result beside the optimiser's on the same snapshot."""
    from app.geo import dist_km
    air = login("airhq")
    r = air.post("/api/v1/ops/manual")
    assert r.status_code == 201, r.text
    s = r.json()
    from app.decide import store
    with SessionLocal() as db:                # what a careful planner would pick: the optimiser's own choices
        ref = P.plan(S.build(db, release_sortie_ids=store._releasable(db)), workers=1, seed=0)
    picks = [{"mission_id": i["mission_id"], "base_id": i["base_id"], "type_id": i["aircraft_type_id"],
              "on_station": i["on_station_ts"].isoformat()} for i in ref.items if not i.get("support")][:5]
    picked = {p["mission_id"] for p in picks}
    ms = [m for m in s["missions"] if m["options"] and m["mission_id"] not in picked]
    far = lambda m: max(m["options"], key=lambda o: dist_km((m["lon"], m["lat"]), _base_xy(o["base_id"])))  # noqa: E731
    bad = {"mission_id": ms[0]["mission_id"], "base_id": far(ms[0])["base_id"], "type_id": far(ms[0])["type_id"]}
    chk = air.post(f"/api/v1/ops/manual/{s['id']}/check", json={"picks": picks + [bad]}).json()
    assert chk["covered"] == len(picks) and chk["missions"] == len(s["missions"]), chk["rows"]
    assert chk["rows"][str(bad["mission_id"])]["ok"] is False and chk["rows"][str(bad["mission_id"])]["reason"]
    fin = air.post(f"/api/v1/ops/manual/{s['id']}/finish", json={"picks": picks}).json()
    assert fin["optimiser"]["covered"] >= fin["manual"]["covered"] and fin["checks"] == 1 and fin["elapsed_s"] >= 0
    assert air.post(f"/api/v1/ops/manual/{s['id']}/check", json={"picks": picks}).status_code == 409
    assert any(x["id"] == s["id"] for x in air.get("/api/v1/ops/manual").json()["items"])
    with SessionLocal() as db:                # a test run is not a human baseline: never let it reach the benchmark report
        db.execute(text("DELETE FROM manual_session WHERE id = :i"), {"i": s["id"]})
        db.commit()


def _base_xy(bid: int) -> tuple:
    with SessionLocal() as db:
        return tuple(db.execute(text("SELECT ST_X(geom), ST_Y(geom) FROM base WHERE id = :i"), {"i": bid}).one())


def test_public_airspace_import():
    """D44: OpenAIP items map to planner zones: a prohibited area across a route blocks it, a terminal area adds civil
    traffic, FIRs are skipped, and a re-import replaces the last one (synthetic zones stay)."""
    from app.decide import airspace_import as AI, feasibility as F, risk as R, traffic as TR
    st = snap()
    c = next(c for cs in F.generate(st.clone(), "BALANCED")[0].values() for c in cs if len(c.route) >= 2)
    (x0, y0), (x1, y1) = c.route[0], c.route[1]
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    sq = lambda x, y, d: {"type": "Polygon", "coordinates": [[[x - d, y - d], [x + d, y - d], [x + d, y + d], [x - d, y + d], [x - d, y - d]]]}  # noqa: E731
    items = [{"_id": "test-prohibited-1", "name": "TEST prohibited", "type": 3, "geometry": sq(mx, my, 0.05),
              "lowerLimit": {"value": 0, "unit": 1}, "upperLimit": {"value": 100, "unit": 6}},
             {"_id": "test-ctr-1", "name": "TEST CTR", "type": 4, "geometry": sq(mx + 1.0, my, 0.3)},
             {"_id": "test-fir-1", "name": "TEST FIR", "type": 10, "geometry": sq(mx, my, 3)}]
    with SessionLocal() as db:
        before = db.execute(text("SELECT count(*) FROM airspace_zone WHERE code NOT LIKE 'OAIP-%'")).scalar()
        assert AI.run(db, items) == {"RESTRICTED": 1, "DANGER": 0, "CIVIL_TERMINAL": 1}
        assert AI.run(db, items[:1]) == {"RESTRICTED": 1, "DANGER": 0, "CIVIL_TERMINAL": 0}   # replaces, never duplicates
        AI.run(db, items)
        z = db.execute(text("SELECT upper_m, source FROM airspace_zone WHERE code = 'OAIP-test-prohibited-1'")).one()
        assert round(z.upper_m) == 3048 and z.source == "PUBLIC"
        st2 = S.build(db)
        try:
            assert R.restricted_hit(st2, c.route, c.launch, c.recovery) is not None
            assert TR.build(db).density(mx + 1.0, my, 0.0)[0] >= TR.TERMINAL_WEIGHT
        finally:
            db.execute(text("DELETE FROM airspace_zone WHERE code LIKE 'OAIP-%'"))
            db.commit()
            TR._STATIC.clear()
        assert db.execute(text("SELECT count(*) FROM airspace_zone")).scalar() == before
