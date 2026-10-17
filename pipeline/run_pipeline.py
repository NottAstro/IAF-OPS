"""Static GIS pipeline (ARCHITECTURE §9): boundaries, places, civil airports -> PostGIS gis_* tables.

Idempotent. Downloads go to data/raw/gis (skipped if present). Uses gdal (ogr2ogr) when it is on PATH, otherwise a
pure-Python loader (pyshp + shapely), so Windows needs no GDAL install.
OSM roads/rail/towers are a separate, heavier step: pipeline/osm.py.
Run: .venv/bin/python pipeline/run_pipeline.py
"""
import csv
import io
import json
import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

import psycopg
import truststore
from dotenv import load_dotenv

truststore.inject_into_ssl()  # use the macOS trust store (python.org builds ship none; campus TLS inspection CA lives there)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "gis"
load_dotenv(ROOT / ".env")
DSN = os.environ.get("DATABASE_URL", "postgresql+psycopg://airops:airops@localhost:5432/airops").replace("+psycopg", "")
PG_OGR = "PG:" + " ".join(f"{k}={v}" for k, v in psycopg.conninfo.conninfo_to_dict(DSN).items())
REGION = json.loads((ROOT / "shared" / "region.json").read_text())
W, S, E, N = REGION["west"], REGION["south"], REGION["east"], REGION["north"]
NEIGHBOURS = ["PAK", "CHN", "NPL", "BTN", "BGD", "MMR", "LKA", "AFG"]  # get ADM1/ADM2; others in the bbox ADM0 only
UA = {"User-Agent": "iaf-airops-pipeline/0.1"}

DATAMEET = "https://raw.githubusercontent.com/datameet/maps/master"
DOWNLOADS = {
    "india-soi.geojson": f"{DATAMEET}/Country/india-soi.geojson",
    **{f"states.{e}": f"{DATAMEET}/States/Admin2.{e}" for e in ("shp", "shx", "dbf", "prj")},
    **{f"districts.{e}": f"{DATAMEET}/Districts/Census_2011/2011_Dist.{e}" for e in ("shp", "shx", "dbf", "prj")},
    "ne_10m_admin_0_countries_ind.geojson":
        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries_ind.geojson",
    "cities1000.zip": "https://download.geonames.org/export/dump/cities1000.zip",
    # de facto control, PLANNING ONLY (never rendered): keeps plan routes on the Indian side of the LoC / LAC
    "ne_10m_admin_0_countries.geojson":
        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson",
}
# OurAirports (public domain): civil airports here, runway geometry in the generator. Saved to data/raw/.
OURAIRPORTS = {name: f"https://davidmegginson.github.io/ourairports-data/{name}" for name in ("airports.csv", "runways.csv")}


def fetch(name: str, url: str) -> Path:
    path = RAW / name
    if not path.exists() or path.stat().st_size == 0:
        print("  download", name)
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r:
            path.write_bytes(r.read())
    return path


def geoboundaries(iso3: str, level: str) -> Path:
    name = f"gb_{iso3}_{level}.geojson"
    path = RAW / name
    if not path.exists():
        with urllib.request.urlopen(urllib.request.Request(
                f"https://www.geoboundaries.org/api/current/gbOpen/{iso3}/{level}/", headers=UA), timeout=120) as r:
            meta = json.load(r)
        fetch(name, meta["simplifiedGeometryGeoJSON"])
        (RAW / f"gb_{iso3}_{level}.licence.txt").write_text(f"{meta.get('boundaryLicense')} {meta.get('boundarySource')}")
    return path


def ogr(path: Path, table: str, extra: tuple = ()) -> None:
    if not shutil.which("ogr2ogr"):
        return stage_python(path, table)
    subprocess.run(["ogr2ogr", "-f", "PostgreSQL", PG_OGR, str(path), "-nln", f"stage.{table}", "-overwrite",
                    "-lco", "GEOMETRY_NAME=geom", "-lco", "FID=fid", "-nlt", "PROMOTE_TO_MULTI", "-t_srs", "EPSG:4326",
                    "-makevalid", *extra], check=True)


