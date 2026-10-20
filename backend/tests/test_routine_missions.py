from datetime import datetime, timedelta

from sqlalchemy import func, select

from app import models as M
from app.db import SessionLocal
from app.sim import missions as RM


def test_routine_tasking_rolls_forward_one_day():
    """D64: tomorrow's routine requests are copies of the latest tasking day one day later, dependencies included."""
    with SessionLocal() as db:
        day = RM.tasking_day(db.scalar(select(func.max(M.Mission.window_start)).where(RM._routine().whereclause)))
        lo = datetime.combine(day, datetime.min.time(), RM.IST) + RM.DAY_STARTS
        in_day = lambda d: RM._routine().where(M.Mission.window_start >= lo + timedelta(days=d),  # noqa: E731
                                               M.Mission.window_start < lo + timedelta(days=d + 1)).order_by(M.Mission.id)
        template = list(db.scalars(in_day(0)))
        try:
            assert RM.roll_forward(db, lo + timedelta(hours=6)) == len(template) > 0      # noon on that day: tomorrow only
            copies = list(db.scalars(in_day(1)))
            assert [(c.name, c.window_start) for c in copies] == [(t.name, t.window_start + timedelta(days=1)) for t in template]
            assert len({c.code for c in copies} | {t.code for t in template}) == 2 * len(template)
            by_id = {c.id: c for c in copies}
            for t, c in zip(template, copies):
                assert (t.depends_on_id is None) == (c.depends_on_id is None)
                assert c.depends_on_id is None or c.depends_on_id in by_id
            assert RM.roll_forward(db, lo + timedelta(hours=6)) == 0                      # idempotent within the day
        finally:
            db.rollback()
