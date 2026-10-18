"""One definition of "free" and "eligible", shared by feasibility, optimiser, assignment and the validator, so the four
can never disagree about what a resource can do."""
from dataclasses import dataclass
from datetime import datetime

from . import config as D
from .snapshot import AircraftInfo, CrewInfo, OpsState, TypeInfo


@dataclass(frozen=True)
class Req:
    """What every pilot of a package must hold."""
    quals: frozenset = frozenset()
    rating: str = "WHITE"
    ops: bool = False          # operational mission: no pilots under conversion

    def covers(self, other: "Req") -> bool:
        """A candidate with requirement `self` also draws on the pool defined by `other`."""
        return self.quals >= other.quals and D.RATING_ORDER.index(self.rating) >= D.RATING_ORDER.index(other.rating) \
            and (self.ops or not other.ops)

    def label(self) -> str:
        bits = [q.replace("_", " ").lower() for q in sorted(self.quals)]
        if self.rating != "WHITE":
            bits.append(f"{self.rating.replace('_', ' ').lower()} rated")
        return ", ".join(bits) or "any current"


def pilot_role(t: TypeInfo) -> str:
    return D.PILOT_ROLE.get(t.family, "PILOT")


def pilots_per_aircraft(t: TypeInfo) -> int:
    return D.PILOTS_PER_AIRCRAFT.get(t.crew_family, 1)


def overlaps(a1: datetime, b1: datetime, a2: datetime, b2: datetime) -> bool:
    return a1 < b2 and a2 < b1


def aircraft_usable(a: AircraftInfo) -> bool:
    return a.status != "QRA"


def aircraft_free(st: OpsState, a: AircraftInfo, start: datetime, end: datetime, extra: dict | None = None) -> bool:
    if not aircraft_usable(a) or a.available_from > start:
        return False
    if any(overlaps(start, end, s, e) for s, e, _ in st.busy_aircraft.get(a.id, ())):
        return False
    return not extra or not any(overlaps(start, end, s, e) for s, e in extra.get(a.id, ()))


def crew_eligible(c: CrewInfo, t: TypeInfo, req: Req, at: datetime) -> bool:
    if c.role != pilot_role(t):
        return False
    exp = c.current.get(t.id)
    if exp is None or exp < at or (c.medical_ok_until and c.medical_ok_until < at):
        return False
    if req.ops and c.ops_category == "UNDER_CONVERSION":
        return False
    if D.RATING_ORDER.index(c.rating) < D.RATING_ORDER.index(req.rating):
        return False
    return c.quals >= req.quals


def crew_free(st: OpsState, c: CrewInfo, start: datetime, end: datetime, extra: dict | None = None) -> bool:
    if c.rest_until and c.rest_until > start:
        return False
    if any(overlaps(start, end, s, e) for s, e, _ in st.busy_crew.get(c.id, ())):
        return False
    return not extra or not any(overlaps(start, end, s, e) for s, e in extra.get(c.id, ()))


def qra_shortfall(st: OpsState, base_id: int, type_id: int) -> int:
    q = st.qra.get((base_id, type_id))
    return max(0, q["required"] - q["have"]) if q else 0