def _features(path: Path):
    """(properties, shapely geometry) from a GeoJSON or a WGS84 shapefile."""
    from shapely.geometry import shape
    if path.suffix == ".shp":
        import shapefile  # pyshp: pure Python, so Windows needs no GDAL install
        prj = path.with_suffix(".prj")
        if prj.exists() and "GCS_WGS_1984" not in prj.read_text() and "WGS 84" not in prj.read_text():
            raise SystemExit(f"{path.name} is not in WGS84; install GDAL (ogr2ogr) to reproject it")
        with shapefile.Reader(str(path), encoding="utf-8", encodingErrors="replace") as r:
            names = [f[0] for f in r.fields[1:]]
            for sr in r.iterShapeRecords():
                if sr.shape.shapeType != shapefile.NULL:
                    yield dict(zip(names, sr.record)), shape(sr.shape.__geo_interface__)
    else:
        for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
            if f.get("geometry"):
                yield f.get("properties") or {}, shape(f["geometry"])


def stage_python(path: Path, table: str) -> None:
    """Fallback for ogr2ogr: same stage table shape (laundered lower-case text columns, MultiPolygon `geom`, EPSG:4326)."""
    rows = list(_features(path))
    cols = sorted({k.lower() for p, _ in rows for k in p if k.lower() not in ("geom", "fid")})
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(f"DROP TABLE IF EXISTS stage.{table}")
        conn.execute(f"CREATE TABLE stage.{table} (fid serial PRIMARY KEY, {''.join(f'{c} text, ' for c in cols)}"
                     f"geom geometry(MultiPolygon, 4326))")
        sql = (f"INSERT INTO stage.{table} ({''.join(f'{c}, ' for c in cols)}geom) VALUES "
               f"({'%s, ' * len(cols)}ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_GeomFromWKB(%s, 4326)), 3)))")
        with conn.cursor() as cur:
            cur.executemany(sql, [([None if (v := {k.lower(): x for k, x in p.items()}.get(c)) is None else str(v)
                                    for c in cols] + [g.wkb]) for p, g in rows])
    print(f"  staged {table}: {len(rows)} (python)")


BUILD_ADMIN = f"""
TRUNCATE gis_admin_area RESTART IDENTITY;
CREATE TEMP TABLE bbox AS SELECT ST_MakeEnvelope({W},{S},{E},{N},4326) AS g;

-- India, official depiction (DataMeet india-soi, Survey of India-derived)
INSERT INTO gis_admin_area(level, country_iso3, name, source, geom)
SELECT 'ADM0','IND','India','DataMeet india-soi (Survey of India)', ST_Multi(ST_Union(ST_MakeValid(geom))) FROM stage.india_soi;
CREATE TEMP TABLE india AS SELECT geom AS g FROM gis_admin_area WHERE level='ADM0' AND country_iso3='IND';

-- every other country in the bbox, India point-of-view, minus India, clipped to bbox
INSERT INTO gis_admin_area(level, country_iso3, name, source, geom)
SELECT 'ADM0', c.adm0_a3, c.name, 'Natural Earth admin-0 (India point of view)',
       ST_Multi(ST_CollectionExtract(ST_Intersection(ST_Difference(ST_MakeValid(c.geom), (SELECT g FROM india)), (SELECT g FROM bbox)), 3))
FROM stage.ne_adm0 c
WHERE c.adm0_a3 <> 'IND' AND ST_Intersects(c.geom, (SELECT g FROM bbox));

-- India states / districts (DataMeet), clipped to the official outline
INSERT INTO gis_admin_area(level, country_iso3, name, source, geom)
SELECT 'ADM1','IND', st_nm, 'DataMeet States (CC BY 2.5 IN)',
       ST_Multi(ST_CollectionExtract(ST_Intersection(ST_MakeValid(geom), (SELECT g FROM india)), 3)) FROM stage.in_states;
INSERT INTO gis_admin_area(level, country_iso3, name, parent_name, source, geom)
SELECT 'ADM2','IND', district, st_nm, 'DataMeet Districts Census 2011 (CC BY 2.5 IN)',
       ST_Multi(ST_CollectionExtract(ST_Intersection(ST_MakeValid(geom), (SELECT g FROM india)), 3)) FROM stage.in_districts;
"""

