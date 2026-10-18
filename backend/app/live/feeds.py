# Portions derived from God's Eye View (server/providers/aircraft/{opensky,adsb-lol}.js,
# src/sources/live/aircraft.js, src/layers/aircraft/classification.js),
# Copyright (c) 2026 Bilawal Sidhu, MIT License. See THIRD_PARTY_NOTICES.md.
"""Live ADS-B: poll adsb.lol + adsb.fi (+ OpenSky), normalise, merge by hex (FR-LIVE-01, 02, 06, 10).

Viewport-driven: GET /live/aircraft?bbox= reports what viewers look at; the poller covers it with ≤ N circles.
"""
import asyncio
import logging
import math
import time
from collections import deque

import httpx

from .. import config
from ..http import client
from .classify import aircraft_class, display_category, emergency

log = logging.getLogger("live")
W, S, E, N = config.BBOX
FT = 0.3048
DEFAULT_VIEW = (68.0, 8.0, 97.0, 36.0)
PROVIDERS = {
    "adsb.lol": {"point": "https://api.adsb.lol/v2/point/{lat}/{lon}/{nm}", "mil": "https://api.adsb.lol/v2/mil",
                 "gap": 1.5},
    "adsb.fi": {"point": "https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{nm}",
                "mil": "https://opendata.adsb.fi/api/v2/mil", "gap": 1.1},
    "airplanes.live": {"point": "https://api.airplanes.live/v2/point/{lat}/{lon}/{nm}",
                       "mil": "https://api.airplanes.live/v2/mil", "gap": 1.1},
}
TRACKS: dict[str, dict] = {}
TRAIL_LIMIT = 120
TRAILS: dict[str, deque[dict]] = {}
MILITARY: set[str] = set()                     # sticky per session (God's Eye createMilitaryRegistry)
STATUS: dict[str, dict] = {p: {"state": "OFF", "last_ok": None, "error": None, "count": 0}
                           for p in [*PROVIDERS, "opensky"] if p in config.ADSB_PROVIDERS}
VIEW = {"bbox": DEFAULT_VIEW, "seen": 0.0}
_opensky_token = {"value": None, "exp": 0.0}


def report_view(bbox: tuple[float, float, float, float]) -> None:
    w, s, e, n = bbox
    VIEW["bbox"] = (max(w, W), max(s, S), min(e, E), min(n, N))
    VIEW["seen"] = time.time()


def circles(bbox, max_circles: int) -> list[tuple[float, float, int]]:
    """Cover a bbox with ≤ max_circles query circles (radius ≤ 250 NM)."""
    w, s, e, n = bbox
    span_km = max((e - w) * 111 * math.cos(math.radians((s + n) / 2)), (n - s) * 111)
    k = 1 if span_km < 900 else 2
    out = []
    for i in range(k):
        for j in range(k):
            lon = w + (e - w) * (i + 0.5) / k
            lat = s + (n - s) * (j + 0.5) / k
            half_diag_km = math.hypot((e - w) / k * 111 * math.cos(math.radians(lat)), (n - s) / k * 111) / 2
            out.append((round(lat, 2), round(lon, 2), int(min(250, max(40, half_diag_km / 1.852)))))
    return out[:max_circles]


def norm_readsb(a: dict, source: str, now: float) -> dict | None:
    lat, lon = a.get("lat"), a.get("lon")
    if lat is None or lon is None:
        return None
    alt = a.get("alt_baro")
    on_ground = alt == "ground"
    alt_ft = a.get("alt_geom") if on_ground or alt is None else alt
    hex_ = str(a.get("hex", "")).lower().lstrip("~")
    t = {"hex": hex_, "callsign": (a.get("flight") or "").strip() or None, "reg": a.get("r"),
         "icao_type": a.get("t"), "lat": lat, "lon": lon,
         "alt_m": None if on_ground or not isinstance(alt_ft, (int, float)) else round(alt_ft * FT),
         "on_ground": on_ground, "gs_kt": a.get("gs"), "track_deg": a.get("track") or a.get("true_heading"),
         "vr_mps": round(a["baro_rate"] * FT / 60, 1) if isinstance(a.get("baro_rate"), (int, float)) else None,
         "squawk": a.get("squawk"), "emitter_cat": a.get("category"), "desc": a.get("desc"),
         "operator": a.get("ownOp"), "db_military": bool((a.get("dbFlags") or 0) & 1), "source": source,
         "ts": now - (a.get("seen_pos") or a.get("seen") or 0), "emergency": emergency(a.get("squawk"), a.get("emergency"))}
    return t


def norm_opensky(s: list, now: float) -> dict | None:
    if s[5] is None or s[6] is None:
        return None
    alt = s[7] if s[7] is not None else s[13]
    return {"hex": s[0].lower(), "callsign": (s[1] or "").strip() or None, "reg": None, "icao_type": None,
            "lat": s[6], "lon": s[5], "alt_m": None if s[8] or alt is None else round(alt), "on_ground": bool(s[8]),
            "gs_kt": round(s[9] * 1.94384) if s[9] is not None else None, "track_deg": s[10],
            "vr_mps": s[11], "squawk": s[14], "emitter_cat": s[17] if len(s) > 17 else None, "desc": None,
            "operator": None, "db_military": False, "source": "opensky", "ts": s[4] or now,
            "emergency": emergency(s[14])}


