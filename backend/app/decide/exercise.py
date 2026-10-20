"""Scenarios and exercise runs (PHASE2_IMPLEMENTATION_PLAN §8, ARCHITECTURE D55): runs, effects ("injects") and the
after-action report.

A scenario is one incident: starting it applies all its effects at once. Effects change the synthetic world exactly as
a real event would (runway status, weather, threat zones, aircraft status, new missions, fuel); the re-tasking monitor
then sees the committed plan break and proposes a repair. Nothing here touches the plan directly.

Several runs may be live at once (one per scenario). Each run keeps a footprint of what its effects touched, so the
monitor can tell which disruptions belong to which scenario (`owner()`).
"""
import copy
import re
from datetime import datetime, timedelta, timezone

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
    "AIRCRAFT_LOST": "Aircraft lost in a crash",
    "BASE_STRIKE": "Strike on a base: runway, radars and fuel",
}
WX = {"MVFR": (2000, 6000), "IFR": (700, 3000), "LIFR": (300, 1000)}
USABLE = ("AVAILABLE", "STANDBY", "TURNAROUND")


def running(db: Session) -> list[M.ExerciseRun]:
    return list(db.scalars(select(M.ExerciseRun).where(M.ExerciseRun.status == "RUNNING").order_by(M.ExerciseRun.id.desc())))


def current(db: Session) -> M.ExerciseRun | None:
    """The newest live run (the single-run callers: exercise state, legacy live injects)."""
    r = running(db)
    return r[0] if r else None


def _z(t: datetime) -> str:
    """Zulu time for inject messages. The sim clock comes back IST-aware, so convert before formatting (D64 fix)."""
    return t.astimezone(timezone.utc).strftime("%d %b %H:%MZ")


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


# ---------------------------------------------------------------- scenario parameters
_PH = re.compile(r"\{(\w+)\}")


def fill(v, p: dict):
    """Replace {key} placeholders in an inject template. A value that is exactly "{key}" takes the parameter's own type
    (a list of bases stays a list)."""
    if isinstance(v, str):
        m = _PH.fullmatch(v)
        if m and m.group(1) in p:
            return p[m.group(1)]
        return _PH.sub(lambda x: str(p.get(x.group(1), x.group(0))), v)
    if isinstance(v, list):
        return [fill(x, p) for x in v]
    if isinstance(v, dict):
        return {k: fill(x, p) for k, x in v.items()}
    return v


def resolve(sc: M.Scenario, params: dict | None, intensity: str | None) -> tuple[dict, str]:
    """Form defaults, then the intensity preset, then what the directing staff typed (known keys only)."""
    lvl = (intensity or sc.intensity or "MEDIUM").upper()
    if lvl not in M.INTENSITY:
        raise ValueError(f"Unknown intensity {intensity}")
    p = {f["key"]: f.get("default") for f in sc.params or []}
    p.update((sc.intensity_presets or {}).get(lvl, {}))
    p.update({k: v for k, v in (params or {}).items() if k in p and v not in (None, "")})
    return p, lvl


# ---------------------------------------------------------------- runs
def start(db: Session, user: dict, scenario_id: int | None, name: str | None, speed: float | None,
          params: dict | None = None, intensity: str | None = None) -> M.ExerciseRun:
    sc = db.get(M.Scenario, scenario_id) if scenario_id else None
    if scenario_id and not sc:
        raise ValueError("Scenario not found")
    if sc and any(r.scenario_id == sc.id for r in running(db)):
        raise ValueError(f"{sc.name} is already running. End it first.")
    p, lvl = resolve(sc, params, intensity) if sc else ({}, None)
    now = sim_now(db)
    injects = [dict(fill(i, p), applied_at=None) for i in (sc.injects if sc else [])]
    run = M.ExerciseRun(scenario_id=sc.id if sc else None, name=name or (sc.name if sc else "Free play"), status="RUNNING",
                        started_sim=now, intensity=lvl, params=p, footprint={}, injects=injects, kpi_timeline=[],
                        started_by=user["id"])
    db.add(run)
    st = db.get(M.SimState, 1, with_for_update=True)
    st.paused = False
    if speed:
        st.speed = speed
    db.flush()
    audit(db, user, "SIM_CONTROL", "exercise_run", run.id, None, None,
          {"action": "start", "scenario": run.name, "intensity": lvl, "params": p, "speed": st.speed, "injects": len(injects)})
    return run


