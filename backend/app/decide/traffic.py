"""Civil-traffic deconfliction (ARCHITECTURE D39, PRD FR-PLN-11): how busy the civil airspace along a route is, so the
planner prefers quieter routings when the choice is otherwise close and tells the crew where to coordinate with ATC.

Two layers on a 0.25° grid:
- static: the terminal areas of large and medium civil airports (OurAirports, already loaded), always present;
- live: civil ADS-B tracks the feed currently holds (airborne, fresh, not military), counted per 0.5° cell. The live
  picture only says something about the next few hours, so it counts fully for launches within LIVE_FULL_H and fades
  to nothing by LIVE_ZERO_H. Where no viewer has looked lately the feed holds little: the static layer still applies.

A soft cost, never a hard constraint: civil and military traffic share Indian airspace under flexible use (FUA).
"""
import math
import time
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from shapely import wkb
from shapely.geometry import Point
from shapely.prepared import prep
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..geo import dist_km

CELL = 0.25                     # static grid
LIVE_CELL = 0.5                 # live counts
TMA_KM = 60                     # terminal area radius
WEIGHT = {"large_airport": 4.0, "medium_airport": 1.5}
LIVE_PER_UNIT = 10              # ten civil aircraft in a 0.5° cell = one unit of density
LIVE_MAX_AGE_S = 180
LIVE_FULL_H, LIVE_ZERO_H = 2.0, 6.0
SAMPLE_KM = 25
TERMINAL_WEIGHT = 1.5           # inside an imported CTR / TMA / ATZ (D44)
BUSY, MODERATE = 2.5, 1.0       # density per sample: what the explanation calls busy / moderate

_STATIC: dict = {}


