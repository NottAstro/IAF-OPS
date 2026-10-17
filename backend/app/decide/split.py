"""Split missions (ARCHITECTURE D42, PRD FR-PLN-12): one mission covered by more than one package.

- RELIEF: the time on station is longer than any one package can hold, so it is cut into consecutive shifts flown by
  successive packages, each arriving a few minutes before the one it relieves leaves (continuous cover).
- BASES: no single base can field the aircraft the mission needs, so parts of the package come from different bases and
  meet on station together.

Parts are ordinary missions in the database (`parent_mission_id`, `part_no`, `parts`, `split_kind`; the parent becomes
SPLIT), so the rest of the system (one package per mission) is unchanged; the optimiser covers the parts of one parent
all or nothing. Splits are proposed as checked fixes on an uncovered mission and applied by a person (audited).
"""
import copy
import math
from dataclasses import replace
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .. import models as M
from ..audit import audit
from . import config as D
from . import feasibility as F
from .snapshot import Mission, OpsState


def _round5(t: datetime) -> datetime:
    return t.replace(second=0, microsecond=0) + timedelta(minutes=(5 - t.minute % 5) % 5)


def relief_parts(m: Mission, n: int, t0: datetime) -> list[Mission]:
    """n consecutive shifts covering [t0, t0 + on_station]; each but the last overlaps the next by the handover."""
    shift = math.ceil(m.on_station_min / n / 5) * 5
    out = []
    for k in range(n):
        a = t0 + timedelta(minutes=k * shift)
        hold = shift + (D.RELIEF_HANDOVER_MIN if k < n - 1 else 0)
        out.append(replace(m, id=-(k + 1), code=f"{m.code}/{k + 1}", window_start=a, window_end=a + timedelta(minutes=hold),
                           on_station_min=hold, parent=m.id, part=(k + 1, n, "RELIEF")))
    return out


def base_parts(m: Mission, sizes: list[int], t0: datetime) -> list[Mission]:
    """Packages of the given sizes, on station together over [t0, t0 + on_station]."""
    end = t0 + timedelta(minutes=m.on_station_min)
    return [replace(m, id=-(k + 1), code=f"{m.code}/{k + 1}", window_start=t0, window_end=end, required=n, parent=m.id,
                    part=(k + 1, len(sizes), "BASES")) for k, n in enumerate(sizes)]


def _options(st: OpsState, parts: list[Mission], preset: str = "BALANCED") -> dict | None:
    """Candidates per part (all virtual), or None if any part has none."""
    v = copy.copy(st)
    v.missions = {p.id: p for p in parts}
    cands, _ = F.generate(v, preset)
    return cands if all(cands.get(p.id) for p in parts) else None


def _starts(st: OpsState, m: Mission, span_min: int) -> list[datetime]:
    """Start times for the covered period: as early as a package can get there, then later, inside the window."""
    first = _round5(max(m.window_start, st.now + timedelta(minutes=D.MIN_LEAD_MIN + 60)))
    last = m.window_end - timedelta(minutes=span_min)
    out, t = [], first
    while t <= last and len(out) < 3:
        out.append(t)
        t += timedelta(minutes=45)
    return out


def proposals(st: OpsState, m: Mission, rejects: list) -> list[dict]:
    """Checked split fixes for an uncovered mission: every part has at least one feasible option, and (bases) the parts
    can come from different bases with enough aircraft. Empty if splitting wouldn't help."""
    if m.part:
        return []
    reasons = {r.reason for r in rejects}
    out = []
    long_hold = any(r.reason == "OUT_OF_RANGE" and r.detail.startswith("needs") for r in rejects)   # endurance, not distance
    if long_hold and m.on_station_min >= 2 * D.RELIEF_MIN_SHIFT:
        for n in range(2, D.SPLIT_MAX_PARTS + 1):
            if m.on_station_min / n < D.RELIEF_MIN_SHIFT:
                break
            hit = next(((t0, parts) for t0 in _starts(st, m, m.on_station_min) for parts in [relief_parts(m, n, t0)]
                        if _options(st, parts)), None)
            if hit:
                t0, parts = hit
                shift = parts[0].on_station_min - D.RELIEF_HANDOVER_MIN
                out.append({"kind": "SPLIT_RELIEF", "parts": n, "t0": t0.isoformat(),
                            "text": f"Split into {n} reliefs of {shift} min: continuous cover {t0:%H:%M}–"
                                    f"{t0 + timedelta(minutes=m.on_station_min):%H:%M}Z, {D.RELIEF_HANDOVER_MIN} min handovers"})
                break
    if m.required >= 2 and reasons & {"NOT_ENOUGH_AIRCRAFT", "LAUNCH_RATE"}:
        for t0 in _starts(st, m, m.on_station_min):
            sizes = _sizes_by_base(st, m, t0)
            if not sizes:
                continue
            cands = _options(st, base_parts(m, sizes, t0))
            bases = _distinct_bases(cands, sizes) if cands else None
            if bases:
                out.append({"kind": "SPLIT_BASES", "parts": len(sizes), "sizes": sizes, "t0": t0.isoformat(),
                            "text": f"Split across bases: {' + '.join(map(str, sizes))} aircraft "
                                    f"({', '.join(st.bases[b].code for b in bases)}), on station together {t0:%H:%M}Z"})
                break
    return out


