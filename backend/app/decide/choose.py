"""A person's own choice for one mission (ARCHITECTURE D61): replace the planner's package with another option, either
one of the planner's other options or a base and aircraft type picked by hand (optionally a time on station).

The planner's own rules judge it, exactly as for the manual baseline (manual.py): candidates for that base and type
(the nearest workable time), tail and crew assignment around every other package in the plan, and the independent
validator over the whole plan (D40). The result goes into the plan waiting for a decision; with nothing waiting it
becomes a new proposal, a change to the plan in force. Nothing reaches the sorties until a person commits (store.commit).
"""
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import models as M
from ..audit import audit
from . import config as D
from . import explain as X
from . import feasibility as F
from . import optimiser as O
from . import planner as P
from . import snapshot as S
from . import store
from .assign import Ledger, assign
from .store import PlanError
from .validate import validate


def _plan(db: Session) -> M.Plan:
    p = store.under_review(db)
    if p is None:
        raise PlanError(409, "There is no plan yet. Start a scenario or plan the next 24 hours first.")
    return p


def _rows(db: Session, p: M.Plan) -> list[dict]:
    live = ("PROPOSED", "APPROVED") if p.status in ("PROPOSED", "APPROVED") else ("COMMITTED",)
    return [r for r in store.items_of(db, p.id) if r["status"] in live]


def _snapshot(db: Session, rows: list[dict], mine: list[dict]) -> S.OpsState:
    # what a re-plan sees: the plan in force's packages still on the ground are free to move, and so is this one's
    return S.build(db, release_sortie_ids=store._releasable(db) | store.own_sorties(db, mine, pre_launch_only=False))


def options(db: Session, mission_id: int) -> dict:
    """The planner's choice for the mission (if any), its other options, and every base and type a person could pick."""
    p = _plan(db)
    rows = _rows(db, p)
    mine = [r for r in rows if r["mission_id"] == mission_id]
    st = _snapshot(db, rows, mine)
    m = st.missions.get(mission_id)
    if m is None:
        raise PlanError(409, "This mission's window has passed or it is no longer open for planning.")
    ids = {r.code: r.id for r in db.execute(text("SELECT id, code FROM base"))}
    tids = {r.name: r.id for r in db.execute(text("SELECT id, name FROM aircraft_type"))}
    alts = []
    for a in (mine[0]["alternatives"] or []) if mine else []:
        code = a["base"].split()[0]
        if code in ids and a["type"] in tids:
            alts.append({**a, "base_id": ids[code], "type_id": tids[a["type"]]})
    held = {}
    for (b, t), tails in st.by_base_type.items():
        n = sum(1 for i in tails if st.aircraft[i].status != "QRA")
        if n and st.types[t].role in m.roles and b in st.bases:
            held[(b, t)] = n
    manual = sorted(({"base_id": b, "base": st.bases[b].code, "base_name": st.bases[b].name.replace("Air Force Station ", ""),
                      "type_id": t, "type": st.types[t].name, "aircraft": n} for (b, t), n in held.items()),
                    key=lambda o: (o["base_name"], o["type"]))
    return {"plan_id": p.id, "mission": {"id": m.id, "code": m.code, "name": m.name, "priority": m.priority,
                                         "window_start": m.window_start, "window_end": m.window_end,
                                         "required": m.required, "on_station_min": m.on_station_min},
            "current": {"item_id": mine[0]["id"], "base_id": mine[0]["base_id"], "type_id": mine[0]["aircraft_type_id"],
                        "launch": mine[0]["launch_ts"]} if mine else None,
            "alternatives": alts, "manual": manual}


