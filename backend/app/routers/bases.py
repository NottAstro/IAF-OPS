"""Map + side-panel data: bases, live base status, base summary, public cards, defence sites (FR-BASE, FR-MAP-13..15)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..weather import metar as metar_mod
from ..services import connectivity as connections

router = APIRouter(tags=["bases"])


@router.get("/bases/{base_id}/connections")
def base_connections(base_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    result = connections.nearby_connections(db, base_id)
    if result is None:
        raise HTTPException(404, "Select an existing IAF base.")
    return result


@router.get("/bases/{base_id}/connections/{destination_id}")
async def base_connection(base_id: int, destination_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    result = await connections.connection(db, base_id, destination_id)
    if result is None:
        raise HTTPException(404, "Select an existing nearby IAF base.")
    return result


def rows(db: Session, sql: str, **params) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(sql), params)]


@router.get("/bases")
def list_bases(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return rows(db, """
        SELECT b.id, b.code, b.name, b.side, b.operator, b.base_type, b.country_iso3, b.affiliation, b.role_tags,
               b.wing, b.ops_status, b.elevation_m, c.code AS command, ST_Y(b.geom) AS lat, ST_X(b.geom) AS lon,
               b.metar_station, b.metar_station_km
        FROM base b LEFT JOIN command c ON c.id = b.command_id ORDER BY b.side, b.code""")


@router.get("/bases/status")
def base_status(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    """Per-base dynamic status for map symbols: serviceability, QRA, worst open alert, airborne."""
    status = {r["base_id"]: r for r in rows(db, """
        SELECT base_id, sum(total)::int AS total, sum(serviceable)::int AS serviceable, sum(effective)::int AS effective,
               sum(airborne)::int AS airborne FROM v_aircraft_serviceability GROUP BY base_id""")}
    for r in rows(db, "SELECT base_id, bool_and(met) AS qra_met, sum(required_aircraft)::int AS qra_required, "
                      "sum(qra_aircraft)::int AS qra_aircraft FROM v_qra_status GROUP BY base_id"):
        status.setdefault(r["base_id"], {"base_id": r["base_id"]}).update(r)
    sev = {"INFO": 0, "CAUTION": 1, "WARNING": 2, "CRITICAL": 3}
    for r in rows(db, "SELECT base_id, severity, count(*) AS n FROM alert WHERE status <> 'CLEARED' AND base_id IS NOT NULL "
                      "GROUP BY base_id, severity"):
        s = status.setdefault(r["base_id"], {"base_id": r["base_id"]})
        if sev[r["severity"]] >= sev.get(s.get("alert_severity", "INFO"), 0):
            s["alert_severity"] = r["severity"]
        s["alerts"] = s.get("alerts", 0) + r["n"]
    for s in status.values():
        eff = s.get("effective") or 0
        s["serviceability"] = round(100 * s.get("serviceable", 0) / eff) if eff else None
    return list(status.values())


@router.get("/bases/{base_id}/summary")
def summary(base_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    head = rows(db, """SELECT b.*, ST_Y(b.geom) AS lat, ST_X(b.geom) AS lon, c.code AS command, c.name AS command_name
                       FROM base b LEFT JOIN command c ON c.id = b.command_id WHERE b.id = :id""", id=base_id)
    if not head:
        raise HTTPException(404, "Base not found")
    base = head[0]
    base.pop("geom", None)
    if base["side"] != "OWN":
        raise HTTPException(409, "Inventory is held only for IAF bases; use /bases/{id}/public.")
    p = {"id": base_id}
    aircraft = rows(db, """
        SELECT a.id, a.tail_no, a.status, a.readiness_min, a.airframe_hours, a.next_maint_due_hours, a.fuel_kg,
               a.maint_eta, a.version, a.home_base_id, a.current_base_id, cb.code AS current_base, hb.code AS home_base,
               t.name AS type, t.category, t.role, t.max_fuel_kg, s.number AS squadron
        FROM aircraft a JOIN aircraft_type t ON t.id = a.aircraft_type_id JOIN squadron s ON s.id = a.squadron_id
        LEFT JOIN base cb ON cb.id = a.current_base_id JOIN base hb ON hb.id = a.home_base_id
        WHERE (a.home_base_id = :id OR a.current_base_id = :id) AND a.status <> 'RETIRED'
        ORDER BY t.category, t.name, a.tail_no""", **p)
    crew = rows(db, """
        SELECT c.id, c.rank, c.first_name, c.last_name, c.callsign, c.aircrew_role, c.stream, c.duty_status,
               c.medical_status, c.ops_category, c.appointment, c.total_hours, s.number AS squadron,
               coalesce(v.available, false) AS available, coalesce(f.fatigued, false) AS fatigued,
               f.hours_24h, f.hours_7d,
               (SELECT min(cur.currency) FILTER (WHERE cur.currency = 'LAPSED') FROM v_aircrew_currency cur WHERE cur.aircrew_id = c.id) AS lapsed,
               (SELECT bool_or(cur.currency = 'LAPSING') FROM v_aircrew_currency cur WHERE cur.aircrew_id = c.id) AS lapsing
        FROM aircrew c LEFT JOIN squadron s ON s.id = c.squadron_id
        LEFT JOIN v_aircrew_availability v ON v.aircrew_id = c.id LEFT JOIN v_aircrew_fatigue f ON f.aircrew_id = c.id
        WHERE c.base_id = :id ORDER BY c.aircrew_role, c.rank DESC, c.last_name""", **p)
    return {
        "base": base,
        "aircraft": aircraft,
        "parking": rows(db, "SELECT slot_size, slots_total::int, slots_us::int, occupied::int FROM v_parking_occupancy "
                            "WHERE base_id = :id ORDER BY slot_size", **p),
        "facilities": rows(db, "SELECT kind, slot_size, slots_total, slots_unserviceable FROM parking_facility WHERE base_id = :id", **p),
        "qra": rows(db, """SELECT q.*, t.name AS type FROM v_qra_status q JOIN aircraft_type t ON t.id = q.aircraft_type_id
                           WHERE q.base_id = :id""", **p),
        "crew": crew,
        "ground_crew": rows(db, """SELECT trade, sum(authorised)::int AS authorised, sum(held)::int AS held,
                                   sum(on_duty)::int AS on_duty, sum(standby)::int AS standby, sum(on_leave)::int AS on_leave
                                   FROM ground_crew_strength WHERE base_id = :id GROUP BY trade ORDER BY trade""", **p),
        "ground_assets": rows(db, """SELECT asset_class, asset_type, count(*)::int AS total,
                                     count(*) FILTER (WHERE status = 'SERVICEABLE')::int AS serviceable
                                     FROM ground_asset WHERE base_id = :id GROUP BY 1, 2 ORDER BY 1, 2""", **p),
        "ground_items": rows(db, """SELECT id, asset_class, asset_type, reg_or_serial, status, capacity_l, last_service_date, version
                                    FROM ground_asset WHERE base_id = :id ORDER BY asset_type, reg_or_serial""", **p),
        "air_defence": rows(db, """
            SELECT d.id, d.code, d.status, d.readiness_min, d.launchers_total, d.launchers_ready, d.version,
                   t.name AS system, t.category, t.max_range_km, ST_Y(d.geom) AS lat, ST_X(d.geom) AS lon,
                   round((ST_Distance(d.geom::geography, b.geom::geography) / 1000)::numeric, 1) AS distance_km
            FROM air_defence_battery d JOIN ad_system_type t ON t.id = d.ad_system_type_id, base b
            WHERE b.id = :id AND (d.protected_base_id = :id OR ST_DWithin(d.geom::geography, b.geom::geography, 30000))
            ORDER BY t.max_range_km DESC""", **p),
        "radars": rows(db, """
            SELECT r.id, r.code, r.status, r.version, t.name AS type, t.category, t.max_range_km,
                   ST_Y(r.geom) AS lat, ST_X(r.geom) AS lon,
                   round((ST_Distance(r.geom::geography, b.geom::geography) / 1000)::numeric, 1) AS distance_km
            FROM radar_site r JOIN radar_type t ON t.id = r.radar_type_id, base b
            WHERE b.id = :id AND r.base_id = :id ORDER BY t.max_range_km DESC""", **p),
        "comms": rows(db, "SELECT id, code, node_type, status FROM comms_node WHERE base_id = :id ORDER BY node_type", **p),
        "fuel": rows(db, """SELECT f.id, f.grade, f.kind, f.capacity_l, f.current_l, f.reserve_l, f.reorder_l, f.tank_count,
                            f.replenish_eta, f.version, d.days_of_supply, d.daily_issue_l
                            FROM fuel_storage f LEFT JOIN v_fuel_days d ON d.fuel_storage_id = f.id
                            WHERE f.base_id = :id ORDER BY f.grade""", **p),
        "fuel_transactions": rows(db, """SELECT t.ts, t.kind, t.quantity_l, t.balance_after_l, t.actor, f.grade
                                         FROM fuel_transaction t JOIN fuel_storage f ON f.id = t.fuel_storage_id
                                         WHERE f.base_id = :id ORDER BY t.ts DESC LIMIT 10""", **p),
        "runways": rows(db, "SELECT id, designator, length_m, width_m, surface, lighted, status, version FROM runway "
                            "WHERE base_id = :id ORDER BY length_m DESC NULLS LAST", **p),
        "nearby_algs": rows(db, """
            SELECT a.id, a.code, a.name, round((ST_Distance(a.geom::geography, b.geom::geography) / 1000)::numeric) AS distance_km
            FROM base a, base b WHERE b.id = :id AND a.base_type = 'ALG' AND ST_DWithin(a.geom::geography, b.geom::geography, 300000)
            ORDER BY 4""", **p),
        "warehouses": rows(db, """
            SELECT w.id, w.name, w.kind, w.capacity_m3, w.utilisation_pct, w.status,
                   count(l.id) FILTER (WHERE l.qty_on_hand < l.reorder_level)::int AS below_reorder, count(l.id)::int AS items
            FROM warehouse w LEFT JOIN stock_level l ON l.warehouse_id = w.id WHERE w.base_id = :id GROUP BY w.id ORDER BY w.kind""", **p),
        "armament": rows(db, """
            SELECT i.category, i.nomenclature, i.unit, sum(l.qty_on_hand)::int AS on_hand, sum(l.reorder_level)::int AS reorder
            FROM stock_level l JOIN stock_item i ON i.id = l.stock_item_id JOIN warehouse w ON w.id = l.warehouse_id
            WHERE w.base_id = :id AND i.category LIKE 'ARMAMENT%' GROUP BY 1, 2, 3 ORDER BY 1""", **p),
        "low_stock": rows(db, """
            SELECT i.nomenclature, i.category, l.qty_on_hand, l.reorder_level, w.name AS warehouse
            FROM stock_level l JOIN stock_item i ON i.id = l.stock_item_id JOIN warehouse w ON w.id = l.warehouse_id
            WHERE w.base_id = :id AND l.qty_on_hand < l.reorder_level ORDER BY l.qty_on_hand / nullif(l.reorder_level, 0) LIMIT 12""", **p),
        "sorties": rows(db, """
            SELECT s.id, s.code, s.mission_type, s.priority, s.status, s.origin, s.planned_launch_ts, s.actual_launch_ts,
                   s.planned_recovery_ts, d.code AS departure, r.code AS recovery,
                   (SELECT string_agg(a.tail_no, ', ') FROM sortie_aircraft sa JOIN aircraft a ON a.id = sa.aircraft_id
                    WHERE sa.sortie_id = s.id) AS aircraft,
                   (SELECT string_agg(sa.callsign, ', ') FROM sortie_aircraft sa WHERE sa.sortie_id = s.id) AS callsign
            FROM sortie s JOIN base d ON d.id = s.departure_base_id JOIN base r ON r.id = s.recovery_base_id
            WHERE (s.departure_base_id = :id OR s.recovery_base_id = :id)
              AND (s.status IN ('CREWED','READY','AIRBORNE','ON_STATION','RTB')
                   OR (s.status = 'PLANNED' AND s.planned_launch_ts < sim_now() + interval '12 hours'))
            ORDER BY s.status = 'PLANNED', s.planned_launch_ts LIMIT 30""", **p),
        "alerts": rows(db, "SELECT id, kind, severity, status, message, raised_at FROM alert WHERE base_id = :id "
                           "AND status <> 'CLEARED' ORDER BY raised_at DESC LIMIT 20", **p),
        "weather": metar_mod.for_base(base),
        "connectivity": connectivity(db, base_id),
    }


def connectivity(db: Session, base_id: int) -> dict:
    """Nearest railheads, civil airports, national highways and IAF bases, by straight-line distance (Infra view).
    ponytail: KNN on lon/lat picks candidates, geography distance orders them; no road-network routing (Phase 2)."""
    # the KNN index needs a constant on the right of <->, hence the scalar subquery rather than a join
    here = "(SELECT geom FROM base WHERE id = :id)"
    knn = """SELECT * FROM (SELECT {cols}, ST_Y(x.geom) AS lat, ST_X(x.geom) AS lon,
                                   round((ST_Distance(x.geom::geography, %s::geography) / 1000)::numeric, 1) AS distance_km
                            FROM {src} x WHERE {where} ORDER BY x.geom <-> %s LIMIT {k}) t ORDER BY distance_km LIMIT {n}""" % (here, here)
    q = lambda **kw: rows(db, knn.format(**kw), id=base_id)  # noqa: E731
    roads = rows(db, f"""WITH near AS (SELECT l.ref, ST_Distance(l.geom::geography, {here}::geography) AS d FROM gis_line l
                                  WHERE l.kind IN ('MOTORWAY', 'TRUNK') AND l.ref IS NOT NULL ORDER BY l.geom <-> {here} LIMIT 80)
                         SELECT ref, round((min(d) / 1000)::numeric, 1) AS distance_km FROM near GROUP BY ref ORDER BY 2 LIMIT 3""",
                 id=base_id)
    return {
        "rail": q(cols="x.name, x.rank", src="gis_point", where="x.kind = 'RAIL_STATION' AND x.name IS NOT NULL", k=12, n=3),
        "rail_major": q(cols="x.name, x.rank", src="gis_point", where="x.kind = 'RAIL_STATION' AND x.rank = 0", k=4, n=1),
        "airports": q(cols="x.name, x.icao, x.iata, x.type", src="civil_airport",
                      where="x.type IN ('large_airport', 'medium_airport')", k=8, n=3),
        "highways": roads,
        "bases": connections.nearby_bases(db, base_id),
    }


@router.get("/bases/{base_id}/public")
def public_card(base_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    head = rows(db, """SELECT b.id, b.code, b.name, b.side, b.operator, b.base_type, b.country_iso3, b.affiliation,
                              b.public_notes, b.elevation_m, b.source_ref, ST_Y(b.geom) AS lat, ST_X(b.geom) AS lon
                       FROM base b WHERE b.id = :id""", id=base_id)
    if not head:
        raise HTTPException(404, "Base not found")
    return {**head[0], "runways": rows(db, "SELECT designator, length_m, width_m, surface FROM runway WHERE base_id = :id",
                                       id=base_id),
            "note": "Public information only — no inventory held."}


@router.get("/sites/{kind}")
def sites(kind: str, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    if kind == "ad":
        return rows(db, """SELECT d.id, d.code, d.status, d.launchers_ready, d.launchers_total, t.name AS system, t.category,
                                  t.max_range_km, ST_Y(d.geom) AS lat, ST_X(d.geom) AS lon, b.code AS base
                           FROM air_defence_battery d JOIN ad_system_type t ON t.id = d.ad_system_type_id
                           LEFT JOIN base b ON b.id = d.protected_base_id""")
    if kind == "radars":
        return rows(db, """SELECT r.id, r.code, r.status, t.name AS type, t.category, t.max_range_km,
                                  ST_Y(r.geom) AS lat, ST_X(r.geom) AS lon, b.code AS base
                           FROM radar_site r JOIN radar_type t ON t.id = r.radar_type_id LEFT JOIN base b ON b.id = r.base_id""")
    if kind == "comms":
        return rows(db, """SELECT n.id, n.code, n.node_type, n.status, ST_Y(n.geom) AS lat, ST_X(n.geom) AS lon, b.code AS base
                           FROM comms_node n LEFT JOIN base b ON b.id = n.base_id""")
    if kind == "comms-links":
        return rows(db, """SELECT l.id, l.medium, l.status, ST_Y(a.geom) AS lat_a, ST_X(a.geom) AS lon_a,
                                  ST_Y(b.geom) AS lat_b, ST_X(b.geom) AS lon_b
                           FROM comms_link l JOIN comms_node a ON a.id = l.node_a_id JOIN comms_node b ON b.id = l.node_b_id""")
    raise HTTPException(404, "Unknown site kind")
