"""Scenario impact assessment (ARCHITECTURE D62): what a scenario does to the plan, found by planning the same moment
twice, once in the world just before the scenario and once in the world with it, and comparing the two.

- The "before" snapshot is captured when the scenario starts, before its effects are applied (routers/scenarios.start).
- The "with" plan keeps each mission's "before" package where it still works (the stability bonus), so the difference
  is what the scenario forces, not solver noise.
- Each change says why: the "before" package is re-checked in the new world with the planner's own rules (a runway
  closed, weather below minima, fuel short, a threat zone), else it gave way to a higher priority.

The result is stored on the run (footprint["analysis"]) and read by the Planner. Read-only on the plan tables: nothing
here proposes or commits anything.
"""
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .. import models as M
from . import feasibility as F
from . import planner as P
from . import snapshot as S

PLAIN = {   # the planner's reason codes as plain sentences
    "OUT_OF_RANGE": "no base with a suitable aircraft can reach it and get back",
    "RUNWAY_CLOSED": "the runway it would launch from is closed then",
    "WX_LAUNCH": "the weather is below minima where it would launch",
    "WX_RECOVERY": "the weather is below minima where it would land",
    "FUEL_SHORT": "there isn't enough fuel above reserve at the bases that could fly it",
    "THREAT_TOO_HIGH": "every route crosses a threat zone above the mission's risk limit",
    "NOT_ENOUGH_AIRCRAFT": "no base has enough suitable aircraft free",
    "LAUNCH_RATE": "too many aircraft would have to launch from one base in one slot",
    "CAPACITY_CONFLICT": "the aircraft that could fly it are needed for higher-priority missions",
    "ASSIGNMENT_FAILED": "no free aircraft or rested crew are left once the plan is assigned",
    "NO_QUALIFIED_CREW": "there aren't enough qualified, current crews",
    "WEAPONS_SHORT": "there aren't enough weapons of the right kind",
    "TIME_WINDOW": "no base can reach the area inside its time window",
    "NO_TANKER": "it needs air-to-air refuelling and no tanker can meet it in time",
    "ROUTE_BORDER_BUFFER": "every route would come too close to the border",
    "AIRSPACE_RESTRICTED": "every route crosses restricted airspace",
    "NO_ELIGIBLE_TYPE": "no aircraft type in service can fly it",
    "NO_COVER": "its supporting AEW&C mission isn't on station at that time",
}


IST = timezone(timedelta(hours=5, minutes=30))


def _hm(t: datetime) -> str:
    return t.astimezone(IST).strftime("%H:%M")


def _closed(st: S.OpsState, it: dict) -> str | None:
    """If the package's base runway is closed at its launch or landing in this world: the reason in words."""
    b = st.bases.get(it["base_id"])
    if b is None:
        return None
    for t, what in ((it["launch_ts"], "launch"), (it["recovery_ts"], "landing")):
        if not b.runway_ok(t):
            reopen = max((w[1] for w in b.closed_windows if w[0] <= t < w[1]), default=None)
            return f"{_short(b.name)}'s runway is closed at its {what} time {_hm(t)}" + (f" (it reopens at {_hm(reopen)})" if reopen else "")
    return None


def _short(name: str) -> str:
    return name.replace("Air Force Station ", "")


def _min(text: str | None) -> float:
    m = re.search(r"([\d.]+)\s*min", text or "")
    return float(m.group(1)) if m else 0.0


def _row(it: dict, label: str) -> str | None:
    return next((r["value"] for r in (it.get("explanation") or {}).get("rows", []) if r["label"] == label), None)


def _pkg(st: S.OpsState, it: dict) -> dict:
    b, t = st.bases.get(it["base_id"]), st.types.get(it["aircraft_type_id"])
    return {"base_id": it["base_id"], "base": _short(b.name) if b else str(it["base_id"]), "type": t.name if t else "",
            "n": it["n_aircraft"], "launch": it["launch_ts"].isoformat(), "transit_min": _min(_row(it, "Transit")),
            "fuel_l": round(it["fuel_l"] or 0), "risk": round(it["risk"] or 0, 2)}


def _why_not_here(st: S.OpsState, mid: int, base_id: int, type_id: int) -> tuple[str, str]:
    """Why the 'before' package can't fly in the new world: (code, plain text with the detail)."""
    cands, rejects = F.generate(st, "BALANCED", {mid}, only={mid: (base_id, type_id)})
    if cands.get(mid):
        return "CAPACITY_CONFLICT", "its aircraft or crew are now needed for higher-priority missions"
    r = next((r for r in rejects.get(mid, []) if (r.base_id, r.type_id) == (base_id, type_id)), None) or (rejects.get(mid) or [None])[0]
    if r is None:
        return "NOT_FEASIBLE", "it can't be flown from there any more"
    return r.reason, PLAIN.get(r.reason, F.REASON_TEXT.get(r.reason, r.reason).lower())


