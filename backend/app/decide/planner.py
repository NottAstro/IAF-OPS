"""Planning pipeline (PHASE2_IMPLEMENTATION_PLAN §5): snapshot → candidates → CP-SAT → tails + crew → validator →
explanations → KPIs → (optionally) stored as a PROPOSED plan. Nothing here touches sorties; commit does (store.py)."""
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from geoalchemy2.shape import from_shape
from shapely.geometry import LineString
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models as M
from . import config as D
from . import explain as X
from . import feasibility as F
from . import optimiser as O
from . import predict as PR
from . import snapshot as S
from .assign import Assignment, Ledger, assign, assign_all
from .resources import Req
from .validate import ItemSpec, validate

log = logging.getLogger("decide")


@dataclass
class PlanResult:
    st: S.OpsState
    items: list = field(default_factory=list)      # dicts ready to store / serialise
    unmet: list = field(default_factory=list)
    kpis: dict = field(default_factory=dict)
    solver_status: str = ""
    solve_ms: int = 0
    total_ms: int = 0
    violations: list = field(default_factory=list)
    selected: dict = field(default_factory=dict)  # mission_id -> Candidate
    assignments: dict = field(default_factory=dict)


def spec(c: F.Candidate, a: Assignment, key: str) -> ItemSpec:
    return ItemSpec(key, c.mission_id, c.base_id, c.type_id, c.launch, c.recovery, c.on_station, list(a.aircraft),
                    list(a.crew), c.fuel_l, dict(c.weapons), c.route, c.req, c.duration_h, c.turnaround)


def specs(c: F.Candidate, a: Assignment, key: str) -> list[ItemSpec]:
    """The package and, if it has one, its support leg (validated as its own package, key "<key>#AAR")."""
    out = [spec(c, a, key)]
    s, sa = c.support, a.support
    if s is not None and sa is not None:
        out.append(ItemSpec(f"{key}#{s.kind}", c.mission_id, s.base_id, s.type_id, s.launch, s.recovery, s.rv_start,
                            list(sa.aircraft), list(sa.crew), s.fuel_l, {}, s.route, s.req, s.duration_h, s.turnaround))
    return out


