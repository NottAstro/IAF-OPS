"""Static GIS layers for the map (FR-MAP-04..07, 13). Compact JSON, coordinates rounded to ~11 m."""
import json

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import config
from ..auth import current_user
from ..db import get_db

router = APIRouter(prefix="/gis", tags=["gis"])
BUCKET_COL = {"lo": "geom_lo", "mid": "geom_mid", "hi": "geom"}


def bbox_args(bbox: str):
    if not bbox:
        return config.BBOX
    try:
        w, s, e, n = (float(x) for x in bbox.split(","))
    except ValueError:
        raise HTTPException(422, "bbox must be w,s,e,n")
    return w, s, e, n


def cached(payload) -> Response:
    return Response(json.dumps(payload, separators=(",", ":")), media_type="application/json",
                    headers={"Cache-Control": "private, max-age=3600"})


MVT_SQL = """
WITH t AS (SELECT ST_TileEnvelope(:z, :x, :y) AS env, ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326) AS env4326),
admin AS (
  SELECT a.level, a.country_iso3 AS country, a.name,
         -- drop the straight edges the pipeline's region clip left on neighbour polygons (they are not borders)
         ST_AsMVTGeom(ST_Transform(ST_ClipByBox2D(ST_Boundary(CASE WHEN :z < 5 THEN a.geom_lo WHEN :z < 8 THEN a.geom_mid ELSE a.geom END),
                                                  ST_MakeEnvelope(:w + 0.01, :s + 0.01, :e - 0.01, :n - 0.01, 4326)::box2d), 3857),
                      t.env, 4096, 64, true) AS geom
  FROM gis_admin_area a, t
  WHERE (CASE WHEN :z < 5 THEN a.geom_lo WHEN :z < 8 THEN a.geom_mid ELSE a.geom END) && t.env4326
    AND (a.level = 'ADM0' OR (a.level = 'ADM1' AND :z >= 3) OR (a.level = 'ADM2' AND :z >= 6))
),
label AS (
  SELECT a.level, a.country_iso3 AS country, a.name, round(a.area_km2) AS area_km2,
         ST_AsMVTGeom(ST_Transform(a.label_pt, 3857), t.env, 4096, 64, true) AS geom
  FROM gis_admin_area a, t
  WHERE a.label_pt && t.env4326
    AND (a.level = 'ADM0' OR (a.level = 'ADM1' AND :z >= 4) OR (a.level = 'ADM2' AND :z >= 6))
),
place AS (
  SELECT p.name, p.population AS pop, p.kind, ST_AsMVTGeom(ST_Transform(p.geom, 3857), t.env, 4096, 64, true) AS geom
  FROM gis_place p, t
  WHERE p.geom && t.env4326
    AND (p.population >= CASE WHEN :z < 4 THEN 3000000 WHEN :z < 5 THEN 1000000 WHEN :z < 6 THEN 300000
                              WHEN :z < 7 THEN 100000 WHEN :z < 8 THEN 30000 WHEN :z < 9 THEN 8000 ELSE 0 END
         OR p.kind = 'PPLC' OR (p.kind = 'PPLA' AND :z >= 5))
),
station AS (
  SELECT p.id, p.name, p.rank, ST_AsMVTGeom(ST_Transform(p.geom, 3857), t.env, 4096, 64, true) AS geom
  FROM gis_point p, t
  WHERE p.kind = 'RAIL_STATION' AND p.geom && t.env4326 AND p.name IS NOT NULL
    AND ((p.rank = 0 AND :z >= 5) OR (p.rank = 1 AND :z >= 8) OR :z >= 10)
),
hwy_lo AS (  -- national highways / expressways for far zoom (the basemap only carries them from ~z7)
  SELECT l.ref, ST_AsMVTGeom(ST_Transform(ST_Simplify(l.geom, CASE WHEN :z < 5 THEN 0.05 WHEN :z < 6 THEN 0.025 ELSE 0.01 END), 3857),
                              t.env, 4096, 16, true) AS geom
  FROM gis_line_lo l, t
  WHERE :z >= 4 AND l.kind IN ('MOTORWAY', 'TRUNK') AND l.geom && t.env4326 AND (:z >= 6 OR (l.ref IS NOT NULL AND ST_Length(l.geom) > 0.2))
),
rail_lo AS (
  SELECT ST_AsMVTGeom(ST_Transform(ST_Simplify(l.geom, CASE WHEN :z < 5 THEN 0.05 WHEN :z < 6 THEN 0.025 ELSE 0.01 END), 3857),
                       t.env, 4096, 16, true) AS geom
  FROM gis_line_lo l, t
  WHERE :z >= 4 AND l.kind = 'RAIL' AND l.geom && t.env4326 AND (:z >= 6 OR ST_Length(l.geom) > 0.3)
),
tower AS (
  SELECT p.id, p.name, p.operator, p.height_m, ST_AsMVTGeom(ST_Transform(p.geom, 3857), t.env, 4096, 64, true) AS geom
  FROM gis_point p, t WHERE :z >= 8 AND p.kind = 'TELECOM_TOWER' AND p.geom && t.env4326
),
airport AS (
  SELECT c.id, c.ident, c.icao, c.iata, c.name, c.type, ST_AsMVTGeom(ST_Transform(c.geom, 3857), t.env, 4096, 64, true) AS geom
  FROM civil_airport c, t
  WHERE c.geom && t.env4326 AND (c.type = 'large_airport' OR (c.type = 'medium_airport' AND :z >= 5)
                                 OR (c.type IN ('small_airport', 'heliport') AND :z >= 8))
)
SELECT (SELECT coalesce(ST_AsMVT(admin.*, 'admin', 4096, 'geom'), '') FROM admin WHERE geom IS NOT NULL)
    || (SELECT coalesce(ST_AsMVT(label.*, 'admin_label', 4096, 'geom'), '') FROM label WHERE geom IS NOT NULL)
    || (SELECT coalesce(ST_AsMVT(place.*, 'place', 4096, 'geom'), '') FROM place WHERE geom IS NOT NULL)
    || (SELECT coalesce(ST_AsMVT(station.*, 'station', 4096, 'geom'), '') FROM station WHERE geom IS NOT NULL)
    || (SELECT coalesce(ST_AsMVT(hwy_lo.*, 'hwy_lo', 4096, 'geom'), '') FROM hwy_lo WHERE geom IS NOT NULL)
    || (SELECT coalesce(ST_AsMVT(rail_lo.*, 'rail_lo', 4096, 'geom'), '') FROM rail_lo WHERE geom IS NOT NULL)
    || (SELECT coalesce(ST_AsMVT(tower.*, 'tower', 4096, 'geom'), '') FROM tower WHERE geom IS NOT NULL)
    || (SELECT coalesce(ST_AsMVT(airport.*, 'airport', 4096, 'geom'), '') FROM airport WHERE geom IS NOT NULL)
"""
_tiles: dict[tuple[int, int, int, bool], bytes] = {}  # ponytail: unbounded-but-small in-process cache (static data)
# gis_line_lo only exists after `make osm`; without it the whole tile query would fail and take the boundaries with it
NO_LINE_LO = "(SELECT NULL::text AS kind, NULL::text AS ref, NULL::geometry AS geom WHERE false)"


