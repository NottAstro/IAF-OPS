"""Inventory optimisation (ARCHITECTURE D56): which moves of fuel, weapons and spares between bases let the plan under
review be flown, and bring bases back above their fuel reserve and spares reorder levels.

One min-cost flow per commodity (OR-Tools): donors offer what they hold beyond their reserve (or reorder level) and their
own planned use; receivers need what the plan's packages will draw plus what puts them back at reserve; arc cost is the
road distance. Advisory only: a person approves each move (services/transfers.py), and nothing here writes.
"""
import math
from datetime import datetime, timedelta

from ortools.graph.python import min_cost_flow
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..geo import dist_km
from . import config as D
from . import snapshot as S
from . import store

FLOWN = ("AIRBORNE", "ON_STATION", "RTB", "LANDED", "COMPLETED", "CANCELLED", "ABORTED")
LABEL = {"ATF": "Aviation fuel (ATF)", "ARMAMENT_AAM_BVR": "Air-to-air missiles, long range",
         "ARMAMENT_AAM_WVR": "Air-to-air missiles, short range", "ARMAMENT_PGM": "Precision-guided munitions",
         "ARMAMENT_BOMB_UNGUIDED": "Unguided bombs", "ARMAMENT_ROCKET": "Rockets", "ARMAMENT_GUN_AMMO": "Gun ammunition",
         "ARMAMENT_CHAFF_FLARE": "Chaff and flares", "ENGINE_SPARES": "Engine spares", "AIRFRAME_SPARES": "Airframe spares",
         "AVIONICS_SPARES": "Avionics spares", "TYRES_BRAKES": "Tyres and brakes", "CONSUMABLES": "Consumables",
         "POL_PACKED": "Packed oils and lubricants", "GSE_SPARES": "GSE spares", "MEDICAL": "Medical stores"}
UNSOLVABLE = 10 ** 7          # cost of the slack arc: what no donor can supply


def label(cat: str) -> str:
    return LABEL.get(cat) or cat.replace("_", " ").capitalize()


def _demand(db: Session, st: S.OpsState, plan_id: int | None) -> tuple[dict, dict, dict, dict]:
    """From the packages of the plan under review still to launch inside the horizon: fuel per base (incl. tanker legs),
    weapons per (base, category) for packages not yet reserved, first launch needing each, and sorties per base."""
    fuel, weap, first, sorties = {}, {}, {}, {}
    if plan_id is None:
        return fuel, weap, first, sorties
    rows = [r for r in store.items_of(db, plan_id) if r["status"] != "REJECTED"]
    done = {r[0] for r in db.execute(text("SELECT id FROM sortie WHERE id = ANY(:i) AND status = ANY(:s)"),
                                     {"i": [r["sortie_id"] for r in rows if r["sortie_id"]] or [0], "s": list(FLOWN)})}

    def need_at(key, ts):
        first[key] = min(first.get(key, ts), ts)
    for r in rows:
        if r["sortie_id"] in done or not (st.now <= r["launch_ts"] <= st.horizon_end):
            continue
        b = r["base_id"]
        fuel[b] = fuel.get(b, 0.0) + float(r["fuel_l"] or 0)
        sorties[b] = sorties.get(b, 0) + 1
        need_at((b, "ATF"), r["launch_ts"])
        sup = r.get("support") or {}
        if sup.get("base_id") and not sup.get("sortie_id"):
            fuel[sup["base_id"]] = fuel.get(sup["base_id"], 0.0) + float(sup.get("fuel_l") or 0)
            need_at((sup["base_id"], "ATF"), datetime.fromisoformat(sup["launch"]))
        if not r["sortie_id"]:                        # committed packages already hold their weapons (qty_reserved)
            for cat, q in (st.loadouts.get(r["loadout_code"] or "", {}).get("items") or {}).items():
                weap[(b, cat)] = weap.get((b, cat), 0) + q * r["n_aircraft"]
                need_at((b, cat), r["launch_ts"])
    return fuel, weap, first, sorties


def _stock(db: Session) -> dict:
    """(base, category) -> dict(free, reorder, unit), counting stock already on its way in."""
    out = {}
    for r in db.execute(text("""SELECT w.base_id b, i.category c, min(i.unit) u, sum(l.qty_on_hand - l.qty_reserved) free,
                                       sum(l.reorder_level) reorder FROM stock_level l
                                JOIN stock_item i ON i.id = l.stock_item_id JOIN warehouse w ON w.id = l.warehouse_id
                                JOIN base bs ON bs.id = w.base_id AND bs.side = 'OWN'
                                WHERE w.status <> 'CLOSED' GROUP BY 1, 2""")):
        out[(r.b, r.c)] = {"free": float(r.free), "reorder": float(r.reorder), "unit": r.u}
    for r in db.execute(text("""SELECT to_base_id b, category c, sum(qty) q FROM inventory_transfer
                                WHERE status = 'IN_TRANSIT' AND kind = 'STOCK' GROUP BY 1, 2""")):
        out.setdefault((r.b, r.c), {"free": 0.0, "reorder": 0.0, "unit": "EA"})["free"] += float(r.q)
    return out