@dataclass
class Traffic:
    airports: list = field(default_factory=list)       # [(lon, lat, ident, name, weight)]
    static: dict = field(default_factory=dict)         # (i, j) at CELL -> density
    live: dict = field(default_factory=dict)           # (i, j) at LIVE_CELL -> civil aircraft
    live_n: int = 0
    live_age_s: float | None = None

    def density(self, lon: float, lat: float, live_w: float) -> tuple[float, int]:
        s = self.static.get((int(lon // CELL), int(lat // CELL)), 0.0)
        n = self.live.get((int(lon // LIVE_CELL), int(lat // LIVE_CELL)), 0)
        return s + live_w * n / LIVE_PER_UNIT, n

    def near(self, lon: float, lat: float) -> tuple | None:
        best = None
        for a in self.airports:
            d = dist_km((lon, lat), (a[0], a[1]))
            if d <= TMA_KM and (best is None or a[4] / (1 + d / 30) > best[0]):
                best = (a[4] / (1 + d / 30), a)
        return best[1] if best else None


def _static(db: Session) -> tuple[list, dict]:
    if "grid" not in _STATIC:
        rows = db.execute(text("""SELECT ST_X(geom), ST_Y(geom), coalesce(icao, ident), name, type FROM civil_airport
                                  WHERE country_iso2 = 'IN' AND type IN ('large_airport', 'medium_airport')""")).all()
        aps = [(float(x), float(y), ident, name, WEIGHT[t]) for x, y, ident, name, t in rows]
        grid = {}
        if aps:
            lon = np.array([a[0] for a in aps])
            lat = np.array([a[1] for a in aps])
            w = np.array([a[4] for a in aps])
            for i in range(int(66 // CELL), int(99 // CELL)):
                for j in range(int(5 // CELL), int(38 // CELL)):
                    cx, cy = (i + 0.5) * CELL, (j + 0.5) * CELL
                    d = 111.2 * np.hypot((lon - cx) * math.cos(math.radians(cy)), lat - cy)
                    hit = d <= TMA_KM
                    if hit.any():
                        grid[(i, j)] = float((w[hit] * (1 - d[hit] / TMA_KM / 2)).sum())   # stronger near the field
        # D44: imported civil terminal airspace (CTR / TMA / ATZ polygons) where present
        for (g,) in db.execute(text("SELECT ST_AsBinary(geom) FROM airspace_zone WHERE kind = 'CIVIL_TERMINAL'")):
            poly = wkb.loads(bytes(g))
            pp = prep(poly)
            x0, y0, x1, y1 = poly.bounds
            for i in range(int(x0 // CELL), int(x1 // CELL) + 1):
                for j in range(int(y0 // CELL), int(y1 // CELL) + 1):
                    if pp.contains(Point((i + 0.5) * CELL, (j + 0.5) * CELL)):
                        grid[(i, j)] = grid.get((i, j), 0.0) + TERMINAL_WEIGHT
        _STATIC["grid"], _STATIC["aps"] = grid, aps
    return _STATIC["aps"], _STATIC["grid"]


def build(db: Session) -> Traffic:
    from ..live import feeds
    aps, grid = _static(db)
    now = time.time()
    live, n, newest = {}, 0, None
    for t in list(feeds.TRACKS.values()):
        if t.get("on_ground") or now - t.get("ts", 0) > LIVE_MAX_AGE_S:
            continue
        if t["hex"] in feeds.MILITARY or t.get("db_military"):
            continue
        k = (int(t["lon"] // LIVE_CELL), int(t["lat"] // LIVE_CELL))
        live[k] = live.get(k, 0) + 1
        n += 1
        newest = max(newest or 0, t["ts"])
    return Traffic(aps, grid, live, n, round(now - newest, 0) if newest else None)


def live_weight(now: datetime, launch: datetime) -> float:
    h = (launch - now).total_seconds() / 3600
    if h <= LIVE_FULL_H:
        return 1.0
    return max(0.0, 1 - (h - LIVE_FULL_H) / (LIVE_ZERO_H - LIVE_FULL_H))


def samples(route: list) -> list[tuple]:
    out = []
    for a, b in zip(route, route[1:]):
        d = dist_km(a, b)
        k = max(1, int(d // SAMPLE_KM))
        out += [(a[0] + (b[0] - a[0]) * i / k, a[1] + (b[1] - a[1]) * i / k) for i in range(k)]
    return out + [tuple(route[-1])] if route else out


def route_profile(tr: Traffic, route: list) -> tuple[list, list]:
    """Static density and live count at each sample along the route (computed once per route)."""
    st, lv = [], []
    for x, y in samples(route):
        s, n = tr.density(x, y, 0.0)
        st.append(s)
        lv.append(n)
    return st, lv


def score(profile: tuple, live_w: float) -> tuple[float, int]:
    """(cost units: density summed per 100 km, index of the busiest sample)."""
    st, lv = profile
    dens = [s + live_w * n / LIVE_PER_UNIT for s, n in zip(st, lv)]
    if not dens:
        return 0.0, 0
    k = max(range(len(dens)), key=dens.__getitem__)
    return sum(dens) * SAMPLE_KM / 100, k


def describe(tr: Traffic, route: list, profile: tuple, live_w: float) -> dict:
    """What the explanation says: how busy, where, and why (TMA and / or live tracks)."""
    st, lv = profile
    pts = samples(route)
    if not pts:
        return {"level": "light", "peak": 0.0}
    dens = [s + live_w * n / LIVE_PER_UNIT for s, n in zip(st, lv)]
    k = max(range(len(dens)), key=dens.__getitem__)
    ap = tr.near(*pts[k])
    level = "busy" if dens[k] >= BUSY else "moderate" if dens[k] >= MODERATE else "light"
    return {"level": level, "peak": round(dens[k], 2), "at": [round(pts[k][0], 3), round(pts[k][1], 3)],
            "airport": f"{ap[2]} {ap[3]}" if ap else None, "live": int(lv[k]) if live_w > 0 else 0,
            "live_weight": round(live_w, 2), "feed_tracks": tr.live_n}