def stop(db: Session, user: dict | None, run_id: int | None = None) -> None:
    """End one run, or every live run when no id is given. Its missions not yet flying are withdrawn (D56): the
    situation no longer demands them, and the monitor's next check frees what their packages held. Effects such as a
    cratered runway keep their own end time."""
    from .store import cancel_mission
    runs = [r for r in running(db) if run_id is None or r.id == run_id]
    if run_id is not None and not runs:
        raise ValueError("That scenario isn't running")
    now = sim_now(db)
    for run in runs:
        run.status, run.ended_sim = "ENDED", now
        withdrawn = 0
        for m in db.scalars(select(M.Mission).where(M.Mission.exercise_run_id == run.id,
                                                    M.Mission.status.in_(("REQUESTED", "APPROVED", "PLANNED", "TASKED")))):
            cancel_mission(db, m, user)
            withdrawn += 1
        audit(db, user, "SIM_CONTROL", "exercise_run", run.id, None, None,
              {"action": "stop", "scenario": run.name, "missions_withdrawn": withdrawn})


def _fp(run: M.ExerciseRun | None, effect: dict | None = None, **ids) -> None:
    """Add what an effect touched to the run's footprint (lists of ids / codes, plus a readable effect row). Bases are
    also kept per effect kind, so a runway disruption goes to the scenario that closed that runway."""
    if run is None:
        return
    fp = copy.deepcopy(run.footprint or {})
    for k, vals in ids.items():
        fp[k] = sorted(set(fp.get(k, [])) | {v for v in vals if v is not None})
    if effect:
        fp.setdefault("effects", []).append(effect)
        if ids.get("bases"):
            bk = fp.setdefault("by_kind", {})
            bk[effect["kind"]] = sorted(set(bk.get(effect["kind"], [])) | set(ids["bases"]))
    run.footprint = fp
    flag_modified(run, "footprint")


CAUSES = {"RUNWAY_CLOSED": ("RUNWAY_CLOSED",), "RECOVERY_UNSAFE": ("RUNWAY_CLOSED", "WX_FRONT"), "WX_BELOW_MINIMA": ("WX_FRONT",),
          "FUEL_SHORT": ("FUEL_DELAY",), "AIRCRAFT_US": ("AIRCRAFT_GROUNDING", "AIRCRAFT_LOST")}


def owner(db: Session, base_id: int | None, entity_type: str | None, entity_id: int | None, mission_id: int | None,
          kind: str | None = None) -> int | None:
    """The live run a disruption belongs to: first the run whose effect explains it (its pop-up, its aircraft, the
    runway / weather / fuel effect at that base), then any run that touched the base; newest first. ponytail: footprint
    matching, not causal tracing; the upgrade is tagging validator violations with the effect that caused them."""
    runs = running(db)
    for run in runs:
        fp = run.footprint or {}
        if mission_id is not None and mission_id in fp.get("missions", []):
            return run.id
        if entity_type == "aircraft" and entity_id in fp.get("aircraft", []):
            return run.id
        if base_id is not None and any(base_id in fp.get("by_kind", {}).get(k, []) for k in CAUSES.get(kind or "", ())):
            return run.id
        if kind == "THREAT_ACTIVATED" and fp.get("zones"):
            return run.id
    for run in runs:
        if base_id is not None and base_id in (run.footprint or {}).get("bases", []):
            return run.id
    return None


