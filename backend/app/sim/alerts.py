"""Alert rules evaluated every tick (FR-ALR-01, DATA_MODEL §9.4). Thresholds are SIMULATED policy.

Each rule yields desired alerts keyed by dedup_key; reconcile() raises new ones, updates changed ones and clears
the ones whose condition went away. Heavy rules run every N ticks; only their kinds are reconciled that tick.
"""
from datetime import datetime, timezone

from sqlalchemy import select, text

from ..live import feeds
from ..models import Alert
from ..weather import metar

SEV = {"INFO": 0, "CAUTION": 1, "WARNING": 2, "CRITICAL": 3}


def q(db, sql, **p):
    return [r._mapping for r in db.execute(text(sql), p)]


def fuel(db):
    for r in q(db, """SELECT fs.id, fs.base_id, b.command_id, b.code, fs.current_l, fs.capacity_l, fs.reserve_l
                      FROM fuel_storage fs JOIN base b ON b.id = fs.base_id WHERE fs.grade = 'ATF'"""):
        pct = 100 * r["current_l"] / r["capacity_l"]
        if r["current_l"] < r["reserve_l"]:
            yield ("FUEL_BELOW_RESERVE", "CRITICAL", r, f"{r['code']}: ATF below reserve ({pct:.0f}% of capacity)", pct, 15)
        elif pct < 25:
            yield ("LOW_FUEL", "WARNING", r, f"{r['code']}: ATF at {pct:.0f}% of capacity", pct, 25)
        elif pct < 40:
            yield ("LOW_FUEL", "CAUTION", r, f"{r['code']}: ATF at {pct:.0f}% of capacity", pct, 40)


def serviceability(db):
    for r in q(db, """SELECT v.base_id, b.command_id, b.code, sum(v.serviceable) s, sum(v.effective) e
                      FROM v_aircraft_serviceability v JOIN base b ON b.id = v.base_id
                      GROUP BY 1, 2, 3 HAVING sum(v.effective) >= 4"""):
        pct = 100 * r["s"] / r["e"]
        sev = "CRITICAL" if pct < 45 else "WARNING" if pct < 60 else "CAUTION" if pct < 70 else None
        if sev:
            yield ("LOW_SERVICEABILITY", sev, {**r, "id": r["base_id"]},
                   f"{r['code']}: aircraft serviceability {pct:.0f}% ({r['s']}/{r['e']})", pct, 70)


def qra(db):
    for r in q(db, """SELECT q.base_id, b.command_id, b.code, q.required_aircraft, q.qra_aircraft, q.qra_crew
                      FROM v_qra_status q JOIN base b ON b.id = q.base_id WHERE NOT q.met"""):
        sev = "CRITICAL" if r["qra_aircraft"] == 0 or r["qra_crew"] == 0 else "WARNING"
        yield ("QRA_SHORTFALL", sev, {**r, "id": r["base_id"]},
               f"{r['code']}: QRA short (aircraft {r['qra_aircraft']}/{r['required_aircraft']}, crew {r['qra_crew']}/{r['required_aircraft']})",
               r["qra_aircraft"], r["required_aircraft"])


def crew(db):
    for r in q(db, """WITH a AS (SELECT base_id, count(*) FILTER (WHERE available AND aircrew_role IN ('PILOT','RPA_PILOT')) p
                                 FROM v_aircrew_availability GROUP BY 1),
                           s AS (SELECT base_id, sum(serviceable) n FROM v_aircraft_serviceability GROUP BY 1)
                      SELECT s.base_id, b.command_id, b.code, coalesce(a.p, 0) p, s.n FROM s JOIN base b ON b.id = s.base_id
                      LEFT JOIN a ON a.base_id = s.base_id WHERE s.n >= 4"""):
        ratio = r["p"] / r["n"]
        sev = "CRITICAL" if ratio < 0.7 else "WARNING" if ratio < 1.0 else "CAUTION" if ratio < 1.2 else None
        if sev:
            yield ("CREW_SHORTFALL", sev, {**r, "id": r["base_id"]},
                   f"{r['code']}: {r['p']} pilots available for {r['n']} serviceable aircraft", ratio, 1.2)
    for r in q(db, """SELECT c.base_id, b.command_id, b.code, count(*) n FROM aircrew c JOIN v_aircrew_fatigue f ON f.aircrew_id = c.id
                      JOIN base b ON b.id = c.base_id WHERE f.fatigued AND c.duty_status IN ('ON_DUTY','QRA','BRIEFED')
                      GROUP BY 1, 2, 3"""):
        yield ("CREW_FATIGUE", "WARNING", {**r, "id": r["base_id"]}, f"{r['code']}: {r['n']} fatigued aircrew rostered", r["n"], 0)
    for r in q(db, """SELECT c.base_id, b.command_id, b.code,
                             count(*) FILTER (WHERE c.medical_valid_until < sim_now()::date) expired,
                             count(*) FILTER (WHERE c.medical_valid_until BETWEEN sim_now()::date AND sim_now()::date + 7) soon
                      FROM aircrew c JOIN base b ON b.id = c.base_id GROUP BY 1, 2, 3
                      HAVING count(*) FILTER (WHERE c.medical_valid_until <= sim_now()::date + 7) > 0"""):
        sev = "WARNING" if r["expired"] else "CAUTION"
        yield ("MEDICAL_EXPIRY", sev, {**r, "id": r["base_id"]},
               f"{r['code']}: medicals expired {r['expired']}, expiring ≤ 7 d {r['soon']}", r["expired"] + r["soon"], 0)


