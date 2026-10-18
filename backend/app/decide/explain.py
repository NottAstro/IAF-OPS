"""Explanations (PHASE2_IMPLEMENTATION_PLAN §7.5). Every sentence is built from the feasibility record, the binding
capacity rows of the solution or the snapshot: nothing is generated after the fact."""
from collections import defaultdict
from datetime import timedelta

from . import config as D
from . import weather_impact as W
from .feasibility import REASON_TEXT, Candidate, Rejection, summarise
from .optimiser import Solution, aircraft_capacity, crew_capacity
from .resources import Req
from .snapshot import OpsState

def _km(st, r, target):
    from ..geo import dist_km
    b = st.bases.get(r.base_id)
    return dist_km((b.lon, b.lat), target) if b else 1e9


def _fix(st, m, code, where, near) -> dict | None:
    if code in ("WX_LAUNCH", "WX_RECOVERY") and near:
        t = m.window_start
        while t < m.window_start + timedelta(hours=24):
            row = st.wx_at(near.base_id, t)
            if row and row[6] in ("VFR", "MVFR"):
                return {"kind": "WAIT_WX", "text": f"Earliest workable weather at {where}: {t:%H:%M}Z"}
            t += timedelta(hours=1)
        return {"kind": "WAIT_WX", "text": f"No workable weather at {where} in the next 24 h: use another base"}
    text = {
        "OUT_OF_RANGE": f"Forward-base the package nearer the area, or add air-to-air refuelling",
        "ROUTE_BORDER_BUFFER": f"Plan from a base whose route keeps clear of the border buffer",
        "THREAT_TOO_HIGH": (f"Accept risk {'MED' if m.max_risk == 'LOW' else 'HIGH'} for this mission" if m.max_risk != "HIGH"
                            else "Wait for the threat zone to clear or move the area inward"),
        "TIME_WINDOW": "Open the window later or shorten time on station",
        "NO_QUALIFIED_CREW": f"Detach qualified crew to {where}, or move the window into daylight",
        "WEAPONS_SHORT": f"Move weapons to {where}, or choose a lighter loadout",
        "FUEL_SHORT": f"Bring the fuel delivery to {where} forward",
        "RUNWAY_CLOSED": f"Wait for the runway at {where} to reopen, or use another base",
        "NOT_ENOUGH_AIRCRAFT": f"Detach aircraft to {where}",
        "LAUNCH_RATE": "Split the package across bases, or into waves",
        "AIRSPACE_RESTRICTED": "Request a corridor through the restricted area",
        "LOADOUT_INCOMPATIBLE": "Choose a loadout the eligible types can carry",
        "NO_ELIGIBLE_TYPE": "Widen the eligible aircraft roles",
    }.get(code)
    return {"kind": code, "text": text} if text else None


PART_LABEL = {"transit": "transit", "risk": "risk", "fuel": "fuel", "weather": "weather", "reserve": "base reserve",
              "home": "home command", "late": "later in window"}


def _code(st, c):
    return st.bases[c.base_id].code


def _usage(sol: Solution):
    """Selected packages as resource draws, for residual-capacity checks."""
    return list(sol.selected.values())


def _residual_ok(st: OpsState, c: Candidate, used: list[Candidate], shift: timedelta = timedelta(0)) -> tuple[bool, str]:
    """Would candidate c (optionally shifted) fit in what the solution leaves free?"""
    a0, a1 = c.ac_iv[0] + shift, c.ac_iv[1] + shift
    r0 = c.cr_iv[0] + shift
    cap_a = aircraft_capacity(st, c.base_id, c.type_id, a0)
    use_a = sum(o.n for o in used if o.base_id == c.base_id and o.type_id == c.type_id and o.ac_iv[0] < a1 and a0 < o.ac_iv[1])
    if cap_a - use_a < c.n:
        return False, f"aircraft {cap_a - use_a}/{c.n}"
    for pool in {Req(), c.req}:
        cap_c = crew_capacity(st, c.base_id, c.type_id, pool, r0)
        use_c = sum(o.pilots for o in used if o.base_id == c.base_id and o.type_id == c.type_id and o.req.covers(pool)
                    and o.cr_iv[0] <= r0 < o.cr_iv[1])
        if cap_c - use_c < c.pilots:
            return False, f"pilots {cap_c - use_c}/{c.pilots}"
    return True, ""


