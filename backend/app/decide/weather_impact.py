"""Weather for planning (PHASE2_IMPLEMENTATION_PLAN §7.1): flight category, minima per instrument rating, crosswind,
night. All limits are SIMULATED policy in decide/config.py."""
import math
from datetime import datetime, timedelta, timezone

from . import config as D

CAT_ORDER = ("VFR", "MVFR", "IFR", "LIFR")
CAT_PENALTY = {"VFR": 0, "MVFR": 8, "IFR": 20, "LIFR": 35}


def category(ceiling_ft: float | None, vis_m: float) -> str:
    c = ceiling_ft if ceiling_ft is not None else 99999
    if c < 500 or vis_m < 1600:
        return "LIFR"
    if c < 1000 or vis_m < 4800:
        return "IFR"
    if c <= 3000 or vis_m <= 8000:
        return "MVFR"
    return "VFR"


def worst(*cats: str) -> str:
    return max(cats, key=CAT_ORDER.index)


def crosswind(wind_kt: float, gust_kt: float | None, wind_dir: float | None, rwy_hdg: float | None) -> float:
    w = max(wind_kt or 0, gust_kt or 0)
    if wind_dir is None or rwy_hdg is None:
        return w * 0.7          # unknown geometry: assume an unfavourable 45° component
    return abs(w * math.sin(math.radians(wind_dir - rwy_hdg)))


def rating_needed(row, family: str, rwy_hdg: float | None) -> tuple[str | None, str]:
    """Lowest instrument rating whose minima this weather meets: (rating | None, reason). None = below every minima."""
    if row is None:
        return "WHITE", "no forecast: assumed VFR"
    _, ceiling, vis, wind, gust, wdir, cat, _ = row
    xw = crosswind(wind, gust, wdir, rwy_hdg)
    if xw > D.CROSSWIND_KT.get(family, 25):
        return None, f"crosswind {xw:.0f} kt > {D.CROSSWIND_KT.get(family, 25)} kt"
    c = ceiling if ceiling is not None else 99999
    if family in ("uav", "uas"):
        lc, lv = D.UAV_MINIMA
        return ("WHITE", cat) if c >= lc and vis >= lv else (None, f"{cat} below UAV minima")
    for r in D.RATING_ORDER:
        lc, lv = D.MINIMA[r]
        if c >= lc and vis >= lv:
            return r, cat
    return None, f"{cat} below every minima"


def solar_elevation(lon: float, lat: float, t: datetime) -> float:
    """NOAA approximation, degrees. Good to ~0.5°, enough to tell day from night."""
    t = t.astimezone(timezone.utc)
    n = t.timetuple().tm_yday
    hr = t.hour + t.minute / 60
    g = 2 * math.pi / 365 * (n - 1 + (hr - 12) / 24)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g)
                    - 0.040849 * math.sin(2 * g))
    ha = math.radians((hr * 60 + eqt + 4 * lon) / 4 - 180)
    la = math.radians(lat)
    cz = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    return 90 - math.degrees(math.acos(max(-1.0, min(1.0, cz))))


def is_night(lon: float, lat: float, t: datetime) -> bool:
    return solar_elevation(lon, lat, t) < -6     # after evening civil twilight


def night_between(lon: float, lat: float, a: datetime, b: datetime) -> bool:
    t = a
    while t <= b:
        if is_night(lon, lat, t):
            return True
        t += timedelta(minutes=30)
    return is_night(lon, lat, b)
