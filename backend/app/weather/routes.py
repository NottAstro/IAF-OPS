"""Weather endpoints (FR-WX-01..06). Every upstream key stays server-side."""
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from .. import config
from ..auth import current_user
from ..http import TTLCache, client
from . import metar

router = APIRouter(prefix="/wx", tags=["weather"])
cache = TTLCache(2048)
OWM_LAYERS = {"clouds_new", "precipitation_new", "pressure_new", "wind_new", "temp_new"}
NOWCOAST = "https://nowcoast.noaa.gov/geoserver/observations/satellite/ows"
WMS_PARAMS = {"bbox", "width", "height", "srs", "crs", "format", "transparent", "styles", "service", "request",
              "version", "time"}


@router.get("/metars")
def metars(user: dict = Depends(current_user)):
    """All region METARs (for flight-category rings) + feed status."""
    return {"updated": metar.STATE["updated"], "error": metar.STATE["error"],
            "stations": [{"icao": k, "lat": m["lat"], "lon": m["lon"], "name": m.get("name"),
                          "flight_category": m.get("flightCategory"), "raw": m.get("rawOb"),
                          "obs_time": m.get("reportTime")} for k, m in metar.STATE["metars"].items()]}


@router.get("/station/{icao}")
def station(icao: str, user: dict = Depends(current_user)):
    m = metar.STATE["metars"].get(icao.upper())
    if not m:
        raise HTTPException(404, "No current METAR for this station.")
    t = metar.STATE["tafs"].get(icao.upper())
    return {**m, "taf": t.get("rawTAF") if t else None}


HOURLY = ("temperature_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,cloud_cover_low,cloud_cover_mid,"
          "cloud_cover_high,visibility,precipitation,freezing_level_height,cape,wind_speed_850hPa,wind_direction_850hPa,"
          "wind_speed_700hPa,wind_direction_700hPa,wind_speed_500hPa,wind_direction_500hPa,wind_speed_300hPa,"
          "wind_direction_300hPa")
CURRENT = ("temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,cloud_cover,"
           "cloud_cover_low,cloud_cover_mid,cloud_cover_high,visibility,precipitation,weather_code,pressure_msl")


@router.get("/point")
async def point(lat: float, lon: float, user: dict = Depends(current_user)):
    """Open-Meteo forecast for any point (FR-WX-02). Cached 10 min on a 0.1° grid."""
    w, s, e, n = config.BBOX
    if not (s <= lat <= n and w <= lon <= e):
        raise HTTPException(422, "Point is outside the region.")
    la, lo = round(lat, 1), round(lon, 1)

    async def fetch():
        r = await client.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": la, "longitude": lo, "current": CURRENT, "hourly": HOURLY, "forecast_days": 2,
            "wind_speed_unit": "kn", "timezone": "Asia/Kolkata"})
        r.raise_for_status()
        return r.json()
    try:
        data = await cache.get(f"om:{la}:{lo}", 600, fetch)
    except httpx.HTTPError as ex:
        raise HTTPException(502, f"Open-Meteo did not respond: {ex}")
    return {"source": "Open-Meteo.com (CC BY 4.0)", **data}


@router.get("/owm/{layer}/{z}/{x}/{y}.png")
async def owm_tile(layer: str, z: int, x: int, y: int, user: dict = Depends(current_user)):
    if not config.OWM_API_KEY:
        raise HTTPException(404, "OWM_API_KEY is not set in .env")
    if layer not in OWM_LAYERS or not 0 <= z <= 12:
        raise HTTPException(404, "Unknown layer")

    async def fetch():
        r = await client.get(f"https://tile.openweathermap.org/map/{layer}/{z}/{x}/{y}.png",
                             params={"appid": config.OWM_API_KEY})
        if r.status_code == 401:
            raise HTTPException(401, "OpenWeatherMap rejected the key (new keys can take ~2 h to activate).")
        r.raise_for_status()
        return r.content
    body = await cache.get(f"owm:{layer}:{z}:{x}:{y}", 600, fetch)
    return Response(body, media_type="image/png", headers={"Cache-Control": "max-age=600"})


@router.get("/ir")
async def ir_wms(request: Request, user: dict = Depends(current_user)):
    """NOAA nowCOAST global longwave IR mosaic, WMS GetMap pass-through (FR-WX-05)."""
    params = {k: v for k, v in request.query_params.items() if k.lower() in WMS_PARAMS}
    params["layers"] = "global_longwave_imagery_mosaic"
    key = "ir:" + "&".join(f"{k}={params[k]}" for k in sorted(params))

    async def fetch():
        r = await client.get(NOWCOAST, params=params)
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "image/png")
    body, ctype = await cache.get(key, 600, fetch)
    return Response(body, media_type=ctype, headers={"Cache-Control": "max-age=600"})


@router.get("/status")
def status(user: dict = Depends(current_user)):
    return {"metar": {"updated": metar.STATE["updated"], "error": metar.STATE["error"],
                      "stations": len(metar.STATE["metars"])},
            "owm": bool(config.OWM_API_KEY), "now": time.time()}


wind_router = APIRouter(prefix="/wind", tags=["weather"])


@wind_router.get("/{path:path}")
async def wind_proxy(path: str, request: Request, user: dict = Depends(current_user)):
    """Proxy to the Node wind sidecar (God's Eye wind server, ARCHITECTURE §7.1)."""
    try:
        r = await client.get(f"{config.WIND_URL}/api/wind/{path}", params=dict(request.query_params), timeout=120)
    except httpx.HTTPError:
        raise HTTPException(503, "Wind service isn't running (npm start in wind/).")
    return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type"),
                    headers={"Cache-Control": r.headers.get("cache-control", "max-age=300")})