# ---------------------------------------------------------------- effects
def inject(db: Session, user: dict | None, kind: str, params: dict, label: str | None = None, sim=None,
           record: bool = True, run: M.ExerciseRun | None = None) -> str:
    """Apply one effect now. Returns a sentence describing what happened. `run` collects the footprint (default: the
    newest live run, for live injects)."""
    now = sim_now(db)
    hours = float(params.get("hours", 6))
    until = now + timedelta(hours=hours)
    owner_run = run if run is not None else (current(db) if record else None)
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
        msg = f"{b.code} runways closed until {_z(until)}"
        _fp(owner_run, {"kind": kind, "base": b.code, "base_name": _short(b), "until": until.isoformat()}, bases=[b.id])
    elif kind == "WX_FRONT":
        cat = params.get("cat", "IFR")
        ceil, vis = WX.get(cat, WX["IFR"])
        codes = [c.upper() for c in params.get("bases", [])]
        ids = []
        for code in codes:
            b = _base(db, code)
            ids.append(b.id)
            t = now.replace(minute=0, second=0, microsecond=0)
            while t < until:
                db.execute(text("""INSERT INTO wx_base_forecast (base_id, valid_ts, ceiling_ft, vis_m, wind_kt, gust_kt, wind_dir,
                                   flight_cat, source, fetched_at, is_simulated) VALUES (:b, :t, :c, :v, 18, 28, 180, :cat,
                                   'EXERCISE', now(), true) ON CONFLICT (base_id, valid_ts, source) DO UPDATE
                                   SET ceiling_ft = :c, vis_m = :v, flight_cat = :cat"""),
                           {"b": b.id, "t": t, "c": ceil, "v": vis, "cat": cat})
                t += timedelta(hours=1)
        msg = f"{cat} over {', '.join(codes)} until {_z(until)}"
        _fp(owner_run, {"kind": kind, "bases": codes, "cat": cat, "until": until.isoformat()}, bases=ids)
    elif kind == "THREAT_ZONE":
        from geoalchemy2.shape import from_shape
        lon, lat, r = float(params["lon"]), float(params["lat"]), float(params.get("radius_km", 40))
        poly = Polygon([offset(lon, lat, r, 360 * i / 36) for i in range(36)])
        n = db.execute(text("SELECT count(*) FROM threat_zone WHERE code LIKE 'EX-THR-%'")).scalar() + 1
        code = f"EX-THR-{n:03d}"
        db.add(M.ThreatZone(code=code, name=params.get("name", "Unknown air activity (exercise)"),
                            kind=params.get("zone_kind", "UNKNOWN_ACTIVITY"), geom=from_shape(MultiPolygon([poly]), srid=4326),
                            risk_level=float(params.get("risk", 0.9)), active_from=now, active_to=until, is_simulated=True))
        msg = f"Threat activity zone ({r:.0f} km, risk {float(params.get('risk', 0.9)):.1f}) until {_z(until)}"
        _fp(owner_run, {"kind": kind, "radius_km": r, "risk": float(params.get("risk", 0.9)), "until": until.isoformat()},
            zones=[code])
    elif kind == "AIRCRAFT_GROUNDING":
        t = db.scalars(select(M.AircraftType).where(M.AircraftType.name == params["type"])).first()
        if not t:
            raise ValueError(f"Unknown aircraft type {params['type']}")
        bases = [_base(db, c, params["type"]) for c in params["bases"]] if params.get("bases") else \
            ([_base(db, params["base"], params["type"])] if params.get("base") else [])
        # aircraft tasked in the committed plan first: an inject should test the plan
        tasked = {r[0] for r in db.execute(text("""SELECT unnest(pi.aircraft_ids) FROM plan_item pi JOIN plan p ON p.id = pi.plan_id
                                                  WHERE p.status = 'COMMITTED' AND pi.launch_ts > :n"""), {"n": now})}
        q = select(M.Aircraft).where(M.Aircraft.aircraft_type_id == t.id, M.Aircraft.status.in_(USABLE))
        if bases:
            q = q.where(M.Aircraft.current_base_id.in_([b.id for b in bases]))
        count = params.get("count")
        pool = sorted(db.scalars(q), key=lambda a: (a.id not in tasked, a.id))
        if count not in (None, "all"):
            pool = pool[: int(count)]
        for a in pool:
            before = {"status": a.status}
            a.status, a.maint_eta, a.status_reason = "MAINT_UNSCHEDULED", now + timedelta(hours=float(params.get("hours", 48))), \
                "Fleet grounding (exercise)"
            a.version += 1
            audit(db, user, "INJECT", "aircraft", a.id, a.home_base_id, before, {"status": a.status, "reason": a.status_reason})
        where = ", ".join(b.code for b in bases)
        msg = f"{len(pool)} {t.name} grounded" + (f" at {where}" if bases else "")
        _fp(owner_run, {"kind": kind, "type": t.name, "count": len(pool), "bases": [b.code for b in bases],
                        "until": (now + timedelta(hours=float(params.get("hours", 48)))).isoformat()},
            aircraft=[a.id for a in pool], bases=[b.id for b in bases])
    elif kind == "MISSION_POPUP":
        msg, m = _popup(db, params, now, owner_run)
        _fp(owner_run, {"kind": kind, "mission": m.code, "name": m.name, "priority": m.priority,
                        "until": m.window_end.isoformat()}, missions=[m.id])
    elif kind == "FUEL_DELAY":
        codes = params["bases"] if params.get("bases") else [params["base"]]
        pct = float(params.get("loss_pct", 35))
        ids = []
        for code in codes:
            b = _base(db, code)
            ids.append(b.id)
            for fs in db.scalars(select(M.FuelStorage).where(M.FuelStorage.base_id == b.id, M.FuelStorage.grade == "ATF")):
                loss = round(fs.current_l * pct / 100, -2)
                fs.current_l -= loss
                fs.replenish_eta = now + timedelta(hours=hours)
                fs.version += 1
                db.add(M.FuelTransaction(fuel_storage_id=fs.id, ts=now, kind="ADJUSTMENT", quantity_l=loss,
                                         balance_after_l=fs.current_l, actor="EXERCISE"))
        msg = f"{', '.join(c.upper() for c in codes)} fuel down {pct:.0f}%, next delivery in {hours:.0f} h"
        _fp(owner_run, {"kind": kind, "bases": [c.upper() for c in codes], "loss_pct": pct, "until": until.isoformat()},
            bases=ids)
    elif kind == "RADAR_DOWN":
        b = _base(db, params["base"])
        ids = [r[0] for r in db.execute(text("""UPDATE radar_site SET status = 'OFFLINE', repair_eta = :u, version = version + 1
                                                WHERE base_id = :b RETURNING id"""), {"b": b.id, "u": until})]
        msg = f"{len(ids)} radar{'' if len(ids) == 1 else 's'} at {b.code} offline until {_z(until)}"
        _fp(owner_run, {"kind": kind, "base": b.code, "base_name": _short(b), "count": len(ids), "until": until.isoformat()},
            radars=ids, bases=[b.id])
    elif kind == "AIRCRAFT_LOST":
        b = _base(db, params["base"])
        t = db.scalars(select(M.AircraftType).where(M.AircraftType.name == params["type"])).first()
        if not t:
            raise ValueError(f"Unknown aircraft type {params['type']}")
        pool = list(db.scalars(select(M.Aircraft).where(M.Aircraft.aircraft_type_id == t.id, M.Aircraft.status.in_(USABLE),
                                                        M.Aircraft.current_base_id == b.id).order_by(M.Aircraft.id)))
        lost = pool[: int(params.get("count", 1))]
        for a in lost:
            # ponytail: a written-off airframe is RETIRED with a reason; a dedicated LOST status would ripple through the
            # serviceability views and the TypeScript enums for no planner benefit.
            before = {"status": a.status}
            a.status, a.status_reason, a.version = "RETIRED", "Lost in a crash (exercise)", a.version + 1
            audit(db, user, "INJECT", "aircraft", a.id, a.home_base_id, before, {"status": a.status, "reason": a.status_reason})
        left = db.execute(text("""SELECT count(*) FROM aircraft WHERE aircraft_type_id = :t AND current_base_id = :b
                                  AND status IN ('AVAILABLE','STANDBY','TURNAROUND')"""), {"t": t.id, "b": b.id}).scalar()
        msg = f"{len(lost)} {t.name} lost at {b.code}"
        _fp(owner_run, {"kind": kind, "type": t.name, "count": len(lost), "base": b.code, "base_name": _short(b),
                        "left": left}, aircraft=[a.id for a in lost], bases=[b.id])
    elif kind == "BASE_STRIKE":
        b = _base(db, params["base"])
        parts = [inject(db, user, "RUNWAY_CLOSED", {"base": b.code, "hours": params.get("hours", 12)}, record=False, run=owner_run),
                 inject(db, user, "RADAR_DOWN", {"base": b.code, "hours": params.get("radar_hours", params.get("hours", 12))},
                        record=False, run=owner_run)]
        if float(params.get("fuel_loss_pct", 0)):
            parts.append(inject(db, user, "FUEL_DELAY", {"base": b.code, "hours": params.get("hours", 12),
                                                          "loss_pct": params["fuel_loss_pct"]}, record=False, run=owner_run))
        msg = f"Strike on {b.code}: " + "; ".join(parts)
    elif kind == "UNKNOWN_TRACK":
        if sim is not None:
            sim.force_unknown = True
        msg = "Unknown track spawned near the border"
    else:
        raise ValueError(f"Unknown inject {kind}")
    audit(db, user, "INJECT", "exercise", None, None, None, {"kind": kind, "params": params, "result": msg})
    if record and run is None and owner_run is not None:
        owner_run.injects = owner_run.injects + [{"kind": kind, "params": params, "label": label or msg,
                                                  "applied_at": now.isoformat(), "result": msg, "live": True}]
    return msg


