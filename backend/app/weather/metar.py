"""METAR/TAF from aviationweather.gov (FR-WX-01). Polled for the whole region; bases map to own or nearest station."""
import asyncio
import logging
import math
import time

from sqlalchemy import text

from .. import config
from ..db import SessionLocal
from ..http import client

log = logging.getLogger("wx.metar")
AWC = "https://aviationweather.gov/api/data"
W, S, E, N = config.BBOX
# AWC caps most responses at 400 entries -> query the region in 4 tiles
TILES = [(S, W, (S + N) / 2, (W + E) / 2), (S, (W + E) / 2, (S + N) / 2, E),
         ((S + N) / 2, W, N, (W + E) / 2), ((S + N) / 2, (W + E) / 2, N, E)]
STATE: dict = {"metars": {}, "tafs": {}, "updated": None, "taf_updated": None, "error": None}


def _vis_sm(v) -> float | None:
    if v is None:
        return None
    s = str(v).replace("+", "")
    try:
        return float(s)
    except ValueError:
        return None


def flight_category(m: dict) -> str:
    """FAA categories from ceiling (lowest BKN/OVC/VV, ft) and visibility (SM)."""
    ceil = min((c.get("base") or 99999 for c in m.get("clouds") or [] if c.get("cover") in ("BKN", "OVC", "VV", "OVX")),
               default=99999)
    vis = _vis_sm(m.get("visib"))
    vis = 10.0 if vis is None else vis
    if ceil < 500 or vis < 1:
        return "LIFR"
    if ceil < 1000 or vis < 3:
        return "IFR"
    if ceil <= 3000 or vis <= 5:
        return "MVFR"
    return "VFR"


def km(a_lat, a_lon, b_lat, b_lon) -> float:
    dx = (a_lon - b_lon) * 111.32 * math.cos(math.radians((a_lat + b_lat) / 2))
    return math.hypot(dx, (a_lat - b_lat) * 110.57)


async def _fetch(kind: str) -> dict:
    out = {}
    for s, w, n, e in TILES:
        r = await client.get(f"{AWC}/{kind}", params={"bbox": f"{s},{w},{n},{e}", "format": "json"})
        r.raise_for_status()
        for m in r.json() or []:
            out[m["icaoId"]] = m
    return out


def assign_stations() -> None:
    """Base -> own METAR station, else nearest within 50 km (stored on base.metar_station)."""
    metars = STATE["metars"]
    if not metars:
        return
    with SessionLocal() as db:
        for bid, code, lat, lon in db.execute(text("SELECT id, code, ST_Y(geom), ST_X(geom) FROM base")):
            if code in metars:
                st, d = code, 0.0
            else:
                st, d = min(((icao, km(lat, lon, m["lat"], m["lon"])) for icao, m in metars.items()),
                            key=lambda x: x[1], default=(None, 1e9))
                if d > 50:
                    st, d = None, None
            db.execute(text("UPDATE base SET metar_station = :s, metar_station_km = :d WHERE id = :id"),
                       {"s": st, "d": None if d is None else round(d, 1), "id": bid})
        db.commit()


async def poll_loop() -> None:
    last_taf = 0.0
    while True:
        try:
            STATE["metars"] = await _fetch("metar")
            for m in STATE["metars"].values():
                m["flightCategory"] = flight_category(m)
            STATE["updated"], STATE["error"] = time.time(), None
            await asyncio.to_thread(assign_stations)
            if time.time() - last_taf > 1800:
                STATE["tafs"] = await _fetch("taf")
                STATE["taf_updated"], last_taf = time.time(), time.time()
        except Exception as ex:  # keep last good data
            STATE["error"] = str(ex)[:200]
            log.warning("METAR poll failed: %s", ex)
        await asyncio.sleep(300)


def for_base(base: dict) -> dict:
    st = base.get("metar_station")
    m = STATE["metars"].get(st) if st else None
    if not m:
        return {"available": False, "station": None,
                "note": "No METAR within 50 km; use the point forecast." if STATE["metars"] else "METAR feed not loaded yet."}
    t = STATE["tafs"].get(st)
    return {"available": True, "station": st, "station_name": m.get("name"), "distance_km": base.get("metar_station_km"),
            "own_station": st == base.get("code"), "raw": m.get("rawOb"), "taf": t.get("rawTAF") if t else None,
            "flight_category": m.get("flightCategory"), "obs_time": m.get("reportTime"), "temp_c": m.get("temp"),
            "dewpoint_c": m.get("dewp"), "wind_dir": m.get("wdir"), "wind_kt": m.get("wspd"), "gust_kt": m.get("wgst"),
            "visibility_sm": m.get("visib"), "altimeter_hpa": m.get("altim"), "clouds": m.get("clouds")}
