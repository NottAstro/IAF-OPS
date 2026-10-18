"""CP-SAT selection model (PHASE2_IMPLEMENTATION_PLAN §7.2).

One boolean per candidate, one "unmet" boolean per mission. Capacities: aircraft per base × type over time (minus the
QRA reserve, I16), pilots per base × type × qualification pool over time (incl. rest), weapons per base × category
(concurrent loads, plus cumulative for expended exercise loads), fuel per base over the horizon, airspace zones over
time. Objective is lexicographic: P1 coverage first, then P2, P3, P4, then the preset's cost, so a P4 sortie can never
displace a P1.
"""
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ortools.sat.python import cp_model

from . import config as D
from .feasibility import Candidate
from .resources import Req, aircraft_free, aircraft_usable, crew_eligible, crew_free, pilot_role, qra_shortfall
from .snapshot import OpsState


@dataclass
class Solution:
    selected: dict                      # mission_id -> Candidate
    unmet: list                         # mission ids
    status: str
    stage_values: dict = field(default_factory=dict)
    solve_ms: int = 0
    binding: dict = field(default_factory=dict)   # resource key -> (time, used, capacity, [mission ids])


def _events(cands: list[Candidate], iv) -> list[datetime]:
    return sorted({iv(c)[0] for c in cands})


def aircraft_capacity(st: OpsState, base_id: int, type_id: int, t: datetime) -> int:
    ids = st.by_base_type.get((base_id, type_id), ())
    free = sum(1 for i in ids if aircraft_free(st, st.aircraft[i], t, t + timedelta(minutes=1)))
    return max(0, free - qra_shortfall(st, base_id, type_id))


def crew_capacity(st: OpsState, base_id: int, type_id: int, req: Req, t: datetime) -> int:
    ty = st.types[type_id]
    return sum(1 for cid in st.crew_by_base.get(base_id, ())
               if crew_eligible(st.crew[cid], ty, req, t) and crew_free(st, st.crew[cid], t, t + timedelta(minutes=1)))