def explain_item(st: OpsState, c: Candidate, mission_cands: list[Candidate], sol: Solution, notes: list) -> tuple[dict, list]:
    t, b, m = st.types[c.type_id], st.bases[c.base_id], st.missions[c.mission_id]
    lo = st.loadouts.get(c.loadout, {}).get("name", c.loadout)
    rows = [
        {"label": "Package", "value": f"{c.n} × {t.name} from {b.code}", "note": lo},
        {"label": "Transit", "value": f"{c.transit_min:.0f} min", "note": f"on station {c.on_station:%H:%M}–{c.off_station:%H:%M}Z"},
        {"label": "Weather", "value": f"{c.wx_launch} at launch, {c.wx_recovery} at recovery",
         "note": f"crew rating {c.req.rating.replace('_', ' ').lower()} or better" if c.req.rating != "WHITE" else ""},
        {"label": "Route risk", "value": f"peak {c.risk_peak:.2f}", "note": c.risk_zone or "outside threat zones",
         "tone": "caution" if c.risk_peak >= 0.5 else "ok"},
    ]
    if c.waves > 1:                           # D45
        per = max(1, b.runways * D.LAUNCH_CAP_PER_RUNWAY)
        sizes = [min(per, c.n - k * per) for k in range(c.waves)]
        rows.append({"label": "Launch", "value": f"{c.waves} waves ({' + '.join(map(str, sizes))}) from {c.launch:%H:%M}Z",
                     "note": f"{b.code} launches {per} per 15 min; the first wave holds {(c.waves - 1) * D.SLOT_MIN} min to join up", "tone": "info"})
    if c.night:
        rows.append({"label": "Night", "value": "night-qualified crew", "note": "part of the sortie is after civil twilight"})
    if c.support is not None:
        s = c.support
        rows.append({"label": "Air-to-air refuelling", "value": f"1 × {st.types[s.type_id].name} from {st.bases[s.base_id].code}",
                     "note": f"meets the receivers {s.rv_start:%H:%M}–{s.rv_end:%H:%M}Z near {s.rv[1]:.2f}, {s.rv[0]:.2f}; "
                             f"receiver crews AAR-qualified", "tone": "info"})
    if c.req.quals - {"NIGHT", "NVG"}:
        rows.append({"label": "Qualifications", "value": c.req.label(), "note": "required by the mission"})
    if m.part:                                # D42: one part of a split mission
        k, n, kind = m.part
        rows.append({"label": "Part of", "value": f"{m.code.rsplit('/', 1)[0]}: {'relief' if kind == 'RELIEF' else 'part'} {k} of {n}",
                     "note": (f"on station {m.window_start:%H:%M}–{m.window_end:%H:%M}Z, hands over to the next relief"
                              if kind == "RELIEF" and k < n else f"on station {m.window_start:%H:%M}–{m.window_end:%H:%M}Z"
                              + (" with the other parts" if kind == "BASES" else "")), "tone": "info"})
    if m.depends_on:                          # D41: who covers it
        cov = _cover(st, m, c, sol)
        sm = st.missions.get(m.depends_on)
        rows.append({"label": "Depends on", "value": f"{sm.code if sm else m.depends_on} ({sm.mission_type.replace('_', ' ').lower() if sm else 'support'})",
                     "note": cov or "covered by the committed plan", "tone": "info"})
    tr = c.traffic
    if tr and tr["level"] != "light":
        where = tr.get("airport") and f"{tr['airport']} terminal area"
        live = f"{tr['live']} civil aircraft in the area now (live ADS-B)" if tr.get("live") else ""
        rows.append({"label": "Civil traffic", "value": f"{tr['level']} near {tr['at'][1]:.2f}, {tr['at'][0]:.2f}",
                     "note": "; ".join(x for x in (where, live) if x) + " · coordinate with ATC (flexible use of airspace)",
                     "tone": "caution" if tr["level"] == "busy" else "info"})
    f = st.fuel.get(c.base_id)
    impact = {}
    if f and f["capacity_l"]:
        before = 100 * (f["current_l"] - f["committed_l"]) / f["capacity_l"]
        used_here = sum(o.fuel_l for o in sol.selected.values() if o.base_id == c.base_id)
        after = 100 * (f["current_l"] - f["committed_l"] - used_here) / f["capacity_l"]
        impact["fuel"] = {"base": b.code, "before_pct": round(before, 1), "after_pct": round(after, 1),
                          "reserve_pct": round(100 * f["reserve_l"] / f["capacity_l"], 1), "this_l": c.fuel_l}
        rows.append({"label": "Fuel", "value": f"{c.fuel_l:,.0f} L", "note": f"{b.code} ATF {before:.0f}% → {after:.0f}% after the plan"})
    if c.weapons:
        stock = st.stock.get(c.base_id, {})
        impact["weapons"] = [{"category": k, "load": v, "held": stock.get(k, 0)} for k, v in sorted(c.weapons.items())]
        rows.append({"label": "Weapons", "value": ", ".join(f"{v:.0f} {k.replace('ARMAMENT_', '').replace('_', '-')}"
                                                            for k, v in sorted(c.weapons.items())),
                     "note": "generic categories; " + ("expended on the range" if c.expended else "returned unless used")})
    binding = []
    s = c.support
    for key, hits in sol.binding.items():
        if s is not None and key[0] in ("aircraft", "crew") and key[1] == s.base_id and key[2] == s.type_id:
            for e, used, cap, mids in hits:
                if c.mission_id in mids:
                    binding.append(f"Uses {used:.0f} of {cap:.0f} available {st.types[s.type_id].name} "
                                   f"{'tankers' if key[0] == 'aircraft' else 'tanker pilots'} at {st.bases[s.base_id].code} around {e:%H:%M}Z")
                    break
            continue
        if key[0] == "launch" and key[1] == c.base_id:
            for e, used, cap, mids in hits:
                if c.mission_id in mids:
                    binding.append(f"Fills the runway at {st.bases[c.base_id].code}: {used:.0f} of {cap:.0f} launches at {e:%H:%M}Z")
                    break
            continue
        if key[0] in ("aircraft", "crew") and key[1] == c.base_id and key[2] == c.type_id:
            for e, used, cap, mids in hits:
                if c.mission_id in mids:
                    what = f"{t.name} at {b.code}" if key[0] == "aircraft" else f"{key[3].label()} {t.name} pilots at {b.code}"
                    binding.append(f"Used {used:.0f} of {cap:.0f} {what} around {e:%H:%M}Z")
                    break
        elif key[0] == "zone" and key[1] == c.zone_id:
            binding.append(f"Fills the airspace slot in {next((z.name for z in st.airspace if z.id == c.zone_id), 'the area')}")
        elif key[0] in ("weapons", "fuel") and key[1] == c.base_id and c.mission_id in hits[0][3]:
            binding.append(f"Uses the last {'weapons' if key[0] == 'weapons' else 'fuel above reserve'} at {b.code}")
    alts = alternatives(st, c, mission_cands, sol)
    return {"rows": rows, "binding": binding[:4], "impact": impact, "notes": notes, "cost": c.cost_parts}, alts


