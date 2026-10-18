"""Public airspace import (ARCHITECTURE D44, PRD FR-MSN-05): prohibited / restricted / danger areas and civil terminal
airspace for India from OpenAIP (openaip.net, CC BY-NC 4.0), next to the synthetic zones, which stay.

    python -m app.decide.airspace_import                    # OPENAIP_API_KEY set: fetch country IN from the API
    python -m app.decide.airspace_import --file data/raw/openaip_in.json   # an OpenAIP export / saved API response

Mapping (OpenAIP type codes from its core API):
- Prohibited (3)               -> RESTRICTED, capacity 0: the planner never routes through it
- Restricted (1), Danger (2)   -> DANGER, capacity 0: shown on the Ops map; not usable as a mission area
- CTR (4), TMA (7), ATZ (13)   -> CIVIL_TERMINAL: adds to the civil-traffic density (decide/traffic.py, D39)
Everything else (FIR, airways, ...) is skipped. Re-running replaces the previous import (codes `OAIP-…`).
"""
import argparse
import json
import logging
import os
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon, box, shape
from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger("decide.airspace_import")
API = "https://api.core.openaip.net/api/airspaces"
KIND = {3: "RESTRICTED", 1: "DANGER", 2: "DANGER", 4: "CIVIL_TERMINAL", 7: "CIVIL_TERMINAL", 13: "CIVIL_TERMINAL",
        "PROHIBITED": "RESTRICTED", "RESTRICTED": "DANGER", "DANGER": "DANGER", "CTR": "CIVIL_TERMINAL", "TMA": "CIVIL_TERMINAL",
        "ATZ": "CIVIL_TERMINAL"}
INDIA = box(66, 5, 99, 38)
FT, FL = 0.3048, 30.48


def _metres(lim: dict | None, default: float) -> float:
    """OpenAIP limit {value, unit: 0 m, 1 ft, 6 FL} -> metres."""
    if not lim:
        return default
    v, u = float(lim.get("value", 0)), lim.get("unit", 1)
    return round(v if u == 0 else v * FL if u == 6 else v * FT)


def fetch(key: str) -> list[dict]:
    import httpx
    out, page = [], 1
    while True:
        r = httpx.get(API, params={"country": "IN", "page": page, "limit": 1000}, headers={"x-openaip-api-key": key}, timeout=60)
        r.raise_for_status()
        d = r.json()
        out += d.get("items", [])
        if page >= d.get("totalPages", 1):
            return out
        page += 1


def zones(items: list[dict]) -> list[dict]:
    """OpenAIP airspace items -> airspace_zone rows (only the kinds the planner uses, inside the India box)."""
    out = []
    for it in items:
        kind = KIND.get(it.get("type"))
        geom = it.get("geometry")
        if not kind or not geom:
            continue
        g = shape(geom)
        if isinstance(g, MultiPolygon):
            g = max(g.geoms, key=lambda p: p.area)
        if not isinstance(g, Polygon) or g.is_empty or not g.intersects(INDIA):
            continue
        if not g.is_valid:
            g = g.buffer(0)
            if not isinstance(g, Polygon):
                continue
        ident = str(it.get("_id") or it.get("id") or abs(hash(g.wkt)))
        out.append({"code": f"OAIP-{ident[-19:]}", "name": f"{it.get('name', 'Airspace')} (OpenAIP)", "kind": kind,
                    "geom": f"SRID=4326;{g.wkt}", "lower_m": _metres(it.get("lowerLimit"), 0), "upper_m": _metres(it.get("upperLimit"), 15000),
                    "cap": 0 if kind in ("RESTRICTED", "DANGER") else 99})
    return out


def run(db: Session, items: list[dict]) -> dict:
    rows = zones(items)
    db.execute(text("DELETE FROM airspace_zone WHERE code LIKE 'OAIP-%'"))
    for z in rows:
        db.execute(text("""INSERT INTO airspace_zone (code, name, kind, geom, lower_m, upper_m, capacity_packages, is_simulated, source,
                                                      source_ref)
                           VALUES (:code, :name, :kind, ST_GeomFromEWKT(:geom), :lower_m, :upper_m, :cap, false, 'PUBLIC',
                                   'OpenAIP (openaip.net), CC BY-NC 4.0')"""), z)
    db.commit()
    from . import traffic
    traffic._STATIC.clear()                     # the civil-traffic grid picks up new terminal areas
    counts = {k: sum(1 for z in rows if z["kind"] == k) for k in ("RESTRICTED", "DANGER", "CIVIL_TERMINAL")}
    log.info("OpenAIP airspace imported: %s", counts)
    return counts


def main() -> None:
    from ..db import SessionLocal
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    a = ap.parse_args()
    if a.file:
        d = json.loads(Path(a.file).read_text(encoding="utf-8"))
        items = d.get("items", d) if isinstance(d, dict) else d
    elif os.environ.get("OPENAIP_API_KEY"):
        items = fetch(os.environ["OPENAIP_API_KEY"])
    else:
        raise SystemExit("Set OPENAIP_API_KEY (free at openaip.net) or pass --file with an OpenAIP export. Synthetic zones stay as they are.")
    with SessionLocal() as db:
        print(run(db, items))


if __name__ == "__main__":
    main()
