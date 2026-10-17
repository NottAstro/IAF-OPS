"""Candidate generation (PHASE2_IMPLEMENTATION_PLAN §7.1).

For every mission × base × aircraft type × launch option, apply the hard rules (range, border buffer, restricted
airspace, threat, runway, weather minima, night, qualifications, weapons, fuel, time window). Survivors become
candidates with a score breakdown; every rejection is recorded with its reason so explanations quote facts, not
generated text.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..geo import bearing, dist_km, offset
from . import config as D
from . import routing
from . import risk as R
from . import traffic as TR
from . import weather_impact as W
from .resources import Req, crew_eligible, pilots_per_aircraft
from .snapshot import Mission, OpsState, TypeInfo

KMH_PER_KT = 1.852
REASON_TEXT = {
    "NO_ELIGIBLE_TYPE": "No aircraft type in service can fly this mission",
    "LOADOUT_INCOMPATIBLE": "Requested loadout doesn't fit the eligible types",
    "NOT_ENOUGH_AIRCRAFT": "Too few aircraft of the type at the base",
    "LAUNCH_RATE": "Too many aircraft to launch from one base in one 15-minute slot",
    "OUT_OF_RANGE": "Out of range or endurance",
    "ROUTE_BORDER_BUFFER": "Route would come within the border buffer",
    "AIRSPACE_RESTRICTED": "Route crosses restricted airspace",
    "THREAT_TOO_HIGH": "Route risk above the mission's limit",
    "TIME_WINDOW": "Can't reach the area inside the time window",
    "RUNWAY_CLOSED": "Runway closed at launch or recovery",
    "WX_LAUNCH": "Weather below minima at launch",
    "WX_RECOVERY": "Weather below minima at recovery",
    "NO_QUALIFIED_CREW": "Not enough qualified, current crew",
    "WEAPONS_SHORT": "Not enough weapons of the loadout's categories",
    "FUEL_SHORT": "Not enough fuel above reserve at the base",
    "CAPACITY_CONFLICT": "Resources taken by higher-priority missions",
    "ASSIGNMENT_FAILED": "No tails or crew left once the plan was assigned",
    "NO_TANKER": "Needs air-to-air refuelling, but no tanker can meet the receivers in time",
    "NO_COVER": "Its AEW&C (support) mission isn't on station when it would be",
}


@dataclass
class SupportLeg:
    """A package that supports the main one (ARCHITECTURE D36): today a tanker meeting the receivers on their outbound
    leg. It draws on the same resources as any package (tanker airframes, tanker crews, fuel, launch slots), so the
    optimiser, assignment, validator and commit treat it uniformly."""
    kind: str
    base_id: int
    type_id: int
    n: int
    launch: datetime
    recovery: datetime
    rv: tuple
    rv_start: datetime
    rv_end: datetime
    route: list
    duration_h: float
    fuel_l: float
    pilots: int
    req: Req
    turnaround: int = 60
    transit_min: float = 0.0

    @property
    def ac_iv(self):
        return self.launch - timedelta(minutes=D.PREP_MIN), self.recovery + timedelta(minutes=self.turnaround)

    @property
    def cr_iv(self):
        return self.launch - timedelta(minutes=D.BRIEF_MIN), self.recovery + timedelta(minutes=D.DEBRIEF_MIN, hours=D.CREW_REST_H)


@dataclass
class Candidate:
    idx: int
    mission_id: int
    base_id: int
    type_id: int
    loadout: str
    n: int
    launch: datetime
    on_station: datetime
    off_station: datetime
    recovery: datetime
    duration_h: float
    route: list
    fuel_l: float
    risk_peak: float
    risk_exposure: float
    risk_zone: str | None
    wx_launch: str
    wx_recovery: str
    req: Req
    night: bool
    pilots: int
    zone_id: int | None
    transit_min: float
    weapons: dict
    expended: dict
    cost: float
    cost_parts: dict = field(default_factory=dict)

    @property
    def ac_iv(self):
        return self.launch - timedelta(minutes=D.PREP_MIN), self.recovery + timedelta(minutes=self.turnaround)

    @property
    def cr_iv(self):
        return self.launch - timedelta(minutes=D.BRIEF_MIN), self.recovery + timedelta(minutes=D.DEBRIEF_MIN, hours=D.CREW_REST_H)

    turnaround: int = 45
    support: SupportLeg | None = None
    traffic: dict | None = None             # civil traffic along the route (D39): level, where, why


@dataclass
class Rejection:
    base_id: int | None
    type_id: int | None
    reason: str
    detail: str


def choose_loadout(m: Mission, t: TypeInfo) -> str | None:
    if m.loadout_code:
        return m.loadout_code if m.loadout_code in t.loadouts else None
    code = D.MISSION_LOADOUT.get((m.mission_type, t.family))
    if code is None and m.mission_type in D.CARGO_MISSIONS:
        code = "CARGO"
    code = code or "CLEAN"
    if code in t.loadouts:
        return code
    return "CLEAN" if "CLEAN" in t.loadouts else None


def build_route(st: OpsState, home: tuple, m: Mission, dest_is_base: bool) -> list | None:
    """Out-and-back route; orbit missions add a small loop round the target. Legs that would cut the standoff from
    foreign territory go through the border-safe router (routing.py). None if nothing fits (I8, I15)."""
    tgt = m.target
    loop = [] if dest_is_base else [offset(*tgt, 15, a) for a in (0, 120, 240)]
    if loop and not st.G.route_clear([tgt, *loop, tgt]):
        loop = []
    out = routing.leg(st.G, home, tgt)
    if out is None:
        return None
    back = list(reversed(out))
    return out + ([*loop, tgt] if loop else []) + back[1:]


def length_km(pts: list) -> float:
    return sum(dist_km(a, b) for a, b in zip(pts, pts[1:]))


def aar_capable(m: Mission, t: TypeInfo) -> bool:
    return t.name in D.AAR_RECEIVERS and m.mission_type in D.AAR_MISSIONS


def tanker_leg(st: OpsState, route: list, out_km: float, t_l: datetime, speed: float, usable: dict) -> tuple:
    """Best tanker to meet the receivers about half-way out. -> (SupportLeg | None, reason detail)."""
    from ..sim.routes import position
    rlen = length_km(route)
    rv_km = max(out_km * 0.3, min(out_km * 0.5, out_km - 80))
    x, y, _ = position(route, rv_km / max(rlen, 1e-6))
    rv = (round(x, 4), round(y, 4))
    rv_time = t_l + timedelta(hours=D.OVERHEAD_H / 2 + rv_km / speed)
    rv_start, rv_end = rv_time - timedelta(minutes=15), rv_time - timedelta(minutes=15) + timedelta(minutes=D.AAR_RV_HOLD_MIN)
    best, why = None, "no tanker within reach"
    for (bid, tid), n in usable.items():
        t = st.types[tid]
        if t.role != "TANKER" or n < 1:
            continue
        b = st.bases[bid]
        out = routing.leg(st.G, (b.lon, b.lat), rv)
        if out is None:
            continue
        tkm = length_km(out)
        transit = tkm / (t.cruise_kt * KMH_PER_KT) + D.OVERHEAD_H / 2
        tl, tr = rv_start - timedelta(hours=transit), rv_end + timedelta(hours=transit)
        if tl < st.now + timedelta(minutes=D.MIN_LEAD_MIN):
            why = f"{t.name} from {b.code} would have to launch before {(st.now + timedelta(minutes=D.MIN_LEAD_MIN)):%H:%M}Z"
            continue
        if not b.runway_ok(tl) or not b.runway_ok(tr):
            why = f"{b.code} runway closed for the tanker"
            continue
        r1, _ = W.rating_needed(st.wx_at(b.id, tl), t.family, b.runway_heading)
        r2, _ = W.rating_needed(st.wx_at(b.id, tr), t.family, b.runway_heading)
        if r1 is None or r2 is None:
            why = f"weather below minima at {b.code} for the tanker"
            continue
        dur = (tr - tl).total_seconds() / 3600
        burn = min(t.burn, t.max_fuel / max(t.endurance_h, 0.1))
        if dur > t.endurance_h:
            why = f"{t.name} from {b.code} lacks endurance"
            continue
        night = W.night_between(b.lon, b.lat, tl, tr)
        req = Req(frozenset({"NIGHT"} if night else set()), max(r1, r2, key=D.RATING_ORDER.index), True)
        pilots = pilots_per_aircraft(t)
        if sum(1 for cid in st.crew_by_base.get(b.id, ()) if crew_eligible(st.crew[cid], t, req, tr)) < pilots:
            why = f"no {req.label()} {t.name} crew at {b.code}"
            continue
        loop = [offset(*rv, 20, a) for a in (60, 180, 300)]
        track = [rv, *loop, rv] if st.G.route_clear([rv, *loop, rv]) else [rv]
        leg = SupportLeg("AAR", b.id, t.id, 1, tl, tr, rv, rv_start, rv_end, out + track[1:] + list(reversed(out))[1:],
                         round(dur, 2), round((burn * dur + D.FUEL_RESERVE_FRACTION * t.max_fuel) / 0.8), pilots, req,
                         t.turnaround_min, round(transit * 60, 1))
        if best is None or leg.transit_min < best.transit_min:
            best = leg
    return best, why


def generate(st: OpsState, preset: str = "BALANCED", mission_ids: set | None = None, only: dict | None = None):
    """-> (candidates by mission id, rejections by mission id). only: mission id -> (base id, type id) to consider
    (the manual planning baseline evaluates a planner's own picks, D43)."""
    w = D.PRESETS.get(preset, D.PRESETS["BALANCED"])
    cands: dict[int, list[Candidate]] = defaultdict(list)
    rejects: dict[int, list[Rejection]] = defaultdict(list)
    idx = 0
    fuel_avail = {b: f["current_l"] - f["reserve_l"] - f["committed_l"] for b, f in st.fuel.items()}
    usable = defaultdict(int)
    for (b, t), ids in st.by_base_type.items():
        usable[(b, t)] = sum(1 for i in ids if st.aircraft[i].status != "QRA")

    for m in sorted(st.missions.values(), key=lambda x: x.id):
        if mission_ids is not None and m.id not in mission_ids:
            continue
        types = [t for t in st.types.values() if t.role in m.roles]
        if not types:
            rejects[m.id].append(Rejection(None, None, "NO_ELIGIBLE_TYPE", f"roles {', '.join(m.roles)}"))
            continue
        mine = []
        ops = m.mission_type != "TRAINING"
        for t in types:
            lo = choose_loadout(m, t)
            if lo is None:
                rejects[m.id].append(Rejection(None, t.id, "LOADOUT_INCOMPATIBLE", f"{m.loadout_code} on {t.name}"))
                continue
            L = st.loadouts.get(lo, {"items": {}, "fuel_penalty_pct": 0, "radius_factor": 1.0})
            speed = t.cruise_kt * KMH_PER_KT
            for b in st.bases.values():
                if only and only.get(m.id) not in (None, (b.id, t.id)):
                    continue
                n_have = usable.get((b.id, t.id), 0)
                if n_have == 0 or m.target_base_id == b.id:
                    continue
                if n_have < m.required:
                    rejects[m.id].append(Rejection(b.id, t.id, "NOT_ENOUGH_AIRCRAFT", f"{n_have} of {m.required} {t.name}"))
                    continue
                if m.required > b.runways * D.LAUNCH_CAP_PER_RUNWAY:      # one package launches inside one slot (D36)
                    rejects[m.id].append(Rejection(b.id, t.id, "LAUNCH_RATE",
                                                   f"{m.required} aircraft; {b.code} launches {b.runways * D.LAUNCH_CAP_PER_RUNWAY} per 15 min"))
                    continue
                home = (b.lon, b.lat)
                d = dist_km(home, m.target)
                aar = False
                if t.radius_km and d > t.radius_km * L["radius_factor"] and m.target_base_id is None:
                    if aar_capable(m, t) and d <= t.radius_km * L["radius_factor"] * D.AAR_RADIUS_GAIN:
                        aar = True
                    else:
                        rejects[m.id].append(Rejection(b.id, t.id, "OUT_OF_RANGE", f"{d:.0f} km > {t.radius_km * L['radius_factor']:.0f} km radius"))
                        continue
                route = build_route(st, home, m, m.target_base_id is not None)
                if route is None:
                    rejects[m.id].append(Rejection(b.id, t.id, "ROUTE_BORDER_BUFFER", f"from {b.code}"))
                    continue
                rlen = length_km(route)
                out_km = length_km(route[:2]) if m.target_base_id else rlen / 2
                transit_out = out_km / speed + D.OVERHEAD_H / 2
                transit_back = (rlen - out_km) / speed + D.OVERHEAD_H / 2
                dur = transit_out + transit_back + m.on_station_min / 60
                burn = min(t.burn, t.max_fuel / max(t.endurance_h, 0.1))   # consistent with the type's endurance
                fuel_kg = burn * (1 + L["fuel_penalty_pct"] / 100) * dur + D.FUEL_RESERVE_FRACTION * t.max_fuel
                if fuel_kg > t.max_fuel or dur > t.endurance_h:
                    if aar_capable(m, t) and fuel_kg <= t.max_fuel * (1 + D.AAR_TOP_UP) and dur <= D.AAR_MAX_SORTIE_H:
                        aar = True          # one refuelling closes the gap
                    else:
                        rejects[m.id].append(Rejection(b.id, t.id, "OUT_OF_RANGE",
                                                       f"needs {dur:.1f} h / {fuel_kg:,.0f} kg; {t.name} has {t.endurance_h:.1f} h / {t.max_fuel:,.0f} kg"
                                                       + (" even with refuelling" if aar_capable(m, t) else "")))
                        continue
                win_a, win_b = m.window_start, m.window_end
                hit = R.restricted_hit(st, route, win_a, win_b)
                if hit:
                    rejects[m.id].append(Rejection(b.id, t.id, "AIRSPACE_RESTRICTED", hit.name))
                    continue
                peak, expo, zname = R.route_risk(st, route, win_a, win_b)
                if peak > D.RISK_LEVELS[m.max_risk]:
                    rejects[m.id].append(Rejection(b.id, t.id, "THREAT_TOO_HIGH",
                                                   f"peak {peak:.2f} in {zname} > {m.max_risk.lower()} ({D.RISK_LEVELS[m.max_risk]:.2f})"))
                    continue
                earliest = max(win_a, st.now + timedelta(minutes=D.MIN_LEAD_MIN, hours=transit_out))
                latest = win_b - timedelta(minutes=m.on_station_min)
                if latest < earliest:
                    rejects[m.id].append(Rejection(b.id, t.id, "TIME_WINDOW",
                                                   f"earliest on station {earliest:%H:%M}Z, window closes {win_b:%H:%M}Z"))
                    continue
                span = (latest - earliest).total_seconds() / 60
                k = min(D.MAX_LAUNCH_OPTIONS, int(span // D.LAUNCH_STEP_MIN) + 1)
                options = [earliest + timedelta(minutes=round(span * i / max(1, k - 1) / 5) * 5) for i in range(k)] if k > 1 else [earliest]
                zone = R.zone_for_target(st, m.target)
                n = m.required
                pilots = n * pilots_per_aircraft(t)
                weapons = {c: q * n for c, q in L["items"].items()}
                expended = weapons if m.mission_type in ("STRIKE_EXERCISE", "CAS_EXERCISE") else {}
                fuel_l = n * min(fuel_kg, t.max_fuel) / 0.8          # from the base; a tanker transfers the rest
                transfer_l = n * max(0.0, fuel_kg - t.max_fuel) / 0.8
                base_stock = st.stock.get(b.id, {})
                short = [c for c, q in weapons.items() if base_stock.get(c, 0) < q]
                if short:
                    rejects[m.id].append(Rejection(b.id, t.id, "WEAPONS_SHORT",
                                                   ", ".join(f"{c.replace('ARMAMENT_', '').replace('_', '-')} {base_stock.get(c, 0):.0f}/{weapons[c]:.0f}" for c in short)))
                    continue
                if fuel_avail.get(b.id, 0) < fuel_l:
                    rejects[m.id].append(Rejection(b.id, t.id, "FUEL_SHORT", f"{fuel_avail.get(b.id, 0):,.0f} L above reserve, needs {fuel_l:,.0f} L"))
                    continue
                prof = None                        # civil-traffic profile of this route, computed on first use
                for t_on in options:
                    t_l = t_on - timedelta(hours=transit_out)
                    if t_l >= st.horizon_end:
                        continue
                    t_off = t_on + timedelta(minutes=m.on_station_min)
                    t_r = t_off + timedelta(hours=transit_back)
                    if not b.runway_ok(t_l) or not b.runway_ok(t_r):
                        rejects[m.id].append(Rejection(b.id, t.id, "RUNWAY_CLOSED", f"{b.code} at {(t_l if not b.runway_ok(t_l) else t_r):%H:%M}Z"))
                        continue
                    r1, why1 = W.rating_needed(st.wx_at(b.id, t_l), t.family, b.runway_heading)
                    if r1 is None:
                        rejects[m.id].append(Rejection(b.id, t.id, "WX_LAUNCH", f"{b.code} {t_l:%H:%M}Z: {why1}"))
                        continue
                    r2, why2 = W.rating_needed(st.wx_at(b.id, t_r), t.family, b.runway_heading)
                    if r2 is None:
                        rejects[m.id].append(Rejection(b.id, t.id, "WX_RECOVERY", f"{b.code} {t_r:%H:%M}Z: {why2}"))
                        continue
                    rating = max(r1, r2, key=D.RATING_ORDER.index)
                    quals = set(m.min_quals) | ({"AAR_RECEIVER"} if aar else set())
                    support = None
                    if aar:
                        support, why = tanker_leg(st, route, out_km, t_l, speed, usable)
                        if support is None:
                            rejects[m.id].append(Rejection(b.id, t.id, "NO_TANKER", why))
                            continue
                        support.fuel_l = round(support.fuel_l + transfer_l)
                        if fuel_avail.get(support.base_id, 0) < support.fuel_l + (fuel_l if support.base_id == b.id else 0):
                            rejects[m.id].append(Rejection(b.id, t.id, "FUEL_SHORT", f"not enough fuel at {st.bases[support.base_id].code} for the tanker"))
                            continue
                    night = t.family not in ("uav", "uas") and (W.night_between(b.lon, b.lat, t_l, t_r)
                                                                or W.is_night(m.target[0], m.target[1], t_on))
                    if night:
                        quals.add("NVG" if t.family == "helo" else "NIGHT")
                    req = Req(frozenset(quals), rating, ops)
                    elig = sum(1 for cid in st.crew_by_base.get(b.id, ()) if crew_eligible(st.crew[cid], t, req, t_r))
                    if elig < pilots:
                        rejects[m.id].append(Rejection(b.id, t.id, "NO_QUALIFIED_CREW",
                                                       f"{elig} of {pilots} {req.label()} {t.name} pilots at {b.code}"))
                        continue
                    cat_l, cat_r = W.category(*_cv(st.wx_at(b.id, t_l))), W.category(*_cv(st.wx_at(b.id, t_r)))
                    if prof is None and st.traffic is not None:
                        prof = TR.route_profile(st.traffic, route)
                    lw = TR.live_weight(st.now, t_l)
                    parts = {
                        "transit": w["transit"] * (transit_out * 60) / 5,
                        "risk": w["risk"] * (peak * 40 + expo * 0.05),
                        "fuel": w["fuel"] * fuel_l / 2000,
                        "weather": w["weather"] * W.CAT_PENALTY[W.worst(cat_l, cat_r)],
                        "reserve": w["reserve"] * 30 * n / max(1, n_have),
                        "home": -w["home"] * 15 * (b.command_id == m.command_id),
                        "late": 0.2 * (t_on - earliest).total_seconds() / 600,
                        "traffic": w.get("traffic", 1.0) * TR.score(prof, lw)[0] if prof else 0.0,
                    }
                    if support:
                        parts["aar"] = D.AAR_PENALTY + w["fuel"] * support.fuel_l / 2000
                    c = Candidate(idx, m.id, b.id, t.id, lo, n, t_l, t_on, t_off, t_r, dur, route, round(fuel_l),
                                  round(peak, 3), round(expo, 1), zname, cat_l, cat_r, req, night, pilots,
                                  zone.id if zone else None, round(transit_out * 60, 1), weapons, expended,
                                  round(sum(parts.values()), 2), {k: round(v, 2) for k, v in parts.items()})
                    c.turnaround = t.turnaround_min
                    c.support = support
                    c.traffic = TR.describe(st.traffic, route, prof, lw) if prof else None
                    idx += 1
                    mine.append(c)
        mine.sort(key=lambda c: (c.cost, c.idx))
        keep, seen = [], defaultdict(int)
        for c in mine:                     # diversity: at most 3 launch options per base/type in the kept set
            if seen[(c.base_id, c.type_id)] < 3:
                keep.append(c)
                seen[(c.base_id, c.type_id)] += 1
            if len(keep) >= D.TOP_K:
                break
        cands[m.id] = keep
    return cands, rejects


def _cv(row):
    if row is None:
        return None, 10000
    return row[1], row[2]


def summarise(rejs: list[Rejection], st: OpsState, target: tuple | None = None, limit: int = 4) -> list[dict]:
    """Group rejections by reason for the unmet-mission explanation, nearest base first: what stops the obvious
    choice leads, not the most frequent reason (every distant base is 'out of range')."""
    def km(r):
        b = st.bases.get(r.base_id)
        return dist_km((b.lon, b.lat), target) if b and target else 0.0
    by = defaultdict(list)
    for r in sorted(rejs, key=km):
        by[r.reason].append(r)
    out = []
    if len(by) > 1:
        by.pop("NOT_ENOUGH_AIRCRAFT", None)   # detachments of one or two aircraft: noise next to real reasons
    for reason, rs in sorted(by.items(), key=lambda kv: km(kv[1][0])):
        ex = []
        for r in rs[:limit]:
            where = st.bases[r.base_id].code if r.base_id in st.bases else ""
            what = st.types[r.type_id].name if r.type_id in st.types else ""
            ex.append(" ".join(x for x in (where, what, "·", r.detail) if x))
        out.append({"code": reason, "text": REASON_TEXT.get(reason, reason), "count": len(rs), "examples": ex,
                    "nearest_km": round(km(rs[0]))})
    return out