def _short(b: M.AirBase) -> str:
    return b.name.replace("Air Force Station ", "").replace("Air Force Academy ", "")


def _pt(db: Session, b: M.AirBase) -> tuple:
    from geoalchemy2.shape import to_shape
    p = to_shape(b.geom)
    return p.x, p.y


def _popup(db: Session, params: dict, now: datetime, run: M.ExerciseRun | None = None) -> tuple[str, M.Mission]:
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point
    kind = params.get("mission_type", "CASEVAC")
    pw, roles, (nmin, _), on_min, _ = D.MISSION_TEMPLATES[kind]
    tb = _base(db, params["target_base"]) if params.get("target_base") else None
    near = _base(db, params["near_base"]) if params.get("near_base") else None
    if tb:
        lon, lat = _pt(db, tb)
    elif near:        # a point some km from a base (a crash site, a high post): the base's elevation decides mountain quals
        lon, lat = offset(*_pt(db, near), float(params.get("offset_km", 0)), float(params.get("bearing", 0)))
    else:
        lon, lat = float(params["lon"]), float(params["lat"])
    short, label = D.MISSION_LABEL[kind]
    n = db.execute(text("SELECT count(*) FROM mission WHERE code LIKE 'SIM-' || :s || '-POP-%'"), {"s": short}).scalar() + 1
    elev = (tb or near).elevation_m if (tb or near) else None
    quals = ["MOUNTAIN_FLYING"] if (elev or 0) >= D.MOUNTAIN_ELEVATION_M else []
    place = params.get("place") or (_short(tb) if tb else "")
    prep = "to" if kind in ("AIRLIFT", "CASEVAC", "HADR") else "over"
    m = M.Mission(code=f"SIM-{short}-POP-{n:02d}", name=f"{label} (pop-up) {prep + ' ' + place if place else ''}".strip(),
                  mission_type=kind, priority=params.get("priority", "P1"), window_start=now + timedelta(minutes=20),
                  window_end=now + timedelta(hours=float(params.get("window_h", 3))), status="APPROVED",
                  target_geom=from_shape(Point(lon, lat), srid=4326), target_base_id=tb.id if tb else None,
                  required_aircraft=int(params.get("required", nmin)), eligible_roles=roles, on_station_min=on_min,
                  min_quals=quals, max_risk=params.get("max_risk", "HIGH" if kind in ("CASEVAC", "RECCE_ISR") else "MED"),
                  approved_at=datetime.now().astimezone(), is_simulated=True, source="SYNTHETIC",
                  exercise_run_id=run.id if run is not None else None)      # D56: tagged with the scenario that demanded it
    db.add(m)
    db.flush()
    return f"Pop-up {m.priority} {label.lower()} {m.code}", m


