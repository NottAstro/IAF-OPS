"""Manual planning baseline (ARCHITECTURE D43, PRD FR-PLN-13, PS-8 "faster planning vs a manual baseline").

A planner plans the same snapshot by hand, timed: for each mission they pick a base, an aircraft type and an
on-station time from the raw picture (which bases hold eligible aircraft), not from the optimiser's options. "Check"
applies the real rules to the picks: feasibility for that base and type (the nearest workable time to the one asked),
tail and crew assignment in priority order, and the independent validator. "Finish" records the time taken and the
result, and plans the same snapshot with the optimiser for comparison. Nothing is written to the sortie tables.
"""
from datetime import datetime

from . import feasibility as F
from . import planner as P
from .assign import assign_all
from .snapshot import OpsState
from .validate import validate


def choices(st: OpsState) -> list[dict]:
    """Per mission: what a planner sees: window, area, needs, and the (base, type) pairs holding eligible aircraft."""
    held: dict = {}
    for (b, t), ids in st.by_base_type.items():
        n = sum(1 for i in ids if st.aircraft[i].status != "QRA")
        if n:
            held[(b, t)] = n
    out = []
    for m in sorted(st.missions.values(), key=lambda m: (m.priority, m.window_start, m.id)):
        opts = sorted(({"base_id": b, "base": st.bases[b].code, "type_id": t, "type": st.types[t].name, "aircraft": n}
                       for (b, t), n in held.items() if st.types[t].role in m.roles), key=lambda o: (o["base"], o["type"]))
        out.append({"mission_id": m.id, "code": m.code, "name": m.name, "type": m.mission_type, "priority": m.priority,
                    "window_start": m.window_start.isoformat(), "window_end": m.window_end.isoformat(),
                    "lon": m.target[0], "lat": m.target[1], "required": m.required, "on_station_min": m.on_station_min,
                    "depends_on": m.depends_on, "options": opts})
    return out


def evaluate(st: OpsState, picks: list[dict]) -> dict:
    """picks: [{mission_id, base_id, type_id, on_station (ISO)}] -> per-pick result and plan KPIs."""
    only = {p["mission_id"]: (p["base_id"], p["type_id"]) for p in picks if p["mission_id"] in st.missions}
    cands, rejects = F.generate(st, "BALANCED", set(only), only=only)
    chosen, rows = {}, {}
    for p in picks:
        mid = p["mission_id"]
        if mid not in only:
            continue
        cs = cands.get(mid, [])
        if not cs:
            why = next((r for r in rejects.get(mid, []) if (r.base_id, r.type_id) == only[mid]), None) or \
                (rejects.get(mid) or [None])[0]
            rows[mid] = {"ok": False, "reason": F.REASON_TEXT.get(why.reason, why.reason) if why else "Not feasible",
                         "detail": why.detail if why else ""}
            continue
        want = datetime.fromisoformat(p["on_station"]) if p.get("on_station") else cs[0].on_station
        c = min(cs, key=lambda c: (abs((c.on_station - want).total_seconds()), c.cost))
        chosen[mid] = c
        moved = abs((c.on_station - want).total_seconds()) >= 300
        rows[mid] = {"ok": True, "on_station": c.on_station.isoformat(), "launch": c.launch.isoformat(),
                     "note": f"nearest workable time {c.on_station:%H:%M}Z" if moved else ""}
    assignments, fails = assign_all(st, chosen)
    for mid, why in fails.items():
        rows[mid] = {"ok": False, "reason": "No tails or crew left", "detail": why}
    specs = [x for mid, a in assignments.items() for x in P.specs(chosen[mid], a, st.missions[mid].code)]
    for v in validate(st, specs):
        if rows.get(v.mission_id, {}).get("ok"):
            rows[v.mission_id] = {"ok": False, "reason": v.as_dict()["text"], "detail": v.detail}
    ok = {mid for mid, r in rows.items() if r["ok"]}
    by = {p: {"covered": 0, "of": 0} for p in ("P1", "P2", "P3", "P4")}
    for m in st.missions.values():
        by[m.priority]["of"] += 1
        by[m.priority]["covered"] += m.id in ok
    return {"rows": {str(k): v for k, v in rows.items()}, "covered": len(ok), "missions": len(st.missions),
            "by_priority": by, "violations": sum(1 for r in rows.values() if not r["ok"])}


def optimiser_result(st: OpsState) -> dict:
    res = P.plan(st.clone(), "BALANCED")
    return {"covered": res.kpis["covered"], "missions": res.kpis["missions"], "by_priority": res.kpis["by_priority"],
            "total_ms": res.total_ms}
