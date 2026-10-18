"""Tail and crew assignment for the selected packages (PHASE2_IMPLEMENTATION_PLAN §7.3).

Deterministic greedy in launch order. Tails: most hours left before inspection (balances fleet hours), never a QRA
aircraft, and the QRA shortfall stays covered (I16). Crew: eligible pilots, currency-lapsing first (the sortie keeps
them current), then fewest hours in the last 7 days; a 4-ship gets a formation lead; other positions best-effort.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import config as D
from .feasibility import Candidate
from .resources import Req, aircraft_free, crew_eligible, crew_free, pilot_role, qra_shortfall
from .predict import tail_risk
from .snapshot import OpsState


@dataclass
class Assignment:
    aircraft: list
    crew: list                      # [(aircrew_id, aircraft_id, position)]
    notes: list = field(default_factory=list)
    support: "Assignment | None" = None   # tails and crew of the support leg (tanker), if the package has one


class Ledger:
    """Intervals taken by packages assigned so far in this plan."""

    def release(self, c, a: Assignment) -> None:
        for aid in a.aircraft:
            self.ac[aid].remove(c.ac_iv)
        for cid, _, _ in a.crew:
            self.crew[cid].remove(c.cr_iv)

    def __init__(self):
        self.ac: dict[int, list] = {}
        self.crew: dict[int, list] = {}

    def take(self, c: Candidate, a: Assignment) -> None:
        for aid in a.aircraft:
            self.ac.setdefault(aid, []).append(c.ac_iv)
        for cid, _, _ in a.crew:
            self.crew.setdefault(cid, []).append(c.cr_iv)
        if a.support is not None and getattr(c, "support", None) is not None:
            self.take(c.support, a.support)


def assign(st: OpsState, c: Candidate, led: Ledger, keep: Assignment | None = None) -> Assignment | str:
    """Assignment, or the reason it failed. `keep` (re-tasking): prefer the same tails and crew where still valid."""
    t = st.types[c.type_id]
    a0, a1 = c.ac_iv
    pool = [st.aircraft[i] for i in st.by_base_type.get((c.base_id, c.type_id), ())]
    free = [a for a in pool if aircraft_free(st, a, a0, a1, led.ac) and a.hours_left >= c.duration_h]
    spare = len(free) - qra_shortfall(st, c.base_id, c.type_id)
    if spare < c.n:
        return f"only {max(0, spare)} of {c.n} {t.name} free at {st.bases[c.base_id].code} for {c.launch:%H:%M}Z"
    prefer = set(keep.aircraft) if keep else set()
    m = st.missions.get(getattr(c, "mission_id", None))
    if m is not None and m.priority in D.SNAG_AWARE and st.snag is not None:
        # priority packages take the tails least likely to go unserviceable (D38), in 2-point bands so that small
        # differences still leave the choice to fleet-hours balancing
        band = {a.id: int(tail_risk(st, a, c.duration_h) / D.SNAG_BAND) for a in free}
        free.sort(key=lambda a: (a.id not in prefer, band[a.id], -a.hours_left, a.id))
    else:
        free.sort(key=lambda a: (a.id not in prefer, -a.hours_left, a.id))
    tails = [a.id for a in free[:c.n]]

    r0, r1 = c.cr_iv
    role = pilot_role(t)
    kept = {cid for cid, _, _ in keep.crew} if keep else set()

    def lapsing(x):
        exp = x.current.get(t.id)
        return 0 if exp and exp - c.recovery < timedelta(days=7) else 1

    elig = [st.crew[cid] for cid in st.crew_by_base.get(c.base_id, ())
            if crew_eligible(st.crew[cid], t, c.req, c.recovery) and crew_free(st, st.crew[cid], r0, r1, led.crew)]
    elig.sort(key=lambda x: (x.id not in kept, lapsing(x), x.hours_7d, x.id))
    if len(elig) < c.pilots:
        return f"only {len(elig)} of {c.pilots} {c.req.label()} {t.name} pilots free at {st.bases[c.base_id].code}"
    chosen, notes = [], []
    if c.n >= 4 and t.family == "fighter":       # a fighter 4-ship needs a qualified lead (fighter-stream qualification)
        lead = next((x for x in elig if "FORMATION_LEAD_4" in x.quals), None)
        if lead is None:
            return f"no 4-ship formation lead free at {st.bases[c.base_id].code}"
        chosen.append(lead)
    for x in elig:
        if len(chosen) >= c.pilots:
            break
        if x not in chosen:
            chosen.append(x)
    per = max(1, c.pilots // c.n)
    crew = []
    for i, x in enumerate(chosen):
        ac = tails[min(i // per, c.n - 1)]
        pos = "RPA_PILOT" if role == "RPA_PILOT" else ("CAPTAIN" if i % per == 0 else "CO_PILOT")
        if t.family == "trainer":
            pos = "INSTRUCTOR"
        crew.append((x.id, ac, pos))
    taken = {x.id for x in chosen}
    for crole, pos in D.OTHER_POSITIONS.get(t.crew_family, ()):
        others = [st.crew[cid] for cid in st.crew_by_base.get(c.base_id, ())
                  if st.crew[cid].role == crole and cid not in taken and crew_free(st, st.crew[cid], r0, r1, led.crew)
                  and (st.crew[cid].medical_ok_until is None or st.crew[cid].medical_ok_until >= c.recovery)]
        others.sort(key=lambda x: (x.hours_7d, x.id))
        for k, ac in enumerate(tails):
            if k < len(others):
                crew.append((others[k].id, ac, pos))
                taken.add(others[k].id)
            else:
                notes.append(f"No {crole.replace('_', ' ').lower()} free for {st.aircraft[ac].tail}")
                break
    return Assignment(tails, crew, notes)


def assign_all(st: OpsState, selected: dict, keep: dict | None = None) -> tuple[dict, dict]:
    """-> (mission_id -> Assignment, mission_id -> failure reason). Higher priority first, then launch time."""
    led, out, fail = Ledger(), {}, {}
    order = sorted(selected.values(), key=lambda c: (st.missions[c.mission_id].priority, c.launch, c.idx))
    for c in order:
        k = (keep or {}).get(c.mission_id)
        a = assign(st, c, led, k)
        if not isinstance(a, str) and c.support is not None:
            led.take(c, a)                       # the receivers' people are taken before the tanker is crewed
            s = assign(st, c.support, led, k.support if k else None)
            if isinstance(s, str):
                led.release(c, a)
                a = f"tanker: {s}"
            else:
                a.support = s
                led.take(c.support, s)
                out[c.mission_id] = a
                continue
        if isinstance(a, str):
            fail[c.mission_id] = a
        else:
            out[c.mission_id] = a
            led.take(c, a)
    return out, fail