def alternatives(st: OpsState, c: Candidate, mission_cands: list[Candidate], sol: Solution, k: int = 3) -> list[dict]:
    out, seen = [], {(c.base_id, c.type_id)}
    used = [o for o in sol.selected.values() if o.mission_id != c.mission_id]
    for o in sorted(mission_cands, key=lambda x: x.cost):
        if (o.base_id, o.type_id) in seen:
            continue
        seen.add((o.base_id, o.type_id))
        ok, short = _residual_ok(st, o, used)
        if not ok:
            takers = sorted({st.missions[x.mission_id].code for x in used if x.base_id == o.base_id and x.type_id == o.type_id
                             and x.ac_iv[0] < o.ac_iv[1] and o.ac_iv[0] < x.ac_iv[1]})
            why = f"{short} free" + (f"; taken by {', '.join(takers[:2])}" if takers else "")
        else:
            diffs = sorted(((o.cost_parts.get(p, 0) - c.cost_parts.get(p, 0), p) for p in PART_LABEL), reverse=True)
            why = ", ".join(f"{PART_LABEL[p]} worse" for d, p in diffs[:2] if d > 0.5) or "similar, slightly higher cost"
        out.append({"base": _code(st, o), "type": st.types[o.type_id].name, "launch": o.launch.isoformat(),
                    "cost_delta": round(o.cost - c.cost, 1), "why_not": why})
        if len(out) >= k:
            break
    return out


def _cover(st: OpsState, m, c: Candidate, sol: Solution) -> str | None:
    """The chosen supporter package on station over c's time on station, in words (D41)."""
    for s in st.family_of(m.depends_on):
        a = sol.selected.get(s)
        if a and a.on_station <= c.on_station and a.off_station >= c.off_station:
            return f"{st.types[a.type_id].name} from {st.bases[a.base_id].code}, on station {a.on_station:%H:%M}–{a.off_station:%H:%M}Z"
    return None