NEIGHBOUR_ADMIN = """
INSERT INTO gis_admin_area(level, country_iso3, name, source, geom)
SELECT %(level)s, %(iso3)s, shapename, %(source)s,
       ST_Multi(ST_CollectionExtract(ST_Intersection(
         ST_Difference(ST_MakeValid(geom), (SELECT geom FROM gis_admin_area WHERE level='ADM0' AND country_iso3='IND')),
         ST_MakeEnvelope(%(w)s,%(s)s,%(e)s,%(n)s,4326)), 3))
FROM stage.{table}
WHERE ST_Intersects(geom, ST_MakeEnvelope(%(w)s,%(s)s,%(e)s,%(n)s,4326));
"""

FINISH_ADMIN = """
DELETE FROM gis_admin_area WHERE geom IS NULL OR ST_IsEmpty(geom);
UPDATE gis_admin_area SET
  geom_lo  = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SimplifyPreserveTopology(geom, 0.02)), 3)),
  geom_mid = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SimplifyPreserveTopology(geom, 0.0025)), 3)),
  label_pt = ST_PointOnSurface(geom);
ANALYZE gis_admin_area;
"""

# acceptance: official depiction + no neighbour overlap (PRD §10)
CHECKS = [
    ("Gilgit inside India", "SELECT ST_Contains(geom, ST_SetSRID(ST_Point(74.31, 35.92),4326)) FROM gis_admin_area WHERE level='ADM0' AND country_iso3='IND'", True),
    ("Muzaffarabad inside India", "SELECT ST_Contains(geom, ST_SetSRID(ST_Point(73.47, 34.37),4326)) FROM gis_admin_area WHERE level='ADM0' AND country_iso3='IND'", True),
    ("Aksai Chin inside India", "SELECT ST_Contains(geom, ST_SetSRID(ST_Point(79.3, 35.2),4326)) FROM gis_admin_area WHERE level='ADM0' AND country_iso3='IND'", True),
    ("Tawang inside India", "SELECT ST_Contains(geom, ST_SetSRID(ST_Point(91.87, 27.59),4326)) FROM gis_admin_area WHERE level='ADM0' AND country_iso3='IND'", True),
    ("Lhasa not in India", "SELECT ST_Contains(geom, ST_SetSRID(ST_Point(91.13, 29.65),4326)) FROM gis_admin_area WHERE level='ADM0' AND country_iso3='IND'", False),
    ("no neighbour polygon overlaps India (>1 km2)",
     """SELECT count(*) = 0 FROM gis_admin_area n, gis_admin_area i
        WHERE i.level='ADM0' AND i.country_iso3='IND' AND n.country_iso3 <> 'IND'
          AND ST_Intersects(n.geom, i.geom) AND ST_Area(ST_Intersection(n.geom, i.geom)::geography) > 1e6""", True),
]


def load_defacto(conn) -> None:
    """Natural Earth default admin-0 -> gis_defacto_admin0 (planner only, ARCHITECTURE D33). Not a map layer."""
    from shapely.geometry import MultiPolygon, box, shape
    conn.execute("CREATE TABLE IF NOT EXISTS gis_defacto_admin0 (id bigserial PRIMARY KEY, iso3 varchar(3), name text, "
                 "geom geometry(MultiPolygon, 4326))")
    conn.execute("TRUNCATE gis_defacto_admin0 RESTART IDENTITY")
    bb = box(W, S, E, N)
    rows = []
    for f in json.loads(fetch("ne_10m_admin_0_countries.geojson", DOWNLOADS["ne_10m_admin_0_countries.geojson"])
                        .read_text(encoding="utf-8"))["features"]:
        g = shape(f["geometry"])
        if g.intersects(bb):
            g = g.intersection(bb)
            polys = [p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon"]
            if polys:
                rows.append((f["properties"]["ADM0_A3"], f["properties"]["NAME"], MultiPolygon(polys).wkb))
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO gis_defacto_admin0(iso3, name, geom) VALUES (%s, %s, ST_GeomFromWKB(%s, 4326))", rows)
    print(f"  de facto admin-0 (planning only): {len(rows)}")


def load_places(conn) -> None:
    conn.execute("TRUNCATE gis_place RESTART IDENTITY")
    z = zipfile.ZipFile(fetch("cities1000.zip", DOWNLOADS["cities1000.zip"]))
    rows = []
    with z.open("cities1000.txt") as f:
        for r in csv.reader(io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE):
            lat, lon = float(r[4]), float(r[5])
            if W <= lon <= E and S <= lat <= N:
                rows.append((r[1], r[7], int(r[14] or 0), r[10], r[8], f"SRID=4326;POINT({lon} {lat})"))
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO gis_place(name, kind, population, admin1, country_code, geom) "
                        "VALUES (%s,%s,%s,%s,%s,ST_GeomFromEWKT(%s))", rows)
    print(f"  places: {len(rows)}")