def has_line_lo(db: Session) -> bool:
    return bool(db.execute(text("SELECT to_regclass('gis_line_lo') IS NOT NULL")).scalar())


def mvt_sql(has_lo: bool) -> str:
    return MVT_SQL if has_lo else MVT_SQL.replace("FROM gis_line_lo l", f"FROM {NO_LINE_LO} l")


@router.get("/tiles/{z}/{x}/{y}.pbf")
def tiles(z: int, x: int, y: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    """Vector tiles (MVT) for GoI-depicted boundaries, admin + place labels, telecom towers, civil airports (FR-MAP-04..07).
    All boundaries and names on the map come from here; the OpenFreeMap basemap supplies only terrain features."""
    if not (0 <= z <= 14 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise HTTPException(404, "tile out of range")
    key = (z, x, y, has_line_lo(db))  # tiles cached before `make osm` are rebuilt once the road table appears
    if key not in _tiles:
        w, s, e, n = config.BBOX
        _tiles[key] = bytes(db.execute(text(mvt_sql(key[3])), {"z": z, "x": x, "y": y, "w": w, "s": s, "e": e, "n": n}).scalar() or b"")
    return Response(_tiles[key], media_type="application/x-protobuf", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/admin")
def admin(level: str = "ADM0", bucket: str = "lo", bbox: str = "", country: str = "", user: dict = Depends(current_user),
          db: Session = Depends(get_db)):
    """Boundary lines + label points. ADM0 India first (drawn in amber), then neighbours."""
    if level not in ("ADM0", "ADM1", "ADM2") or bucket not in BUCKET_COL:
        raise HTTPException(422, "bad level/bucket")
    w, s, e, n = bbox_args(bbox)
    col = BUCKET_COL[bucket]
    where = "level = :level AND {col} && ST_MakeEnvelope(:w,:s,:e,:n,4326)".format(col=col)
    p = {"level": level, "w": w, "s": s, "e": e, "n": n}
    if country:
        where += " AND country_iso3 = :c"
        p["c"] = country
    res = db.execute(text(f"""
        SELECT name, country_iso3, parent_name, ST_AsGeoJSON(ST_Boundary({col}), 4)::json -> 'coordinates' AS lines,
               ST_X(label_pt) AS lon, ST_Y(label_pt) AS lat, ST_Area({col}::geography) / 1e6 AS area_km2
        FROM gis_admin_area WHERE {where}"""), p)
    feats = []
    for r in res:
        coords = r.lines or []
        if coords and isinstance(coords[0][0], (int, float)):  # LineString -> wrap as multi
            coords = [coords]
        feats.append({"name": r.name, "country": r.country_iso3, "parent": r.parent_name, "lines": coords,
                      "label": [round(r.lon, 4), round(r.lat, 4)], "area_km2": round(r.area_km2 or 0)})
    return cached({"level": level, "features": feats})


@router.get("/places")
def places(bbox: str = "", min_pop: int = 0, limit: int = 300, user: dict = Depends(current_user),
           db: Session = Depends(get_db)):
    w, s, e, n = bbox_args(bbox)
    res = db.execute(text("""SELECT name, population, kind, country_code, ST_X(geom) lon, ST_Y(geom) lat FROM gis_place
                             WHERE geom && ST_MakeEnvelope(:w,:s,:e,:n,4326) AND population >= :mp
                             ORDER BY population DESC LIMIT :lim"""),
                     {"w": w, "s": s, "e": e, "n": n, "mp": min_pop, "lim": min(limit, 1500)})
    return cached([{"name": r.name, "pop": r.population, "kind": r.kind, "cc": r.country_code,
                    "lon": round(r.lon, 4), "lat": round(r.lat, 4)} for r in res])


@router.get("/lines")
def lines(kind: str = "ROAD", detail: str = "lo", bbox: str = "", user: dict = Depends(current_user),
          db: Session = Depends(get_db)):
    """Roads / rail. detail=lo: merged motorway+trunk (+rail) for the whole view; hi: segments in bbox (capped)."""
    w, s, e, n = bbox_args(bbox)
    kinds = ["RAIL"] if kind == "RAIL" else (["MOTORWAY", "TRUNK"] if detail == "lo" else ["MOTORWAY", "TRUNK", "PRIMARY"])
    p = {"w": w, "s": s, "e": e, "n": n, "kinds": kinds}
    exists = db.execute(text("SELECT to_regclass('gis_line_lo') IS NOT NULL")).scalar()
    if detail == "lo" and exists:
        sql = """SELECT kind, ref AS name, ST_AsGeoJSON(geom, 3)::json -> 'coordinates' AS c FROM gis_line_lo
                 WHERE kind = ANY(:kinds) AND geom && ST_MakeEnvelope(:w,:s,:e,:n,4326) LIMIT 20000"""
    else:
        sql = """SELECT kind, coalesce(ref, name) AS name, ST_AsGeoJSON(geom_simplified, 4)::json -> 'coordinates' AS c
                 FROM gis_line WHERE kind = ANY(:kinds) AND geom && ST_MakeEnvelope(:w,:s,:e,:n,4326) LIMIT 25000"""
    return cached([{"k": r.kind, "n": r.name, "c": r.c} for r in db.execute(text(sql), p) if r.c])


@router.get("/towers")
def towers(bbox: str = "", user: dict = Depends(current_user), db: Session = Depends(get_db)):
    w, s, e, n = bbox_args(bbox)
    res = db.execute(text("""SELECT id, name, operator, height_m, ST_X(geom) lon, ST_Y(geom) lat FROM gis_point
                             WHERE kind = 'TELECOM_TOWER' AND geom && ST_MakeEnvelope(:w,:s,:e,:n,4326) LIMIT 4000"""),
                     {"w": w, "s": s, "e": e, "n": n})
    return cached([{"id": r.id, "name": r.name, "operator": r.operator, "height_m": r.height_m,
                    "lon": round(r.lon, 5), "lat": round(r.lat, 5)} for r in res])


@router.get("/civil-airports")
def civil_airports(bbox: str = "", types: str = "large_airport,medium_airport", user: dict = Depends(current_user),
                   db: Session = Depends(get_db)):
    w, s, e, n = bbox_args(bbox)
    res = db.execute(text("""SELECT id, ident, icao, iata, name, type, country_iso2, elevation_m, ST_X(geom) lon, ST_Y(geom) lat
                             FROM civil_airport WHERE type = ANY(:t) AND geom && ST_MakeEnvelope(:w,:s,:e,:n,4326) LIMIT 3000"""),
                     {"w": w, "s": s, "e": e, "n": n, "t": types.split(",")})
    return cached([dict(r._mapping) for r in res])