def assess(db: Session, run: M.ExerciseRun, before: S.OpsState) -> dict:
    """Plan before vs with the scenario and describe the difference."""
    t0 = datetime.now()
    after = S.build(db)
    fp = run.footprint or {}
    bases = set(fp.get("bases", []))
    popups = set(fp.get("missions", []))
    base_res = P.plan(before.clone(), "BALANCED")
    stab = {it["mission_id"]: (it["base_id"], it["aircraft_type_id"], it["launch_ts"]) for it in base_res.items}
    with_res = P.plan(after.clone(), "BALANCED", stability=stab)
    B = {it["mission_id"]: it for it in base_res.items}
    A = {it["mission_id"]: it for it in with_res.items}
    UA = {u["mission_id"]: u for u in with_res.unmet}
    common = set(before.missions) & set(after.missions)

    changes, knock, kept = [], 0, []
    for mid in sorted(common | (popups & set(after.missions)), key=lambda k: (after.missions[k].priority, after.missions[k].window_start)):
        m = after.missions[mid]
        b, a = B.get(mid), A.get(mid)
        row = {"mission_id": mid, "code": m.code, "name": m.name, "priority": m.priority,
               "window": [m.window_start.isoformat(), m.window_end.isoformat()]}
        if mid in popups:
            u = UA.get(mid)
            changes.append({**row, "kind": "added", "after": _pkg(after, a) if a else None,
                            "reason": None if a else _unmet_text(u)})
            continue
        if b is None:
            continue
        here = b["base_id"] in bases or (a is not None and a["base_id"] in bases)
        if a is None:
            shut = _closed(after, b)
            code, why = ("RUNWAY_CLOSED", shut) if shut else _why_not_here(after, mid, b["base_id"], b["aircraft_type_id"])
            if here or code != "CAPACITY_CONFLICT":
                changes.append({**row, "kind": "dropped", "before": _pkg(before, b), "reason_code": code,
                                "reason": _unmet_text(UA.get(mid)) or why, "blocked": why})
            else:
                knock += 1
            continue
        moved = (a["base_id"], a["aircraft_type_id"]) != (b["base_id"], b["aircraft_type_id"]) or \
            abs((a["launch_ts"] - b["launch_ts"]).total_seconds()) >= 15 * 60
        if moved:
            shut = _closed(after, b)
            if shut:
                code, why = "RUNWAY_CLOSED", shut
            elif (a["base_id"], a["aircraft_type_id"]) != (b["base_id"], b["aircraft_type_id"]):
                code, why = _why_not_here(after, mid, b["base_id"], b["aircraft_type_id"])
            else:
                code, why = "RETIMED", "its aircraft or crew are needed elsewhere at the original time"
            if here or code != "CAPACITY_CONFLICT":
                changes.append({**row, "kind": "moved", "before": _pkg(before, b), "after": _pkg(after, a), "reason_code": code,
                                "reason": why})
            else:
                knock += 1
        elif b["base_id"] in bases:
            kept.append(mid)

    kinds = {e.get("kind") for e in fp.get("effects", [])}
    kept_why = []
    if kept and ("RUNWAY_CLOSED" in kinds or "BASE_STRIKE" in kinds):
        kept_why.append("they launch and land outside the closure")
    if kept and "WX_FRONT" in kinds:
        kept_why.append("their crews are rated for that weather")
    kb, ka = base_res.kpis, with_res.kpis
    # how big the hit is: the aircraft at the bases it touched, and the quick-reaction alert postures there
    held: dict = {}
    for (bid, tid), ids in before.by_base_type.items():
        if bid in bases:
            n = sum(1 for i in ids if before.aircraft[i].status != "QRA")
            if n:
                held[before.types[tid].name] = held.get(before.types[tid].name, 0) + n
    qra = [{"base": _short(before.bases[bid].name), "type": before.types[tid].name, "required": q["required"],
            "have_before": q["have"], "have_after": (after.qra.get((bid, tid)) or {}).get("have", 0)}
           for (bid, tid), q in before.qra.items() if bid in bases]
    out = {
        "assessed_at": after.now.isoformat(), "took_s": round((datetime.now() - t0).total_seconds(), 1),
        "bases": [_short(before.bases[b].name) for b in bases if b in before.bases],
        "aircraft_there": sum(held.values()), "aircraft_by_type": held, "qra": qra,
        "aircraft_removed": len(fp.get("aircraft", [])),
        "before": {"covered": kb["covered"], "missions": kb["missions"], "by_priority": kb["by_priority"], "sorties": kb.get("sorties"),
                   "flying_hours": kb.get("flying_hours"), "fuel_l": kb.get("fuel_l"), "risk_peak": kb.get("risk_peak")},
        "with": {"covered": ka["covered"], "missions": ka["missions"], "by_priority": ka["by_priority"], "sorties": ka.get("sorties"),
                 "flying_hours": ka.get("flying_hours"), "fuel_l": ka.get("fuel_l"), "risk_peak": ka.get("risk_peak")},
        "flights_there_before": sum(1 for it in base_res.items if it["base_id"] in bases),
        "kept_there": len(kept), "kept_why": kept_why, "knock_on": knock, "changes": changes,
        "transit_added_min": round(sum(c["after"]["transit_min"] - c["before"]["transit_min"] for c in changes if c["kind"] == "moved"), 1),
    }
    out["brief"] = brief(run, out)
    return out


