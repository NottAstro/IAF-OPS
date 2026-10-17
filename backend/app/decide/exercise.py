"""Exercise mode (PHASE2_IMPLEMENTATION_PLAN §8): runs, directing-staff injects and the after-action report.

Injects change the synthetic world exactly as a real event would (runway status, weather, threat zones, aircraft
status, new missions, fuel); the re-tasking monitor then sees the committed plan break and proposes a repair. Nothing
here touches the plan directly.
"""
import copy
import json
from datetime import datetime, timedelta

from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .. import models as M
from ..audit import audit
from ..geo import offset
from . import config as D

KINDS = {
    "RUNWAY_CLOSED": "Close a base's runways for some hours",
    "WX_FRONT": "Weather below minima over bases",
    "THREAT_ZONE": "Threat activity zone (generic)",
    "AIRCRAFT_GROUNDING": "Ground aircraft of a type",
    "MISSION_POPUP": "Pop-up mission",
    "FUEL_DELAY": "Fuel convoy delayed",
    "RADAR_DOWN": "Radars at a base go offline",
    "UNKNOWN_TRACK": "Unknown track near the border",
}
WX = {"MVFR": (2000, 6000), "IFR": (700, 3000), "LIFR": (300, 1000)}


def current(db: Session) -> M.ExerciseRun | None:
    return db.scalars(select(M.ExerciseRun).where(M.ExerciseRun.status == "RUNNING").order_by(M.ExerciseRun.id.desc())).first()


def sim_now(db: Session) -> datetime:
    return db.execute(text("SELECT sim_now()")).scalar()


def _base(db: Session, code: str, type_name: str | None = None) -> M.AirBase:
    """code "AUTO": the base with the most committed packages launching in the next 8 h (of that type, if given), so a
    scripted inject always tests the plan that is actually committed."""
    if (code or "").upper() == "AUTO":
        row = db.execute(text("""SELECT b.code FROM plan_item pi JOIN plan p ON p.id = pi.plan_id AND p.status = 'COMMITTED'
                                 JOIN base b ON b.id = pi.base_id JOIN aircraft_type t ON t.id = pi.aircraft_type_id
                                 WHERE pi.status = 'COMMITTED' AND pi.launch_ts BETWEEN sim_now() + interval '20 minutes'
                                   AND sim_now() + interval '8 hours' AND (CAST(:t AS text) IS NULL OR t.name = :t)
                                 GROUP BY b.code ORDER BY count(*) DESC, b.code LIMIT 1"""), {"t": type_name}).first()
        code = row[0] if row else "VIAX"
    b = db.scalars(select(M.AirBase).where(M.AirBase.code == (code or "").upper(), M.AirBase.side == "OWN")).first()
    if not b:
        raise ValueError(f"Unknown IAF base {code}")
    return b


def start(db: Session, user: dict, scenario_id: int | None, name: str | None, speed: float | None) -> M.ExerciseRun:
    run = current(db)
    if run:
        stop(db, user)
    sc = db.get(M.Scenario, scenario_id) if scenario_id else None
    now = sim_now(db)
    injects = [dict(i, applied_at=None) for i in (sc.injects if sc else [])]
    run = M.ExerciseRun(scenario_id=sc.id if sc else None, name=name or (sc.name if sc else "Free play"), status="RUNNING",
                        started_sim=now, injects=injects, kpi_timeline=[], started_by=user["id"])
    db.add(run)
    st = db.get(M.SimState, 1, with_for_update=True)
    st.paused = False
    if speed or sc:
        st.speed = speed or sc.speed
    db.flush()
    audit(db, user, "SIM_CONTROL", "exercise_run", run.id, None, None,
          {"action": "start", "scenario": run.name, "speed": st.speed, "injects": len(injects)})
    return run


def stop(db: Session, user: dict | None) -> None:
    run = current(db)
    if not run:
        return
    run.status, run.ended_sim = "ENDED", sim_now(db)
    audit(db, user, "SIM_CONTROL", "exercise_run", run.id, None, None, {"action": "stop"})