def plan(st: S.OpsState, preset: str = "BALANCED", stability: dict | None = None, keep: dict | None = None,
         fixed_missions: set | None = None, workers: int = D.SOLVER_WORKERS, seed: int = 0,
         time_s: float = D.SOLVER_TIME_S) -> PlanResult:
    """Pure: reads the snapshot only. fixed_missions are excluded (already covered by frozen packages)."""
    t0 = time.perf_counter()
    scope = {m for m in st.missions if m not in (fixed_missions or set())}
    cands, rejects = F.generate(st, preset, scope)
    view = {m: cands.get(m, []) for m in scope}
    forbid: set[int] = set()
    fail_reason: dict[int, str] = {}
    sol, assignments = None, {}
    sub = _scoped(st, scope)
    base = O.base_model(sub, view)                 # once: retries only forbid options
    for _ in range(5):
        sol = O.solve(sub, view, preset, forbid=forbid, stability=stability, workers=workers, seed=seed, time_s=time_s,
                      base=base)
        assignments, fails = assign_all(sub, sol.selected, keep)
        if not fails:
            # the independent validator has the last word; an option it rejects is forbidden and the model re-solved
            vs = validate(st, [x for mid, c in sol.selected.items() for x in specs(c, assignments[mid], st.missions[mid].code)])
            fails = {v.mission_id: f"validator: {v.detail}" for v in vs if v.mission_id in sol.selected}
            if not fails:
                break
        for mid, why in fails.items():
            forbid.add(sol.selected[mid].idx)
            fail_reason[mid] = why
    for mid in list(sol.selected):
        if mid not in assignments:
            sol.selected.pop(mid)
            if mid not in sol.unmet:
                sol.unmet.append(mid)
    all_specs = [x for mid, c in sol.selected.items() for x in specs(c, assignments[mid], st.missions[mid].code)]
    violations = validate(st, all_specs)
    for v in violations:   # defensive: the validator is independent; anything it rejects is not proposed
        log.warning("plan item rejected by validator: %s %s %s", v.key, v.rule, v.detail)
        if v.mission_id in sol.selected:
            sol.selected.pop(v.mission_id)
            sol.unmet.append(v.mission_id)
            fail_reason[v.mission_id] = f"validator: {v.detail}"
    if _fill(sub, st, view, sol, assignments):
        all_specs = [x for mid, c in sol.selected.items() for x in specs(c, assignments[mid], st.missions[mid].code)]
    violations = validate(st, all_specs)           # what is reported is the final plan (expected: none)
    res = PlanResult(st, solver_status=sol.status, solve_ms=sol.solve_ms, violations=[v.as_dict() for v in violations],
                     selected=sol.selected, assignments=assignments)
    for mid, c in sorted(sol.selected.items(), key=lambda kv: kv[1].launch):
        a = assignments[mid]
        expl, alts = X.explain_item(st, c, cands.get(mid, []), sol, a.notes)
        res.items.append(_item_dict(st, c, a, expl, alts))
    for mid in sorted(set(sol.unmet)):
        reasons, fixes = X.explain_unmet(st, mid, [c for c in cands.get(mid, []) if c.idx not in forbid], rejects.get(mid, []),
                                         sol, fail_reason.get(mid))
        res.unmet.append({"mission_id": mid, "reasons": reasons, "fixes": fixes})
    res.kpis = kpis(st, res, sol, sum(len(v) for v in view.values()))
    res.total_ms = int((time.perf_counter() - t0) * 1000)
    res.kpis["total_ms"] = res.total_ms
    return res


def _fill(sub: S.OpsState, st: S.OpsState, view: dict, sol: O.Solution, assignments: dict) -> list:
    """Fill pass (D40): the model's capacity rows are aggregates, so an option can pass them and still fail detailed
    crewing; after the retries such a mission is left uncovered although another option would fit. Give every uncovered
    mission one more try, priority first: the cheapest option that can be crewed around the plan and still validates."""
    led = Ledger()
    for mid, c in sol.selected.items():
        led.take(c, assignments[mid])
    acc = [x for mid, c in sol.selected.items() for x in specs(c, assignments[mid], st.missions[mid].code)]
    added = []
    for mid in sorted(set(sol.unmet), key=lambda m: (st.missions[m].priority, st.missions[m].window_start, m)):
        for c in sorted(view.get(mid, []), key=lambda c: (c.cost, c.idx))[:8]:
            a = assign(sub, c, led)
            if isinstance(a, str):
                continue
            led.take(c, a)
            if c.support is not None:
                s = assign(sub, c.support, led)
                if isinstance(s, str):
                    led.release(c, a)
                    continue
                a.support = s
                led.take(c.support, s)
            sp = specs(c, a, st.missions[mid].code)
            if validate(st, acc + sp):
                led.release(c, a)
                if a.support is not None:
                    led.release(c.support, a.support)
                continue
            acc += sp
            sol.selected[mid], assignments[mid] = c, a
            added.append(mid)
            break
    if added:
        sol.unmet = [m for m in sol.unmet if m not in added]
        log.info("fill pass covered %d more mission(s)", len(added))
    return added


def _scoped(st: S.OpsState, scope: set) -> S.OpsState:
    if scope == set(st.missions):
        return st
    import copy
    sub = copy.copy(st)
    sub.missions = {m: st.missions[m] for m in scope}
    return sub


