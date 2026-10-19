"""OpsState: an immutable picture of everything the planner needs at time T (PHASE2_IMPLEMENTATION_PLAN §5).

The planner, validator, forecasts, what-if and re-tasking all read a snapshot, never the live session. What-if works on
a copy (`clone()`), so it can never write. Built in well under a second for the whole theatre.
"""
import copy
import json
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from shapely import wkb
from shapely.prepared import prep
from sqlalchemy import text
from sqlalchemy.orm import Session

from generator import config as GC

from .. import config as appcfg
from ..geo import India, load_india
from . import config as D
from . import predict
from . import traffic

SERVICEABLE = ("AVAILABLE", "STANDBY", "TURNAROUND")
MAINT = ("MAINT_SCHEDULED", "MAINT_UNSCHEDULED", "AOG")
LIVE_SORTIE = ("PLANNED", "CREWED", "READY", "AIRBORNE", "ON_STATION", "RTB")
_INDIA: India | None = None


def india(db: Session) -> India:
    global _INDIA
    if _INDIA is None:
        _INDIA = load_india(db)
    return _INDIA


@dataclass
class BaseInfo:
    id: int
    code: str
    name: str
    command_id: int | None
    command: str | None
    lon: float
    lat: float
    elev: float
    base_type: str
    ops_status: str
    runway_status: str          # best runway: OPEN / RESTRICTED / CLOSED / UNDER_REPAIR / NONE
    runway_heading: float | None
    runways: int = 1            # usable runways (launch-rate capacity)
    closed_windows: list = field(default_factory=list)   # [(from, to)] runway closures known in advance (injects)

    def runway_ok(self, t: datetime) -> bool:
        """Scheduled closures (exercise injects) are exact windows; otherwise the current runway status holds."""
        if self.ops_status == "CLOSED":
            return False
        if self.closed_windows:
            return all(not (a <= t < b) for a, b in self.closed_windows)
        return self.runway_status not in ("CLOSED", "UNDER_REPAIR", "NONE")


@dataclass
class TypeInfo:
    id: int
    name: str
    role: str
    category: str
    family: str
    crew_family: str
    cruise_kt: float
    burn: float
    max_fuel: float
    endurance_h: float
    radius_km: float | None
    turnaround_min: int
    maint_interval_h: float
    slot_size: str
    loadouts: tuple = ()


@dataclass
class AircraftInfo:
    id: int
    tail: str
    type_id: int
    base_id: int | None
    home_base_id: int
    squadron_id: int
    status: str
    hours_left: float
    available_from: datetime    # when it can be prepared for a sortie (maintenance / turnaround end)
    frac: float = 0.0           # share of the inspection interval used        } snag-risk features (D38)
    age_y: float = 10.0         # years since induction                       }
    family: str = "transport"   #                                             }
    recent: int = 0             # defects in the last 30 days                 }


@dataclass
class CrewInfo:
    id: int
    name: str
    rank: str
    role: str
    stream: str
    base_id: int
    squadron_id: int | None
    duty: str
    rating: str
    ops_category: str
    medical_ok_until: datetime | None
    quals: frozenset
    current: dict               # type_id -> currency expiry (datetime)
    hours_7d: float
    rest_until: datetime | None


@dataclass
class Mission:
    id: int
    code: str
    name: str
    mission_type: str
    priority: str
    status: str
    window_start: datetime
    window_end: datetime
    command_id: int | None
    target: tuple               # (lon, lat)
    target_base_id: int | None
    required: int
    roles: tuple
    loadout_code: str | None
    on_station_min: int
    min_quals: tuple
    max_risk: str
    depends_on: int | None = None   # D41: mission that must be on station whenever this one is
    parent: int | None = None       # D42: split parent (parts are covered all or nothing)
    part: tuple | None = None       # (part_no, parts, kind)


@dataclass
class Zone:
    id: int
    code: str
    name: str
    kind: str
    geom: object
    prepared: object
    risk: float
    capacity: int
    active_from: datetime | None
    active_to: datetime | None

    def active(self, a: datetime, b: datetime) -> bool:
        return (self.active_from is None or self.active_from < b) and (self.active_to is None or self.active_to > a)