def inject(db: Session, user: dict | None, kind: str, params: dict, label: str | None = None, sim=None,
           record: bool = True) -> str:
    """Apply one inject now. Returns a sentence describing what happened."""
    now = sim_now(db)
    hours = float(params.get("hours", 6))
    until = now + timedelta(hours=hours)
    if kind == "RUNWAY_CLOSED":
        b = _base(db, params["base"])
        db.execute(text("UPDATE runway SET status = 'CLOSED', version = version + 1 WHERE base_id = :b"), {"b": b.id})
        z = db.scalars(select(M.AirspaceZone).where(M.AirspaceZone.code == f"RWY-{b.code}")).first()
        poly = Polygon([offset(*_pt(db, b), 6, 360 * i / 12) for i in range(12)])
        if z:
            z.active_from, z.active_to = now, until
        else:
            from geoalchemy2.shape import from_shape
            db.add(M.AirspaceZone(code=f"RWY-{b.code}", name=f"{b.code} runway closed (exercise)", kind="TEMP_RESERVATION",
                                  geom=from_shape(poly, srid=4326), lower_m=0, upper_m=3000, capacity_packages=0,
                                  base_id=b.id, active_from=now, active_to=until))
        msg = f"{b.code} runways closed until {until:%H:%M}Z"
    elif kind == "WX_FRONT":
        cat = params.get("cat", "IFR")
        ceil, vis = WX.get(cat, WX["IFR"])
        codes = [c.upper() for c in params.get("bases", [])]
        for code in codes:
            b = _base(db, code)
            t = now.replace(minute=0, second=0, microsecond=0)
            while t < until:
                db.execute(text("""INSERT INTO wx_base_forecast (base_id, valid_ts, ceiling_ft, vis_m, wind_kt, gust_kt, wind_dir,
                                   flight_cat, source, fetched_at, is_simulated) VALUES (:b, :t, :c, :v, 18, 28, 180, :cat,
                                   'EXERCISE', now(), true) ON CONFLICT (base_id, valid_ts, source) DO UPDATE
                                   SET ceiling_ft = :c, vis_m = :v, flight_cat = :cat"""),
                           {"b": b.id, "t": t, "c": ceil, "v": vis, "cat": cat})
                t += timedelta(hours=1)
        msg = f"{cat} over {', '.join(codes)} until {until:%H:%M}Z"
    elif kind == "THREAT_ZONE":
        from geoalchemy2.shape import from_shape
        lon, lat, r = float(params["lon"]), float(params["lat"]), float(params.get("radius_km", 40))
        poly = Polygon([offset(lon, lat, r, 360 * i / 36) for i in range(36)])
        n = db.execute(text("SELECT count(*) FROM threat_zone WHERE code LIKE 'EX-THR-%'")).scalar() + 1
        db.add(M.ThreatZone(code=f"EX-THR-{n:03d}", name=params.get("name", "Unknown air activity (exercise)"),
                            kind=params.get("zone_kind", "UNKNOWN_ACTIVITY"), geom=from_shape(MultiPolygon([poly]), srid=4326),
                            risk_level=float(params.get("risk", 0.9)), active_from=now, active_to=until, is_simulated=True))
        msg = f"Threat activity zone ({r:.0f} km, risk {float(params.get('risk', 0.9)):.1f}) until {until:%H:%M}Z"
    elif kind == "AIRCRAFT_GROUNDING":
        t = db.scalars(select(M.AircraftType).where(M.AircraftType.name == params["type"])).first()
        if not t:
            raise ValueError(f"Unknown aircraft type {params['type']}")
        base = _base(db, params["base"], params["type"]) if params.get("base") else None
        # aircraft tasked in the committed plan first: an inject should test the plan
        tasked = {r[0] for r in db.execute(text("""SELECT unnest(pi.aircraft_ids) FROM plan_item pi JOIN plan p ON p.id = pi.plan_id
                                                  WHERE p.status = 'COMMITTED' AND pi.launch_ts > :n"""), {"n": now})}
        q = select(M.Aircraft).where(M.Aircraft.aircraft_type_id == t.id, M.Aircraft.status.in_(("AVAILABLE", "STANDBY", "TURNAROUND")))
        if base:
            q = q.where(M.Aircraft.current_base_id == base.id)
        pool = sorted(db.scalars(q), key=lambda a: (a.id not in tasked, a.id))[: int(params.get("count", 4))]
        for a in pool:
            before = {"status": a.status}
            a.status, a.maint_eta, a.status_reason = "MAINT_UNSCHEDULED", now + timedelta(hours=float(params.get("hours", 48))), \
                "Fleet grounding (exercise)"
            a.version += 1
            audit(db, user, "INJECT", "aircraft", a.id, a.home_base_id, before, {"status": a.status, "reason": a.status_reason})
        msg = f"{len(pool)} {t.name} grounded" + (f" at {base.code}" if base else "")
    elif kind == "MISSION_POPUP":
        msg = _popup(db, params, now)
    elif kind == "FUEL_DELAY":
        b = _base(db, params["base"])
        for fs in db.scalars(select(M.FuelStorage).where(M.FuelStorage.base_id == b.id, M.FuelStorage.grade == "ATF")):
            loss = round(fs.current_l * float(params.get("loss_pct", 35)) / 100, -2)
            fs.current_l -= loss
            fs.replenish_eta = now + timedelta(hours=hours)
            fs.version += 1
            db.add(M.FuelTransaction(fuel_storage_id=fs.id, ts=now, kind="ADJUSTMENT", quantity_l=loss,
                                     balance_after_l=fs.current_l, actor="EXERCISE"))
        msg = f"{b.code} fuel down {params.get('loss_pct', 35)}%, next delivery in {hours:.0f} h"
    elif kind == "RADAR_DOWN":
        b = _base(db, params["base"])
        n = db.execute(text("""UPDATE radar_site SET status = 'OFFLINE', repair_eta = :u, version = version + 1
                               WHERE base_id = :b"""), {"b": b.id, "u": until}).rowcount
        msg = f"{n} radar(s) at {b.code} offline until {until:%H:%M}Z"
    elif kind == "UNKNOWN_TRACK":
        if sim is not None:
            sim.force_unknown = True
        msg = "Unknown track spawned near the border"
    else:
        raise ValueError(f"Unknown inject {kind}")
    audit(db, user, "INJECT", "exercise", None, None, None, {"kind": kind, "params": params, "result": msg})
    run = current(db)
    if run and record:
        run.injects = run.injects + [{"kind": kind, "params": params, "label": label or msg, "applied_at": now.isoformat(),
                                      "result": msg, "live": True}]
    return msg