def snag_view(st: S.OpsState, aircraft_ids: list, dur_h: float) -> dict | None:
    """Predicted defect risk per tail and for the whole package (D38); None without a model."""
    if st.snag is None:
        return None
    tails = {aid: PR.tail_risk(st, st.aircraft[aid], dur_h) for aid in aircraft_ids if aid in st.aircraft}
    if not tails:
        return None
    pkg = 1.0
    for p in tails.values():
        pkg *= 1 - p
    worst = max(tails, key=tails.get)
    a = st.aircraft[worst]
    return {"tails": {st.aircraft[k].tail: round(v, 4) for k, v in tails.items()}, "package": round(1 - pkg, 4),
            "worst": a.tail, "worst_p": round(tails[worst], 4), "model_id": st.snag.id,
            "drivers": st.snag.drivers(a.frac, a.age_y, dur_h, a.family, a.recent),
            "auc": st.snag.metrics.get("test", {}).get("auc")}


def _item_dict(st: S.OpsState, c: F.Candidate, a: Assignment, expl: dict, alts: list) -> dict:
    sn = snag_view(st, a.aircraft, c.duration_h)
    if sn:
        why = f" ({'; '.join(sn['drivers'])})" if sn["drivers"] else ""
        expl["rows"].append({"label": "Snag risk", "value": f"{sn['package']:.0%} for the package",
                             "note": f"worst tail {sn['worst']} {sn['worst_p']:.0%}{why} · predicted, model AUC {sn['auc']}",
                             **({"tone": "caution"} if sn["package"] >= D.SNAG_CAUTION else {})})
    return dict(mission_id=c.mission_id, base_id=c.base_id, recovery_base_id=c.base_id, aircraft_type_id=c.type_id,
                loadout_code=c.loadout, launch_ts=c.launch, on_station_ts=c.on_station, recovery_ts=c.recovery,
                n_aircraft=c.n, aircraft_ids=list(a.aircraft), aircrew_ids=[x[0] for x in a.crew],
                crew_positions=[list(x) for x in a.crew], route=[list(p) for p in c.route], risk=c.risk_peak,
                fuel_l=c.fuel_l, explanation=expl, alternatives=alts,
                score={"cost": c.cost, "parts": c.cost_parts, "req": {"quals": sorted(c.req.quals), "rating": c.req.rating,
                                                                       "ops": c.req.ops},
                       "duration_h": round(c.duration_h, 2), "weapons": c.weapons, "expended": c.expended,
                       "turnaround": c.turnaround, "off_station": c.off_station.isoformat(), "night": c.night,
                       "zone_id": c.zone_id, "snag": sn, "traffic": c.traffic},
                support=_support_dict(c, a))


def _support_dict(c: F.Candidate, a: Assignment) -> dict | None:
    s, sa = c.support, a.support
    if s is None or sa is None:
        return None
    return {"kind": s.kind, "base_id": s.base_id, "type_id": s.type_id, "n": s.n, "launch": s.launch.isoformat(),
            "recovery": s.recovery.isoformat(), "rv": list(s.rv), "rv_start": s.rv_start.isoformat(), "rv_end": s.rv_end.isoformat(),
            "route": [list(p) for p in s.route], "duration_h": s.duration_h, "fuel_l": s.fuel_l, "pilots": s.pilots,
            "req": {"quals": sorted(s.req.quals), "rating": s.req.rating, "ops": s.req.ops}, "turnaround": s.turnaround,
            "transit_min": s.transit_min, "aircraft_ids": list(sa.aircraft), "crew_positions": [list(x) for x in sa.crew],
            "sortie_id": None}