def _unmet_text(u: dict | None) -> str | None:
    if not u:
        return None
    r = (u.get("reasons") or [{}])[0]
    s = PLAIN.get(r.get("code"), (r.get("text") or "").lower())
    if r.get("nearest_km"):
        s += f" (the nearest is {r['nearest_km']:.0f} km away)"
    return s


def brief(run: M.ExerciseRun, a: dict) -> list[str]:
    """The situation in a few factual sentences, from the assessment."""
    fp = run.footprint or {}
    ends = [e.get("until") for e in fp.get("effects", []) if e.get("until") and e.get("kind") != "MISSION_POPUP"]
    out = []
    where = ", ".join(a["bases"]) or "no base in particular"
    if a["aircraft_there"]:
        types = ", ".join(f"{n} {t}" for t, n in sorted(a["aircraft_by_type"].items(), key=lambda x: -x[1])[:4])
        out.append(f"It hits {where}, where {a['aircraft_there']} aircraft are based ({types}).")
    if a["aircraft_removed"]:
        out.append(f"{a['aircraft_removed']} aircraft are taken out of the plan.")
    short = [q for q in a["qra"] if q["have_after"] < q["required"]]
    if short:
        out.append("Quick-reaction alert falls short at " + ", ".join(f"{q['base']} ({q['type']}, {q['have_after']} of {q['required']})" for q in short) + ".")
    ch = a["changes"]
    moved, dropped, added = [c for c in ch if c["kind"] == "moved"], [c for c in ch if c["kind"] == "dropped"], [c for c in ch if c["kind"] == "added"]
    if a["flights_there_before"]:
        parts = []
        if moved:
            parts.append(f"{len(moved)} move to other bases or times")
        if dropped:
            parts.append(f"{len(dropped)} can't be flown")
        if a["kept_there"]:
            parts.append(f"{a['kept_there']} still fly from there" + (f" ({'; '.join(a['kept_why'])})" if a.get("kept_why") else ""))
        out.append(f"Without it the plan flies {a['flights_there_before']} packages from {where}" + (f"; with it, {', '.join(parts)}." if parts else
                   "; all of them still fly."))
    elif moved or dropped:
        out.append(f"It changes {len(moved) + len(dropped)} packages elsewhere: {len(moved)} move, {len(dropped)} can't be flown.")
    if added:
        out.append(f"It adds {len(added)} mission{'s' if len(added) > 1 else ''}: " +
                   "; ".join(f"{c['priority']} {c['name']}" + ("" if c["after"] else " (not covered)") for c in added) + ".")
    if a["knock_on"]:
        out.append(f"{a['knock_on']} other package{'s' if a['knock_on'] > 1 else ''} shift to make room.")
    b, w = a["before"], a["with"]
    cost = [f"coverage {b['covered']} → {w['covered']} of {w['missions']} missions"]
    p1b, p1w = (b["by_priority"].get("P1") or {}), (w["by_priority"].get("P1") or {})
    cost.append(f"P1 {p1b.get('covered', 0)}/{p1b.get('of', 0)} → {p1w.get('covered', 0)}/{p1w.get('of', 0)}")
    if b.get("flying_hours") is not None and w.get("flying_hours") is not None:
        cost.append(f"flying hours {w['flying_hours'] - b['flying_hours']:+.1f}")
    if b.get("fuel_l") is not None and w.get("fuel_l") is not None:
        cost.append(f"fuel {(w['fuel_l'] - b['fuel_l']) / 1000:+.0f} kL")
    if a["transit_added_min"]:
        cost.append(f"transit {a['transit_added_min']:+.0f} min")
    out.append("Cost to the plan: " + ", ".join(cost) + ".")
    if ends:
        last, now = datetime.fromisoformat(max(ends)), datetime.fromisoformat(a["assessed_at"])
        when = f"{last:%H:%M}" + ("" if last.date() == now.date() else f" on {last:%-d %b}")
        out.append(f"The effects last until {when}." if last > now else f"The effects ended at {when}.")
    return out


def save(db: Session, run_id: int, before: S.OpsState) -> dict | None:
    run = db.get(M.ExerciseRun, run_id)
    if run is None:
        return None
    a = assess(db, run, before)
    run.footprint = {**(run.footprint or {}), "analysis": S.to_json(a)}
    return a