def _pt(db: Session, b: M.AirBase) -> tuple:
    from geoalchemy2.shape import to_shape
    p = to_shape(b.geom)
    return p.x, p.y


def _popup(db: Session, params: dict, now: datetime) -> str:
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point
    kind = params.get("mission_type", "CASEVAC")
    pw, roles, (nmin, _), on_min, _ = D.MISSION_TEMPLATES[kind]
    tb = _base(db, params["target_base"]) if params.get("target_base") else None
    if tb:
        lon, lat = _pt(db, tb)
    else:
        lon, lat = float(params["lon"]), float(params["lat"])
    short, label = D.MISSION_LABEL[kind]
    n = db.execute(text("SELECT count(*) FROM mission WHERE code LIKE 'SIM-' || :s || '-POP-%'"), {"s": short}).scalar() + 1
    elev = tb.elevation_m if tb else None
    quals = ["MOUNTAIN_FLYING"] if (elev or 0) >= D.MOUNTAIN_ELEVATION_M else []
    m = M.Mission(code=f"SIM-{short}-POP-{n:02d}", name=f"{label} (pop-up) {'to ' + tb.name.replace('Air Force Station ', '') if tb else ''}".strip(),
                  mission_type=kind, priority=params.get("priority", "P1"), window_start=now + timedelta(minutes=20),
                  window_end=now + timedelta(hours=float(params.get("window_h", 3))), status="APPROVED",
                  target_geom=from_shape(Point(lon, lat), srid=4326), target_base_id=tb.id if tb else None,
                  required_aircraft=int(params.get("required", nmin)), eligible_roles=roles, on_station_min=on_min,
                  min_quals=quals, max_risk=params.get("max_risk", "HIGH" if kind in ("CASEVAC", "RECCE_ISR") else "MED"),
                  approved_at=datetime.now().astimezone(), is_simulated=True, source="SYNTHETIC")
    db.add(m)
    db.flush()
    return f"Pop-up {m.priority} {label.lower()} {m.code}"