def apply_due(db: Session, run: M.ExerciseRun, now: datetime, sim=None) -> list[str]:
    """Apply the run's scripted effects whose time has come (all of them at start, for a one-event scenario)."""
    out = []
    elapsed = (now - run.started_sim).total_seconds() / 60
    injects, changed = copy.deepcopy(run.injects), False   # never mutate the loaded JSONB in place
    for i in injects:
        if i.get("applied_at") is None and not i.get("live") and elapsed >= float(i.get("offset_min", 0)):
            try:
                i["result"] = inject(db, None, i["kind"], i.get("params", {}), i.get("label"), sim, record=False, run=run)
            except Exception as e:    # a bad scenario row must not stop the exercise
                i["result"] = f"failed: {e}"
            i["applied_at"] = now.isoformat()
            changed = True
            out.append(i["result"])
    if changed:
        run.injects = injects
        flag_modified(run, "injects")
    return out


def tick(db: Session, now: datetime, sim=None) -> list[str]:
    """Called by the simulator every tick: due scenario effects, expiries, KPI samples."""
    out = []
    for run in running(db):
        out += apply_due(db, run, now, sim)
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
    # a scenario run owns its disruptions (D55); free play falls back to the time window
    disruptions = q("""SELECT d.id, d.ts, d.kind, d.message, d.status, d.proposal_ms, d.created_at, d.resolved_at,
                              p.status AS proposal_status, p.committed_at, p.summary AS proposal_summary
                       FROM disruption d LEFT JOIN plan p ON p.id = d.proposal_plan_id
                       WHERE (d.exercise_run_id = :r OR (:free AND d.ts BETWEEN :a AND :b)) ORDER BY d.ts""",
                    r=run.id, free=run.scenario_id is None, a=run.started_sim, b=end)
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