@dataclass
class OpsState:
    now: datetime
    horizon_end: datetime
    G: India
    bases: dict
    types: dict
    aircraft: dict
    crew: dict
    missions: dict
    loadouts: dict              # code -> dict(name, items, fuel_penalty_pct, radius_factor)
    fuel: dict                  # base_id -> dict(current_l, reserve_l, capacity_l, committed_l)
    stock: dict                 # base_id -> {category: qty available}
    qra: dict                   # (base_id, type_id) -> dict(required, have)
    wx: dict                    # base_id -> sorted list of (ts, ceiling_ft, vis_m, wind_kt, gust_kt, dir, cat, source)
    airspace: list
    threats: list
    busy_aircraft: dict         # aircraft_id -> [(from, to, sortie_id)]
    busy_crew: dict             # aircrew_id -> [(from, to, sortie_id)]
    committed: list             # current committed plan items (dicts) for stability / re-tasking
    committed_plan_id: int | None
    launches: dict = field(default_factory=dict)       # base_id -> [launch times] of sorties already planned (per aircraft)
    by_base_type: dict = field(default_factory=dict)   # (base_id, type_id) -> [aircraft ids]
    tails: dict = field(default_factory=dict)          # every aircraft id -> tail number (incl. ones not usable now)
    crew_by_base: dict = field(default_factory=dict)   # base_id -> [aircrew ids]
    snag: object = None                                # decide/predict.Model in use (None: no model yet)
    traffic: object = None                             # decide/traffic.Traffic: civil airspace density (D39)

    def clone(self) -> "OpsState":
        """Copy for what-if: every mutable table is deep-copied; geometry (India, zones) is shared read-only."""
        c = copy.copy(self)
        for name in ("bases", "types", "aircraft", "crew", "missions", "fuel", "stock", "qra", "wx", "busy_aircraft",
                     "busy_crew"):
            setattr(c, name, copy.deepcopy(getattr(self, name)))
        c.airspace, c.threats, c.committed = list(self.airspace), list(self.threats), list(self.committed)
        c.index()
        return c

    # -------------------------------------------------------------- weather
    def family_of(self, mid: int) -> list:
        """A mission, or the parts it was split into (D42): what counts as "that mission" for a dependency."""
        kids = [k for k, m in self.missions.items() if m.parent == mid]
        return kids or [mid]

    def cover_of(self, mids: set) -> dict:
        """mission id -> [(on station, off station)] of committed packages that are still live (D41)."""
        from datetime import datetime as _dt
        out: dict = {}
        for it in self.committed:
            if it["mission_id"] in mids and it.get("sortie_status") not in ("CANCELLED", "ABORTED") and it.get("on_station_ts"):
                off = (it.get("score") or {}).get("off_station")
                if off:
                    out.setdefault(it["mission_id"], []).append((it["on_station_ts"], _dt.fromisoformat(off) if isinstance(off, str) else off))
        return out

    def wx_at(self, base_id: int, t: datetime):
        rows = self.wx.get(base_id)
        if not rows:
            return None
        i = bisect_right([r[0] for r in rows], t) - 1
        return rows[max(0, i)]

    def index(self) -> None:
        self.by_base_type, self.crew_by_base = {}, {}
        for a in self.aircraft.values():
            if a.base_id is not None:
                self.by_base_type.setdefault((a.base_id, a.type_id), []).append(a.id)
        for c in self.crew.values():
            self.crew_by_base.setdefault(c.base_id, []).append(c.id)


def _geo(g):
    return wkb.loads(bytes(g)) if g is not None else None


