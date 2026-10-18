"""Public-road estimates for Infra, independent of simulated operational planning."""
import asyncio
import json
import math
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import config
from ..http import TTLCache, client

ROUTE_URL = "https://valhalla1.openstreetmap.de/route"  # Fixed allow-list: no caller-supplied host or coordinates.
MAX_BYTES = 2 * 1024 * 1024
CACHE = TTLCache(512)
_lock = asyncio.Lock()
_next_request = 0.0


class RoadUnavailable(Exception):
    pass


def _parse(body: dict) -> dict:
    routes = body.get("routes")
    if not routes:
        raise RoadUnavailable("No road route was found between these locations.")
    route = routes[0]
    geometry = route.get("geometry", {})
    points = geometry.get("coordinates", [])
    distance = route.get("distance")
    if geometry.get("type") != "LineString" or not 2 <= len(points) <= 100000:
        raise RoadUnavailable("The routing service returned an invalid path.")
    w, s, e, n = config.BBOX
    for p in points:
        if (not isinstance(p, list) or len(p) != 2 or
                not all(isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x) for x in p) or
                not (w <= p[0] <= e and s <= p[1] <= n)):
            raise RoadUnavailable("The routing service returned a path outside the map region.")
    if not isinstance(distance, (int, float)) or isinstance(distance, bool) or not math.isfinite(distance) or distance < 0:
        raise RoadUnavailable("The routing service returned an invalid distance.")
    return {"status": "available", "geometry": {"type": "LineString", "coordinates": points},
            "road_distance_km": round(distance / 1000, 1), "source": "Valhalla / FOSSGIS / OpenStreetMap",
            "fetched_at": datetime.now(timezone.utc).isoformat()}


async def _fetch(source: dict, destination: dict) -> dict:
    global _next_request
    payload = {
        "locations": [{"lat": b["lat"], "lon": b["lon"], "radius": 5000} for b in (source, destination)],
        "costing": "auto", "costing_options": {"auto": {"shortest": True, "disable_hierarchy_pruning": True}},
        "format": "osrm", "shape_format": "geojson", "directions_type": "none", "units": "kilometers",
    }
    async with _lock:
        now = time.monotonic()
        if _next_request - now > 2:
            raise RoadUnavailable("Road routing is temporarily unavailable. Try again shortly.")
        await asyncio.sleep(max(0, _next_request - now))
        _next_request = time.monotonic() + 1.1
        try:
            async with asyncio.timeout(30), client.stream("POST", ROUTE_URL, json=payload, follow_redirects=False,
                                     timeout=httpx.Timeout(25, connect=8)) as response:
                if response.status_code == 429:
                    _next_request = time.monotonic() + 60
                    raise RoadUnavailable("The routing service is busy. Try again in a minute.")
                if response.status_code != 200:
                    raise RoadUnavailable("No road route is available from the routing service.")
                if int(response.headers.get("content-length", 0)) > MAX_BYTES:
                    raise RoadUnavailable("The road route is too large to display.")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise RoadUnavailable("The road route is too large to display.")
            return _parse(json.loads(data))
        except (TimeoutError, httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
            _next_request = time.monotonic() + 15
            raise RoadUnavailable("Road routing could not be reached. Direct distances are still available.") from exc


async def road_route(source: dict, destination: dict) -> dict:
    if config.OFFLINE_MODE:
        return {"status": "unavailable", "message": "Road routing needs an internet connection. Direct distances are available offline."}
    key = repr([(b["id"], b["lon"], b["lat"]) for b in (source, destination)])
    try:
        # ponytail: a 512-pair, 24 h process cache for the single-machine demo; move to a shared cache for multiple workers.
        return await CACHE.get(key, 86400, lambda: _fetch(source, destination), stale_ok=False)
    except RoadUnavailable as exc:
        return {"status": "unavailable", "message": str(exc)}


def nearby_bases(db: Session, source_id: int) -> list[dict]:
    """The same exact geographic ordering feeds normal Infra connections and focus mode."""
    return [dict(b) for b in db.execute(text("""SELECT id, code, name, ST_X(geom) AS lon, ST_Y(geom) AS lat,
        round((ST_Distance(geom::geography, (SELECT geom::geography FROM base WHERE id = :s)) / 1000)::numeric, 1) AS distance_km
        FROM base WHERE side = 'OWN' AND country_iso3 = 'IND' AND base_type <> 'ALG' AND id <> :s
        AND source = 'PUBLIC' AND source_ref IS NOT NULL
        ORDER BY ST_Distance(geom::geography, (SELECT geom::geography FROM base WHERE id = :s)), id LIMIT 4"""),
        {"s": source_id}).mappings()]


def nearby_connections(db: Session, source_id: int) -> dict | None:
    """A lightweight public-only response; no inventory, readiness or weather queries."""
    source = db.execute(text("""SELECT id, code, name, ST_X(geom) AS lon, ST_Y(geom) AS lat FROM base
        WHERE id = :s AND side = 'OWN' AND country_iso3 = 'IND' AND source = 'PUBLIC' AND source_ref IS NOT NULL"""),
        {"s": source_id}).mappings().first()
    return {"base": dict(source), "connectivity": {"bases": nearby_bases(db, source_id)}} if source else None


async def connection(db: Session, source_id: int, destination_id: int) -> dict | None:
    """Only existing public own-force base coordinates may be sent to the routing service."""
    nearby = nearby_connections(db, source_id)
    if not nearby:
        return None
    destination = next((b for b in nearby["connectivity"]["bases"] if b["id"] == destination_id), None)
    if not destination:
        return None
    return {"source_id": source_id, "destination_id": destination_id, **await road_route(nearby["base"], destination)}
