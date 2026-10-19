"""Inventory transfers (ARCHITECTURE D56): the only writes for a move of fuel, weapons or spares between bases.

approve(): a person accepts a recommended move (decide/logistics.py). The donor is debited now (it never goes below its
fuel reserve or its stock reorder level) and the convoy is IN_TRANSIT. deliver_due(): the simulator credits the receiver
when the convoy arrives. Both audited; the snapshot counts stock in transit as arriving (decide/snapshot.py).
"""
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import models as M
from ..audit import audit
from ..decide import config as D
from ..geo import dist_km

STORE_KIND = {"POL_PACKED": "POL_PACKED", "MEDICAL": "MEDICAL"}   # anything ARMAMENT_* goes to ARMAMENT_STORE, spares to AVIATION_SPARES


class TransferError(Exception):
    pass


def _pt(db: Session, base_id: int) -> tuple:
    r = db.execute(text("SELECT ST_X(geom), ST_Y(geom) FROM base WHERE id = :b AND side = 'OWN'"), {"b": base_id}).first()
    if not r:
        raise TransferError("Unknown IAF base")
    return r[0], r[1]


def approve(db: Session, user: dict, kind: str, category: str, qty: float, from_base_id: int, to_base_id: int,
            needed_by: datetime | None = None, reason: str | None = None, plan_id: int | None = None,
            run_id: int | None = None, request_id: str | None = None) -> M.InventoryTransfer:
    if from_base_id == to_base_id or qty <= 0:
        raise TransferError("A transfer needs two different bases and a positive quantity.")
    now = db.execute(text("SELECT sim_now()")).scalar()
    km = dist_km(_pt(db, from_base_id), _pt(db, to_base_id)) * D.ROAD_FACTOR
    if km > D.TRANSFER_MAX_KM:
        raise TransferError(f"Too far by road ({km:.0f} km).")
    lines = None
    if kind == "FUEL":
        tanks = list(db.scalars(select(M.FuelStorage).where(M.FuelStorage.base_id == from_base_id, M.FuelStorage.grade == "ATF")
                                .order_by((M.FuelStorage.current_l - M.FuelStorage.reserve_l).desc()).with_for_update()))
        if sum(t.current_l - t.reserve_l for t in tanks) < qty:
            raise TransferError("The donor no longer has that much fuel above its reserve.")
        left = qty
        for t in tanks:
            take = min(left, max(0.0, t.current_l - t.reserve_l))
            if take <= 0:
                continue
            t.current_l -= take
            t.version += 1
            db.add(M.FuelTransaction(fuel_storage_id=t.id, ts=now, kind="TRANSFER_OUT", quantity_l=take,
                                     balance_after_l=t.current_l, actor=user.get("username", "USER")))
            left -= take
            if left <= 0:
                break
        unit = "L"
    elif kind == "STOCK":
        levels = list(db.scalars(select(M.StockLevel).join(M.StockItem, M.StockItem.id == M.StockLevel.stock_item_id)
                                 .join(M.Warehouse, M.Warehouse.id == M.StockLevel.warehouse_id)
                                 .where(M.Warehouse.base_id == from_base_id, M.Warehouse.status != "CLOSED",
                                        M.StockItem.category == category)
                                 .order_by((M.StockLevel.qty_on_hand - M.StockLevel.qty_reserved - M.StockLevel.reorder_level).desc())
                                 .with_for_update()))
        if sum(lv.qty_on_hand - lv.qty_reserved - lv.reorder_level for lv in levels) < qty:
            raise TransferError("The donor no longer has that much above its reorder level.")
        left, lines = qty, []
        for lv in levels:
            take = min(left, max(0.0, lv.qty_on_hand - lv.qty_reserved - lv.reorder_level))
            if take <= 0:
                continue
            lv.qty_on_hand -= take
            lv.version += 1
            lines.append({"stock_item_id": lv.stock_item_id, "qty": take})
            left -= take
            if left <= 0:
                break
        unit = db.execute(text("SELECT min(unit) FROM stock_item WHERE category = :c"), {"c": category}).scalar() or "EA"
    else:
        raise TransferError("Unknown transfer kind.")
    t = M.InventoryTransfer(kind=kind, category=category if kind == "STOCK" else "ATF", qty=qty, unit=unit,
                            from_base_id=from_base_id, to_base_id=to_base_id, distance_km=round(km, 1), depart_ts=now,
                            eta=now + timedelta(hours=D.LOAD_H + km / D.CONVOY_KMH), needed_by=needed_by, status="IN_TRANSIT",
                            reason=reason, lines=lines, plan_id=plan_id, exercise_run_id=run_id, created_by=user["id"])
    db.add(t)
    db.flush()
    audit(db, user, "CREATE", "inventory_transfer", t.id, from_base_id, None,
          {"kind": kind, "category": t.category, "qty": qty, "from_base_id": from_base_id, "to_base_id": to_base_id,
           "eta": t.eta.isoformat()}, request_id=request_id)
    return t


def deliver_due(db: Session, now: datetime) -> list[str]:
    """Called by the simulator every tick: convoys that have arrived credit the receiver."""
    out = []
    for t in db.scalars(select(M.InventoryTransfer).where(M.InventoryTransfer.status == "IN_TRANSIT",
                                                          M.InventoryTransfer.eta <= now).with_for_update()):
        if t.kind == "FUEL":
            left = t.qty
            for tank in db.scalars(select(M.FuelStorage).where(M.FuelStorage.base_id == t.to_base_id, M.FuelStorage.grade == "ATF")
                                   .order_by((M.FuelStorage.capacity_l - M.FuelStorage.current_l).desc())):
                put = min(left, max(0.0, tank.capacity_l - tank.current_l))
                if put <= 0:
                    continue
                tank.current_l += put
                tank.version += 1
                db.add(M.FuelTransaction(fuel_storage_id=tank.id, ts=now, kind="TRANSFER_IN", quantity_l=put,
                                         balance_after_l=tank.current_l, actor="SIMULATOR"))
                left -= put
                if left <= 0:
                    break
        else:
            kind = "ARMAMENT_STORE" if t.category.startswith("ARMAMENT") else STORE_KIND.get(t.category, "AVIATION_SPARES")
            wh = db.scalars(select(M.Warehouse).where(M.Warehouse.base_id == t.to_base_id, M.Warehouse.status != "CLOSED")
                            .order_by((M.Warehouse.kind != kind), M.Warehouse.id)).first()
            for ln in (t.lines or []) if wh else []:
                lv = db.scalars(select(M.StockLevel).where(M.StockLevel.warehouse_id == wh.id,
                                                           M.StockLevel.stock_item_id == ln["stock_item_id"])).first()
                if lv:
                    lv.qty_on_hand += ln["qty"]
                    lv.version += 1
                else:
                    db.add(M.StockLevel(warehouse_id=wh.id, stock_item_id=ln["stock_item_id"], qty_on_hand=ln["qty"],
                                        qty_reserved=0, reorder_level=0, max_level=ln["qty"], last_receipt_at=now))
        t.status, t.delivered_at, t.version = "DELIVERED", now, t.version + 1
        audit(db, None, "SIM_TRANSITION", "inventory_transfer", t.id, t.to_base_id, {"status": "IN_TRANSIT"},
              {"status": "DELIVERED"})
        out.append(f"transfer {t.id} delivered")
    return out
