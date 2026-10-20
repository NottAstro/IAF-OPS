"""Inventory transfers (ARCHITECTURE D56): the optimiser sends the nearest spare stock, never drains a donor below its
reserve, reports what nobody can supply; approving debits the donor (audited), the simulator credits the receiver at the
ETA, and the planner counts stock on the road. Needs a seeded database and the dev server stopped. Every test rolls back."""
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from app import config
from app import models as M
from app.db import SessionLocal
from app.decide import logistics as LG
from app.decide import snapshot as S
from app.main import app
from app.services import transfers as TR

AIRHQ = {"id": 2, "role": "COMMAND_HQ", "username": "airhq"}


def _base(db, code):
    return db.execute(text("SELECT id FROM base WHERE code = :c"), {"c": code}).scalar()


def _fuel(db, base_id):
    return db.execute(text("SELECT sum(current_l), sum(reserve_l) FROM fuel_storage WHERE base_id = :b AND grade = 'ATF'"),
                      {"b": base_id}).one()


def test_min_cost_flow_takes_the_nearest_spare_and_reports_the_rest():
    where = {1: (75.0, 31.0), 2: (75.3, 31.1), 3: (80.0, 22.0), 4: (77.0, 30.0)}     # 2 is near 1; 3 is far
    moves, short = LG._solve({1: 10}, {2: 6, 3: 50}, where)
    got = {(d, r): q for d, r, q, _ in moves}
    assert got.get((2, 1)) == 6, moves                    # all the near donor can spare
    assert sum(q for _, r, q, _ in moves if r == 1) + short.get(1, 0) == 10
    moves, short = LG._solve({1: 10}, {3: 50}, {1: where[1], 3: (95.0, 10.0)})      # only donor beyond the road limit
    assert moves == [] and short == {1: 10}


def test_a_base_below_reserve_gets_fuel_from_a_donor_that_stays_above_its_own():
    with SessionLocal() as db:
        hx = _base(db, "VIHX")
        cur, res = _fuel(db, hx)
        db.execute(text("UPDATE fuel_storage SET current_l = reserve_l * 0.5 WHERE base_id = :b AND grade = 'ATF'"), {"b": hx})
        st = S.build(db)
        out = LG.recommend(db, st, None, set())
        into = [m for m in out["moves"] if m["kind"] == "FUEL" and m["to_base"]["id"] == hx]
        assert into, out["unmet"]
        short = st.fuel[hx]["reserve_l"] - st.fuel[hx]["current_l"]
        assert sum(m["qty"] for m in into) >= short
        for m in into:
            d = st.fuel[m["from_base"]["id"]]
            assert d["current_l"] - m["qty"] >= d["reserve_l"]          # never below the donor's own reserve
        db.rollback()


def test_approve_debits_the_donor_and_delivery_credits_the_receiver():
    with SessionLocal() as db:
        bt, hx = _base(db, "VIBT"), _base(db, "VIHX")
        before_d, before_r = _fuel(db, bt)[0], _fuel(db, hx)[0]
        t = TR.approve(db, AIRHQ, "FUEL", "ATF", 12000, bt, hx, reason="test")
        db.flush()
        assert abs(_fuel(db, bt)[0] - (before_d - 12000)) < 1 and t.status == "IN_TRANSIT"
        assert db.execute(text("SELECT count(*) FROM audit_log WHERE entity_type = 'inventory_transfer' AND entity_id = :i "
                               "AND action = 'CREATE'"), {"i": t.id}).scalar() == 1
        # the planner counts it as arriving
        assert abs(S.build(db).fuel[hx]["current_l"] - (before_r + 12000)) < 1
        TR.deliver_due(db, t.eta + timedelta(minutes=1))
        db.flush()
        assert t.status == "DELIVERED" and abs(_fuel(db, hx)[0] - (before_r + 12000)) < 1
        assert db.execute(text("SELECT count(*) FROM fuel_transaction WHERE kind = 'TRANSFER_IN' AND quantity_l > 0 AND ts = :t"),
                          {"t": t.eta + timedelta(minutes=1)}).scalar() >= 1
        db.rollback()


def test_a_donor_cannot_be_drained_below_its_reserve():
    with SessionLocal() as db:
        bt, hx = _base(db, "VIBT"), _base(db, "VIHX")
        cur, res = _fuel(db, bt)
        try:
            TR.approve(db, AIRHQ, "FUEL", "ATF", cur - res + 1000, bt, hx)
            raise AssertionError("allowed a transfer below the donor's reserve")
        except TR.TransferError:
            pass
        db.rollback()


def test_transfers_are_for_air_hq_and_admin_only():
    for who in ("viewer", "cdr.viax"):
        c = TestClient(app)
        assert c.post("/api/v1/auth/login", json={"username": who, "password": config.DEMO_PASSWORD}).status_code == 200
        r = c.post("/api/v1/ops/transfers", json={"moves": [{"kind": "FUEL", "category": "ATF", "qty": 1000, "from_base_id": 1,
                                                             "to_base_id": 2}]})
        assert r.status_code == 403, (who, r.status_code)


def test_a_move_offers_other_donors_that_could_send_the_same():
    """D63: besides the planner's donor, the nearest other bases with enough spare are offered, nearest first."""
    with SessionLocal() as db:
        hx = _base(db, "VIHX")
        db.execute(text("UPDATE fuel_storage SET current_l = reserve_l * 0.5 WHERE base_id = :b AND grade = 'ATF'"), {"b": hx})
        out = LG.recommend(db, S.build(db), None, set())
        m = next(m for m in out["moves"] if m["kind"] == "FUEL" and m["to_base"]["id"] == hx)
        alts = m["alternatives"]
        assert alts, "another base within road reach has spare fuel"
        assert all(a["from_base"]["id"] not in (m["from_base"]["id"], hx) and a["spare"] >= m["qty"] for a in alts)
        assert [a["distance_km"] for a in alts] == sorted(a["distance_km"] for a in alts)
        db.rollback()