def _solve(needs: dict, offers: dict, where: dict) -> tuple[list, dict]:
    """Min-cost flow: offers {donor: units} → needs {receiver: units}, cost = road km. Returns ([(donor, receiver, units,
    km)], {receiver: units nobody can supply})."""
    if not needs or not offers:
        return [], dict(needs)
    total = sum(needs.values())
    f = min_cost_flow.SimpleMinCostFlow()
    src, snk = 0, 1
    don = {b: 2 + k for k, b in enumerate(offers)}
    rec = {b: 2 + len(don) + k for k, b in enumerate(needs)}
    arcs = []
    for b, n in don.items():
        f.add_arc_with_capacity_and_unit_cost(src, n, int(offers[b]), 0)
    for d, dn in don.items():
        for r, rn in rec.items():
            if d == r or d not in where or r not in where:
                continue
            km = dist_km(where[d], where[r]) * D.ROAD_FACTOR
            if km <= D.TRANSFER_MAX_KM:
                arcs.append((f.add_arc_with_capacity_and_unit_cost(dn, rn, int(total), int(round(km))), d, r, km))
    for r, rn in rec.items():
        f.add_arc_with_capacity_and_unit_cost(rn, snk, int(needs[r]), 0)
    f.add_arc_with_capacity_and_unit_cost(src, snk, int(total), UNSOLVABLE)       # slack: what can't be supplied
    f.set_node_supply(src, int(total))
    f.set_node_supply(snk, -int(total))
    if f.solve() != f.OPTIMAL:
        return [], dict(needs)
    moves = [(d, r, f.flow(a), km) for a, d, r, km in arcs if f.flow(a) > 0]
    got = {}
    for _, r, q, _ in moves:
        got[r] = got.get(r, 0) + q
    return moves, {r: n - got.get(r, 0) for r, n in needs.items() if n - got.get(r, 0) > 0}


def recommend(db: Session, st: S.OpsState, plan_id: int | None, focus_bases: set | None = None) -> dict:
    """Moves that make the plan under review flyable and restore reserves. focus_bases: where spares shortages count
    (the bases a live scenario touched or flies from); fuel and weapons count everywhere."""
    fuel_d, weap_d, first, sorties = _demand(db, st, plan_id)
    where = {b.id: (b.lon, b.lat) for b in st.bases.values()}
    names = {b.id: (b.code, b.name.replace("Air Force Station ", "")) for b in st.bases.values()}
    eta = lambda km: st.now + timedelta(hours=D.LOAD_H + km / D.CONVOY_KMH)     # noqa: E731
    moves, unmet = [], []

    def emit(kind, cat, unit, scale, solved, why):
        sol, short = solved
        for d, r, q, km in sol:
            # needed by the first launch that draws on it; fuel below reserve is needed now; spares only restock
            need_by = first.get((r, cat)) or (st.now if kind == "FUEL" or cat.startswith("ARMAMENT") else None)
            moves.append({"key": f"{kind}:{cat}:{d}:{r}", "kind": kind, "category": cat, "label": label(cat),
                          "qty": q * scale, "unit": unit, "from_base": {"id": d, "code": names[d][0], "name": names[d][1]},
                          "to_base": {"id": r, "code": names[r][0], "name": names[r][1]}, "distance_km": round(km),
                          "depart_ts": st.now, "eta": eta(km), "needed_by": need_by,
                          "late": need_by is not None and eta(km) > need_by, "reason": why(r)})
        for r, q in short.items():
            unmet.append({"kind": kind, "category": cat, "label": label(cat), "qty": q * scale, "unit": unit,
                          "to_base": {"id": r, "code": names[r][0], "name": names[r][1]},
                          "reason": f"No base within {D.TRANSFER_MAX_KM} km by road can spare it"})

    # ---- fuel (ATF), in whole kL
    needs, offers = {}, {}
    for b, f in st.fuel.items():
        if b not in names:
            continue
        left = f["current_l"] - f["reserve_l"] - fuel_d.get(b, 0.0)
        if left < 0:
            needs[b] = math.ceil(-left / 1000)
        else:
            spare = left - D.DONOR_KEEP_FRAC * f["capacity_l"]
            if spare >= 1000:
                offers[b] = math.floor(spare / 1000)
    fuel_why = lambda r: (f"{names[r][1]} needs more fuel for its {sorties[r]} planned sorties and its reserve"  # noqa: E731
                          if fuel_d.get(r) else f"{names[r][1]} is below its fuel reserve")
    emit("FUEL", "ATF", "L", 1000, _solve(needs, offers, where), fuel_why)

    # ---- weapons and spares, per category
    stock = _stock(db)
    focus = focus_bases or set()
    for cat in sorted({c for _, c in stock} | {c for _, c in weap_d}):
        armament = cat.startswith("ARMAMENT")
        if not armament and cat not in D.SPARE_CATEGORIES:
            continue
        needs, offers, unit = {}, {}, "EA"
        for (b, c), s in stock.items():
            if c != cat or b not in names:
                continue
            unit = s["unit"]
            use = weap_d.get((b, cat), 0)
            short = use - s["free"] if armament else (s["reorder"] - s["free"] if b in focus else 0)
            if short > 0:
                needs[b] = math.ceil(short)
            else:
                spare = s["free"] - use - s["reorder"]
                if spare >= 1:
                    offers[b] = math.floor(spare)
        for (b, c), q in weap_d.items():          # a base flying the plan with none of it at all
            if c == cat and (b, c) not in stock and b in names:
                needs[b] = math.ceil(q)
        if not needs:
            continue
        why = (lambda r, cat=cat: f"{names[r][1]} short of {label(cat).lower()} for its planned packages") if armament else \
              (lambda r, cat=cat: f"{names[r][1]} below its reorder level for {label(cat).lower()}")
        emit("STOCK", cat, unit, 1, _solve(needs, offers, where), why)
    moves.sort(key=lambda m: (m["needed_by"] is None, m["needed_by"] or st.now, m["kind"] != "FUEL", -m["qty"]))
    return {"moves": moves, "unmet": unmet}