def kpis(st: S.OpsState, res: PlanResult, sol: O.Solution, n_cands: int) -> dict:
    by = {p: {"covered": 0, "of": 0} for p in D.PRIORITIES}
    for m in st.missions.values():
        by[m.priority]["of"] += 1
    for it in res.items:
        by[st.missions[it["mission_id"]].priority]["covered"] += 1
    q = list(st.qra.values())
    return {
        "missions": len(st.missions), "covered": len(res.items), "unmet": len(res.unmet), "by_priority": by,
        "sorties": sum(i["n_aircraft"] + (i["support"]["n"] if i.get("support") else 0) for i in res.items),
        "tanker_sorties": sum(1 for i in res.items if i.get("support")),
        "flying_hours": round(sum(i["n_aircraft"] * i["score"]["duration_h"] for i in res.items), 1),
        "fuel_l": round(sum(i["fuel_l"] for i in res.items)),
        "risk_peak": round(max([i["risk"] for i in res.items] or [0]), 2),
        "risk_mean": round(sum(i["risk"] for i in res.items) / max(1, len(res.items)), 2),
        "aircraft": len({a for i in res.items for a in i["aircraft_ids"]}),
        "aircrew": len({c for i in res.items for c in i["aircrew_ids"]}),
        "qra_postures": len(q), "qra_met": sum(1 for x in q if x["have"] >= x["required"]),
        "qra_backfill": sum(max(0, x["required"] - x["have"]) for x in q),
        "snag_expected": round(sum(sum((i["score"].get("snag") or {}).get("tails", {}).values()) for i in res.items), 2)
        if st.snag else None,                     # predicted defects across every tail in the plan (D38)
        "candidates": n_cands, "solver_status": sol.status, "solve_ms": sol.solve_ms,
        "stages": sol.stage_values, "violations": len(res.violations),
    }


# ---------------------------------------------------------------------------------------------- storage
def store(db: Session, res: PlanResult, *, preset: str, user: dict | None, kind: str = "PLAN", scope: str = "THEATRE",
          command_id: int | None = None, parent_plan_id: int | None = None, disruption_id: int | None = None,
          changes: dict | None = None, summary: str | None = None) -> int:
    st = res.st
    p = M.Plan(kind=kind, scope=scope, command_id=command_id, horizon_start=st.now, horizon_end=st.horizon_end,
               status="PROPOSED", preset=preset, weights=D.PRESETS.get(preset), seed=0, solver_status=res.solver_status,
               solve_ms=res.solve_ms, kpis=S.to_json(res.kpis), created_by=user["id"] if user else None,
               parent_plan_id=parent_plan_id, trigger_disruption_id=disruption_id, summary=summary, is_simulated=True)
    db.add(p)
    db.flush()
    for it in res.items:
        ch = (changes or {}).get(it["mission_id"], {})
        db.add(M.PlanItem(plan_id=p.id, mission_id=it["mission_id"], base_id=it["base_id"],
                          recovery_base_id=it["recovery_base_id"], aircraft_type_id=it["aircraft_type_id"],
                          loadout_code=it["loadout_code"], launch_ts=it["launch_ts"], on_station_ts=it["on_station_ts"],
                          recovery_ts=it["recovery_ts"], n_aircraft=it["n_aircraft"], aircraft_ids=it["aircraft_ids"],
                          aircrew_ids=it["aircrew_ids"], crew_positions=it["crew_positions"],
                          route_geom=from_shape(LineString([tuple(x) for x in it["route"]]), srid=4326) if len(it["route"]) > 1 else None,
                          risk=it["risk"], fuel_l=it["fuel_l"], score=S.to_json(it["score"]),
                          explanation=S.to_json(it["explanation"]), alternatives=S.to_json(it["alternatives"]),
                          change=ch.get("change"), source_item_id=ch.get("source_item_id"), status="PROPOSED",
                          support=S.to_json(it["support"]) if it.get("support") else None))
    for u in res.unmet:
        ch = (changes or {}).get(u["mission_id"], {})
        db.add(M.PlanUnmet(plan_id=p.id, mission_id=u["mission_id"], reasons=S.to_json(u["reasons"]),
                           fixes=S.to_json(u["fixes"]), dropped_item_id=ch.get("source_item_id")))
    db.flush()
    return p.id