def choose(db: Session, user: dict, mission_id: int, base_id: int, type_id: int, on_station: datetime | None = None,
           request_id: str | None = None) -> dict:
    """Put a person's choice for one mission into the plan, if every rule holds. -> {plan_id, item_id, package}."""
    p = _plan(db)
    rows = _rows(db, p)
    mine = [r for r in rows if r["mission_id"] == mission_id]
    others = [r for r in rows if r["mission_id"] != mission_id]
    st = _snapshot(db, rows, mine)
    m = st.missions.get(mission_id)
    if m is None:
        raise PlanError(409, "This mission's window has passed or it is no longer open for planning.")
    if base_id not in st.bases or type_id not in st.types:
        raise PlanError(422, "That base or aircraft type isn't available.")
    b, t = st.bases[base_id], st.types[type_id]

    # 1. the planner's own rules for that base and type: range, weather, runway, threat, fuel, crew quals, window
    cands, rejects = F.generate(st, p.preset if p.preset in D.PRESETS else "BALANCED", {mission_id}, only={mission_id: (base_id, type_id)})
    cs = cands.get(mission_id, [])
    if not cs:
        why = next((r for r in rejects.get(mission_id, []) if (r.base_id, r.type_id) == (base_id, type_id)), None) or \
            (rejects.get(mission_id) or [None])[0]
        raise PlanError(422, f"{t.name} from {b.code} can't fly this mission: "
                        + (F.REASON_TEXT.get(why.reason, why.reason) + (f" ({why.detail})" if why.detail else "") if why else "not feasible"))
    want = on_station or cs[0].on_station
    c = min(cs, key=lambda c: (abs((c.on_station - want).total_seconds()), c.cost))

    # 2. tails and crew, around every other package in the plan
    led = Ledger()
    for k, r in enumerate(others):
        led.take(P.cand_from_row(st, r, -1 - k), P.assignment_from_row(r))
    a = assign(st, c, led)
    if isinstance(a, str):
        raise PlanError(422, f"No tails or crew left for it: {a}")
    if c.support is not None:
        led.take(c, a)
        s = assign(st, c.support, led)
        if isinstance(s, str):
            raise PlanError(422, f"No tanker for it: {s}")
        a.support = s

    # 3. the independent validator over the whole plan has the last word (D40)
    specs = [x for r in others for x in P.specs_from_row(r)] + P.specs(c, a, "choice")
    bad = [v for v in validate(st, specs) if v.key.startswith("choice")]
    if bad:
        raise PlanError(422, f"That choice breaks a rule: {bad[0].detail}", [v.as_dict() for v in bad])

    # 4. the package, explained like the planner's own, saying who chose it
    expl, alts = X.explain_item(st, c, cs, O.Solution({mission_id: c}, [], "MANUAL"), [])
    expl["rows"].insert(0, {"label": "Chosen by", "value": user.get("username") or "a person",
                            "note": "a person's choice, checked against every rule the planner uses", "tone": "info"})
    it = P._item_dict(st, c, a, expl, (mine[0]["alternatives"] or []) if mine else alts)
    before = {"base": st.bases[mine[0]["base_id"]].code if mine and mine[0]["base_id"] in st.bases else None,
              "type": st.types[mine[0]["aircraft_type_id"]].name if mine and mine[0]["aircraft_type_id"] in st.types else None,
              "launch": mine[0]["launch_ts"].isoformat() if mine else None}
    after = {"base": b.code, "type": t.name, "launch": c.launch.isoformat()}

    # 5. into the plan waiting for a decision, or a new proposal on top of the plan in force
    if p.status in ("PROPOSED", "APPROVED"):
        old = db.get(M.PlanItem, mine[0]["id"]) if mine else None
        ch = {"change": ("MOVED" if old.source_item_id else old.change) if old else ("NEW" if p.kind == "RETASK" else None),
              "source_item_id": old.source_item_id if old else None}
        if old is not None:
            db.delete(old)
        db.execute(text("DELETE FROM plan_unmet WHERE plan_id = :p AND mission_id = :m"), {"p": p.id, "m": mission_id})
        new = P.item_model(p.id, it, ch)
        db.add(new)
        p.status, p.version = "PROPOSED", p.version + 1
        pid = p.id
    else:
        res = P.PlanResult(st, items=[it], unmet=[], kpis={**(p.kpis or {}), "rung": "person", "why": f"Your choice for {m.name}"},
                           solver_status="MANUAL", solve_ms=0)
        pid = P.store(db, res, preset=p.preset, user=user, kind="RETASK", parent_plan_id=p.id,
                      changes={mission_id: {"change": "MOVED" if mine else "NEW", "source_item_id": mine[0]["id"] if mine else None}},
                      summary="1 moved" if mine else "1 new")
        store.copy_items(db, p.id, pid, [r["id"] for r in others], "KEPT")
        db.execute(text("""INSERT INTO plan_unmet (plan_id, mission_id, reasons, fixes)
                           SELECT :n, mission_id, reasons, fixes FROM plan_unmet WHERE plan_id = :p AND mission_id <> :m"""),
                   {"n": pid, "p": p.id, "m": mission_id})
        db.execute(text("""UPDATE plan SET status = 'SUPERSEDED' WHERE kind = 'RETASK' AND status = 'PROPOSED' AND id <> :p"""), {"p": pid})
        new = db.scalars(select(M.PlanItem).where(M.PlanItem.plan_id == pid, M.PlanItem.mission_id == mission_id)).first()
    db.flush()
    _resummarise(db, pid, mission_id, bool(mine))
    item_id = new.id
    audit(db, user, "PLAN_OVERRIDE", "plan_item", item_id, base_id, before, {**after, "chosen_by": "person", "mission_id": mission_id},
          request_id=request_id)
    return {"plan_id": pid, "item_id": item_id, "package": f"{c.n} × {t.name} from {b.name.replace('Air Force Station ', '')}",
            "launch": c.launch, "on_station": c.on_station}


def _resummarise(db: Session, pid: int, mission_id: int, was_covered: bool) -> None:
    """After a person's choice: one more mission covered if it wasn't before (the plan's own mission count stands), and
    the change summary counted like retask.propose does."""
    p = db.get(M.Plan, pid)
    k = dict(p.kpis or {})
    if not was_covered:
        prio = db.execute(text("SELECT priority FROM mission WHERE id = :m"), {"m": mission_id}).scalar()
        k["covered"] = (k.get("covered") or 0) + 1
        k["unmet"] = max(0, (k.get("unmet") or 0) - 1)
        by = {q: dict(v) for q, v in (k.get("by_priority") or {}).items()}
        if prio in by:
            by[prio]["covered"] = by[prio].get("covered", 0) + 1
        k["by_priority"] = by
    if p.kind == "RETASK":
        items = [r for r in store.items_of(db, pid) if r["status"] != "REJECTED"]
        counts = {c: sum(1 for r in items if r["change"] == c) for c in ("SWAP", "MOVED", "NEW", "DROPPED", "DIVERT", "REROLE")}
        k["changes"] = {**counts, "KEPT": sum(1 for r in items if r["change"] in (None, "KEPT"))}
        p.summary = ", ".join(f"{v} {c.lower()}" for c, v in counts.items() if v) or "no change needed"
    else:
        p.summary = f"{k.get('covered')} of {k.get('missions')} missions covered"
    p.kpis = S.to_json(k)
