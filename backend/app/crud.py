"""Generic inventory CRUD driven by model metadata (FR-INV-01..09). One router serves every entity:

GET  /inv/{entity}/meta            columns, types, enums, editability (drives the UI table + form)
GET  /inv/{entity}                 list: ?page=&page_size=&sort=&order=&q=&<column>=<value>&command=<code>
GET  /inv/{entity}/{id}
POST /inv/{entity}                 create            (RBAC scope + audit + validation)
PATCH /inv/{entity}/{id}           update, needs "version" (409 on mismatch)
POST /inv/{entity}/{id}/retire     soft-retire
DELETE /inv/{entity}/{id}          only if nothing references it, else 409 suggesting retire
"""
from dataclasses import dataclass, field
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from geoalchemy2 import Geometry
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy import ARRAY, Boolean, Date, DateTime, Enum, Float, Integer, BigInteger, String, Text, func, or_, select
from sqlalchemy.exc import IntegrityError, DBAPIError
from sqlalchemy.orm import Session

from . import models as M
from .audit import audit
from .auth import current_user
from .db import get_db
from .rbac import assert_edit_base

router = APIRouter(prefix="/inv", tags=["inventory"])
NEVER_EDIT = {"id", "created_at", "updated_at", "version", "is_simulated", "source", "source_ref"}


@dataclass
class Entity:
    model: type
    label: str
    scope: str | None = None            # column holding the owning base id
    parent: tuple | None = None         # (fk column, parent model, parent scope column) when scope is indirect
    search: list[str] = field(default_factory=list)
    readonly: bool = False              # nobody edits (reference data)
    admin_only: bool = False
    retire: tuple | None = None         # (column, value) used by soft-retire
    hidden: set[str] = field(default_factory=set)


ENTITIES: dict[str, Entity] = {
    "aircraft": Entity(M.Aircraft, "Aircraft", "home_base_id", search=["tail_no"], retire=("status", "RETIRED")),
    "aircrew": Entity(M.Aircrew, "Aircrew", "base_id", search=["first_name", "last_name", "service_no", "callsign"]),
    "ground-crew": Entity(M.GroundCrewStrength, "Ground crew strength", "base_id"),
    "ground-assets": Entity(M.GroundAsset, "Vehicles & GSE", "base_id", search=["reg_or_serial", "asset_type"],
                            retire=("status", "UNSERVICEABLE")),
    "fuel-storage": Entity(M.FuelStorage, "Fuel storage", "base_id"),
    "fuel-transactions": Entity(M.FuelTransaction, "Fuel transactions", parent=("fuel_storage_id", M.FuelStorage, "base_id")),
    "warehouses": Entity(M.Warehouse, "Warehouses", "base_id", search=["name"], retire=("status", "CLOSED")),
    "stock-levels": Entity(M.StockLevel, "Stock levels", parent=("warehouse_id", M.Warehouse, "base_id")),
    "stock-items": Entity(M.StockItem, "Stock catalogue", search=["part_no", "nomenclature"], admin_only=True),
    "ad-batteries": Entity(M.AirDefenceBattery, "Air defence batteries", "protected_base_id", search=["code"],
                           retire=("status", "OFFLINE")),
    "radars": Entity(M.RadarSite, "Radar sites", "base_id", search=["code"], retire=("status", "OFFLINE")),
    "comms-nodes": Entity(M.CommsNode, "Comms nodes", "base_id", search=["code"], retire=("status", "DOWN")),
    "runways": Entity(M.Runway, "Runways", "base_id", search=["designator"], retire=("status", "CLOSED")),
    "parking": Entity(M.ParkingFacility, "Aircraft parking", "base_id"),
    "qra-posture": Entity(M.QraPosture, "QRA posture", "base_id", retire=("active", False)),
    "squadrons": Entity(M.Squadron, "Squadrons", "home_base_id", search=["number", "name"], admin_only=True),
    "missions": Entity(M.Mission, "Missions", search=["code", "name"], admin_only=True, retire=("status", "CANCELLED")),
    "sorties": Entity(M.Sortie, "Sorties", "departure_base_id", search=["code"], readonly=True),
    "bases": Entity(M.AirBase, "Bases", search=["code", "name"], admin_only=True,
                    hidden={"metar_station", "metar_station_km"}),
    "aircraft-types": Entity(M.AircraftType, "Aircraft types", search=["name", "icao_type"], readonly=True),
    "ad-system-types": Entity(M.AdSystemType, "AD system types", search=["name"], readonly=True),
    "radar-types": Entity(M.RadarType, "Radar types", search=["name"], readonly=True),
}
LABEL_COL = {"base": "code", "squadron": "number", "aircraft_type": "name", "aircraft": "tail_no",
             "aircrew": "service_no", "command": "code", "fuel_storage": "grade", "warehouse": "name",
             "stock_item": "nomenclature", "ad_system_type": "name", "radar_type": "name", "mission": "code",
             "sortie": "code", "comms_node": "code"}