def _sizes_by_base(st: OpsState, m: Mission, t0: datetime) -> list[int] | None:
    """Part sizes from the bases that can fly the mission at all (a one-aircraft probe), largest fleet first, at most
    SPLIT_MAX_PARTS parts; None if those bases together don't hold enough."""
    probe = _options(st, [replace(m, id=-1, window_start=t0, window_end=t0 + timedelta(minutes=m.on_station_min), required=1)])
    if not probe:
        return None
    from .optimiser import aircraft_capacity, crew_capacity
    from .resources import pilots_per_aircraft
    have: dict = {}
    for c in probe[-1]:               # free at launch, with pilots for them (the optimiser's own capacity rows)
        ac = aircraft_capacity(st, c.base_id, c.type_id, c.ac_iv[0])
        crews = crew_capacity(st, c.base_id, c.type_id, c.req, c.cr_iv[0]) // max(1, pilots_per_aircraft(st.types[c.type_id]))
        launch = st.bases[c.base_id].runways * D.LAUNCH_CAP_PER_RUNWAY * D.MAX_WAVES   # a part may launch in waves (D45)
        have[c.base_id] = max(have.get(c.base_id, 0), min(int(min(ac, crews) * D.SPLIT_HEADROOM), launch))   # leave some for others
    sizes, left = [], m.required
    for n in sorted(have.values(), reverse=True)[:D.SPLIT_MAX_PARTS]:
        take = min(n, left)
        sizes.append(take)
        left -= take
        if left == 0:
            return sizes if len(sizes) > 1 else None
    return None


def _distinct_bases(cands: dict, sizes: list[int]) -> list | None:
    """One base per part (largest part first), each with an option for that part; None if they can't all differ."""
    used, out = set(), []
    for k in sorted(range(len(sizes)), key=lambda i: -sizes[i]):
        opts = sorted(cands[-(k + 1)], key=lambda c: c.cost)
        b = next((c.base_id for c in opts if c.base_id not in used), None)
        if b is None:
            return None
        used.add(b)
        out.append(b)
    return out


def apply(db: Session, user: dict, m: M.Mission, kind: str, parts: int, t0: datetime, sizes: list[int] | None = None,
          request_id: str | None = None) -> list[M.Mission]:
    """Create the parts and mark the parent SPLIT (audited). The monitor picks the parts up as new missions."""
    if kind == "SPLIT_RELIEF":
        shift = math.ceil(m.on_station_min / parts / 5) * 5
        spans = []
        for k in range(parts):
            a = t0 + timedelta(minutes=k * shift)
            hold = shift + (D.RELIEF_HANDOVER_MIN if k < parts - 1 else 0)
            spans.append((a, a + timedelta(minutes=hold), hold, m.required_aircraft))
    else:
        sizes = sizes or [m.required_aircraft // parts + (1 if k < m.required_aircraft % parts else 0) for k in range(parts)]
        end = t0 + timedelta(minutes=m.on_station_min)
        spans = [(t0, end, m.on_station_min, n) for n in sizes]
    now = datetime.now().astimezone()
    out = []
    for k, (a, b, hold, n) in enumerate(spans):
        word = f"relief {k + 1}/{parts}" if kind == "SPLIT_RELIEF" else f"part {k + 1}/{parts}, {n} aircraft"
        c = M.Mission(code=f"{m.code}/{k + 1}", name=f"{m.name} · {word}", mission_type=m.mission_type, priority=m.priority,
                      window_start=a, window_end=b, status="APPROVED", requesting_command_id=m.requesting_command_id,
                      target_geom=m.target_geom, target_base_id=m.target_base_id, required_aircraft=n,
                      eligible_roles=m.eligible_roles, loadout_code=m.loadout_code, on_station_min=hold, min_quals=m.min_quals,
                      max_risk=m.max_risk, notes=m.notes, depends_on_id=m.depends_on_id, requested_by=user["id"],
                      approved_by=user["id"], approved_at=now, parent_mission_id=m.id, part_no=k + 1, parts=parts,
                      split_kind="RELIEF" if kind == "SPLIT_RELIEF" else "BASES", is_simulated=True, source="SYNTHETIC")
        db.add(c)
        out.append(c)
    before = {"status": m.status}
    m.status, m.parts, m.split_kind, m.version = "SPLIT", parts, "RELIEF" if kind == "SPLIT_RELIEF" else "BASES", m.version + 1
    db.flush()
    audit(db, user, "UPDATE", "mission", m.id, None, before,
          {"status": "SPLIT", "kind": m.split_kind, "parts": [c.code for c in out], "from": t0}, request_id=request_id)
    return out
