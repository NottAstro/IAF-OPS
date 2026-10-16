"""Sortie route planning. Every route stays ≥ border_buffer_km inside India (invariant I8)."""
import random

from ..geo import India, bearing, dist_km, offset

KT_TO_KMH = 1.852


def _loop(G: India, rng: random.Random, home: tuple, rmin: float, rmax: float, legs: int = 3):
    for _ in range(40):
        c = G.place_near(rng, *home, rmin, rmax)
        if not c:
            continue
        pts = [home]
        b0 = rng.uniform(0, 360)
        for i in range(legs):
            p = offset(*c, rng.uniform(15, 40), b0 + i * 360 / legs)
            pts.append(p)
        pts.append(home)
        if G.route_ok(pts[1:-1]) and G.route_ok(pts):
            return pts
    return None


def plan(G: India, rng: random.Random, family: str, mission_type: str, home: tuple, dest: tuple | None,
         cruise_kt: float, hours: float) -> tuple[list, float]:
    """Return (waypoints [(lon,lat)...], duration_h). Falls back to a tight local loop if nothing fits."""
    speed = cruise_kt * KT_TO_KMH
    if dest and dest != home:                                   # transport / helicopter leg out and back
        pts = [home, dest, home]
        if G.route_ok(pts):
            return pts, max(hours, 2 * dist_km(home, dest) / speed + 0.3)
    reach = min(speed * hours / 2.5, {"fighter": 180, "trainer": 80, "helo": 70, "uas": 8, "uav": 250}.get(family, 250))
    if mission_type in ("RECCE_ISR", "AEW_SUPPORT", "AAR_SUPPORT", "AIR_DEFENCE_PATROL"):
        pts = _loop(G, rng, home, reach * 0.6, reach, legs=2)  # racetrack
    else:
        pts = _loop(G, rng, home, reach * 0.3, reach * 0.8, legs=3)
    if not pts:
        pts = _loop(G, rng, home, 2, 6, legs=3) or [home, home]
    return pts, hours


def position(pts: list, frac: float) -> tuple[float, float, float]:
    """Point + heading at fraction of total path length."""
    segs = [(pts[i], pts[i + 1], dist_km(pts[i], pts[i + 1])) for i in range(len(pts) - 1)]
    total = sum(s[2] for s in segs) or 1e-9
    target = max(0.0, min(1.0, frac)) * total
    for a, b, d in segs:
        if target <= d or (a, b, d) == segs[-1]:
            f = 0 if d == 0 else min(1.0, target / d)
            return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, bearing(a, b) if d else 0.0
        target -= d
    return pts[-1][0], pts[-1][1], 0.0
