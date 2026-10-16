"""Command overview KPIs (FR-CMD-01..05). Values only: no composite scores or rankings."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db

router = APIRouter(tags=["overview"])

PER_BASE = """
WITH ac AS (SELECT base_id, sum(effective) eff, sum(serviceable) svc, sum(airborne) air FROM v_aircraft_serviceability GROUP BY 1),
     q AS (SELECT base_id, bool_and(met) met, count(*) n FROM v_qra_status GROUP BY 1),
     cr AS (SELECT base_id, count(*) FILTER (WHERE available AND aircrew_role IN ('PILOT','RPA_PILOT')) pilots_avail,
                   count(*) FILTER (WHERE aircrew_role IN ('PILOT','RPA_PILOT')) pilots FROM v_aircrew_availability GROUP BY 1),
     f AS (SELECT base_id, sum(current_l) cur, sum(capacity_l) cap, bool_or(current_l < reserve_l) below_reserve
           FROM fuel_storage WHERE grade = 'ATF' GROUP BY 1),
     ad AS (SELECT coalesce(protected_base_id, 0) base_id, count(*) n, count(*) FILTER (WHERE status = 'OPERATIONAL') ok
            FROM air_defence_battery GROUP BY 1),
     rd AS (SELECT base_id, count(*) n, count(*) FILTER (WHERE status = 'OPERATIONAL') ok FROM radar_site GROUP BY 1),
     al AS (SELECT base_id, count(*) FILTER (WHERE severity = 'CRITICAL') crit, count(*) FILTER (WHERE severity = 'WARNING') warn,
                   count(*) n FROM alert WHERE status <> 'CLEARED' GROUP BY 1)
SELECT b.id, b.code, b.name, b.base_type, c.code AS command, ST_Y(b.geom) lat, ST_X(b.geom) lon,
       coalesce(ac.eff, 0)::int AS aircraft, coalesce(ac.svc, 0)::int AS serviceable, coalesce(ac.air, 0)::int AS airborne,
       CASE WHEN ac.eff > 0 THEN round(100.0 * ac.svc / ac.eff) END AS serviceability,
       q.met AS qra_met, coalesce(q.n, 0)::int AS qra_postures,
       coalesce(cr.pilots_avail, 0)::int AS pilots_available, coalesce(cr.pilots, 0)::int AS pilots,
       CASE WHEN f.cap > 0 THEN round(100.0 * f.cur / f.cap) END AS atf_pct, coalesce(f.below_reserve, false) AS below_reserve,
       coalesce(ad.n, 0)::int AS ad_total, coalesce(ad.ok, 0)::int AS ad_ok, coalesce(rd.n, 0)::int AS radar_total,
       coalesce(rd.ok, 0)::int AS radar_ok, coalesce(al.crit, 0)::int AS alerts_critical,
       coalesce(al.warn, 0)::int AS alerts_warning, coalesce(al.n, 0)::int AS alerts
FROM base b JOIN command c ON c.id = b.command_id
LEFT JOIN ac ON ac.base_id = b.id LEFT JOIN q ON q.base_id = b.id LEFT JOIN cr ON cr.base_id = b.id
LEFT JOIN f ON f.base_id = b.id LEFT JOIN ad ON ad.base_id = b.id LEFT JOIN rd ON rd.base_id = b.id
LEFT JOIN al ON al.base_id = b.id
WHERE b.side = 'OWN' ORDER BY c.code, b.code
"""


def roll(bases: list[dict]) -> dict:
    s = lambda k: sum(b[k] or 0 for b in bases)  # noqa: E731
    qra = [b for b in bases if b["qra_postures"]]
    return {"bases": len(bases), "aircraft": s("aircraft"), "serviceable": s("serviceable"), "airborne": s("airborne"),
            "serviceability": round(100 * s("serviceable") / s("aircraft")) if s("aircraft") else None,
            "qra_met": sum(1 for b in qra if b["qra_met"]), "qra_bases": len(qra),
            "pilots_available": s("pilots_available"), "pilots": s("pilots"),
            "below_reserve": sum(1 for b in bases if b["below_reserve"]),
            "ad_ok": s("ad_ok"), "ad_total": s("ad_total"), "radar_ok": s("radar_ok"), "radar_total": s("radar_total"),
            "alerts_critical": s("alerts_critical"), "alerts_warning": s("alerts_warning"), "alerts": s("alerts")}


@router.get("/overview")
def overview(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    bases = [dict(r._mapping) for r in db.execute(text(PER_BASE))]
    for b in bases:
        b["serviceability"] = float(b["serviceability"]) if b["serviceability"] is not None else None
        b["atf_pct"] = float(b["atf_pct"]) if b["atf_pct"] is not None else None
    area_ad = db.execute(text("SELECT count(*), count(*) FILTER (WHERE status='OPERATIONAL') FROM air_defence_battery "
                              "WHERE protected_base_id IS NULL")).one()
    commands = []
    for code, name, op in db.execute(text("SELECT code, name, is_operational FROM command ORDER BY id")):
        mine = [b for b in bases if b["command"] == code]
        commands.append({"code": code, "name": name, "operational": op, **roll(mine)})
    theatre = roll(bases)
    theatre["ad_total"] += area_ad[0]
    theatre["ad_ok"] += area_ad[1]
    return {"theatre": theatre, "commands": commands, "bases": bases}


@router.get("/kpi-snapshots")
def kpi_snapshots(scope: str = "THEATRE", scope_id: int | None = None, metric: str = "serviceability",
                  user: dict = Depends(current_user), db: Session = Depends(get_db)):
    q = "SELECT ts, value FROM kpi_snapshot WHERE scope = :scope AND metric = :metric"
    q += " AND scope_id = :sid" if scope_id is not None else " AND scope_id IS NULL"
    q += " AND ts > sim_now() - interval '24 hours' ORDER BY ts"
    return [dict(r._mapping) for r in db.execute(text(q), {"scope": scope, "metric": metric, "sid": scope_id})]
