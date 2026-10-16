"""OSM roads / railways / telecom towers -> PostGIS (ARCHITECTURE §9 step 7). Heavy: ~4.6 GB of downloads.

Per country: download Geofabrik .pbf -> osmium tags-filter (keeps only what we need) -> delete the raw .pbf.
Then merge, clip to the region bbox, export GeoJSONSeq, COPY into gis_line / gis_point, build a merged
low-detail table for far zoom. Idempotent: countries already filtered are skipped.
Railway stations come from the Overpass API instead (the filtered .pbf files don't keep them).
Run: .venv/bin/python pipeline/osm.py            (everything)
     .venv/bin/python pipeline/osm.py stations   (railway stations only, ~1 min)
"""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import psycopg
import truststore
from dotenv import load_dotenv

truststore.inject_into_ssl()
ROOT = Path(__file__).resolve().parents[1]
OSM = ROOT / "data" / "raw" / "osm"
load_dotenv(ROOT / ".env")
DSN = os.environ.get("DATABASE_URL", "postgresql+psycopg://airops:airops@localhost:5432/airops").replace("+psycopg", "")
REGION = json.loads((ROOT / "shared" / "region.json").read_text())
BBOX = f"{REGION['west']},{REGION['south']},{REGION['east']},{REGION['north']}"
COUNTRIES = ["bhutan", "afghanistan", "sri-lanka", "pakistan", "myanmar", "bangladesh", "nepal", "india", "china"]
FILTERS = ["w/highway=motorway,trunk,primary", "w/railway=rail",
           "n/man_made=mast,tower,communications_tower"]
ROAD_KIND = {"motorway": "MOTORWAY", "trunk": "TRUNK", "primary": "PRIMARY"}


def sh(*args: str) -> None:
    subprocess.run(args, check=True)


def is_telecom(tags: dict) -> bool:
    mm = tags.get("man_made")
    return mm == "communications_tower" or tags.get("tower:type") == "communication" or (
        mm in ("mast", "tower") and any(k.startswith("communication:") for k in tags))


def load(conn, geojsonseq: Path) -> None:
    conn.execute("TRUNCATE gis_line RESTART IDENTITY; TRUNCATE gis_point RESTART IDENTITY;")
    n_line = n_pt = 0
    with conn.cursor() as cur, open(geojsonseq, encoding="utf-8") as f, \
            cur.copy("COPY gis_line(kind, name, ref, geom) FROM STDIN") as lines:
        towers = []
        for raw in f:
            feat = json.loads(raw.strip("\x1e\n"))
            tags, geom = feat.get("properties", {}), feat.get("geometry") or {}
            if geom.get("type") == "LineString":
                kind = ROAD_KIND.get(tags.get("highway")) or ("RAIL" if tags.get("railway") == "rail" else None)
                if kind:
                    wkt = "SRID=4326;LINESTRING(" + ",".join(f"{x} {y}" for x, y in geom["coordinates"]) + ")"
                    lines.write_row((kind, tags.get("name:en") or tags.get("name"), tags.get("ref"), wkt))
                    n_line += 1
            elif geom.get("type") == "Point" and is_telecom(tags):
                x, y = geom["coordinates"]
                height = tags.get("height", "").replace("m", "").strip()
                towers.append((feat.get("id") and int(str(feat["id"]).lstrip("n")) or None, tags.get("name"),
                               tags.get("operator"), float(height) if height.replace(".", "", 1).isdigit() else None,
                               f"SRID=4326;POINT({x} {y})"))
    with conn.cursor() as cur, cur.copy("COPY gis_point(kind, osm_id, name, operator, height_m, geom) FROM STDIN") as cp:
        for t in towers:
            cp.write_row(("TELECOM_TOWER", *t))
            n_pt += 1
    print(f"  loaded {n_line} line segments, {n_pt} telecom towers")


POST = """
UPDATE gis_line SET geom_simplified = ST_SimplifyPreserveTopology(geom, 0.002);
DROP TABLE IF EXISTS gis_line_lo;
CREATE TABLE gis_line_lo AS
SELECT kind, ref, (ST_Dump(ST_SimplifyPreserveTopology(ST_LineMerge(ST_Collect(geom)), 0.01))).geom AS geom
FROM gis_line WHERE kind IN ('MOTORWAY','TRUNK','RAIL') GROUP BY kind, ref;
DELETE FROM gis_line_lo WHERE GeometryType(geom) <> 'LINESTRING' OR ST_Length(geom) < 0.03;
ALTER TABLE gis_line_lo ADD COLUMN id bigserial PRIMARY KEY;
CREATE INDEX ON gis_line_lo USING gist (geom);
ANALYZE gis_line; ANALYZE gis_line_lo; ANALYZE gis_point;
"""


OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]
MAJOR_WORDS = ("Junction", " Jn", "Central", "Terminus", "Cantt")


def station_rank(tags: dict) -> int:
    """0 = junction / central / terminus with a Wikipedia entry, 1 = notable (Wikipedia/Wikidata), 2 = other.
    ponytail: name + wiki heuristic; Indian Railways station category (NSG) is almost never tagged in OSM."""
    name = tags.get("name:en") or tags.get("name") or ""
    notable = "wikidata" in tags or "wikipedia" in tags
    return 0 if notable and any(w in name for w in MAJOR_WORDS) else 1 if notable else 2


def stations() -> None:
    """railway=station nodes in the region (metro / light rail / monorail excluded) -> gis_point RAIL_STATION."""
    s, w, n, e = REGION["south"], REGION["west"], REGION["north"], REGION["east"]
    query = f'[out:json][timeout:170];node["railway"="station"]({s},{w},{n},{e});out body qt;'
    for url in OVERPASS:  # public mirrors; the main one often answers 502/504 when busy
        req = urllib.request.Request(url, urllib.parse.urlencode({"data": query}).encode(),
                                     headers={"User-Agent": "iaf-airops/0.1 (SIH26250 demo pipeline)"})
        try:
            with urllib.request.urlopen(req, timeout=200) as r:
                elements = json.load(r)["elements"]
            break
        except OSError as ex:
            print(f"  {url}: {ex}")
    else:
        raise SystemExit("All Overpass mirrors failed; try again in a few minutes.")
    rows = [(el["id"], el["tags"].get("name:en") or el["tags"].get("name"), el["tags"].get("operator"), station_rank(el["tags"]),
             f"SRID=4326;POINT({el['lon']} {el['lat']})")
            for el in elements
            if el.get("tags", {}).get("station") not in ("subway", "light_rail", "monorail") and "subway" not in el.get("tags", {})]
    with psycopg.connect(DSN) as conn:
        conn.execute("DELETE FROM gis_point WHERE kind = 'RAIL_STATION'")
        with conn.cursor() as cur, cur.copy("COPY gis_point(kind, osm_id, name, operator, rank, geom) FROM STDIN") as cp:
            for row in rows:
                cp.write_row(("RAIL_STATION", *row))
        conn.execute("ANALYZE gis_point")
    print(f"  loaded {len(rows)} railway stations ({sum(1 for r in rows if r[3] == 0)} major)")


def main() -> None:
    OSM.mkdir(parents=True, exist_ok=True)
    filtered = []
    for c in COUNTRIES:
        out = OSM / f"{c}.filtered.pbf"
        if not out.exists():
            raw = OSM / f"{c}-latest.osm.pbf"
            print(f"download {c}")
            sh("curl", "-sSL", "-C", "-", "--retry", "5", "-o", str(raw),
               f"https://download.geofabrik.de/asia/{c}-latest.osm.pbf")
            print(f"filter {c}")
            sh("osmium", "tags-filter", str(raw), *FILTERS, "-o", str(out), "--overwrite")
            raw.unlink()
        filtered.append(str(out))
    merged, region, seq = OSM / "merged.pbf", OSM / "region.pbf", OSM / "region.geojsonseq"
    print("merge + clip to region")
    sh("osmium", "merge", *filtered, "-o", str(merged), "--overwrite")
    sh("osmium", "extract", "--bbox", BBOX, "--strategy", "complete_ways", str(merged), "-o", str(region), "--overwrite")
    sh("osmium", "export", str(region), "-f", "geojsonseq", "-o", str(seq), "--overwrite", "--add-unique-id=type_id",
       "--geometry-types=point,linestring")
    with psycopg.connect(DSN) as conn:
        load(conn, seq)
        print("simplify + build far-zoom table")
        conn.execute(POST)
        n = conn.execute("SELECT count(*) FROM gis_line_lo").fetchone()[0]
        print(f"  gis_line_lo: {n} merged lines")
    for p in (merged, seq):
        p.unlink(missing_ok=True)
    stations()  # load() truncated gis_point


if __name__ == "__main__":
    stations() if sys.argv[1:] == ["stations"] else main()