def maintenance_stock(db):
    for r in q(db, """SELECT a.home_base_id base_id, b.command_id, b.code,
                             count(*) FILTER (WHERE a.status = 'AOG') aog,
                             count(*) FILTER (WHERE a.status NOT IN ('MAINT_SCHEDULED','MAINT_UNSCHEDULED','AOG','DEPOT','RETIRED')
                                              AND a.airframe_hours >= a.next_maint_due_hours) overdue
                      FROM aircraft a JOIN base b ON b.id = a.home_base_id GROUP BY 1, 2, 3
                      HAVING count(*) FILTER (WHERE a.status = 'AOG') > 0
                          OR count(*) FILTER (WHERE a.airframe_hours >= a.next_maint_due_hours
                                              AND a.status NOT IN ('MAINT_SCHEDULED','MAINT_UNSCHEDULED','AOG','DEPOT','RETIRED')) > 0"""):
        sev = "WARNING" if r["overdue"] else "CAUTION"
        yield ("MAINTENANCE_OVERDUE", sev, {**r, "id": r["base_id"]},
               f"{r['code']}: {r['aog']} AOG, {r['overdue']} past maintenance due", r["aog"] + r["overdue"], 0)
    for r in q(db, """SELECT w.base_id, b.command_id, b.code, count(*) FILTER (WHERE l.qty_on_hand < l.reorder_level) below,
                             count(*) FILTER (WHERE l.qty_on_hand <= 0) zero
                      FROM stock_level l JOIN warehouse w ON w.id = l.warehouse_id JOIN base b ON b.id = w.base_id
                      GROUP BY 1, 2, 3 HAVING count(*) FILTER (WHERE l.qty_on_hand < l.reorder_level) > 0"""):
        sev = "CRITICAL" if r["zero"] else "CAUTION"
        yield ("STOCK_BELOW_REORDER", sev, {**r, "id": r["base_id"]},
               f"{r['code']}: {r['below']} stock items below reorder level ({r['zero']} at zero)", r["below"], 0)


def sites(db):
    for kind, sql in (("RADAR_DOWN", "SELECT r.id, r.code, r.status, r.base_id, b.command_id FROM radar_site r LEFT JOIN base b ON b.id = r.base_id WHERE r.status <> 'OPERATIONAL'"),
                      ("AD_DEGRADED", "SELECT d.id, d.code, d.status, d.protected_base_id base_id, d.command_id FROM air_defence_battery d WHERE d.status <> 'OPERATIONAL'"),
                      ("COMMS_DOWN", "SELECT n.id, n.code, n.status, n.base_id, b.command_id FROM comms_node n LEFT JOIN base b ON b.id = n.base_id WHERE n.status <> 'UP'")):
        for r in q(db, sql):
            sev = "CAUTION" if r["status"] == "DEGRADED" else "WARNING"
            yield (kind, sev, r, f"{r['code']}: {r['status'].lower()}", None, None)


def weather(db):
    cat_sev = {"MVFR": "CAUTION", "IFR": "WARNING", "LIFR": "CRITICAL"}
    for r in q(db, "SELECT id, code, command_id, metar_station FROM base WHERE side = 'OWN' AND metar_station IS NOT NULL"):
        m = metar.STATE["metars"].get(r["metar_station"])
        if m and m.get("flightCategory") in cat_sev:
            yield ("WX_BELOW_MINIMA", cat_sev[m["flightCategory"]], {**r, "base_id": r["id"]},
                   f"{r['code']}: {m['flightCategory']} at {r['metar_station']}", None, None)


def feeds_rule(db):
    import time
    for name, st in feeds.STATUS.items():
        age = time.time() - st["last_ok"] if st["last_ok"] else None
        if age is None or age > 300:
            yield ("FEED_STALE", "WARNING", {"id": None, "base_id": None, "command_id": None, "code": name},
                   f"Live feed {name} unavailable", age, 300)
        elif age > 60:
            yield ("FEED_STALE", "CAUTION", {"id": None, "base_id": None, "command_id": None, "code": name},
                   f"Live feed {name} stale ({age:.0f} s)", age, 60)