def load_civil_airports(conn) -> None:
    conn.execute("TRUNCATE civil_airport RESTART IDENTITY")
    curated = set()
    for name in ("iaf_bases.csv", "other_indian_mil.csv", "neighbour_bases.csv"):
        curated |= {r["ident"] for r in csv.DictReader(open(ROOT / "data" / "curated" / name, encoding="utf-8"))}
    rows = []
    for r in csv.DictReader(open(ROOT / "data" / "raw" / "airports.csv", encoding="utf-8")):
        lat, lon = float(r["latitude_deg"]), float(r["longitude_deg"])
        if r["type"] in ("large_airport", "medium_airport", "small_airport", "heliport") and r["ident"] not in curated \
                and W <= lon <= E and S <= lat <= N:
            elev = float(r["elevation_ft"]) * 0.3048 if r["elevation_ft"] else None
            rows.append((r["ident"], r["icao_code"] or r["gps_code"] or None, r["iata_code"] or None, r["name"],
                         r["type"], r["iso_country"], elev, f"SRID=4326;POINT({lon} {lat})"))
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO civil_airport(ident, icao, iata, name, type, country_iso2, elevation_m, geom) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,ST_GeomFromEWKT(%s))", rows)
    print(f"  civil airports: {len(rows)}")


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    print("1/5 download")
    for name, url in DOWNLOADS.items():
        fetch(name, url)
    for name, url in OURAIRPORTS.items():
        path = RAW.parent / name
        if not path.exists() or path.stat().st_size == 0:
            print("  download", name)
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r:
                path.write_bytes(r.read())
    gb = {(iso3, lvl): geoboundaries(iso3, lvl) for iso3 in NEIGHBOURS for lvl in ("ADM1", "ADM2")}

    print("2/5 stage (ogr2ogr)")
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS stage")
    ogr(RAW / "india-soi.geojson", "india_soi")
    ogr(RAW / "states.shp", "in_states")
    ogr(RAW / "districts.shp", "in_districts")
    ogr(RAW / "ne_10m_admin_0_countries_ind.geojson", "ne_adm0")
    for (iso3, lvl), path in gb.items():
        ogr(path, f"gb_{iso3.lower()}_{lvl.lower()}")

    print("3/5 build admin areas")
    with psycopg.connect(DSN) as conn:
        conn.execute(BUILD_ADMIN)
        for (iso3, lvl), path in gb.items():
            licence = (RAW / f"gb_{iso3}_{lvl}.licence.txt").read_text().strip()
            conn.execute(NEIGHBOUR_ADMIN.format(table=f"gb_{iso3.lower()}_{lvl.lower()}"),
                         {"level": lvl, "iso3": iso3, "source": f"geoBoundaries ({licence})",
                          "w": W, "s": S, "e": E, "n": N})
        conn.execute(FINISH_ADMIN)
        for lvl, n in conn.execute("SELECT level, count(*) FROM gis_admin_area GROUP BY level ORDER BY level"):
            print(f"  {lvl}: {n}")

        print("4/5 places + civil airports")
        load_places(conn)
        load_civil_airports(conn)
        load_defacto(conn)

        print("5/5 boundary acceptance tests")
        failed = 0
        for label, sql, want in CHECKS:
            got = conn.execute(sql).fetchone()[0]
            ok = got == want
            failed += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {label}")
        conn.execute("ANALYZE gis_place; ANALYZE civil_airport;")
    if failed:
        raise SystemExit(f"{failed} boundary test(s) failed")


if __name__ == "__main__":
    main()
