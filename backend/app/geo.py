"""India outline + border-buffer geometry shared by the generator and the simulator (invariant I8)."""
import math
from dataclasses import dataclass

from shapely import wkb
from shapely.geometry import LineString, Point
from shapely.ops import unary_union
from shapely.prepared import prep
from sqlalchemy import text

from . import config

BUFFER_DEG = config.BORDER_BUFFER_KM / 100.0  # ≥ the buffer on both axes at Indian latitudes
NEIGHBOURS = ["PAK", "CHN", "NPL", "BTN", "BGD", "MMR", "LKA", "AFG"]


def offset(lon: float, lat: float, km: float, bearing: float) -> tuple[float, float]:
    b = math.radians(bearing)
    return (lon + km * math.sin(b) / (111.32 * math.cos(math.radians(lat))), lat + km * math.cos(b) / 110.57)


def dist_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = (a[0] - b[0]) * 111.32 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot(dx, (a[1] - b[1]) * 110.57)


def bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = (b[0] - a[0]) * math.cos(math.radians((a[1] + b[1]) / 2))
    return (math.degrees(math.atan2(dx, b[1] - a[1])) + 360) % 360


@dataclass
class India:
    shape: object
    inner_shape: object
    inner: object          # prepared: inside India and ≥ buffer from the boundary
    outside: object        # prepared India polygon grown by the buffer (unknown tracks must stay outside it)
    land_border: object
    hostile_border: object

    def ok(self, x: float, y: float) -> bool:
        return self.inner.contains(Point(x, y))

    def route_ok(self, coords: list[tuple[float, float]]) -> bool:
        return self.inner.contains(LineString(coords)) if len(coords) > 1 else self.ok(*coords[0])

    def place_near(self, rng, lon, lat, rmin, rmax, tries=60):
        for _ in range(tries):
            x, y = offset(lon, lat, rng.uniform(rmin, rmax), rng.uniform(0, 360))
            if self.ok(x, y):
                return x, y
        return None

    def border_samples(self, step_km: float, hostile_only: bool = False) -> list[tuple[float, float]]:
        geom = self.hostile_border if hostile_only else self.land_border
        out = []
        for line in getattr(geom, "geoms", [geom]):
            if line.geom_type != "LineString":
                continue
            step, d = step_km / 105.0, step_km / 210.0
            while d < line.length:
                p = line.interpolate(d)
                out.append((p.x, p.y))
                d += step
        return out


def load_india(conn) -> India:
    """conn: SQLAlchemy Session/Connection, or a raw psycopg connection (generator)."""
    import psycopg
    if isinstance(conn, psycopg.Connection):
        def run(q, p=None):
            return conn.execute(q.replace(":c", "%(c)s"), p or {})
    else:
        def run(q, p=None):
            return conn.execute(text(q), p or {})
    row = run("SELECT ST_AsBinary(geom_mid) FROM gis_admin_area WHERE level='ADM0' AND country_iso3='IND'").fetchone()
    if not row:
        raise SystemExit("India outline missing: run pipeline/run_pipeline.py first")
    india = wkb.loads(bytes(row[0]))
    inner_shape = india.buffer(-BUFFER_DEG)

    def union(codes):
        return unary_union([wkb.loads(bytes(g)) for (g,) in run(
            "SELECT ST_AsBinary(geom_lo) FROM gis_admin_area WHERE level='ADM0' AND country_iso3 = ANY(:c)", {"c": codes})])
    land = india.boundary.intersection(union(NEIGHBOURS).buffer(0.05))
    hostile = india.boundary.intersection(union(["PAK", "CHN"]).buffer(0.05))
    return India(india, inner_shape, prep(inner_shape), prep(india.buffer(BUFFER_DEG)), land, hostile)