def ent(name: str) -> Entity:
    if name not in ENTITIES:
        raise HTTPException(404, f"Unknown entity '{name}'")
    return ENTITIES[name]


def col_kind(col) -> dict:
    t = col.type
    if isinstance(t, Geometry):
        return {"type": "point" if t.geometry_type == "POINT" else "geometry"}
    if isinstance(t, Enum):
        return {"type": "enum", "values": list(t.enums)}
    if isinstance(t, Boolean):
        return {"type": "bool"}
    if isinstance(t, (Integer, BigInteger)):
        return {"type": "int"}
    if isinstance(t, Float):
        return {"type": "float"}
    if isinstance(t, DateTime):
        return {"type": "datetime"}
    if isinstance(t, Date):
        return {"type": "date"}
    if isinstance(t, ARRAY):
        return {"type": "list"}
    return {"type": "text"}


def columns(e: Entity) -> list[dict]:
    out = []
    for c in e.model.__table__.columns:
        if c.name in e.hidden:
            continue
        info = {"name": c.name, "nullable": c.nullable, **col_kind(c)}
        fks = list(c.foreign_keys)
        if fks:
            info["fk"] = fks[0].column.table.name
        info["editable"] = not e.readonly and c.name not in NEVER_EDIT and info["type"] != "geometry"
        out.append(info)
    return out


def row_dict(obj, e: Entity | None = None) -> dict:
    d = {}
    for c in obj.__table__.columns:
        if e and c.name in e.hidden:
            continue
        v = getattr(obj, c.name)
        if isinstance(c.type, Geometry):
            if v is not None and c.type.geometry_type == "POINT":
                p = to_shape(v)
                d["lat"], d["lon"] = round(p.y, 6), round(p.x, 6)
            continue
        d[c.name] = v
    d["simulated"] = bool(getattr(obj, "is_simulated", True))
    return d


