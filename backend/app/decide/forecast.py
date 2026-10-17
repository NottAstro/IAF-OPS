"""Forecasts (PHASE2_IMPLEMENTATION_PLAN §7.6): explainable projections from the snapshot. Rule-based except the
expected defects, which come from the snag-risk model (decide/predict.py, D38). Every series is SIMULATED."""
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import config as D
from . import weather_impact as W
from .predict import tail_risk
from .resources import Req, aircraft_free, crew_eligible, crew_free, pilot_role
from .snapshot import OpsState

SNAG_PER_SORTIE = 0.06       # fallback before a snag-risk model exists (the history's average defect rate)


def _times(st: OpsState, hours: int, step: int):
    return [st.now + timedelta(hours=h) for h in range(0, hours + 1, step)]


def base(db: Session, st: OpsState, base_id: int, hours: int = 72, step: int = 3) -> dict:
    b = st.bases[base_id]
    times = _times(st, hours, step)
    planned = defaultdict(list)        # type_id -> (launch, predicted defect chance) per tail of sorties not yet flown here
    for r in db.execute(text("""SELECT a.aircraft_type_id, s.planned_launch_ts, sa.aircraft_id,
                                       extract(epoch FROM s.planned_recovery_ts - s.planned_launch_ts) / 3600 AS h FROM sortie s
                                JOIN sortie_aircraft sa ON sa.sortie_id = s.id JOIN aircraft a ON a.id = sa.aircraft_id
                                WHERE s.departure_base_id = :b AND s.status IN ('PLANNED','CREWED','READY')"""), {"b": base_id}):
        a = st.aircraft.get(r[2])
        planned[r[0]].append((r[1], tail_risk(st, a, float(r[3])) if a and st.snag else SNAG_PER_SORTIE))
    series = []
    for (bid, tid), ids in sorted(st.by_base_type.items(), key=lambda kv: st.types[kv[0][1]].name):
        if bid != base_id:
            continue
        t = st.types[tid]
        pts = []
        for ts in times:
            free = sum(1 for i in ids if aircraft_free(st, st.aircraft[i], ts, ts + timedelta(minutes=1)))
            risks = [p for x, p in planned[tid] if x <= ts]
            exp = max(0.0, free - sum(risks))
            pilots = sum(1 for cid in st.crew_by_base.get(base_id, ()) if crew_eligible(st.crew[cid], t, Req(), ts)
                         and crew_free(st, st.crew[cid], ts, ts + timedelta(minutes=1)))
            pts.append({"ts": ts.isoformat(), "aircraft": round(exp, 1), "band": round(sum(p * (1 - p) for p in risks) ** 0.5, 1),
                        "expected_defects": round(sum(risks), 2), "pilots": pilots})
        series.append({"type": t.name, "type_id": tid, "role": t.role, "points": pts})
    fuel = st.fuel.get(base_id)
    fuel_pts = []
    if fuel:
        daily = db.execute(text("SELECT coalesce(sum(daily_issue_l), 0) FROM v_fuel_days WHERE base_id = :b AND grade = 'ATF'"),
                           {"b": base_id}).scalar() or 0
        for ts in times:
            days = (ts - st.now).total_seconds() / 86400
            level = fuel["current_l"] - fuel["committed_l"] * min(1, days) - daily * days
            if fuel["replenish_eta"] and fuel["replenish_eta"] <= ts:
                level = max(level, fuel["capacity_l"] * 0.9 - daily * (ts - fuel["replenish_eta"]).total_seconds() / 86400)
            fuel_pts.append({"ts": ts.isoformat(), "pct": round(100 * max(0, level) / fuel["capacity_l"], 1)})
    wx = []
    for ts in times:
        row = st.wx_at(base_id, ts)
        wx.append({"ts": ts.isoformat(), "cat": row[6] if row else None, "source": row[7] if row else None,
                   "night": W.is_night(b.lon, b.lat, ts)})
    reserve = round(100 * fuel["reserve_l"] / fuel["capacity_l"], 1) if fuel else None
    breach = next((p["ts"] for p in fuel_pts if reserve is not None and p["pct"] < reserve), None)
    return {"base": {"id": b.id, "code": b.code, "name": b.name}, "times": [t.isoformat() for t in times], "aircraft": series,
            "fuel": {"points": fuel_pts, "reserve_pct": reserve, "reserve_breach": breach,
                     "replenish_eta": fuel["replenish_eta"].isoformat() if fuel and fuel["replenish_eta"] else None},
            "weapons": st.stock.get(base_id, {}), "weather": wx, "simulated": True,
            "method": "Maintenance returns, planned sorties × each tail's predicted defect risk (snag-risk model), crew "
                      "rest and currency, fuel use at the 3-day average plus planned issues, replenishment ETA."}


def wx_impact(st: OpsState, hours: int = 6) -> list[dict]:
    """Bases whose forecast drops below VFR in the next `hours` (Ops view rings, planner hint)."""
    out = []
    for b in st.bases.values():
        worst, when = "VFR", None
        for h in range(0, hours + 1):
            row = st.wx_at(b.id, st.now + timedelta(hours=h))
            if row and W.CAT_ORDER.index(row[6]) > W.CAT_ORDER.index(worst):
                worst, when = row[6], row[0]
        closed = not b.runway_ok(st.now) or any(not b.runway_ok(st.now + timedelta(hours=h)) for h in range(hours))
        if worst != "VFR" or closed:
            out.append({"base_id": b.id, "code": b.code, "lon": b.lon, "lat": b.lat, "worst": worst,
                        "at": when.isoformat() if when else None, "runway_closed": closed})
    return out