RULES = [  # (rule, every N ticks, kinds it owns)
    (fuel, 1, {"FUEL_BELOW_RESERVE", "LOW_FUEL"}), (serviceability, 2, {"LOW_SERVICEABILITY"}), (qra, 1, {"QRA_SHORTFALL"}),
    (crew, 6, {"CREW_SHORTFALL", "CREW_FATIGUE", "MEDICAL_EXPIRY"}),
    (maintenance_stock, 6, {"MAINTENANCE_OVERDUE", "STOCK_BELOW_REORDER"}), (sites, 1, {"RADAR_DOWN", "AD_DEGRADED", "COMMS_DOWN"}),
    (weather, 2, {"WX_BELOW_MINIMA"}), (feeds_rule, 2, {"FEED_STALE"}),
]


def evaluate(ctx, unknowns: dict) -> list[dict]:
    db = ctx.db
    desired, kinds = {}, set()
    for rule, every, owned in RULES:
        if ctx.tick % every:
            continue
        kinds |= owned
        for kind, sev, r, msg, value, threshold in rule(db):
            ent_id = r.get("id")
            key = f"{kind}:{r.get('base_id')}:{ent_id if kind not in ('LOW_SERVICEABILITY', 'QRA_SHORTFALL', 'CREW_SHORTFALL', 'CREW_FATIGUE', 'MEDICAL_EXPIRY', 'MAINTENANCE_OVERDUE', 'STOCK_BELOW_REORDER', 'WX_BELOW_MINIMA') else ''}:{r.get('code') if kind == 'FEED_STALE' else ''}"
            desired[key] = dict(kind=kind, severity=sev, entity_type=None, entity_id=ent_id, base_id=r.get("base_id"),
                                command_id=r.get("command_id"), message=msg,
                                value=float(value) if value is not None else None,
                                threshold=float(threshold) if threshold is not None else None)
    kinds.add("UNKNOWN_TRACK")
    for u in unknowns.values():
        if u.get("detected"):
            close = u.get("phase") in ("LOITER",) or (u.get("phase") == "INBOUND" and u.get("near_border_km", 999) < 60)
            desired[f"UNKNOWN_TRACK:{u['id']}"] = dict(
                kind="UNKNOWN_TRACK", severity="CRITICAL" if close else "WARNING", entity_type="track", entity_id=None,
                base_id=None, command_id=None, value=None, threshold=None,
                message=f"Unknown track {u['id']} near the border (simulated)"
                        + (f"; QRA scrambled from {u['interceptor_base']}" if u.get("interceptor_base") else ""))
    return reconcile(db, desired, kinds)


def reconcile(db, desired: dict, kinds: set) -> list[dict]:
    now = datetime.now(timezone.utc)
    changed = []
    existing = {a.dedup_key: a for a in db.scalars(select(Alert).where(Alert.status != "CLEARED", Alert.kind.in_(kinds)))}
    for key, a in existing.items():
        if key not in desired:
            a.status, a.cleared_at = "CLEARED", now
            changed.append({"event": "cleared", "id": a.id, "kind": a.kind, "base_id": a.base_id, "message": a.message})
    for key, d in desired.items():
        a = existing.get(key)
        if a is None:
            a = Alert(dedup_key=key, status="OPEN", raised_at=now, **d)
            db.add(a)
            db.flush()
            changed.append({"event": "raised", "id": a.id, **d})
        elif SEV[d["severity"]] != SEV[a.severity] or a.message != d["message"]:
            escalated = SEV[d["severity"]] > SEV[a.severity]
            a.severity, a.message, a.value = d["severity"], d["message"], d["value"]
            if escalated:
                a.status = "OPEN"
                changed.append({"event": "escalated", "id": a.id, **d})
    return changed


# ---------------------------------------------------------------- alerts without the simulator
async def loop(hub, every_s: float = 30) -> None:
    """Evaluate alert rules on current data when the tick simulator is off (alerts are data checks, not simulation)."""
    import asyncio
    import logging
    tick = 0
    while True:
        await asyncio.sleep(every_s)
        tick += 1
        try:
            raised = await asyncio.to_thread(_evaluate_once, tick * 6)  # multiple of 6: every rule runs
        except Exception:
            logging.getLogger("alerts").exception("alert evaluation failed")
            continue
        for a in raised:
            await hub.broadcast("alert", a, None)


def _evaluate_once(tick: int) -> list[dict]:
    from types import SimpleNamespace

    from ..db import SessionLocal
    with SessionLocal() as db:
        raised = evaluate(SimpleNamespace(db=db, tick=tick), {})
        db.commit()
    return raised
