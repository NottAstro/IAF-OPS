"""Tick simulator (DATA_MODEL §9, FR-SIM-01..12). One transaction per tick, then a WebSocket broadcast.

ponytail: runs in-process in the single uvicorn worker; move to its own process + pub/sub if it ever needs to scale.
"""
import asyncio
import logging
import math
import random
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from geoalchemy2.shape import from_shape
from shapely.geometry import LineString
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from .. import config
from .. import models as M
from ..audit import audit
from ..db import SessionLocal
from ..geo import India, bearing, dist_km, load_india, offset
from ..live import feeds
from ..weather import metar
from . import alerts as alert_rules
from . import reliability as REL
from .routes import plan, position

from generator import config as GC  # shared synthetic policy (rates, mixes, families)

log = logging.getLogger("sim")
IST = timezone(timedelta(hours=5, minutes=30))
ATF_DENSITY = GC.ATF_DENSITY
POSITIONS = {"fighter": [("PILOT", "CAPTAIN", True)], "fighter2": [("PILOT", "CAPTAIN", True), ("WSO", "WSO", False)],
             "transport": [("PILOT", "CAPTAIN", True), ("PILOT", "CO_PILOT", True), ("NAVIGATOR", "NAVIGATOR", False),
                           ("FLIGHT_ENGINEER", "FLIGHT_ENGINEER", False), ("LOADMASTER", "LOADMASTER", False)],
             "helo": [("PILOT", "CAPTAIN", True), ("PILOT", "CO_PILOT", True), ("FLIGHT_ENGINEER", "FLIGHT_ENGINEER", False)],
             "trainer": [("PILOT", "INSTRUCTOR", True)],
             "uav": [("RPA_PILOT", "RPA_PILOT", True), ("PAYLOAD_OPERATOR", "PAYLOAD_OPERATOR", False)],
             "uas": [("RPA_PILOT", "RPA_PILOT", True)]}


def family(t: M.AircraftType) -> str:
    return GC.ROLE_FAMILY[t.role][0]


def crew_family(t: M.AircraftType) -> str:
    f = family(t)
    return "fighter2" if f == "fighter" and t.seats_other > 0 else f


def pt(geom) -> tuple[float, float]:
    from geoalchemy2.shape import to_shape
    p = to_shape(geom)
    return p.x, p.y


@dataclass
class Ctx:
    db: Session
    rng: random.Random
    prev: datetime
    now: datetime
    tick: int
    changed: set = field(default_factory=set)

    @property
    def dt_h(self) -> float:
        return (self.now - self.prev).total_seconds() / 3600

    def log(self, obj, before: dict, base_id=None):
        after = {k: getattr(obj, k) for k in before}
        if after != before:
            self.changed.add(obj.__tablename__)
            audit(self.db, None, "SIM_TRANSITION", obj.__tablename__, obj.id, base_id, before, after)


def snap(obj, *keys) -> dict:
    return {k: getattr(obj, k) for k in keys}