def tick(db: Session, now: datetime, sim=None) -> list[str]:
    """Called by the simulator every tick: due scenario injects, expiries, KPI samples."""
    out = []
    run = current(db)
    if run:
        elapsed = (now - run.started_sim).total_seconds() / 60
        injects, changed = copy.deepcopy(run.injects), False   # never mutate the loaded JSONB in place
        for i in injects:
            if i.get("applied_at") is None and not i.get("live") and elapsed >= float(i.get("offset_min", 0)):
                try:
                    i["result"] = inject(db, None, i["kind"], i.get("params", {}), i.get("label"), sim, record=False)
                except Exception as e:    # a bad scenario row must not stop the exercise
                    i["result"] = f"failed: {e}"
                i["applied_at"] = now.isoformat()
                changed = True
                out.append(i["result"])
        if changed:
            run.injects = injects
            flag_modified(run, "injects")
        last = run.kpi_timeline[-1]["sim_ts"] if run.kpi_timeline else None
        if not last or (now - datetime.fromisoformat(last)).total_seconds() >= 1800:
            run.kpi_timeline = run.kpi_timeline + [_kpis(db, now)]
    # expiries: runways reopen when their exercise closure ends
    for z in db.scalars(select(M.AirspaceZone).where(M.AirspaceZone.code.like("RWY-%"), M.AirspaceZone.active_to <= now)):
        n = db.execute(text("UPDATE runway SET status = 'OPEN', version = version + 1 WHERE base_id = :b AND status = 'CLOSED'"),
                       {"b": z.base_id}).rowcount
        if n:
            out.append(f"{z.code[4:]} runways reopened")
    return out


def _kpis(db: Session, now: datetime) -> dict:
    r = db.execute(text("""SELECT
        (SELECT round(100.0 * sum(serviceable) / nullif(sum(effective), 0), 1) FROM v_aircraft_serviceability) svc,
        (SELECT count(*) FROM aircraft WHERE status = 'AIRBORNE') airborne,
        (SELECT count(*) FROM alert WHERE status <> 'CLEARED' AND severity IN ('WARNING','CRITICAL')) alerts,
        (SELECT count(*) FROM mission WHERE status IN ('TASKED','ACTIVE')) tasked,
        (SELECT count(*) FROM mission WHERE outcome = 'MET') met,
        (SELECT count(*) FROM disruption WHERE status IN ('OPEN','ASSESSED')) disruptions""")).mappings().one()
    return {"sim_ts": now.isoformat(), **{k: float(v) if v is not None else None for k, v in r.items()}}


def aar(db: Session, run_id: int) -> dict:
    run = db.get(M.ExerciseRun, run_id)
    if not run:
        raise ValueError("Exercise run not found")
    end = run.ended_sim or sim_now(db)
    q = lambda sql, **p: [dict(x) for x in db.execute(text(sql), p).mappings()]  # noqa: E731
    disruptions = q("""SELECT d.id, d.ts, d.kind, d.message, d.status, d.proposal_ms, d.created_at, d.resolved_at,
                              p.status AS proposal_status, p.committed_at, p.summary AS proposal_summary
                       FROM disruption d LEFT JOIN plan p ON p.id = d.proposal_plan_id
                       WHERE d.ts BETWEEN :a AND :b ORDER BY d.ts""", a=run.started_sim, b=end)
    for d in disruptions:
        d["decision_s"] = round((d["committed_at"] - d["created_at"]).total_seconds()) if d["committed_at"] and d["created_at"] else None
    plans = q("""SELECT p.id, p.kind, p.status, p.summary, p.created_at, p.committed_at, p.solve_ms, p.kpis, u.username AS approved_by
                 FROM plan p LEFT JOIN app_user u ON u.id = p.approved_by WHERE p.created_at >= :a ORDER BY p.id""", a=run.started_real)
    missions = q("""SELECT m.code, m.name, m.priority, m.mission_type, m.status, m.outcome, m.on_station_min,
                           m.on_station_achieved_min, m.window_start, m.window_end FROM mission m
                    WHERE m.window_start < :b AND m.window_end > :a ORDER BY m.priority, m.window_start""", a=run.started_sim, b=end)
    outcome = {k: sum(1 for m in missions if m["outcome"] == k) for k in ("MET", "PARTIAL", "MISSED", "NONE")}
    latency = [d["decision_s"] for d in disruptions if d["decision_s"] is not None]
    props = [d["proposal_ms"] for d in disruptions if d["proposal_ms"] is not None]
    return {"run": {"id": run.id, "name": run.name, "status": run.status, "started_sim": run.started_sim, "ended_sim": run.ended_sim,
                    "started_real": run.started_real},
            "injects": run.injects, "disruptions": disruptions, "plans": plans, "missions": missions, "outcome": outcome,
            "kpi_timeline": run.kpi_timeline,
            "summary": {"disruptions": len(disruptions), "proposals": sum(1 for d in disruptions if d["proposal_ms"] is not None),
                        "proposal_ms_max": max(props) if props else None,
                        "decision_s_median": sorted(latency)[len(latency) // 2] if latency else None,
                        "plans_committed": sum(1 for p in plans if p["committed_at"]), **outcome}, "simulated": True}