def merge(tracks: list[dict]) -> None:
    for t in tracks:
        if not t or not t["hex"]:
            continue
        old = TRACKS.get(t["hex"])
        if old and old["ts"] > t["ts"]:
            for k in ("icao_type", "reg", "desc", "operator"):  # keep richer metadata from the other feed
                if not old.get(k) and t.get(k):
                    old[k] = t[k]
            continue
        if old:
            for k in ("icao_type", "reg", "desc", "operator"):
                t[k] = t.get(k) or old.get(k)
        TRACKS[t["hex"]] = t
        trail = TRAILS.setdefault(t["hex"], deque(maxlen=TRAIL_LIMIT))
        # Repeated provider snapshots aren't new observations; keep the trail chronological.
        if not trail or t["ts"] > trail[-1]["ts"]:
            trail.append({k: t[k] for k in ("lat", "lon", "alt_m", "ts")})


def prune(now: float) -> None:
    """Expire a track and its entire recorded trail together (FR-LIVE-06/09)."""
    for h in [h for h, t in TRACKS.items() if t["ts"] < now - 120]:
        TRACKS.pop(h, None)
        TRAILS.pop(h, None)


def _ok(name: str, n: int) -> None:
    STATUS[name].update(state="LIVE", last_ok=time.time(), error=None, count=n)


def _fail(name: str, ex: Exception) -> None:
    st = STATUS[name]
    st["error"] = str(ex)[:160]
    st["state"] = "STALE" if st["last_ok"] and time.time() - st["last_ok"] < 120 else "OFF"


async def poll_readsb(name: str) -> None:
    p = PROVIDERS[name]
    last_mil = 0.0
    while True:
        active = time.time() - VIEW["seen"] < 30
        try:
            now = time.time()
            got = []
            for lat, lon, nm in circles(VIEW["bbox"] if active else DEFAULT_VIEW, config.ADSB_MAX_CIRCLES):
                r = await client.get(p["point"].format(lat=lat, lon=lon, nm=nm))
                if r.status_code == 429:
                    raise httpx.HTTPStatusError("rate limited", request=r.request, response=r)
                r.raise_for_status()
                body = r.json()
                got += [norm_readsb(a, name, now) for a in body.get("ac") or body.get("aircraft") or []]
                await asyncio.sleep(p["gap"])
            if now - last_mil > 30:
                r = await client.get(p["mil"])
                r.raise_for_status()
                body = r.json()
                mil = [a for a in body.get("ac") or body.get("aircraft") or []
                       if a.get("lat") is not None and W <= a["lon"] <= E and S <= a["lat"] <= N]
                MILITARY.update(str(a.get("hex", "")).lower() for a in mil)
                got += [norm_readsb(a, name, now) for a in mil]
                last_mil = now
            merge(got)
            _ok(name, len(got))
        except Exception as ex:
            _fail(name, ex)
            log.info("%s poll failed: %s", name, ex)
            retry = getattr(getattr(ex, "response", None), "headers", {}).get("retry-after")
            await asyncio.sleep(min(120, int(retry)) if retry and str(retry).isdigit() else 30)
        await asyncio.sleep(10 if active else 30)


async def _opensky_auth() -> dict:
    if not (config.OPENSKY_CLIENT_ID and config.OPENSKY_CLIENT_SECRET):
        return {}
    if _opensky_token["value"] and _opensky_token["exp"] > time.time() + 60:
        return {"Authorization": f"Bearer {_opensky_token['value']}"}
    r = await client.post("https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token",
                          data={"grant_type": "client_credentials", "client_id": config.OPENSKY_CLIENT_ID,
                                "client_secret": config.OPENSKY_CLIENT_SECRET})
    r.raise_for_status()
    tok = r.json()
    _opensky_token.update(value=tok["access_token"], exp=time.time() + tok.get("expires_in", 1800))
    return {"Authorization": f"Bearer {tok['access_token']}"}


async def poll_opensky() -> None:
    """Whole-region snapshot: 4 credits/call -> every 90 s with an API client, every 15 min anonymous."""
    while True:
        interval = 90 if config.OPENSKY_CLIENT_ID else 900
        try:
            headers = await _opensky_auth()
            r = await client.get("https://opensky-network.org/api/states/all", headers=headers,
                                 params={"lamin": S, "lomin": W, "lamax": N, "lomax": E, "extended": 1})
            if r.status_code == 429:
                interval = max(interval, int(r.headers.get("x-rate-limit-retry-after-seconds", 900)))
                raise httpx.HTTPStatusError("rate limited", request=r.request, response=r)
            r.raise_for_status()
            now = time.time()
            got = [norm_opensky(s, now) for s in r.json().get("states") or []]
            merge(got)
            _ok("opensky", len(got))
        except Exception as ex:
            _fail("opensky", ex)
        await asyncio.sleep(interval)


async def janitor() -> None:
    while True:
        prune(time.time())
        for name, st in STATUS.items():
            if st["last_ok"] and time.time() - st["last_ok"] > 120 and st["state"] == "LIVE":
                st["state"] = "STALE"
        await asyncio.sleep(10)


def start() -> list[asyncio.Task]:
    tasks = [asyncio.create_task(janitor())]
    for name in config.ADSB_PROVIDERS:
        if name in PROVIDERS:
            tasks.append(asyncio.create_task(poll_readsb(name)))
        elif name == "opensky":
            tasks.append(asyncio.create_task(poll_opensky()))
    return tasks


def snapshot(bbox) -> list[dict]:
    w, s, e, n = bbox
    now = time.time()
    out = []
    for t in TRACKS.values():
        if not (w <= t["lon"] <= e and s <= t["lat"] <= n):
            continue
        cls = aircraft_class(t["icao_type"], t["emitter_cat"])
        item = {**t, "cls": cls, "is_military": t["hex"] in MILITARY or t["db_military"], "age_s": round(now - t["ts"]),
                "simulated": False}
        item["category"] = display_category(item)
        out.append(item)
    return out
