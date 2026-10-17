"""Base forecast poller for planning (PHASE2_IMPLEMENTATION_PLAN §7.1). Hourly Open-Meteo for every IAF base in one
request -> wx_base_forecast (source OPEN_METEO). The planner prefers it over the synthetic seed forecast; exercise
overrides win over both. Ceiling is estimated from low / mid cloud cover (Open-Meteo has no cloud base), so the row is
labelled derived. Offline or failing: the synthetic forecast stays in use."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from ..db import SessionLocal
from ..decide.weather_impact import category
from ..http import client

log = logging.getLogger("wx.forecast")
STATE = {"updated": None, "error": None, "rows": 0}


def ceiling_from(low: float, mid: float) -> float | None:
    if low >= 75:
        return 800.0
    if low >= 50:
        return 1800.0
    if mid >= 75:
        return 6000.0
    return None


async def poll_once() -> int:
    with SessionLocal() as db:
        bases = db.execute(text("SELECT id, ST_Y(geom), ST_X(geom) FROM base WHERE side = 'OWN' ORDER BY id")).all()
    if not bases:
        return 0
    r = await client.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": ",".join(f"{b[1]:.3f}" for b in bases), "longitude": ",".join(f"{b[2]:.3f}" for b in bases),
        "hourly": "cloud_cover_low,cloud_cover_mid,visibility,wind_speed_10m,wind_gusts_10m,wind_direction_10m",
        "wind_speed_unit": "kn", "forecast_days": 4, "timezone": "UTC"}, timeout=60)
    r.raise_for_status()
    data = r.json()
    data = data if isinstance(data, list) else [data]
    rows = []
    for (bid, _, _), d in zip(bases, data):
        h = d.get("hourly", {})
        for i, ts in enumerate(h.get("time", [])):
            vis = h["visibility"][i] if h["visibility"][i] is not None else 10000
            ceil = ceiling_from(h["cloud_cover_low"][i] or 0, h["cloud_cover_mid"][i] or 0)
            rows.append({"b": bid, "t": datetime.fromisoformat(ts).replace(tzinfo=timezone.utc), "c": ceil, "v": min(vis, 10000),
                         "w": h["wind_speed_10m"][i] or 0, "g": h["wind_gusts_10m"][i], "d": h["wind_direction_10m"][i],
                         "cat": category(ceil, min(vis, 10000))})
    with SessionLocal() as db:
        db.execute(text("""INSERT INTO wx_base_forecast (base_id, valid_ts, ceiling_ft, vis_m, wind_kt, gust_kt, wind_dir, flight_cat,
                           source, fetched_at, is_simulated) VALUES (:b, :t, :c, :v, :w, :g, :d, :cat, 'OPEN_METEO', now(), false)
                           ON CONFLICT (base_id, valid_ts, source) DO UPDATE SET ceiling_ft = :c, vis_m = :v, wind_kt = :w,
                           gust_kt = :g, wind_dir = :d, flight_cat = :cat, fetched_at = now()"""), rows)
        db.commit()
    return len(rows)


async def poll_loop(every_s: float = 3600) -> None:
    while True:
        try:
            STATE["rows"] = await poll_once()
            STATE["updated"], STATE["error"] = datetime.now(timezone.utc).isoformat(), None
        except Exception as e:      # stale-while-error: the synthetic / previous forecast stays in use
            STATE["error"] = str(e)[:200]
            log.warning("base forecast poll failed: %s", e)
        await asyncio.sleep(every_s)
