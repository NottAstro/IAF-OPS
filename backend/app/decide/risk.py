"""Route risk and airspace (PHASE2_IMPLEMENTATION_PLAN §7.1). Threat zones are generic (ARCHITECTURE D31)."""
from datetime import datetime

from shapely.geometry import LineString, Point

from ..geo import dist_km
from .snapshot import OpsState, Zone


def sample(pts: list, step_km: float = 10.0) -> list:
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        d = dist_km(a, b)
        n = max(1, int(d // step_km))
        out += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(1, n + 1)]
    return out


def point_risk(st: OpsState, x: float, y: float, a: datetime, b: datetime) -> tuple[float, Zone | None]:
    best, zone = 0.0, None
    p = Point(x, y)
    for z in st.threats:
        if z.risk > best and z.active(a, b) and z.prepared.contains(p):
            best, zone = z.risk, z
    return best, zone


def route_risk(st: OpsState, pts: list, a: datetime, b: datetime) -> tuple[float, float, str | None]:
    """(peak risk 0..1, exposure = Σ risk × km, name of the worst zone)."""
    peak, exposure, worst = 0.0, 0.0, None
    sp = sample(pts)
    for p, q in zip(sp, sp[1:]):
        r, z = point_risk(st, (p[0] + q[0]) / 2, (p[1] + q[1]) / 2, a, b)
        exposure += r * dist_km(p, q)
        if r > peak:
            peak, worst = r, z.name if z else None
    return peak, exposure, worst


def restricted_hit(st: OpsState, pts: list, a: datetime, b: datetime) -> Zone | None:
    line = LineString(pts)
    for z in st.airspace:
        if z.kind in ("RESTRICTED", "TEMP_RESERVATION") and not z.code.startswith("RWY-") and z.active(a, b) \
                and z.prepared.intersects(line) and not z.prepared.contains(Point(pts[0])):
            return z
    return None


def zone_for_target(st: OpsState, target: tuple) -> Zone | None:
    p = Point(target)
    for z in st.airspace:
        if z.kind in ("TRAINING_AREA", "DANGER") and z.capacity > 0 and z.prepared.contains(p):
            return z
    return None