def explain_unmet(st: OpsState, mid: int, cands: list[Candidate], rejects: list[Rejection], sol: Solution,
                  assign_fail: str | None = None) -> tuple[list, list]:
    m = st.missions[mid]
    reasons, fixes = [], []
    used = _usage(sol)
    if m.depends_on and cands and not any(_cover(st, m, c, sol) for c in cands):
        sm = st.missions.get(m.depends_on)
        fam = st.family_of(m.depends_on)
        chosen = [sol.selected[s] for s in fam if s in sol.selected]
        ex = [f"{sm.code if sm else m.depends_on} ({sm.priority if sm else '?'}) " +
              (f"on station {chosen[0].on_station:%H:%M}–{chosen[0].off_station:%H:%M}Z only" if chosen else "isn't covered in this plan")]
        reasons.append({"code": "NO_COVER", "text": REASON_TEXT["NO_COVER"], "count": len(cands), "examples": ex})
        fixes.append({"kind": "COVER_SUPPORT", "text": f"Cover {sm.code if sm else 'the support mission'} first (raise its priority), "
                      f"or fly without AEW&C cover (remove the dependency)"})
    if assign_fail:
        reasons.append({"code": "ASSIGNMENT_FAILED", "text": REASON_TEXT["ASSIGNMENT_FAILED"], "count": 1, "examples": [assign_fail]})
    if cands:
        takers, taker_prio = defaultdict(set), set()
        best = min(cands, key=lambda c: c.cost)
        for c in cands:
            for o in used:
                if o.base_id == c.base_id and o.type_id == c.type_id and o.ac_iv[0] < c.ac_iv[1] and c.ac_iv[0] < o.ac_iv[1]:
                    om = st.missions[o.mission_id]
                    takers[(st.bases[c.base_id].code, st.types[c.type_id].name)].add(f"{om.code} ({om.priority})")
                    taker_prio.add(om.priority)
        ex = [f"{b} {t} taken by {', '.join(sorted(v)[:2])}" for (b, t), v in list(takers.items())[:4]]
        reasons.append({"code": "CAPACITY_CONFLICT", "text": REASON_TEXT["CAPACITY_CONFLICT"], "count": len(cands),
                        "examples": ex or [f"{len(cands)} feasible options, all needed by other missions"]})
        for mins in (30, 60, 90, 120, 180):
            shift = timedelta(minutes=mins)
            fits = [c for c in sorted(cands, key=lambda c: c.cost) if c.off_station + shift <= m.window_end + timedelta(hours=3)
                    and _residual_ok(st, c, used, shift)[0]]
            if fits:
                c = fits[0]
                fixes.append({"kind": "SHIFT_WINDOW", "text": f"Move the window {mins} min later: {st.bases[c.base_id].code} "
                              f"{st.types[c.type_id].name} free from {(c.launch + shift):%H:%M}Z", "minutes": mins})
                break
        ok, short = _residual_ok(st, best, used)
        if not ok:
            need = best.n if short.startswith("aircraft") else best.pilots
            have = int(short.split()[1].split("/")[0])
            what = st.types[best.type_id].name + (" aircraft" if short.startswith("aircraft") else f" pilots ({best.req.label()})")
            fixes.append({"kind": "ADD_RESOURCE", "text": f"+{need - max(0, have)} {what} at {st.bases[best.base_id].code}"})
        lower = sorted(p for p in taker_prio if p > m.priority)
        if lower and m.priority != "P1":
            fixes.append({"kind": "RAISE_PRIORITY", "text": f"Raise to P{max(1, int(m.priority[1]) - 1)} to displace "
                          f"{lower[-1]} tasks", "priority": m.priority})
    summary = summarise(rejects, st, m.target)
    reasons += summary
    if not cands:   # a fix for what stops the two nearest options
        for r in summary[:2]:
            near = next((x for x in sorted(rejects, key=lambda x: _km(st, x, m.target)) if x.reason == r["code"]), None)
            where = st.bases[near.base_id].code if near and near.base_id in st.bases else "the nearest base"
            f = _fix(st, m, r["code"], where, near)
            if f and f not in fixes:
                fixes.append(f)
    if not reasons:
        reasons.append({"code": "NO_OPTION", "text": "No base can fly this mission in the horizon", "count": 0, "examples": []})
    if not cands and rejects:                 # D42: a checked split, first: it is the fix that keeps the mission whole
        from .split import proposals
        fixes = proposals(st, m, rejects) + fixes
    return reasons, fixes
