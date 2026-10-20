"""Routine tasking repeats (D64). The generator seeds two IST days of mission requests; at ×10 the simulator flies through
them in about five hours, after which the planner has nothing to plan. Each new simulated IST day, the routine requests of
the latest tasking day are copied one day forward, so tomorrow's tasking is always there. Scenario pop-ups, split parts and
missions people created are not copied."""
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as M

IST = ZoneInfo("Asia/Kolkata")
DAY_STARTS = timedelta(hours=6)      # a tasking day runs 06:00–06:00 IST: night windows (up to 02:00) belong to the day before


def tasking_day(ts: datetime) -> date:
    return (ts.astimezone(IST) - DAY_STARTS).date()


def _routine():
    return select(M.Mission).where(M.Mission.source == "SYNTHETIC", M.Mission.exercise_run_id.is_(None),
                                   M.Mission.parent_mission_id.is_(None), ~M.Mission.code.like("%-POP-%"))


def roll_forward(db: Session, now: datetime) -> int:
    """Copy routine tasking forward until tomorrow (IST) has its requests. Returns how many missions were added."""
    last = db.scalar(select(func.max(M.Mission.window_start)).where(_routine().whereclause))
    if last is None:
        return 0
    want, day = now.astimezone(IST).date() + timedelta(days=1), tasking_day(last)
    seq: dict[str, int] = {}
    for (code,) in db.execute(select(M.Mission.code)):
        m = re.fullmatch(r"(.+)-(\d+)", code)
        if m:
            seq[m[1]] = max(seq.get(m[1], 0), int(m[2]))
    added = 0
    while day < want:
        lo = datetime.combine(day, datetime.min.time(), IST) + DAY_STARTS
        template = list(db.scalars(_routine().where(M.Mission.window_start >= lo, M.Mission.window_start < lo + timedelta(days=1))
                                   .order_by(M.Mission.id)))
        if not template:
            break
        copies: dict[int, M.Mission] = {}
        for t in template:
            prefix = t.code.rsplit("-", 1)[0]
            seq[prefix] = seq.get(prefix, 0) + 1
            c = M.Mission(code=f"{prefix}-{seq[prefix]:03d}", name=t.name, mission_type=t.mission_type, priority=t.priority,
                          window_start=t.window_start + timedelta(days=1), window_end=t.window_end + timedelta(days=1),
                          area_geom=t.area_geom, status="REQUESTED" if t.status == "REQUESTED" else "APPROVED",
                          requesting_command_id=t.requesting_command_id, target_geom=t.target_geom, target_base_id=t.target_base_id,
                          required_aircraft=t.required_aircraft, eligible_roles=t.eligible_roles, loadout_code=t.loadout_code,
                          on_station_min=t.on_station_min, min_quals=t.min_quals, max_risk=t.max_risk, notes=t.notes,
                          approved_at=None if t.status == "REQUESTED" else now, is_simulated=True, source="SYNTHETIC")
            db.add(c)
            copies[t.id] = c
        db.flush()
        for t in template:             # D41: a barrier CAP depends on the copy of its AEW&C orbit
            if t.depends_on_id in copies:
                copies[t.id].depends_on_id = copies[t.depends_on_id].id
        added += len(template)
        day += timedelta(days=1)
    return added