class Simulator:
    def __init__(self, hub):
        self.hub = hub
        self.G: India | None = None
        self.routes: dict[int, list] = {}
        self.unknowns: dict[str, dict] = {}
        self.hostile_samples: list = []
        self.lock = asyncio.Lock()
        self.last_tracks: list = []
        self.force_unknown = False        # exercise inject: spawn an unknown track on the next tick
        self.route_ver: dict[int, int] = {}

    # ------------------------------------------------------------------ loop
    async def run(self) -> None:
        while True:
            await asyncio.sleep(config.SIM_TICK_SECONDS)
            if config.SIM_ENABLED:
                await self.step()

    async def step(self, force: bool = False) -> dict:
        async with self.lock:
            try:
                msg = await asyncio.to_thread(self.tick, force)
            except Exception:
                log.exception("simulator tick failed")
                return {}
        await self.publish(msg)
        return msg

    async def publish(self, msg: dict) -> None:
        if not msg:
            return
        sim_ts = msg["clock"]["sim_now"]
        await self.hub.broadcast("sim.clock", msg["clock"], sim_ts)
        await self.hub.broadcast("tracks.sim", msg.get("tracks", []), sim_ts)
        if msg.get("changed"):
            await self.hub.broadcast("entity.changed", {"types": sorted(msg["changed"])}, sim_ts)
        for a in msg.get("alerts", []):
            await self.hub.broadcast("alert", a, sim_ts)

    # ------------------------------------------------------------------ one tick
    def tick(self, force: bool = False) -> dict:
        with SessionLocal() as db:
            st = db.get(M.SimState, 1, with_for_update=True)
            if not st:
                return {}
            if self.G is None:
                self.G = load_india(db)
                self.hostile_samples = self.G.border_samples(60, hostile_only=True)
            if st.paused and not force:
                db.rollback()
                return {"clock": self.clock(st), "tracks": self.last_tracks}
            prev = st.sim_now
            st.sim_now = prev + timedelta(seconds=config.SIM_TICK_SECONDS * st.speed)
            st.tick_no += 1
            db.flush()
            ctx = Ctx(db, random.Random(f"{st.seed}:{st.tick_no}"), prev, st.sim_now, st.tick_no)
            self.programme(ctx, st)
            self.sorties(ctx)
            self.aircraft(ctx)
            self.fuel(ctx)
            self.crew(ctx)
            self.faults(ctx)
            self.qra(ctx)
            self.unknown_tracks(ctx)
            from ..decide import exercise          # Phase 2: scenario injects, expiries, KPI samples
            for msg in exercise.tick(db, ctx.now, self):
                log.info("exercise: %s", msg)
                ctx.changed |= {"aircraft", "runway", "fuel_storage", "mission"}
            raised = alert_rules.evaluate(ctx, self.unknowns)
            if st.tick_no % 12 == 0:
                self.kpis(ctx)
            if st.tick_no % 720 == 0:
                db.execute(text("SET LOCAL airops.audit_prune = 'on'"))
                db.execute(text("DELETE FROM audit_log WHERE actor_type = 'SIMULATOR' AND ts < now() - interval '7 days'"))
            if config.SIM_ASSERT:
                from .invariants import check
                check(db)
            db.commit()
            self.last_tracks = self.tracks(db, ctx)
            return {"clock": self.clock(st), "tracks": self.last_tracks, "changed": ctx.changed, "alerts": raised}

    @staticmethod
    def clock(st: M.SimState) -> dict:
        return {"sim_now": st.sim_now.isoformat(), "speed": st.speed, "paused": st.paused, "tick_no": st.tick_no,
                "tick_seconds": config.SIM_TICK_SECONDS}

    # ------------------------------------------------------------------ daily flying programme (FR-SIM-02)
    def programme(self, ctx: Ctx, st: M.SimState) -> None:
        day = ctx.now.astimezone(IST).date()
        if st.last_programme_date == day:
            return
        st.last_programme_date = day
        db, rng = ctx.db, random.Random(f"{st.seed}:programme:{day.isoformat()}")
        own = {b.id: b for b in db.scalars(select(M.AirBase).where(M.AirBase.side == "OWN"))}
        missions = list(db.scalars(select(M.Mission).where(M.Mission.status == "ACTIVE")))
        busy_until: dict[int, datetime] = {}
        for sid, aid, end in db.execute(text("""SELECT s.id, sa.aircraft_id, s.planned_recovery_ts FROM sortie s
                JOIN sortie_aircraft sa ON sa.sortie_id = s.id WHERE s.status IN
                ('PLANNED','CREWED','READY','AIRBORNE','ON_STATION','RTB')""")):
            busy_until[aid] = max(busy_until.get(aid, end), end)
        day_start = datetime.combine(day, datetime.min.time(), IST)
        remaining = max(0.0, min(1.0, (day_start + timedelta(hours=23) - ctx.now).total_seconds() / (17 * 3600)))
        seq = db.execute(text("SELECT coalesce(max(id), 0) FROM sortie")).scalar()
        created = 0
        for sq, t in db.execute(select(M.Squadron, M.AircraftType).join(M.AircraftType, M.AircraftType.id == M.Squadron.aircraft_type_id)):
            fam = family(t)
            home = own.get(sq.home_base_id)
            if not home:
                continue
            fleet = list(db.scalars(select(M.Aircraft).where(M.Aircraft.squadron_id == sq.id,
                         M.Aircraft.current_base_id == sq.home_base_id, M.Aircraft.status.in_(("AVAILABLE", "STANDBY")))))
            if not fleet:
                continue
            n = round(len(fleet) * GC.SORTIE_RATE[fam] * rng.uniform(0.8, 1.2) * remaining * config.SIM_PROGRAMME_SCALE)
            hp = pt(home.geom)
            for i in range(n):
                ac = fleet[i % len(fleet)]
                hour = rng.uniform(19, 22.5) if rng.random() < 0.15 else rng.uniform(6.5, 17)
                launch = day_start + timedelta(hours=hour)
                hours = rng.uniform(*GC.SORTIE_HOURS[fam])
                if launch < ctx.now + timedelta(minutes=45):
                    continue
                free = busy_until.get(ac.id)
                if free and launch < free + timedelta(minutes=t.turnaround_min + 60):
                    continue
                mtype = "AAR_SUPPORT" if t.role == "TANKER" else "AEW_SUPPORT" if t.role == "AEW_C" else \
                    rng.choices([m for m, _ in GC.MISSION_MIX[fam]], [w for _, w in GC.MISSION_MIX[fam]])[0]
                dest = None
                if mtype in ("AIRLIFT", "HADR", "CASEVAC", "PARA_DROP") or (fam == "helo" and mtype == "AIRLIFT"):
                    reach = 250 if fam == "helo" else 900
                    cands = [b for b in own.values() if b.id != home.id and dist_km(hp, pt(b.geom)) < reach and
                             (fam != "helo" or b.base_type in ("ALG", "HELIBASE", "FBSU", "AIR_FORCE_STATION"))]
                    if cands:
                        dest = pt(rng.choice(cands).geom)
                pts, dur = plan(self.G, rng, fam, mtype, hp, dest, t.cruise_kt, hours)
                busy_until[ac.id] = launch + timedelta(hours=dur)
                seq += 1
                ms = [m for m in missions if m.mission_type == mtype]
                s = M.Sortie(code=f"SIM-{home.code}-{seq:06d}", origin="SIM_PROGRAMME", mission_type=mtype,
                             priority=rng.choices(["P1", "P2", "P3", "P4"], [5, 20, 50, 25])[0],
                             mission_id=None,      # routine flying; operational missions are tasked by the planner
                             departure_base_id=home.id, recovery_base_id=home.id, status="PLANNED",
                             planned_launch_ts=launch, planned_recovery_ts=launch + timedelta(hours=dur),
                             route_geom=from_shape(LineString(pts), srid=4326),
                             cruise_alt_m={"fighter": 7500, "transport": 7500, "helo": 1500, "uav": 5500,
                                           "uas": 120, "trainer": 3000}[fam],
                             fuel_planned_kg=round(t.burn_kg_per_h * dur), is_simulated=True)
                db.add(s)
                db.flush()
                db.add(M.SortieAircraft(sortie_id=s.id, aircraft_id=ac.id,
                                        callsign=f"{rng.choice(['VAJRA', 'GARUDA', 'TEJAS', 'AGNI', 'VAYU', 'MEGH', 'NEEL', 'SHER'])}{rng.randint(10, 99)}"))
                created += 1
        # daily diesel issue to vehicles
        for fs in db.scalars(select(M.FuelStorage).where(M.FuelStorage.grade == "DIESEL_HSD")):
            q = round(min(fs.current_l, fs.capacity_l * rng.uniform(0.01, 0.025)), -1)
            if q > 0:
                fs.current_l -= q
                db.add(M.FuelTransaction(fuel_storage_id=fs.id, ts=ctx.now, kind="ISSUE_VEHICLE", quantity_l=q,
                                         balance_after_l=fs.current_l, actor="SIMULATOR"))
        ctx.changed |= {"sortie", "fuel_storage"}
        log.info("programme %s: %d sorties planned", day, created)

    # ------------------------------------------------------------------ sortie lifecycle (FR-SIM-03)
    def sorties(self, ctx: Ctx) -> None:
        db, now, rng = ctx.db, ctx.now, ctx.rng
        due = db.scalars(select(M.Sortie).where(or_(
            and_(M.Sortie.status == "PLANNED", M.Sortie.planned_launch_ts <= now + timedelta(minutes=60)),
            and_(M.Sortie.status == "CREWED", M.Sortie.planned_launch_ts <= now + timedelta(minutes=15)),
            and_(M.Sortie.status == "READY", M.Sortie.planned_launch_ts <= now),
            M.Sortie.status.in_(("AIRBORNE", "ON_STATION", "RTB")),
            and_(M.Sortie.status == "LANDED", M.Sortie.actual_recovery_ts <= now - timedelta(minutes=30)),
        )).order_by(M.Sortie.planned_launch_ts)).all()
        for s in due:
            before = snap(s, "status", "cancel_reason")
            if s.status == "PLANNED":
                self.crew_up(ctx, s)
            elif s.status == "CREWED":
                s.status = "READY"
            elif s.status == "READY":
                self.launch(ctx, s)
            elif s.status in ("AIRBORNE", "ON_STATION", "RTB"):
                t0 = s.reroute_ts or s.actual_launch_ts            # a re-roled sortie flies its new route from reroute_ts
                dur = (s.planned_recovery_ts - (s.reroute_ts or s.planned_launch_ts)).total_seconds()
                frac = (now - t0).total_seconds() / max(dur, 60)
                hit = self._airborne_defect(ctx, s) if s.status != "RTB" and s.cancel_reason is None else None
                if hit:                                            # airborne snag (D38 second stage): RTB
                    self._log_maint(db, hit, "AIRBORNE", now, s, hsm=hit.hours_since_maint + (now - s.actual_launch_ts).total_seconds() / 3600)
                    s.cancel_reason, s.status = "OTHER", "RTB"
                    left = max(0.15, 1 - frac) * dur * 0.3
                    s.planned_recovery_ts = now + timedelta(seconds=left)
                    self.routes.pop(s.id, None)
                elif now >= s.planned_recovery_ts:
                    self.land(ctx, s)
                elif frac > 0.8 and s.status != "RTB":
                    s.status = "RTB"
                elif frac > 0.2 and s.status == "AIRBORNE":
                    s.status = "ON_STATION"
            elif s.status == "LANDED":
                s.status = "COMPLETED"
            ctx.log(s, before, s.departure_base_id)

    @staticmethod
    def _p_defect(ac: M.Aircraft, t: M.AircraftType, s: M.Sortie, now: datetime, hsm: float | None = None) -> float:
        """The simulated world's defect law (sim/reliability.py) for this tail on this sortie. Hidden from the planner."""
        planned_h = (s.planned_recovery_ts - s.planned_launch_ts).total_seconds() / 3600
        h = ac.hours_since_maint if hsm is None else hsm
        return REL.p_defect(h / max(1.0, t.maint_interval_h), now.year - (ac.induction_year or now.year - 10) + 0.5,
                            planned_h, family(t), ac.tail_no)

    @staticmethod
    def _log_maint(db, ac: M.Aircraft, kind: str, now: datetime, s: M.Sortie | None = None, hsm: float | None = None) -> None:
        planned_h = (s.planned_recovery_ts - s.planned_launch_ts).total_seconds() / 3600 if s else None
        db.add(M.MaintenanceEvent(aircraft_id=ac.id, ts=now, kind=kind, sortie_id=s.id if s else None,
                                  hours_since_maint=round(ac.hours_since_maint if hsm is None else hsm, 1),
                                  airframe_hours=round(ac.airframe_hours, 1), planned_h=round(planned_h, 2) if planned_h else None))

    @staticmethod
    def _support(db, s: M.Sortie) -> bool:
        """A plan tanker sortie (D36): it serves the receivers' mission but isn't the mission itself."""
        if s.origin != "PLAN" or s.mission_type != "AAR_SUPPORT" or not s.mission_id:
            return False
        return db.get(M.Mission, s.mission_id).mission_type != "AAR_SUPPORT"

    def _airborne_defect(self, ctx: Ctx, s: M.Sortie) -> M.Aircraft | None:
        """The tail that develops a defect this tick, if any: each tail's in-flight share of its defect probability,
        spread evenly over the planned flight."""
        db = ctx.db
        planned_h = max(0.2, (s.planned_recovery_ts - s.planned_launch_ts).total_seconds() / 3600)
        for sa in db.scalars(select(M.SortieAircraft).where(M.SortieAircraft.sortie_id == s.id)):
            ac = db.get(M.Aircraft, sa.aircraft_id)
            t = db.get(M.AircraftType, ac.aircraft_type_id)
            p = REL.STAGES[1][1] * self._p_defect(ac, t, s, ctx.now, hsm=sa.hsm_at_launch)
            if ctx.rng.random() < p * ctx.dt_h / planned_h:
                return ac
        return None

    def _cancel(self, ctx: Ctx, s: M.Sortie, reason: str) -> None:
        if s.origin == "PLAN" and self._support(ctx.db, s):
            pass                                  # the receivers' package stays tasked; the monitor re-plans its tanker
        elif s.origin == "PLAN":
            from ..services import sorties as SV
            SV.adjust_stock(ctx.db, s.departure_base_id, SV.sortie_weapons(ctx.db, s), reserve=-1)
            m = ctx.db.get(M.Mission, s.mission_id) if s.mission_id else None
            if m and m.status == "TASKED":
                m.status = "APPROVED"           # the re-tasking monitor picks the gap up
            ctx.changed |= {"mission", "stock_level"}
        s.status, s.cancel_reason = "CANCELLED", reason
        for c in ctx.db.scalars(select(M.Aircrew).join(M.SortieCrew, M.SortieCrew.aircrew_id == M.Aircrew.id)
                                .where(M.SortieCrew.sortie_id == s.id, M.Aircrew.duty_status == "BRIEFED")):
            c.duty_status = "ON_DUTY"

    def crew_up(self, ctx: Ctx, s: M.Sortie) -> None:
        db, rng = ctx.db, ctx.rng
        sas = list(db.scalars(select(M.SortieAircraft).where(M.SortieAircraft.sortie_id == s.id)))
        ok_status = ("AVAILABLE", "STANDBY", "QRA") if s.origin == "QRA_SCRAMBLE" else ("AVAILABLE", "STANDBY")
        busy = set(db.scalars(select(M.SortieAircraft.aircraft_id).join(M.Sortie, M.Sortie.id == M.SortieAircraft.sortie_id)
                              .where(M.Sortie.status.in_(M.ACTIVE_SORTIE), M.Sortie.id != s.id)))
        for sa in sas:
            ac = db.get(M.Aircraft, sa.aircraft_id)
            if ac.status not in ok_status or ac.current_base_id != s.departure_base_id or ac.id in busy:
                swap = db.scalars(select(M.Aircraft).where(M.Aircraft.aircraft_type_id == ac.aircraft_type_id,
                                  M.Aircraft.current_base_id == s.departure_base_id, M.Aircraft.status.in_(("AVAILABLE", "STANDBY")),
                                  M.Aircraft.id.notin_(busy | {x.aircraft_id for x in sas}))).first()
                if not swap:
                    return self._cancel(ctx, s, "AIRCRAFT_US")
                sa.aircraft_id = swap.id
        for sa in sas:                     # pre-flight inspection (D38): the defect law's first stage
            ac = db.get(M.Aircraft, sa.aircraft_id)
            t = db.get(M.AircraftType, ac.aircraft_type_id)
            if rng.random() >= REL.STAGES[0][1] * self._p_defect(ac, t, s, ctx.now):
                continue
            before = snap(ac, "status")
            self._log_maint(db, ac, "PREFLIGHT", ctx.now, s)
            ac.status, ac.maint_eta, ac.status_reason = "MAINT_UNSCHEDULED", ctx.now + timedelta(hours=rng.uniform(3, 24)), "Pre-flight defect"
            ctx.log(ac, before, ac.home_base_id)
            ctx.changed.add("aircraft")
            busy = set(db.scalars(select(M.SortieAircraft.aircraft_id).join(M.Sortie, M.Sortie.id == M.SortieAircraft.sortie_id)
                                  .where(M.Sortie.status.in_(("PLANNED", *M.ACTIVE_SORTIE)), M.Sortie.id != s.id)))
            swap = db.scalars(select(M.Aircraft).where(M.Aircraft.aircraft_type_id == ac.aircraft_type_id,
                              M.Aircraft.current_base_id == s.departure_base_id, M.Aircraft.status.in_(("AVAILABLE", "STANDBY")),
                              M.Aircraft.id.notin_(busy | {x.aircraft_id for x in sas}))).first()
            if not swap:
                return self._cancel(ctx, s, "AIRCRAFT_US")
            sa.aircraft_id = swap.id
        base = db.get(M.AirBase, s.departure_base_id)
        wx = metar.STATE["metars"].get(base.metar_station or "", {})
        if s.mission_type == "TRAINING" and wx.get("flightCategory") in ("IFR", "LIFR"):
            return self._cancel(ctx, s, "WX")
        atf = db.scalars(select(M.FuelStorage).where(M.FuelStorage.base_id == base.id, M.FuelStorage.grade == "ATF")).first()
        if atf and s.priority not in ("P1",) and atf.current_l - s.fuel_planned_kg / ATF_DENSITY < atf.reserve_l:
            return self._cancel(ctx, s, "FUEL")
        have = list(db.scalars(select(M.SortieCrew).where(M.SortieCrew.sortie_id == s.id)))
        if have:  # human-planned crew: verify still available
            for sc in have:
                c = db.get(M.Aircrew, sc.aircrew_id)
                if c.medical_status not in ("FIT_FULL", "FIT_RESTRICTED") or c.duty_status in ("LEAVE", "SICK", "AIRBORNE"):
                    return self._cancel(ctx, s, "CREW_UNAVAILABLE")
                c.duty_status = "BRIEFED"
        else:
            rest_cut = ctx.now - timedelta(hours=10)
            taken: set[int] = set(db.scalars(select(M.SortieCrew.aircrew_id).join(M.Sortie, M.Sortie.id == M.SortieCrew.sortie_id)
                                             .where(M.Sortie.status.in_(("PLANNED", *M.ACTIVE_SORTIE)), M.Sortie.id != s.id)))
            rows = []
            for sa in sas:
                ac = db.get(M.Aircraft, sa.aircraft_id)
                t = db.get(M.AircraftType, ac.aircraft_type_id)
                for role, position_, required in POSITIONS[crew_family(t)]:
                    duty = ("QRA",) if s.origin == "QRA_SCRAMBLE" and role == "PILOT" else ("ON_DUTY", "STANDBY")
                    q = select(M.Aircrew).where(M.Aircrew.squadron_id == ac.squadron_id, M.Aircrew.aircrew_role == role,
                                                M.Aircrew.base_id == s.departure_base_id,
                                                M.Aircrew.medical_status.in_(("FIT_FULL", "FIT_RESTRICTED")),
                                                M.Aircrew.duty_status.in_(duty),
                                                or_(M.Aircrew.rest_started_at.is_(None), M.Aircrew.rest_started_at < rest_cut))
                    if s.origin == "QRA_SCRAMBLE" and role == "PILOT":
                        q = select(M.Aircrew).where(M.Aircrew.base_id == s.departure_base_id, M.Aircrew.duty_status == "QRA",
                                                    M.Aircrew.aircrew_role == "PILOT")
                    pool = [c for c in db.scalars(q.limit(40)) if c.id not in taken]
                    if not pool:
                        if required:
                            return self._cancel(ctx, s, "CREW_UNAVAILABLE")
                        continue
                    c = rng.choice(pool)
                    taken.add(c.id)
                    rows.append((c, ac, position_))
            for c, ac, position_ in rows:
                before = snap(c, "duty_status")
                c.duty_status = "BRIEFED"
                db.add(M.SortieCrew(sortie_id=s.id, aircrew_id=c.id, aircraft_id=ac.id, position=position_))
                ctx.log(c, before, c.base_id)
        s.status = "CREWED"
        ctx.changed.add("aircrew")

    def launch(self, ctx: Ctx, s: M.Sortie) -> None:
        db = ctx.db
        s.status, s.actual_launch_ts = "AIRBORNE", ctx.now
        if s.mission_id and not self._support(db, s):
            m = db.get(M.Mission, s.mission_id)
            if m and m.status in ("TASKED", "APPROVED", "PLANNED"):
                m.status = "ACTIVE"
                ctx.changed.add("mission")
        dur = s.planned_recovery_ts - s.planned_launch_ts
        s.planned_recovery_ts = ctx.now + dur
        for sa in db.scalars(select(M.SortieAircraft).where(M.SortieAircraft.sortie_id == s.id)):
            ac = db.get(M.Aircraft, sa.aircraft_id)
            t = db.get(M.AircraftType, ac.aircraft_type_id)
            before = snap(ac, "status", "current_base_id")
            sa.hsm_at_launch = round(ac.hours_since_maint, 2)
            ac.status, ac.current_base_id, ac.readiness_min = "AIRBORNE", None, None
            ac.fuel_kg = t.max_fuel_kg
            ctx.log(ac, before, ac.home_base_id)
        for c in db.scalars(select(M.Aircrew).join(M.SortieCrew, M.SortieCrew.aircrew_id == M.Aircrew.id)
                            .where(M.SortieCrew.sortie_id == s.id)):
            c.duty_status = "AIRBORNE"
        ctx.changed |= {"aircraft", "aircrew"}

    def land(self, ctx: Ctx, s: M.Sortie) -> None:
        db, now = ctx.db, ctx.now
        hours = (now - s.actual_launch_ts).total_seconds() / 3600
        aborted = s.cancel_reason == "OTHER"
        s.status, s.actual_recovery_ts = ("ABORTED" if aborted else "LANDED"), now
        launch_ist = s.actual_launch_ts.astimezone(IST).hour
        night = hours if launch_ist >= 19 or launch_ist < 6 else 0.0
        burn = 0.0
        bad = set(db.scalars(select(M.MaintenanceEvent.aircraft_id).where(M.MaintenanceEvent.sortie_id == s.id,
                                                                          M.MaintenanceEvent.kind == "AIRBORNE")))
        for sa in db.scalars(select(M.SortieAircraft).where(M.SortieAircraft.sortie_id == s.id)):
            ac = db.get(M.Aircraft, sa.aircraft_id)
            t = db.get(M.AircraftType, ac.aircraft_type_id)
            before = snap(ac, "status", "current_base_id")
            snag = aborted and (ac.id in bad or not bad)
            ac.status, ac.current_base_id = ("MAINT_UNSCHEDULED" if snag else "TURNAROUND"), s.recovery_base_id
            if snag:
                ac.maint_eta, ac.status_reason = now + timedelta(hours=ctx.rng.uniform(4, 24)), "Airborne snag (simulated)"
            elif ctx.rng.random() < REL.STAGES[2][1] * self._p_defect(ac, t, s, now, hsm=sa.hsm_at_launch):
                self._log_maint(db, ac, "POSTFLIGHT", now, s, hsm=(sa.hsm_at_launch or ac.hours_since_maint) + hours)
                ac.status_reason = "Post-flight defect"          # rectified when the turnaround ends
            ac.airframe_hours += hours
            ac.hours_since_maint += hours
            ac.last_sortie_at = now
            ac.fuel_kg = max(t.max_fuel_kg * 0.05, t.max_fuel_kg - t.burn_kg_per_h * hours)
            burn += t.burn_kg_per_h * hours
            ctx.log(ac, before, ac.home_base_id)
            for sc in db.scalars(select(M.SortieCrew).where(M.SortieCrew.sortie_id == s.id, M.SortieCrew.aircraft_id == ac.id)):
                sc.hours_logged, sc.night_hours = round(hours, 2), round(night, 2)
                c = db.get(M.Aircrew, sc.aircrew_id)
                c.duty_status, c.rest_started_at = "CREW_REST", now
                c.total_hours += hours
                c.night_hours += night
                th = db.scalars(select(M.AircrewTypeHours).where(M.AircrewTypeHours.aircrew_id == c.id,
                                                                 M.AircrewTypeHours.aircraft_type_id == t.id)).first()
                if not th:
                    th = M.AircrewTypeHours(aircrew_id=c.id, aircraft_type_id=t.id, hours=0, captain_hours=0,
                                            night_hours=0, instrument_hours=0)
                    db.add(th)
                th.hours += hours
                th.night_hours += night
                if sc.position in ("CAPTAIN", "INSTRUCTOR", "RPA_PILOT"):
                    th.captain_hours += hours
                th.last_flown_at = now
        s.fuel_used_kg = round(burn)
        self.routes.pop(s.id, None)
        ctx.changed |= {"aircraft", "aircrew"}
        if s.origin == "PLAN":
            self._plan_landed(ctx, s, hours, aborted)

    def _plan_landed(self, ctx: Ctx, s: M.Sortie, hours: float, aborted: bool) -> None:
        """Phase 2: release / expend the generic weapons and record how much time on station the mission got."""
        from ..services import sorties as SV
        db = ctx.db
        w = SV.sortie_weapons(db, s)
        if w:
            if s.mission_type in ("STRIKE_EXERCISE", "CAS_EXERCISE") and not aborted:
                SV.adjust_stock(db, s.departure_base_id, w, consume=1)
            else:
                SV.adjust_stock(db, s.departure_base_id, w, reserve=-1)
            ctx.changed.add("stock_level")
        m = db.get(M.Mission, s.mission_id) if s.mission_id and not self._support(db, s) else None
        if m:
            t0 = s.reroute_ts or s.actual_launch_ts            # a re-roled sortie's mission starts at the re-role
            planned_h = max(0.1, (s.planned_recovery_ts - t0).total_seconds() / 3600)
            flown_h = hours - (t0 - s.actual_launch_ts).total_seconds() / 3600
            share = 1.0 if not aborted else max(0.0, min(1.0, flown_h / planned_h))
            m.on_station_achieved_min = round((m.on_station_achieved_min or 0) + m.on_station_min * share, 1)
            m.outcome = "MET" if m.on_station_achieved_min >= m.on_station_min * 0.95 else "PARTIAL" if m.on_station_achieved_min > 0 else "MISSED"
            m.status = "COMPLETED"
            ctx.changed.add("mission")

    # ------------------------------------------------------------------ turnaround + maintenance (FR-SIM-06)
    def aircraft(self, ctx: Ctx) -> None:
        db, now, rng = ctx.db, ctx.now, ctx.rng
        for ac, t in db.execute(select(M.Aircraft, M.AircraftType).join(M.AircraftType, M.AircraftType.id == M.Aircraft.aircraft_type_id)
                                .where(M.Aircraft.status == "TURNAROUND")):
            if ac.last_sortie_at and ac.last_sortie_at + timedelta(minutes=t.turnaround_min) > now:
                continue
            before = snap(ac, "status", "fuel_kg")
            need_l = max(0.0, (t.max_fuel_kg - ac.fuel_kg) / ATF_DENSITY)
            atf = db.scalars(select(M.FuelStorage).where(M.FuelStorage.base_id == ac.current_base_id,
                                                         M.FuelStorage.grade == "ATF")).first()
            if atf and need_l > 1:
                q = round(min(need_l, max(0.0, atf.current_l)), -1)
                if q > 0:
                    atf.current_l -= q
                    ac.fuel_kg += q * ATF_DENSITY
                    db.add(M.FuelTransaction(fuel_storage_id=atf.id, ts=now, kind="ISSUE_AIRCRAFT", quantity_l=q,
                                             balance_after_l=atf.current_l, aircraft_id=ac.id, actor="SIMULATOR"))
                    ctx.changed.add("fuel_storage")
            if ac.hours_since_maint >= t.maint_interval_h:
                self._log_maint(db, ac, "SCHEDULED", now)
                ac.status, ac.maint_eta, ac.status_reason = "MAINT_SCHEDULED", now + timedelta(hours=rng.uniform(12, 48)), \
                    f"{t.maint_interval_h} h scheduled inspection"
            elif ac.status_reason == "Post-flight defect":
                spare = db.execute(text("""SELECT l.id, l.qty_on_hand FROM stock_level l JOIN stock_item i ON i.id = l.stock_item_id
                    JOIN warehouse w ON w.id = l.warehouse_id WHERE w.base_id = :b AND i.aircraft_type_id = :t
                    ORDER BY random() LIMIT 1"""), {"b": ac.home_base_id, "t": t.id}).first()
                if spare and spare.qty_on_hand <= 0:
                    ac.status, ac.maint_eta, ac.status_reason = "AOG", now + timedelta(hours=rng.uniform(24, 72)), "Awaiting spares"
                else:
                    if spare:
                        db.execute(text("UPDATE stock_level SET qty_on_hand = qty_on_hand - 1, version = version + 1 WHERE id = :id"),
                                   {"id": spare.id})
                        ctx.changed.add("stock_level")
                    ac.status, ac.maint_eta, ac.status_reason = "MAINT_UNSCHEDULED", now + timedelta(hours=rng.uniform(3, 24)), "Snag rectification"
            else:
                ac.status, ac.status_reason = "AVAILABLE", None
            ctx.log(ac, before, ac.home_base_id)
        for ac, t in db.execute(select(M.Aircraft, M.AircraftType).join(M.AircraftType, M.AircraftType.id == M.Aircraft.aircraft_type_id)
                                .where(M.Aircraft.status.in_(("MAINT_SCHEDULED", "MAINT_UNSCHEDULED", "AOG")),
                                       M.Aircraft.maint_eta <= now)):
            before = snap(ac, "status")
            if ac.status == "MAINT_SCHEDULED":
                ac.hours_since_maint = 0
                ac.next_maint_due_hours = ac.airframe_hours + t.maint_interval_h
            ac.status, ac.maint_eta, ac.status_reason = "AVAILABLE", None, None
            ctx.log(ac, before, ac.home_base_id)

    # ------------------------------------------------------------------ fuel replenishment (FR-SIM-04)
    def fuel(self, ctx: Ctx) -> None:
        db, now, rng = ctx.db, ctx.now, ctx.rng
        for fs, btype in db.execute(select(M.FuelStorage, M.AirBase.base_type).join(M.AirBase, M.AirBase.id == M.FuelStorage.base_id)
                                    .where(or_(and_(M.FuelStorage.current_l < M.FuelStorage.reorder_l, M.FuelStorage.replenish_eta.is_(None)),
                                               M.FuelStorage.replenish_eta <= now))):
            before = snap(fs, "current_l", "replenish_eta")
            if fs.replenish_eta is None:
                lead = rng.uniform(48, 96) if btype == "ALG" else rng.uniform(12, 48)
                fs.replenish_eta = now + timedelta(hours=lead)
            else:
                q = round(max(0.0, fs.capacity_l * 0.9 - fs.current_l), -2)
                fs.current_l += q
                fs.replenish_eta = None
                db.add(M.FuelTransaction(fuel_storage_id=fs.id, ts=now, kind="RECEIPT", quantity_l=q,
                                         balance_after_l=fs.current_l, actor="SIMULATOR"))
            ctx.log(fs, before, fs.base_id)

    # ------------------------------------------------------------------ crew duty cycle (FR-SIM-05)
    def crew(self, ctx: Ctx) -> None:
        db, now, rng = ctx.db, ctx.now, ctx.rng
        db.execute(text("""UPDATE aircrew SET duty_status = 'OFF_DUTY', rest_started_at = NULL, version = version + 1
                           WHERE duty_status = 'CREW_REST' AND rest_started_at < :cut"""), {"cut": now - timedelta(hours=10)})
        prev_ist, now_ist = ctx.prev.astimezone(IST), now.astimezone(IST)
        shifts = [h for d in sorted({prev_ist.date(), now_ist.date()}) for h in (6, 14, 22)
                  if prev_ist < datetime.combine(d, datetime.min.time(), IST) + timedelta(hours=h) <= now_ist]
        if not shifts:
            return
        db.execute(text("SELECT setseed(:s)"), {"s": rng.random() * 2 - 1})  # deterministic SQL random() (FR-SIM-11)
        db.execute(text("""UPDATE aircrew SET duty_status = CASE
                WHEN duty_status = 'ON_DUTY' AND random() < 0.45 THEN 'OFF_DUTY'
                WHEN duty_status = 'OFF_DUTY' AND random() < 0.55 THEN 'ON_DUTY'
                WHEN duty_status = 'STANDBY' AND random() < 0.5 THEN 'ON_DUTY'
                WHEN duty_status IN ('OFF_DUTY','ON_DUTY') AND random() < 0.003 THEN 'LEAVE'
                WHEN duty_status IN ('OFF_DUTY','ON_DUTY') AND random() < 0.001 THEN 'SICK'
                WHEN duty_status = 'LEAVE' AND random() < 0.1 THEN 'OFF_DUTY'
                WHEN duty_status = 'SICK' AND random() < 0.25 THEN 'OFF_DUTY'
                ELSE duty_status END, version = version + 1
            WHERE duty_status IN ('ON_DUTY','OFF_DUTY','STANDBY','LEAVE','SICK')"""))
        shift = {6: "A", 14: "B", 22: "C"}[shifts[-1]]
        db.execute(text("""UPDATE ground_crew_strength SET
                on_duty = CASE WHEN shift = :s THEN greatest(held - on_leave, 0) ELSE 0 END,
                standby = CASE WHEN shift = :nx THEN round(held * 0.3) ELSE 0 END, version = version + 1"""),
                   {"s": shift, "nx": {"A": "B", "B": "C", "C": "A"}[shift]})
        audit(db, None, "SIM_TRANSITION", "aircrew", None, None, None, {"event": f"shift change {shift}"})
        ctx.changed |= {"aircrew", "ground_crew_strength"}

    # ------------------------------------------------------------------ radar / AD / comms faults (FR-SIM-08)
    def faults(self, ctx: Ctx) -> None:
        db, now, rng = ctx.db, ctx.now, ctx.rng
        p = 0.006 * ctx.dt_h
        for model, ok, bad in ((M.RadarSite, "OPERATIONAL", ("DEGRADED", "OFFLINE")),
                               (M.AirDefenceBattery, "OPERATIONAL", ("DEGRADED", "OFFLINE")),
                               (M.CommsNode, "UP", ("DEGRADED", "DOWN"))):
            for site in db.scalars(select(model).where(or_(model.repair_eta <= now, model.status == ok))):
                before = snap(site, "status")
                if site.status != ok and site.repair_eta and site.repair_eta <= now:
                    site.status, site.repair_eta = ok, None
                    if model is M.AirDefenceBattery:
                        site.launchers_ready = site.launchers_total
                elif site.status == ok and rng.random() < p:
                    site.status = bad[0] if rng.random() < 0.7 else bad[1]
                    site.repair_eta = now + timedelta(hours=rng.uniform(2, 24))
                    if model is M.AirDefenceBattery:
                        site.launchers_ready = max(0, site.launchers_total - rng.randint(1, site.launchers_total))
                if snap(site, "status") != before:
                    site.version += 1
                ctx.log(site, before, getattr(site, "base_id", None) or getattr(site, "protected_base_id", None))

    # ------------------------------------------------------------------ QRA posture (FR-SIM-07)
    def qra(self, ctx: Ctx) -> None:
        db, now = ctx.db, ctx.now
        rest_cut = now - timedelta(hours=10)
        tasked = select(M.SortieAircraft.aircraft_id).join(M.Sortie, M.Sortie.id == M.SortieAircraft.sortie_id) \
            .where(M.Sortie.status.in_(("PLANNED", *M.ACTIVE_SORTIE)))
        tasked_crew = select(M.SortieCrew.aircrew_id).join(M.Sortie, M.Sortie.id == M.SortieCrew.sortie_id) \
            .where(M.Sortie.status.in_(("PLANNED", *M.ACTIVE_SORTIE)))
        for q in db.scalars(select(M.QraPosture).where(M.QraPosture.active)):
            have = db.scalar(select(func.count()).where(M.Aircraft.current_base_id == q.base_id, M.Aircraft.status == "QRA",
                                                        M.Aircraft.aircraft_type_id == q.aircraft_type_id))
            for ac in db.scalars(select(M.Aircraft).where(M.Aircraft.current_base_id == q.base_id,
                                 M.Aircraft.aircraft_type_id == q.aircraft_type_id, M.Aircraft.status == "AVAILABLE",
                                 M.Aircraft.id.notin_(tasked))
                                 .limit(max(0, q.required_aircraft - have))):
                before = snap(ac, "status")
                ac.status, ac.readiness_min = "QRA", q.readiness_min
                ctx.log(ac, before, q.base_id)
            crew = db.scalar(select(func.count()).where(M.Aircrew.base_id == q.base_id, M.Aircrew.duty_status == "QRA"))
            if crew < q.required_aircraft:
                for c in db.scalars(select(M.Aircrew).where(
                        M.Aircrew.base_id == q.base_id, M.Aircrew.aircrew_role == "PILOT", M.Aircrew.stream == "FIGHTER",
                        M.Aircrew.duty_status.in_(("ON_DUTY", "STANDBY")), M.Aircrew.medical_status == "FIT_FULL",
                        M.Aircrew.ops_category.in_(("FULLY_OPERATIONAL", "FLIGHT_LEAD")),
                        or_(M.Aircrew.rest_started_at.is_(None), M.Aircrew.rest_started_at < rest_cut),
                        M.Aircrew.id.notin_(tasked_crew))
                        .limit(q.required_aircraft - crew)):
                    before = snap(c, "duty_status")
                    c.duty_status = "QRA"
                    ctx.log(c, before, q.base_id)

    # ------------------------------------------------------------------ simulated unknown tracks + scramble (FR-SIM-07)
    def unknown_tracks(self, ctx: Ctx) -> None:
        db, now, rng = ctx.db, ctx.now, ctx.rng
        forced, self.force_unknown = self.force_unknown, False
        if self.hostile_samples and (forced or rng.random() < 0.5 * ctx.dt_h):   # λ = 0.5 per sim hour, theatre-wide
            for _ in range(20):
                bp = rng.choice(self.hostile_samples)
                out = (bearing((78.9, 22.5), bp))                     # away from India's interior
                p0 = offset(*bp, 160, out + rng.uniform(-25, 25))
                p1 = offset(*bp, config.BORDER_BUFFER_KM + 12, out)
                if not self.G.outside.contains(LineString([p0, p1])):
                    uid = f"UNK-{ctx.tick}-{rng.randint(100, 999)}"
                    self.unknowns[uid] = {"id": uid, "p0": p0, "p1": p1, "border": bp, "spawn": now,
                                          "speed_kmh": rng.uniform(650, 850), "alt_m": rng.choice([6000, 8500, 10500]),
                                          "loiter_min": rng.uniform(6, 14), "detected": False, "scrambled": False}
                    break
        for uid, u in list(self.unknowns.items()):
            leg_h = dist_km(u["p0"], u["p1"]) / u["speed_kmh"]
            el = (now - u["spawn"]).total_seconds() / 3600
            if el > 2 * leg_h + u["loiter_min"] / 60:
                self.unknowns.pop(uid)
                continue
            if el < leg_h:
                frac, phase = el / leg_h, "INBOUND"
            elif el < leg_h + u["loiter_min"] / 60:
                frac, phase = 1.0, "LOITER"
            else:
                frac, phase = 1 - (el - leg_h - u["loiter_min"] / 60) / leg_h, "OUTBOUND"
            x, y, hdg = position([u["p0"], u["p1"]], frac)
            if phase == "OUTBOUND":
                hdg = (hdg + 180) % 360
            u.update(lon=x, lat=y, heading=hdg, phase=phase,
                     near_border_km=max(0.0, dist_km((x, y), u["border"]) - 0))
            if not u["detected"]:
                hit = db.execute(text("""SELECT r.id FROM radar_site r JOIN radar_type t ON t.id = r.radar_type_id
                    WHERE r.status <> 'OFFLINE' AND ST_DWithin(r.geom::geography, ST_SetSRID(ST_Point(:x,:y),4326)::geography,
                    t.max_range_km * 1000) LIMIT 1"""), {"x": x, "y": y}).first()
                u["detected"] = bool(hit)
            if u["detected"] and not u["scrambled"]:
                u["scrambled"] = self.scramble(ctx, u)

    def scramble(self, ctx: Ctx, u: dict) -> bool:
        db, now, rng = ctx.db, ctx.now, ctx.rng
        best = None
        for q, b in db.execute(select(M.QraPosture, M.AirBase).join(M.AirBase, M.AirBase.id == M.QraPosture.base_id)
                               .where(M.QraPosture.active)):
            d = dist_km(pt(b.geom), u["border"])
            n = db.scalar(select(func.count()).where(M.Aircraft.current_base_id == b.id, M.Aircraft.status == "QRA"))
            if n and d < 900 and (best is None or d < best[2]):
                best = (q, b, d)
        if not best:
            return False
        q, b, _ = best
        home = pt(b.geom)
        inward = (bearing(u["border"], (78.9, 22.5)))
        cap = offset(*u["border"], config.BORDER_BUFFER_KM + 15, inward)
        if not self.G.ok(*cap):
            cap = self.G.place_near(rng, *u["border"], config.BORDER_BUFFER_KM + 10, config.BORDER_BUFFER_KM + 60)
        if not cap:
            return False
        t = db.get(M.AircraftType, q.aircraft_type_id)
        loop = [offset(*cap, 18, a) for a in (0, 120, 240)]
        pts = [home, cap, *loop, cap, home]
        if not self.G.route_ok(pts):
            pts = [home, cap, home]
        dur = 2 * dist_km(home, cap) / (t.cruise_kt * 1.852 * 1.3) + 0.4
        launch = now + timedelta(minutes=q.readiness_min)
        seq = db.execute(text("SELECT coalesce(max(id), 0) + 1 FROM sortie")).scalar()
        s = M.Sortie(code=f"SIM-{b.code}-Q{seq:05d}", origin="QRA_SCRAMBLE", mission_type="INTERCEPT", priority="P1",
                     departure_base_id=b.id, recovery_base_id=b.id, status="PLANNED", planned_launch_ts=launch,
                     planned_recovery_ts=launch + timedelta(hours=dur), route_geom=from_shape(LineString(pts), srid=4326),
                     cruise_alt_m=u["alt_m"], fuel_planned_kg=round(t.burn_kg_per_h * dur), target_track_id=u["id"],
                     is_simulated=True)
        db.add(s)
        db.flush()
        for i, ac in enumerate(db.scalars(select(M.Aircraft).where(M.Aircraft.current_base_id == b.id, M.Aircraft.status == "QRA")
                                          .limit(q.required_aircraft))):
            db.add(M.SortieAircraft(sortie_id=s.id, aircraft_id=ac.id, callsign=f"SCRAMBLE{i + 1}", formation_pos=i + 1))
        db.flush()
        self.crew_up(ctx, s)          # QRA crews are pre-briefed: crew immediately
        u["interceptor_base"] = b.code
        u["sortie_id"] = s.id
        ctx.changed.add("sortie")
        log.info("scramble %s from %s against %s", s.code, b.code, u["id"])
        return s.status == "CREWED"

    # ------------------------------------------------------------------ KPI snapshots (FR-CMD-05)
    def kpis(self, ctx: Ctx) -> None:
        db = ctx.db
        db.execute(text("""
            INSERT INTO kpi_snapshot (ts, scope, scope_id, metric, value)
            SELECT sim_now(), 'COMMAND', c.id, 'serviceability',
                   round(100.0 * sum(v.serviceable) / nullif(sum(v.effective), 0), 1)
            FROM v_aircraft_serviceability v JOIN base b ON b.id = v.base_id JOIN command c ON c.id = b.command_id GROUP BY c.id
            UNION ALL
            SELECT sim_now(), 'THEATRE', NULL, 'serviceability', round(100.0 * sum(serviceable) / nullif(sum(effective), 0), 1)
            FROM v_aircraft_serviceability
            UNION ALL
            SELECT sim_now(), 'THEATRE', NULL, 'airborne', count(*) FROM aircraft WHERE status = 'AIRBORNE'"""))

    # ------------------------------------------------------------------ simulated track DTOs (tracks.sim)
    def tracks(self, db: Session, ctx: Ctx) -> list[dict]:
        out = []
        rows = db.execute(text("""
            SELECT s.id, s.code, s.status, s.mission_type, s.actual_launch_ts, s.planned_recovery_ts, s.cruise_alt_m,
                   s.reroute_ts, s.version,
                   s.origin, s.target_track_id, sa.callsign, sa.formation_pos, a.id AS aircraft_id, a.tail_no,
                   t.name AS type, t.icao_type, t.category, t.cruise_kt, t.burn_kg_per_h, t.max_fuel_kg, b.code AS base,
                   CASE WHEN s.id = ANY(:known) THEN NULL ELSE ST_AsGeoJSON(s.route_geom, 5) END AS route
            FROM sortie s JOIN sortie_aircraft sa ON sa.sortie_id = s.id JOIN aircraft a ON a.id = sa.aircraft_id
            JOIN aircraft_type t ON t.id = a.aircraft_type_id JOIN base b ON b.id = s.departure_base_id
            WHERE s.status IN ('AIRBORNE','ON_STATION','RTB')"""), {"known": list(self.routes)}).mappings()
        import json
        for r in rows:
            if r["route"]:
                self.routes[r["id"]] = [tuple(c) for c in json.loads(r["route"])["coordinates"]]
                self.route_ver[r["id"]] = r["version"]
            elif self.route_ver.get(r["id"]) != r["version"]:   # re-roled or re-routed since cached
                g = db.execute(text("SELECT ST_AsGeoJSON(route_geom, 5) FROM sortie WHERE id = :i"), {"i": r["id"]}).scalar()
                if g:
                    self.routes[r["id"]] = [tuple(c) for c in json.loads(g)["coordinates"]]
                self.route_ver[r["id"]] = r["version"]
            pts = self.routes.get(r["id"])
            if not pts:
                continue
            t0 = r["reroute_ts"] or r["actual_launch_ts"]
            dur = (r["planned_recovery_ts"] - t0).total_seconds()
            el = (ctx.now - r["actual_launch_ts"]).total_seconds()
            frac = (ctx.now - t0).total_seconds() / max(dur, 60)
            x, y, hdg = position(pts, frac)
            off = (r["formation_pos"] - 1) * 0.012
            climb = min(1.0, frac / 0.08, (1 - frac) / 0.08) if frac < 1 else 0
            if r["reroute_ts"]:
                climb = min(1.0, (1 - frac) / 0.08) if frac < 1 else 0   # already at height when re-roled
            out.append({"track_id": f"SIM-{r['aircraft_id']}", "kind": "SIM_IAF", "simulated": True,
                        "sortie_id": r["id"], "sortie_code": r["code"], "aircraft_id": r["aircraft_id"],
                        "tail_no": r["tail_no"], "callsign": r["callsign"], "type": r["type"], "icao_type": r["icao_type"],
                        "category": r["category"], "mission_type": r["mission_type"], "origin": r["origin"],
                        "lat": round(y + off, 5), "lon": round(x + off, 5), "heading_deg": round(hdg),
                        "alt_m": round(max(0, climb) * r["cruise_alt_m"]), "gs_kt": round(r["cruise_kt"]),
                        "phase": "CLIMB" if frac < 0.08 else "DESCENT" if frac > 0.92 else
                        ("ON_STATION" if r["status"] == "ON_STATION" else "CRUISE"),
                        "fuel_kg": round(max(0, r["max_fuel_kg"] - r["burn_kg_per_h"] * el / 3600)),
                        "status": r["status"], "base": r["base"], "target_track_id": r["target_track_id"]})
        for u in self.unknowns.values():
            if "lon" in u:
                out.append({"track_id": u["id"], "kind": "SIM_UNKNOWN", "simulated": True, "callsign": u["id"],
                            "lat": round(u["lat"], 5), "lon": round(u["lon"], 5), "heading_deg": round(u["heading"]),
                            "alt_m": u["alt_m"], "gs_kt": round(u["speed_kmh"] / 1.852), "phase": u["phase"],
                            "detected": u["detected"], "scrambled": u["scrambled"],
                            "interceptor_base": u.get("interceptor_base")})
        return out


def feed_status() -> dict:
    return feeds.STATUS