def coerce(e: Entity, payload: dict, partial: bool) -> dict:
    """Validate + convert an incoming payload against column types. 422 with field messages on error."""
    cols = {c.name: c for c in e.model.__table__.columns}
    out, errors = {}, {}
    geom_col = next((c for c in cols.values() if isinstance(c.type, Geometry) and c.type.geometry_type == "POINT"), None)
    for k, v in payload.items():
        if k in ("version", "lat", "lon", "simulated"):
            continue
        c = cols.get(k)
        if c is None or k in NEVER_EDIT or k in e.hidden:
            errors[k] = "This field can't be set."
            continue
        if v in ("", None):
            if not c.nullable:
                errors[k] = "Required."
            else:
                out[k] = None
            continue
        try:
            t = c.type
            if isinstance(t, Enum):
                if v not in t.enums:
                    raise ValueError(f"Must be one of: {', '.join(t.enums)}")
                out[k] = v
            elif isinstance(t, Boolean):
                out[k] = v if isinstance(v, bool) else str(v).lower() in ("true", "1", "yes")
            elif isinstance(t, (Integer, BigInteger)):
                out[k] = int(v)
            elif isinstance(t, Float):
                out[k] = float(v)
            elif isinstance(t, DateTime):
                out[k] = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            elif isinstance(t, Date):
                out[k] = date.fromisoformat(str(v)[:10])
            elif isinstance(t, ARRAY):
                out[k] = v if isinstance(v, list) else [s.strip() for s in str(v).split(",") if s.strip()]
            elif isinstance(t, (String, Text)):
                out[k] = str(v).strip()
            else:
                out[k] = v
            if isinstance(out.get(k), (int, float)) and not isinstance(out[k], bool) and out[k] < 0 and \
                    not k.endswith("_deg"):
                raise ValueError("Can't be negative.")
        except (ValueError, TypeError) as ex:
            errors[k] = str(ex) if str(ex) else "Invalid value."
    if geom_col is not None and ("lat" in payload or "lon" in payload):
        try:
            lat, lon = float(payload["lat"]), float(payload["lon"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError
            out[geom_col.name] = from_shape(Point(lon, lat), srid=4326)
        except (KeyError, ValueError, TypeError):
            errors["lat"] = "Pick a location on the map (latitude and longitude)."
    if not partial:
        for name, c in cols.items():
            if name in NEVER_EDIT or c.nullable or c.default is not None or c.server_default is not None:
                continue
            if name not in out and not (geom_col is not None and name == geom_col.name and geom_col.name in out):
                errors.setdefault(name, "Required.")
    if errors:
        raise HTTPException(422, {"message": "Some fields need attention.", "fields": errors})
    return out


def scope_base(db: Session, e: Entity, values: dict, obj=None) -> int | None:
    if e.scope:
        return values.get(e.scope, getattr(obj, e.scope, None) if obj is not None else None)
    if e.parent:
        fk, parent_model, parent_scope = e.parent
        pid = values.get(fk, getattr(obj, fk, None) if obj is not None else None)
        parent = db.get(parent_model, pid) if pid else None
        return getattr(parent, parent_scope) if parent else None
    return None


def check_write(user: dict, e: Entity, base_id: int | None) -> None:
    if e.readonly:
        raise HTTPException(403, f"{e.label} are maintained by the system and can't be edited here.")
    if e.admin_only or (e.scope is None and e.parent is None):
        if user["role"] != "ADMIN":
            raise HTTPException(403, f"Only an admin can change {e.label.lower()}.")
        return
    assert_edit_base(user, base_id)


def domain_rules(db: Session, e: Entity, values: dict, obj=None) -> None:
    """FR-INV-09 rules that need more than column types."""
    m = e.model
    if m is M.Aircraft:
        if obj is not None and obj.status == "AIRBORNE" and values:
            raise HTTPException(409, "This aircraft is airborne. Edit it after it lands.")
        sq_id = values.get("squadron_id", getattr(obj, "squadron_id", None))
        t_id = values.get("aircraft_type_id", getattr(obj, "aircraft_type_id", None))
        sq = db.get(M.Squadron, sq_id) if sq_id else None
        if sq and t_id and sq.aircraft_type_id != t_id:
            raise HTTPException(422, {"message": "Aircraft type doesn't match the squadron's type.",
                                      "fields": {"aircraft_type_id": "Must match the squadron's aircraft type."}})
        if values.get("status") == "AIRBORNE":
            raise HTTPException(422, {"message": "Aircraft become airborne only through a sortie.",
                                      "fields": {"status": "Create a sortie instead."}})
    if m is M.FuelStorage:
        cap = values.get("capacity_l", getattr(obj, "capacity_l", None))
        cur = values.get("current_l", getattr(obj, "current_l", None))
        if cap is not None and cur is not None and cur > cap:
            raise HTTPException(422, {"message": f"Fuel can't exceed tank capacity ({cap:,.0f} L). Enter a lower amount.",
                                      "fields": {"current_l": f"Max {cap:,.0f} L"}})
    if e.scope and e.scope in values and values[e.scope] is not None:
        base = db.get(M.AirBase, values[e.scope])
        if not base or base.side != "OWN":
            raise HTTPException(422, {"message": "Inventory can only be held at IAF bases.",
                                      "fields": {e.scope: "Choose an IAF base."}})


def friendly_db_error(ex: Exception) -> HTTPException:
    msg = str(getattr(ex, "orig", ex))
    if "unique" in msg.lower():
        return HTTPException(409, "A record with this identifier already exists.")
    if "foreign key" in msg.lower():
        return HTTPException(409, "Other records still reference this one. Retire it instead.")
    if "fuel_level_within_capacity" in msg:
        return HTTPException(422, "Fuel can't exceed tank capacity.")
    if "OWN bases" in msg:
        return HTTPException(422, "Inventory can only be held at IAF bases.")
    return HTTPException(422, msg.splitlines()[0][:200])


def labels_for(db: Session, e: Entity, rows: list[dict]) -> dict:
    """{column: {id: label}} so tables can show codes instead of ids."""
    out = {}
    for c in e.model.__table__.columns:
        fks = list(c.foreign_keys)
        if not fks:
            continue
        table = fks[0].column.table
        lc = LABEL_COL.get(table.name)
        ids = {r[c.name] for r in rows if r.get(c.name) is not None}
        if not lc or not ids:
            continue
        res = db.execute(select(table.c.id, table.c[lc]).where(table.c.id.in_(ids)))
        out[c.name] = {str(i): lab for i, lab in res}
    return out


@router.get("/{entity}/meta")
def meta(entity: str, user: dict = Depends(current_user)):
    e = ent(entity)
    return {"entity": entity, "label": e.label, "columns": columns(e), "search": e.search,
            "readonly": e.readonly, "admin_only": e.admin_only, "scope": e.scope, "retire": bool(e.retire),
            "has_point": any(c["type"] == "point" for c in columns(e))}


@router.get("/{entity}")
def list_rows(entity: str, request: Request, page: int = 1, page_size: int = 50, sort: str = "id", order: str = "asc",
              q: str = "", command: str = "", user: dict = Depends(current_user), db: Session = Depends(get_db)):
    e = ent(entity)
    m = e.model
    cols = m.__table__.c
    stmt = select(m)
    for k, v in request.query_params.items():
        if k in cols and v != "":
            col = cols[k]
            vals = v.split(",")
            if isinstance(col.type, (Integer, BigInteger)):
                vals = [int(x) for x in vals]
            stmt = stmt.where(col.in_(vals))
    if q and e.search:
        stmt = stmt.where(or_(*[cols[s].ilike(f"%{q}%") for s in e.search]))
    if command and e.scope:
        stmt = stmt.where(cols[e.scope].in_(
            select(M.AirBase.id).join(M.Command, M.Command.id == M.AirBase.command_id).where(M.Command.code == command)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    sort_col = cols[sort] if sort in cols else cols["id"]
    stmt = stmt.order_by(sort_col.desc() if order == "desc" else sort_col.asc(), cols["id"].asc())
    page_size = max(1, min(page_size, 500))
    items = [row_dict(o, e) for o in db.scalars(stmt.offset((max(page, 1) - 1) * page_size).limit(page_size))]
    return {"items": items, "total": total, "page": page, "page_size": page_size, "labels": labels_for(db, e, items)}


@router.get("/{entity}/{row_id}")
def get_row(entity: str, row_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    e = ent(entity)
    obj = db.get(e.model, row_id)
    if not obj:
        raise HTTPException(404, "Not found")
    d = row_dict(obj, e)
    return {**d, "labels": labels_for(db, e, [d])}


@router.post("/{entity}", status_code=201)
def create(entity: str, payload: dict, request: Request, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    e = ent(entity)
    values = coerce(e, payload, partial=False)
    base_id = scope_base(db, e, values)
    check_write(user, e, base_id)
    domain_rules(db, e, values)
    obj = e.model(**values)
    if hasattr(obj, "is_simulated"):
        obj.is_simulated, obj.source = True, "SYNTHETIC"
    db.add(obj)
    try:
        db.flush()
        audit(db, user, "CREATE", e.model.__tablename__, obj.id, base_id, None, row_dict(obj),
              request_id=request.state.request_id)
        db.commit()
    except (IntegrityError, DBAPIError) as ex:
        db.rollback()
        raise friendly_db_error(ex)
    return row_dict(obj, e)


@router.patch("/{entity}/{row_id}")
def update(entity: str, row_id: int, payload: dict, request: Request, user: dict = Depends(current_user),
           db: Session = Depends(get_db)):
    e = ent(entity)
    obj = db.get(e.model, row_id, with_for_update=True)
    if not obj:
        raise HTTPException(404, "Not found")
    if "version" not in payload:
        raise HTTPException(422, "Include the record's version to save changes.")
    if int(payload["version"]) != obj.version:
        raise HTTPException(409, {"message": "This record was changed by the simulator or another user. Reload it.",
                                  "current": row_dict(obj, e)})
    values = coerce(e, payload, partial=True)
    old_base = scope_base(db, e, {}, obj)
    check_write(user, e, old_base)
    if e.scope and e.scope in values:
        check_write(user, e, values[e.scope])
    domain_rules(db, e, values, obj)
    before = row_dict(obj)
    for k, v in values.items():
        setattr(obj, k, v)
    obj.version += 1
    try:
        db.flush()
        audit(db, user, "UPDATE", e.model.__tablename__, obj.id, old_base, before, row_dict(obj),
              request_id=request.state.request_id)
        db.commit()
    except (IntegrityError, DBAPIError) as ex:
        db.rollback()
        raise friendly_db_error(ex)
    return row_dict(obj, e)


@router.post("/{entity}/{row_id}/retire")
def retire(entity: str, row_id: int, request: Request, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    e = ent(entity)
    if not e.retire:
        raise HTTPException(400, f"{e.label} can't be retired; delete instead.")
    obj = db.get(e.model, row_id, with_for_update=True)
    if not obj:
        raise HTTPException(404, "Not found")
    base_id = scope_base(db, e, {}, obj)
    check_write(user, e, base_id)
    if e.model is M.Aircraft and obj.status == "AIRBORNE":
        raise HTTPException(409, "This aircraft is airborne. Retire it after it lands.")
    before = row_dict(obj)
    setattr(obj, e.retire[0], e.retire[1])
    obj.version += 1
    audit(db, user, "RETIRE", e.model.__tablename__, obj.id, base_id, before, row_dict(obj),
          request_id=request.state.request_id)
    db.commit()
    return row_dict(obj, e)


@router.delete("/{entity}/{row_id}")
def delete(entity: str, row_id: int, request: Request, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    e = ent(entity)
    obj = db.get(e.model, row_id)
    if not obj:
        raise HTTPException(404, "Not found")
    base_id = scope_base(db, e, {}, obj)
    check_write(user, e, base_id)
    before = row_dict(obj)
    try:
        db.delete(obj)
        db.flush()
        audit(db, user, "DELETE", e.model.__tablename__, row_id, base_id, before, None,
              request_id=request.state.request_id)
        db.commit()
    except (IntegrityError, DBAPIError) as ex:
        db.rollback()
        raise friendly_db_error(ex)
    return {"ok": True}