def build(db: Session, horizon_h: float = D.HORIZON_H, now: datetime | None = None,
          release_sortie_ids: set | None = None, mission_ids: set | None = None) -> OpsState:
    """release_sortie_ids: sorties whose aircraft and crew are treated as free (re-planning those packages)."""
    release = set(release_sortie_ids or ())
    now = now or db.execute(text("SELECT sim_now()")).scalar()
    end = now + timedelta(hours=horizon_h)
    q = lambda sql, **p: db.execute(text(sql), p).mappings().all()  # noqa: E731

    # -------------------------------------------------------------- bases (+ best runway)
    bases = {}
    for r in q("""SELECT b.id, b.code, b.name, b.command_id, c.code AS command, ST_X(b.geom) lon, ST_Y(b.geom) lat,
                         coalesce(b.elevation_m, 0) elev, b.base_type, b.ops_status,
                         (SELECT r.status FROM runway r WHERE r.base_id = b.id ORDER BY
                            CASE r.status WHEN 'OPEN' THEN 0 WHEN 'RESTRICTED' THEN 1 ELSE 2 END, r.length_m DESC NULLS LAST LIMIT 1) rwy,
                         (SELECT r.heading_true_deg FROM runway r WHERE r.base_id = b.id AND r.status IN ('OPEN','RESTRICTED')
                            ORDER BY r.length_m DESC NULLS LAST LIMIT 1) hdg,
                         (SELECT count(*) FROM runway r WHERE r.base_id = b.id AND r.status IN ('OPEN','RESTRICTED')) nrwy
                  FROM base b LEFT JOIN command c ON c.id = b.command_id WHERE b.side = 'OWN'"""):
        bases[r["id"]] = BaseInfo(r["id"], r["code"], r["name"], r["command_id"], r["command"], r["lon"], r["lat"],
                                  r["elev"], r["base_type"], r["ops_status"], r["rwy"] or "OPEN", r["hdg"],
                                  max(1, r["nrwy"] or 1))

    # -------------------------------------------------------------- types + loadouts
    loadouts = {r["code"]: dict(name=r["name"], items=r["items"] or {}, fuel_penalty_pct=r["fuel_penalty_pct"],
                                radius_factor=r["radius_factor"], role_family=r["role_family"])
                for r in q("SELECT code, name, items, fuel_penalty_pct, radius_factor, role_family FROM loadout_config")}
    compat: dict[int, list] = {}
    for r in q("SELECT tl.aircraft_type_id, l.code FROM type_loadout tl JOIN loadout_config l ON l.id = tl.loadout_id"):
        compat.setdefault(r["aircraft_type_id"], []).append(r["code"])
    types = {}
    for r in q("SELECT * FROM aircraft_type WHERE in_service"):
        fam = GC.ROLE_FAMILY[r["role"]][0]
        types[r["id"]] = TypeInfo(r["id"], r["name"], r["role"], r["category"], fam,
                                  "fighter2" if fam == "fighter" and r["seats_other"] > 0 else fam, r["cruise_kt"],
                                  r["burn_kg_per_h"], r["max_fuel_kg"], r["endurance_h"], r["combat_radius_km"],
                                  r["turnaround_min"], r["maint_interval_h"], r["slot_size"], tuple(sorted(compat.get(r["id"], []))))

    # -------------------------------------------------------------- existing sorties -> busy intervals
    busy_ac: dict[int, list] = {}
    busy_cr: dict[int, list] = {}
    future_base: dict[int, int] = {}
    launches: dict[int, list] = {}
    turn = {t.id: t.turnaround_min for t in types.values()}
    committed_fuel: dict[int, float] = {}
    for r in q("""SELECT s.id, s.status, s.planned_launch_ts, s.planned_recovery_ts, s.recovery_base_id, s.departure_base_id,
                         s.fuel_planned_kg, sa.aircraft_id, a.aircraft_type_id
                  FROM sortie s JOIN sortie_aircraft sa ON sa.sortie_id = s.id JOIN aircraft a ON a.id = sa.aircraft_id
                  WHERE s.status IN :st AND s.planned_recovery_ts > :now""".replace(":st", str(LIVE_SORTIE)), now=now):
        if r["id"] in release:
            continue
        busy_ac.setdefault(r["aircraft_id"], []).append(
            (r["planned_launch_ts"] - timedelta(minutes=D.PREP_MIN),
             r["planned_recovery_ts"] + timedelta(minutes=turn.get(r["aircraft_type_id"], 45)), r["id"]))
        if r["status"] in ("AIRBORNE", "ON_STATION", "RTB"):
            future_base[r["aircraft_id"]] = r["recovery_base_id"]
        elif r["status"] == "PLANNED" and r["planned_launch_ts"] < end:
            committed_fuel[r["departure_base_id"]] = committed_fuel.get(r["departure_base_id"], 0) + \
                (r["fuel_planned_kg"] or 0) / GC.ATF_DENSITY
        if r["status"] in ("PLANNED", "CREWED", "READY"):
            launches.setdefault(r["departure_base_id"], []).append(r["planned_launch_ts"])
    for r in q("""SELECT s.id, s.planned_launch_ts, s.planned_recovery_ts, sc.aircrew_id FROM sortie s
                  JOIN sortie_crew sc ON sc.sortie_id = s.id WHERE s.status IN :st AND s.planned_recovery_ts > :now"""
               .replace(":st", str(LIVE_SORTIE)), now=now):
        if r["id"] in release:
            continue
        busy_cr.setdefault(r["aircrew_id"], []).append(
            (r["planned_launch_ts"] - timedelta(minutes=D.BRIEF_MIN),
             r["planned_recovery_ts"] + timedelta(minutes=D.DEBRIEF_MIN, hours=D.CREW_REST_H), r["id"]))

    # -------------------------------------------------------------- aircraft
    recent = {r["aircraft_id"]: r["n"] for r in q("""SELECT aircraft_id, count(*) AS n FROM maintenance_event
                  WHERE kind <> 'SCHEDULED' AND ts >= :a AND ts < :b GROUP BY 1""", a=now - timedelta(days=30), b=now)}
    aircraft = {}
    for r in q("""SELECT a.id, a.tail_no, a.aircraft_type_id, a.current_base_id, a.home_base_id, a.squadron_id, a.status,
                         a.hours_since_maint, a.maint_eta, a.last_sortie_at, t.maint_interval_h, t.turnaround_min,
                         a.induction_year, t.role
                  FROM aircraft a JOIN aircraft_type t ON t.id = a.aircraft_type_id
                  WHERE t.in_service AND a.status NOT IN ('RETIRED','DEPOT')"""):
        st, frm = r["status"], now
        base = r["current_base_id"] if r["current_base_id"] is not None else future_base.get(r["id"])
        if st in MAINT:
            if not r["maint_eta"] or r["maint_eta"] > end:
                continue
            frm = r["maint_eta"]
        elif st == "TURNAROUND" and r["last_sortie_at"]:
            frm = max(now, r["last_sortie_at"] + timedelta(minutes=r["turnaround_min"]))
        if base is None or base not in bases:
            continue
        aircraft[r["id"]] = AircraftInfo(r["id"], r["tail_no"], r["aircraft_type_id"], base, r["home_base_id"],
                                         r["squadron_id"], st, max(0.0, r["maint_interval_h"] - r["hours_since_maint"]), frm,
                                         r["hours_since_maint"] / max(1.0, r["maint_interval_h"]),
                                         now.year - (r["induction_year"] or now.year - 10) + 0.5,
                                         GC.ROLE_FAMILY.get(r["role"], ("transport",))[0], recent.get(r["id"], 0))

    # -------------------------------------------------------------- crew (fit, with quals, currency, rest)
    quals: dict[int, set] = {}
    for r in q("""SELECT aircrew_id, code FROM aircrew_qualification
                  WHERE expires_on IS NULL OR expires_on >= CAST(:d AS date)""", d=now.date()):
        quals.setdefault(r["aircrew_id"], set()).add(r["code"])
    current: dict[int, dict] = {}
    for r in q("SELECT aircrew_id, aircraft_type_id, expires_at FROM v_aircrew_currency WHERE currency <> 'LAPSED'"):
        current.setdefault(r["aircrew_id"], {})[r["aircraft_type_id"]] = r["expires_at"]
    h7 = {r["aircrew_id"]: float(r["hours_7d"]) for r in q("SELECT aircrew_id, hours_7d FROM v_aircrew_fatigue")}
    crew = {}
    for r in q("""SELECT id, rank, first_name, last_name, aircrew_role, stream, base_id, squadron_id, duty_status,
                         instrument_rating, ops_category, medical_status, medical_valid_until, rest_started_at
                  FROM aircrew WHERE medical_status IN ('FIT_FULL','FIT_RESTRICTED')
                    AND duty_status NOT IN ('LEAVE','SICK','COURSE','QRA')"""):
        if r["base_id"] not in bases:
            continue
        rest = r["rest_started_at"] + timedelta(hours=D.CREW_REST_H) if r["rest_started_at"] and r["duty_status"] == "CREW_REST" else None
        med = datetime.combine(r["medical_valid_until"], datetime.max.time(), now.tzinfo) if r["medical_valid_until"] else None
        crew[r["id"]] = CrewInfo(r["id"], f"{r['first_name']} {r['last_name']}", r["rank"], r["aircrew_role"], r["stream"],
                                 r["base_id"], r["squadron_id"], r["duty_status"], r["instrument_rating"],
                                 r["ops_category"], med, frozenset(quals.get(r["id"], ())), current.get(r["id"], {}),
                                 h7.get(r["id"], 0.0), rest)

    # -------------------------------------------------------------- fuel, weapons, QRA
    fuel = {}
    for r in q("""SELECT base_id, sum(current_l) cur, sum(reserve_l) res, sum(capacity_l) cap, min(replenish_eta) eta
                  FROM fuel_storage WHERE grade = 'ATF' GROUP BY base_id"""):
        fuel[r["base_id"]] = dict(current_l=float(r["cur"]), reserve_l=float(r["res"]), capacity_l=float(r["cap"]),
                                  committed_l=committed_fuel.get(r["base_id"], 0.0), replenish_eta=r["eta"])
    stock: dict[int, dict] = {}
    for r in q("""SELECT w.base_id, i.category, sum(l.qty_on_hand - l.qty_reserved) qty FROM stock_level l
                  JOIN stock_item i ON i.id = l.stock_item_id JOIN warehouse w ON w.id = l.warehouse_id
                  WHERE i.category LIKE 'ARMAMENT%' AND w.status <> 'CLOSED' GROUP BY 1, 2"""):
        stock.setdefault(r["base_id"], {})[r["category"]] = max(0.0, float(r["qty"]))
    # D56: approved transfers on their way in count as arriving. ponytail: the arrival time inside the horizon is not
    # modelled (fuel and weapons are horizon totals here, D40); the upgrade is a time-indexed stock timeline.
    for r in q("""SELECT to_base_id b, kind, category c, sum(qty) qty FROM inventory_transfer WHERE status = 'IN_TRANSIT'
                  AND eta < :e GROUP BY 1, 2, 3""", e=end):
        if r["kind"] == "FUEL" and r["b"] in fuel:
            fuel[r["b"]]["current_l"] += float(r["qty"])
        elif r["c"].startswith("ARMAMENT"):
            stock.setdefault(r["b"], {})[r["c"]] = stock.get(r["b"], {}).get(r["c"], 0.0) + float(r["qty"])
    if release:   # weapons reserved for packages being re-planned are available to the re-plan again
        for r in q("""SELECT s.departure_base_id AS b, l.items, count(sa.id) AS n FROM sortie s
                      JOIN loadout_config l ON l.code = s.loadout_code JOIN sortie_aircraft sa ON sa.sortie_id = s.id
                      WHERE s.id = ANY(:ids) AND s.origin = 'PLAN' GROUP BY s.id, s.departure_base_id, l.items""", ids=list(release)):
            for cat, qty in (r["items"] or {}).items():
                stock.setdefault(r["b"], {})[cat] = stock.get(r["b"], {}).get(cat, 0.0) + qty * r["n"]
    qra = {}
    for r in q("""SELECT q.base_id, q.aircraft_type_id, sum(q.required_aircraft) req,
                         (SELECT count(*) FROM aircraft a WHERE a.current_base_id = q.base_id
                            AND a.aircraft_type_id = q.aircraft_type_id AND a.status = 'QRA') have
                  FROM qra_posture q WHERE q.active GROUP BY 1, 2"""):
        qra[(r["base_id"], r["aircraft_type_id"])] = dict(required=int(r["req"]), have=int(r["have"]))

    # -------------------------------------------------------------- weather timelines (exercise > live > synthetic)
    rank = {"EXERCISE": 0, "OPEN_METEO": 1, "SYNTHETIC": 2}
    best: dict[tuple, tuple] = {}
    for r in q("""SELECT base_id, valid_ts, ceiling_ft, vis_m, wind_kt, gust_kt, wind_dir, flight_cat, source
                  FROM wx_base_forecast WHERE valid_ts BETWEEN :a AND :b""",
               a=now - timedelta(hours=2), b=end + timedelta(hours=12)):
        k = (r["base_id"], r["valid_ts"])
        row = (r["valid_ts"], r["ceiling_ft"], r["vis_m"], r["wind_kt"], r["gust_kt"], r["wind_dir"], r["flight_cat"],
               r["source"])
        if k not in best or rank[r["source"]] < rank[best[k][7]]:
            best[k] = row
    wx: dict[int, list] = {}
    for (bid, _), row in best.items():
        wx.setdefault(bid, []).append(row)
    for rows in wx.values():
        rows.sort(key=lambda x: x[0])

    # -------------------------------------------------------------- zones
    def zones(sql):
        out = []
        for r in q(sql, a=now, b=end):
            g = _geo(r["g"])
            out.append(Zone(r["id"], r["code"], r["name"], r["kind"], g, prep(g), float(r.get("risk") or 0),
                            int(r.get("cap") or 0), r["active_from"], r["active_to"]))
        return out
    airspace = zones("""SELECT id, code, name, kind, ST_AsBinary(geom) g, capacity_packages cap, active_from, active_to
                        FROM airspace_zone WHERE (active_from IS NULL OR active_from < :b) AND (active_to IS NULL OR active_to > :a)""")
    threats = zones("""SELECT id, code, name, kind, ST_AsBinary(geom) g, risk_level risk, active_from, active_to
                       FROM threat_zone WHERE (active_from IS NULL OR active_from < :b) AND (active_to IS NULL OR active_to > :a)""")
    # runway closures scheduled by injects show up as runway status + an airspace TEMP_RESERVATION over the base
    for z in airspace:
        if z.kind == "TEMP_RESERVATION" and z.code.startswith("RWY-"):
            b = next((b for b in bases.values() if z.code == f"RWY-{b.code}"), None)
            if b:
                b.closed_windows.append((z.active_from or now, z.active_to or end + timedelta(days=1)))

    # -------------------------------------------------------------- missions in the horizon
    missions = {}
    params = dict(a=now + timedelta(minutes=D.MIN_LEAD_MIN), b=end)
    for r in q("""SELECT m.*, ST_X(m.target_geom) tx, ST_Y(m.target_geom) ty FROM mission m
                  WHERE m.status IN ('APPROVED','PLANNED','TASKED') AND m.window_end > :a AND m.window_start < :b
                    AND m.target_geom IS NOT NULL ORDER BY m.id""", **params):
        if mission_ids is not None and r["id"] not in mission_ids:
            continue
        missions[r["id"]] = Mission(r["id"], r["code"], r["name"], r["mission_type"], r["priority"], r["status"],
                                    r["window_start"], r["window_end"], r["requesting_command_id"], (r["tx"], r["ty"]),
                                    r["target_base_id"], r["required_aircraft"], tuple(r["eligible_roles"] or ()),
                                    r["loadout_code"], r["on_station_min"], tuple(r["min_quals"] or ()), r["max_risk"],
                                    r["depends_on_id"], r["parent_mission_id"],
                                    (r["part_no"], r["parts"], r["split_kind"]) if r["parent_mission_id"] else None)

    # -------------------------------------------------------------- committed plan (for stability and re-tasking)
    committed, cpid = [], None
    row = db.execute(text("SELECT id FROM plan WHERE status = 'COMMITTED' AND kind <> 'WHATIF' ORDER BY id DESC LIMIT 1")).first()
    if row:
        cpid = row[0]
        for r in q("""SELECT pi.*, s.status AS sortie_status FROM plan_item pi LEFT JOIN sortie s ON s.id = pi.sortie_id
                      WHERE pi.plan_id = :p AND pi.status = 'COMMITTED'""", p=cpid):
            committed.append(dict(r))

    st = OpsState(now, end, india(db), bases, types, aircraft, crew, missions, loadouts, fuel, stock, qra, wx,
                  airspace, threats, busy_ac, busy_cr, committed, cpid)
    st.tails = dict(db.execute(text("SELECT id, tail_no FROM aircraft")).all())
    st.launches = launches
    st.snag = predict.current(db)
    st.traffic = traffic.build(db)
    st.index()
    return st


def to_json(v):
    return json.loads(json.dumps(v, default=str))