def cand_from_row(st: S.OpsState, r: dict, idx: int) -> F.Candidate:
    """A stored plan item (dict) back as a Candidate, for re-assignment (re-tasking, commit-time repair)."""
    sc = r["score"] or {}
    rq = sc.get("req", {})
    t = st.types[r["aircraft_type_id"]]
    from .resources import pilots_per_aircraft
    c = F.Candidate(idx, r["mission_id"], r["base_id"], r["aircraft_type_id"], r["loadout_code"], r["n_aircraft"],
                  r["launch_ts"], r["on_station_ts"] or r["launch_ts"], r["on_station_ts"] or r["launch_ts"], r["recovery_ts"],
                  sc.get("duration_h", 1.0), [tuple(p) for p in r["route"] or []], r["fuel_l"], r["risk"], 0, None, "VFR", "VFR",
                  Req(frozenset(rq.get("quals", [])), rq.get("rating", "WHITE"), rq.get("ops", False)), sc.get("night", False),
                  r["n_aircraft"] * pilots_per_aircraft(t), sc.get("zone_id"), 0, sc.get("weapons", {}), sc.get("expended", {}), 0)
    c.turnaround = sc.get("turnaround", 45)
    c.support = support_from_row(st, r)
    return c


def _dt(v):
    return datetime.fromisoformat(v) if isinstance(v, str) else v


def support_from_row(st: S.OpsState, r: dict) -> F.SupportLeg | None:
    s = r.get("support")
    if not s:
        return None
    rq = s.get("req", {})
    return F.SupportLeg(s["kind"], s["base_id"], s["type_id"], s.get("n", 1), _dt(s["launch"]), _dt(s["recovery"]), tuple(s["rv"]),
                        _dt(s["rv_start"]), _dt(s["rv_end"]), [tuple(p) for p in s["route"]], s["duration_h"], s["fuel_l"],
                        s["pilots"], Req(frozenset(rq.get("quals", [])), rq.get("rating", "WHITE"), rq.get("ops", True)),
                        s.get("turnaround", 60), s.get("transit_min", 0))


def assignment_from_row(r: dict) -> Assignment:
    s = r.get("support")
    sup = Assignment(list(s["aircraft_ids"]), [tuple(x) for x in s["crew_positions"]]) if s else None
    return Assignment(list(r["aircraft_ids"] or []), [tuple(x) for x in r["crew_positions"] or []], support=sup)


def specs_from_row(r: dict) -> list[ItemSpec]:
    """The stored package and its support leg, as validator specs (support key "<item id>#AAR")."""
    out = [item_spec_from_row(r)]
    s = r.get("support")
    if s:
        rq = s.get("req", {})
        out.append(ItemSpec(f"{r['id']}#{s['kind']}", r["mission_id"], s["base_id"], s["type_id"], _dt(s["launch"]), _dt(s["recovery"]),
                            _dt(s["rv_start"]), list(s["aircraft_ids"]), [tuple(x) for x in s["crew_positions"]], s["fuel_l"], {},
                            s["route"], Req(frozenset(rq.get("quals", [])), rq.get("rating", "WHITE"), rq.get("ops", True)),
                            s["duration_h"], s.get("turnaround", 60)))
    return out


def item_spec_from_row(r: dict) -> ItemSpec:
    """Plan item row (dict) -> ItemSpec for the validator / monitor."""
    sc = r["score"] or {}
    rq = sc.get("req", {})
    route = r.get("route") or []
    return ItemSpec(str(r["id"]), r["mission_id"], r["base_id"], r["aircraft_type_id"], r["launch_ts"], r["recovery_ts"],
                    r["on_station_ts"], list(r["aircraft_ids"] or []), [tuple(x) for x in (r["crew_positions"] or [])],
                    r["fuel_l"], sc.get("weapons", {}), route, Req(frozenset(rq.get("quals", [])), rq.get("rating", "WHITE"),
                                                                   rq.get("ops", False)),
                    sc.get("duration_h", 1.0), sc.get("turnaround", 45))
