"""Independent plan checker (PHASE2_IMPLEMENTATION_PLAN §7.5, invariants I13–I16).

Re-derives every rule from the snapshot rather than trusting the optimiser. Runs in tests, before approval, before
commit, and every few seconds over the committed plan (the re-tasking monitor): a violation there is a disruption.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import config as D
from . import weather_impact as W
from .resources import Req, aircraft_free, crew_eligible, crew_free, overlaps, qra_shortfall
from .snapshot import OpsState

RULE_TEXT = {
    "AIRCRAFT_STATE": "Aircraft no longer serviceable or not at the base",
    "AIRCRAFT_OVERLAP": "Aircraft double-booked",
    "AIRCRAFT_HOURS": "Aircraft would overrun its inspection",
    "CREW_STATE": "Crew member no longer fit, current or qualified",
    "CREW_OVERLAP": "Crew member double-booked or not rested",
    "FUEL": "Fuel would drop below reserve",
    "WEAPONS": "Weapons over stock",
    "QRA": "QRA posture would not be kept",
    "ROUTE": "Route inside the border buffer",
    "RUNWAY": "Runway closed at launch or recovery",
    "WX": "Weather below the crew's minima",
    "THREAT": "Route risk above the mission's limit",
    "LAUNCH_RATE": "More launches than the runways can take in one slot",
    "TANKER": "The package's tanker can no longer fly as planned",
    "DEPENDENCY": "Its AEW&C (support) mission isn't on station for the whole time",
}


@dataclass
class ItemSpec:
    key: str                        # stable id for messages (plan item id or mission code)
    mission_id: int
    base_id: int
    type_id: int
    launch: datetime
    recovery: datetime
    on_station: datetime | None
    aircraft: list
    crew: list                      # [(aircrew_id, aircraft_id, position)]
    fuel_l: float
    weapons: dict
    route: list
    req: Req = field(default_factory=Req)
    duration_h: float = 1.0
    turnaround: int = 45
    off_station: datetime | None = None

    @property
    def ac_iv(self):
        return self.launch - timedelta(minutes=D.PREP_MIN), self.recovery + timedelta(minutes=self.turnaround)

    @property
    def cr_iv(self):
        return self.launch - timedelta(minutes=D.BRIEF_MIN), self.recovery + timedelta(minutes=D.DEBRIEF_MIN, hours=D.CREW_REST_H)


@dataclass
class Violation:
    key: str
    mission_id: int
    rule: str
    detail: str
    entity_type: str | None = None
    entity_id: int | None = None

    def as_dict(self) -> dict:
        return {"key": self.key, "mission_id": self.mission_id, "rule": self.rule, "text": RULE_TEXT[self.rule],
                "detail": self.detail, "entity_type": self.entity_type, "entity_id": self.entity_id}


def validate(st: OpsState, items: list[ItemSpec], check_wx: bool = True, cover: dict | None = None) -> list[Violation]:
    """cover: supporter mission id -> [(on, off)] that may stand in for a supporter package missing from `items` (the
    planner passes only supporters outside its scope); None = the committed plan's live packages (monitor, commit)."""
    out: list[Violation] = []
    ac_use: dict[int, list] = defaultdict(list)
    cr_use: dict[int, list] = defaultdict(list)
    for it in items:
        for a in it.aircraft:
            ac_use[a].append((it.ac_iv, it.key))
        for c, _, _ in it.crew:
            cr_use[c].append((it.cr_iv, it.key))
    for it in items:
        b, t = st.bases.get(it.base_id), st.types.get(it.type_id)
        if b is None or t is None:
            out.append(Violation(it.key, it.mission_id, "AIRCRAFT_STATE", "base or type no longer available"))
            continue
        a0, a1 = it.ac_iv
        for aid in it.aircraft:
            a = st.aircraft.get(aid)
            if a is None or a.base_id != it.base_id or a.type_id != it.type_id or a.status == "QRA":
                status = "unserviceable or away from the base" if a is None else a.status.replace("_", " ").lower()
                if a is not None and a.base_id != it.base_id and a.base_id in st.bases and it.base_id in st.bases:
                    status = f"{status}, will be at {st.bases[a.base_id].code} not {st.bases[it.base_id].code}"   # e.g. diverted
                out.append(Violation(it.key, it.mission_id, "AIRCRAFT_STATE",
                                     f"{a.tail if a else st.tails.get(aid, aid)}: {status}", "aircraft", aid))
                continue
            if not aircraft_free(st, a, a0, a1):
                why = "in maintenance until %s" % a.available_from.strftime("%H:%MZ") if a.available_from > a0 else "already tasked"
                out.append(Violation(it.key, it.mission_id, "AIRCRAFT_STATE" if a.available_from > a0 else "AIRCRAFT_OVERLAP",
                                     f"{a.tail}: {why}", "aircraft", aid))
            if a.hours_left < it.duration_h:
                out.append(Violation(it.key, it.mission_id, "AIRCRAFT_HOURS",
                                     f"{a.tail}: {a.hours_left:.1f} h left, sortie {it.duration_h:.1f} h", "aircraft", aid))
            clash = [k for iv, k in ac_use[aid] if k != it.key and overlaps(a0, a1, *iv)]
            if clash:
                out.append(Violation(it.key, it.mission_id, "AIRCRAFT_OVERLAP", f"{a.tail} also in {clash[0]}", "aircraft", aid))
        r0, r1 = it.cr_iv
        for cid, _, pos in it.crew:
            c = st.crew.get(cid)
            if c is None or c.base_id != it.base_id:
                out.append(Violation(it.key, it.mission_id, "CREW_STATE", f"aircrew {cid}: unavailable (leave, sick, QRA or unfit)",
                                     "aircrew", cid))
                continue
            if pos in ("CAPTAIN", "CO_PILOT", "INSTRUCTOR", "RPA_PILOT") and not crew_eligible(c, t, it.req, it.recovery):
                out.append(Violation(it.key, it.mission_id, "CREW_STATE", f"{c.name}: not current or not {it.req.label()}",
                                     "aircrew", cid))
            if not crew_free(st, c, r0, r1):
                out.append(Violation(it.key, it.mission_id, "CREW_OVERLAP", f"{c.name}: resting or already tasked", "aircrew", cid))
            clash = [k for iv, k in cr_use[cid] if k != it.key and overlaps(r0, r1, *iv)]
            if clash:
                out.append(Violation(it.key, it.mission_id, "CREW_OVERLAP", f"{c.name} also in {clash[0]}", "aircrew", cid))
        if len(it.route) > 1 and not st.G.route_clear([tuple(p) for p in it.route]):
            out.append(Violation(it.key, it.mission_id, "ROUTE", "route inside the border buffer"))
        for when, ts in (("launch", it.launch), ("recovery", it.recovery)):
            if not b.runway_ok(ts):
                out.append(Violation(it.key, it.mission_id, "RUNWAY", f"{b.code} runway closed at {when} {ts:%H:%M}Z", "base", b.id))
            elif check_wx:
                need, why = W.rating_needed(st.wx_at(b.id, ts), t.family, b.runway_heading)
                if need is None:
                    out.append(Violation(it.key, it.mission_id, "WX", f"{b.code} at {when} {ts:%H:%M}Z: {why}", "base", b.id))
                elif D.RATING_ORDER.index(need) > D.RATING_ORDER.index(it.req.rating):
                    pilots = [st.crew[c] for c, _, p in it.crew if c in st.crew and p in ("CAPTAIN", "CO_PILOT", "INSTRUCTOR")]
                    weak = [p.name for p in pilots if D.RATING_ORDER.index(p.rating) < D.RATING_ORDER.index(need)]
                    if weak:
                        out.append(Violation(it.key, it.mission_id, "WX",
                                             f"{b.code} {why} at {when}: {weak[0]} not {need.replace('_', ' ').lower()} rated", "base", b.id))
    # per base: runway launch rate, fuel over the horizon, weapons concurrency, QRA reserve
    from .optimiser import launch_capacity, slot_of, wave_slots
    slots = defaultdict(int)
    for it in items:
        for slot, k in wave_slots(st, it.base_id, len(it.aircraft), it.launch):     # D45: big packages launch in waves
            slots[(it.base_id, slot)] += k
    for (bid, slot), n in slots.items():
        cap = launch_capacity(st, bid, slot) if bid in st.bases else 0
        if n > cap:
            k = next((it for it in items if it.base_id == bid and slot in {s for s, _ in wave_slots(st, bid, len(it.aircraft), it.launch)}),
                     next(it for it in items if it.base_id == bid))
            out.append(Violation(k.key, k.mission_id, "LAUNCH_RATE",
                                 f"{st.bases[bid].code}: {n} launches at {slot:%H:%M}Z, runways take {cap} more", "base", bid))
    fuel = defaultdict(float)
    for it in items:
        fuel[it.base_id] += it.fuel_l
    for bid, used in fuel.items():
        f = st.fuel.get(bid)
        avail = f["current_l"] - f["reserve_l"] - f["committed_l"] if f else 0
        if used > avail + 1:
            k = next(it for it in items if it.base_id == bid)
            out.append(Violation(k.key, k.mission_id, "FUEL", f"{st.bases[bid].code}: needs {used:,.0f} L, {max(0, avail):,.0f} L above reserve",
                                 "base", bid))
    # D41: a dependent package needs its supporter on station for its whole time on station (a supporter package in
    # this list if there is one, else the committed plan's, as long as its sortie is still live)
    deps = [it for it in items if "#" not in it.key and it.mission_id in st.missions and st.missions[it.mission_id].depends_on
            and it.on_station and it.off_station]
    if deps:
        here: dict = {}
        for o in items:
            if "#" not in o.key and o.on_station and o.off_station:
                here.setdefault(o.mission_id, []).append((o.on_station, o.off_station))
        for it in deps:
            s = st.missions[it.mission_id].depends_on
            fam = st.family_of(s)
            if any(x in here for x in fam):
                covers = [w for x in fam for w in here.get(x, [])]
            elif cover is not None:
                covers = [w for x in fam for w in cover.get(x, [])]
            else:
                covers = [w for ws in st.cover_of(set(fam)).values() for w in ws]
            if not any(on <= it.on_station and off >= it.off_station for on, off in covers):
                sm = st.missions.get(s)
                out.append(Violation(it.key, it.mission_id, "DEPENDENCY",
                                     f"{sm.code if sm else s} not on station {it.on_station:%H:%M}–{it.off_station:%H:%M}Z", "mission", s))
    # weapons and QRA are concurrency limits: what is out at the same moment, checked at every start inside this
    # package's interval (the optimiser's rows use the same events), not the sum of everything that overlaps it
    for it in items:
        a0, a1 = it.ac_iv
        for cat, q in it.weapons.items():
            same = [o for o in items if o.base_id == it.base_id and cat in o.weapons and overlaps(*o.ac_iv, a0, a1)]
            conc = max(sum(o.weapons[cat] for o in same if o.ac_iv[0] <= e < o.ac_iv[1])
                       for e in {max(o.ac_iv[0], a0) for o in same})
            have = st.stock.get(it.base_id, {}).get(cat, 0)
            if conc > have:
                out.append(Violation(it.key, it.mission_id, "WEAPONS",
                                     f"{st.bases[it.base_id].code} {cat.replace('ARMAMENT_', '').replace('_', '-')}: {conc:.0f} loaded, {have:.0f} held",
                                     "base", it.base_id))
                break
        short = qra_shortfall(st, it.base_id, it.type_id)
        if short:
            same = [o for o in items if o.base_id == it.base_id and o.type_id == it.type_id and overlaps(*o.ac_iv, a0, a1)]
            left = short
            for e in sorted({max(o.ac_iv[0], a0) for o in same}):
                used = {a for o in same if o.ac_iv[0] <= e < o.ac_iv[1] for a in o.aircraft}
                left = min(left, sum(1 for i in st.by_base_type.get((it.base_id, it.type_id), ())
                                     if i not in used and aircraft_free(st, st.aircraft[i], e, e + timedelta(minutes=1))))
            if left < short:
                out.append(Violation(it.key, it.mission_id, "QRA",
                                     f"{st.bases[it.base_id].code}: {left} {st.types[it.type_id].name} left for a QRA shortfall of {short}",
                                     "base", it.base_id))
    return out