def slot_of(t: datetime) -> datetime:
    return t.replace(minute=(t.minute // D.SLOT_MIN) * D.SLOT_MIN, second=0, microsecond=0)


def launch_capacity(st: OpsState, base_id: int, slot: datetime) -> int:
    used = sum(1 for x in st.launches.get(base_id, ()) if slot_of(x) == slot)
    return max(0, D.LAUNCH_CAP_PER_RUNWAY * st.bases[base_id].runways - used)


def wave_slots(st: OpsState, base_id: int, n: int, launch: datetime) -> list[tuple[datetime, int]]:
    """D45: how a package of n aircraft takes off: a full slot's worth of runway launches per 15-minute slot from the first
    launch on. The optimiser's launch rows and the validator both use this, so they mean the same thing (D40)."""
    cap = max(1, D.LAUNCH_CAP_PER_RUNWAY * st.bases[base_id].runways) if base_id in st.bases else max(1, n)
    out, k = [], 0
    while n > 0:
        out.append((slot_of(launch + timedelta(minutes=k * D.SLOT_MIN)), min(cap, n)))
        n -= cap
        k += 1
    return out


def draws(c: Candidate) -> list:
    """Everything a candidate takes from shared pools: the package itself and any support leg (tanker)."""
    return [c] + ([c.support] if c.support is not None else [])


def build_constraints(st: OpsState, cands: list[Candidate]):
    """-> list of (key, time, [(candidate, qty)], capacity). Shared with explain.py to find binding resources.
    Aircraft, crew, fuel and launch rows count support legs too, against the support leg's own base and type."""
    rows = []
    by_ac, by_zone, by_wpn, by_fuel, by_launch = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for c in cands:
        for d in draws(c):
            by_ac[(d.base_id, d.type_id)].append((c, d))
            by_fuel[d.base_id].append((c, d.fuel_l))
            for slot, k in wave_slots(st, d.base_id, d.n, d.launch):
                by_launch[(d.base_id, slot)].append((c, k))
        if c.zone_id is not None:
            by_zone[c.zone_id].append(c)
        for cat in c.weapons:
            by_wpn[(c.base_id, cat)].append(c)
    for (b, t), cd in by_ac.items():
        ivs = [(c, d, *d.ac_iv, *d.cr_iv) for c, d in cd]          # properties computed once, not per event
        for e in sorted({x[2] for x in ivs}):
            act = [(c, d.n) for c, d, a0, a1, _, _ in ivs if a0 <= e < a1]
            rows.append((("aircraft", b, t), e, act, aircraft_capacity(st, b, t, e)))
        reqs = sorted({d.req for _, d in cd}, key=lambda r: (len(r.quals), r.rating, r.ops, sorted(r.quals)))
        ty = st.types[t]
        pilots = [st.crew[cid] for cid in st.crew_by_base.get(b, ()) if st.crew[cid].role == pilot_role(ty)]
        for pool in {Req()} | set(reqs):
            members = [x for x in ivs if x[1].req.covers(pool)]
            for e in sorted({x[4] for x in members}):
                act = [(c, d.pilots) for c, d, _, _, r0, r1 in members if r0 <= e < r1]
                cap = sum(1 for p in pilots if crew_eligible(p, ty, pool, e) and crew_free(st, p, e, e + timedelta(minutes=1)))
                rows.append((("crew", b, t, pool), e, act, cap))
    zones = {z.id: z for z in st.airspace}
    for zid, cs in by_zone.items():
        for e in _events(cs, lambda c: (c.on_station, c.off_station)):
            act = [(c, 1) for c in cs if c.on_station <= e < c.off_station]
            rows.append((("zone", zid), e, act, zones[zid].capacity if zid in zones else 1))
    for (b, cat), cs in by_wpn.items():
        cap = int(st.stock.get(b, {}).get(cat, 0))
        ivs = [(c, *c.ac_iv) for c in cs]
        for e in sorted({x[1] for x in ivs}):
            act = [(c, c.weapons[cat]) for c, a0, a1 in ivs if a0 <= e < a1]
            rows.append((("weapons", b, cat), e, act, cap))
        exp = [(c, c.expended[cat]) for c in cs if cat in c.expended]
        if exp:
            rows.append((("expended", b, cat), None, exp, cap))
    for b, cq in by_fuel.items():
        f = st.fuel.get(b)
        cap = int(f["current_l"] - f["reserve_l"] - f["committed_l"]) if f else 0
        rows.append((("fuel", b), None, cq, cap))
    for (b, slot), cq in by_launch.items():
        rows.append((("launch", b), slot, cq, launch_capacity(st, b, slot)))
    # the same set of options under the same key needs one row: keep the tightest capacity
    out, seen = [], {}
    for key, e, act, cap in rows:
        sig = (key, frozenset((c.idx, q) for c, q in act))
        k = seen.get(sig)
        if k is None:
            seen[sig] = len(out)
            out.append((key, e, act, cap))
        elif cap < out[k][3]:
            out[k] = (key, e, act, cap)
    return out


@dataclass
class Base:
    """The model every retry starts from: one choice per mission and every capacity row (built once per plan)."""
    model: cp_model.CpModel
    y: dict
    u: dict
    rows: list


def base_model(st: OpsState, cands_by_mission: dict, rows: list | None = None, cover_fixed: dict | None = None) -> Base:
    """cover_fixed: supporter mission id -> [(on, off)] of committed packages for supporters outside this solve (D41)."""
    allc = [c for cs in cands_by_mission.values() for c in cs]
    model = cp_model.CpModel()
    y = {c.idx: model.NewBoolVar(f"y{c.idx}") for c in allc}
    u = {m: model.NewBoolVar(f"u{m}") for m in st.missions}
    for mid in u:
        model.Add(sum(y[c.idx] for c in cands_by_mission.get(mid, [])) + u[mid] == 1)
    # D42: the parts of a split mission are covered all or nothing (a relief chain with a gap is no cover)
    groups: dict = defaultdict(list)
    for mid, m in st.missions.items():
        if m.parent is not None:
            groups[m.parent].append(mid)
    for kids in groups.values():
        for a, b in zip(kids, kids[1:]):
            model.Add(u[a] == u[b])
    # D41: an option for a dependent mission is chosen only with a supporter option on station for its whole time
    for mid, m in st.missions.items():
        if not m.depends_on or not cands_by_mission.get(mid):
            continue
        fam = st.family_of(m.depends_on)
        sup = [a for s in fam for a in cands_by_mission.get(s, [])]
        fixed = [w for s in fam for w in (cover_fixed or {}).get(s, [])]
        for c in cands_by_mission[mid]:
            cov = [a for a in sup if a.on_station <= c.on_station and a.off_station >= c.off_station]
            if any(on <= c.on_station and off >= c.off_station for on, off in fixed):
                continue                           # a committed supporter package already covers it
            if cov:
                model.Add(y[c.idx] <= sum(y[a.idx] for a in cov))
            else:
                model.Add(y[c.idx] == 0)
    rows = rows if rows is not None else build_constraints(st, allc)
    for key, _, act, cap in rows:
        if act:
            model.Add(sum(int(round(q)) * y[c.idx] for c, q in act) <= max(0, int(cap)))
    return Base(model, y, u, rows)


def solve(st: OpsState, cands_by_mission: dict, preset: str = "BALANCED", forbid: set | None = None,
          fixed: dict | None = None, stability: dict | None = None, time_s: float = D.SOLVER_TIME_S,
          workers: int = D.SOLVER_WORKERS, seed: int = 0, rows: list | None = None, base: Base | None = None,
          cover_fixed: dict | None = None, hint: set | None = None) -> Solution:
    """forbid: candidate idx never chosen. fixed: mission_id -> candidate idx that must be chosen (frozen items).
    stability: mission_id -> (base_id, type_id, launch) of the committed package; matching candidates get a bonus.
    rows / base: build_constraints() output, or the whole base model, when the caller re-solves the same candidates
    (planner retries): the base is cloned, so each retry only adds its forbids and the lexicographic stages."""
    t0 = time.perf_counter()
    forbid, fixed, stability = forbid or set(), fixed or {}, stability or {}
    allc = [c for cs in cands_by_mission.values() for c in cs]
    base = base or base_model(st, cands_by_mission, rows, cover_fixed)
    model = base.model.clone()
    y = {k: model.get_bool_var_from_proto_index(v.Index()) for k, v in base.y.items()}
    u = {k: model.get_bool_var_from_proto_index(v.Index()) for k, v in base.u.items()}
    rows = base.rows
    for i in forbid:
        if i in y:
            model.Add(y[i] == 0)
    for mid, i in fixed.items():
        if i in y:
            model.Add(y[i] == 1)
    if hint is not None:                       # warm start from the previous retry's choice (minus what is now forbidden)
        for i, v in y.items():
            model.AddHint(v, 1 if i in hint and i not in forbid else 0)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_s
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = seed
    stage_values, status = {}, "OPTIMAL"
    covered = lambda ms: sum(1 - u[m] for m in ms)  # noqa: E731
    for p in D.PRIORITIES:
        tier = [m for m in u if st.missions[m].priority == p]
        if not tier:
            continue
        model.Maximize(covered(tier))
        r = solver.Solve(model)
        if r not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return Solution({}, list(u), "INFEASIBLE", stage_values, int((time.perf_counter() - t0) * 1000))
        if r == cp_model.FEASIBLE:
            status = "FEASIBLE"
        val = int(round(solver.ObjectiveValue()))
        stage_values[p] = {"covered": val, "of": len(tier)}
        model.Add(covered(tier) >= val)
        _hint(model, solver, y, u)
    cost = []
    for c in allc:
        bonus = 0
        s = stability.get(c.mission_id)
        if s and c.base_id == s[0] and c.type_id == s[1] and abs((c.launch - s[2]).total_seconds()) <= 20 * 60:
            bonus = D.STABILITY_WEIGHT
        cost.append(int(round((c.cost - bonus) * 10)) * y[c.idx])
    model.Minimize(sum(cost))
    r = solver.Solve(model)
    if r not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Solution({}, list(u), "INFEASIBLE", stage_values, int((time.perf_counter() - t0) * 1000))
    if r == cp_model.FEASIBLE:
        status = "FEASIBLE"
    selected = {c.mission_id: c for c in allc if solver.Value(y[c.idx])}
    unmet = sorted(m for m in u if solver.Value(u[m]))
    chosen = {c.idx for c in selected.values()}
    binding = {}
    for key, e, act, cap in rows:
        used = sum(q for c, q in act if c.idx in chosen)
        if act and used >= cap > -1 and used > 0:
            binding.setdefault(key, []).append((e, used, cap, sorted({c.mission_id for c, _ in act if c.idx in chosen})))
    return Solution(selected, unmet, status, stage_values, int((time.perf_counter() - t0) * 1000), binding)


def _hint(model, solver, y, u) -> None:
    model.ClearHints()
    for v in list(y.values()) + list(u.values()):
        model.AddHint(v, solver.Value(v))


def aircraft_usable_count(st: OpsState, base_id: int, type_id: int) -> int:
    return sum(1 for i in st.by_base_type.get((base_id, type_id), ()) if aircraft_usable(st.aircraft[i]))
