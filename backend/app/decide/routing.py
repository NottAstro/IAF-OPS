"""Border-safe routing for plan packages (I8, I15, ARCHITECTURE D34).

Most routes are straight out-and-back lines. When a straight leg would cut the standoff from foreign territory (the
Siliguri corridor is ~22 km wide between Nepal and Bangladesh; Bagdogra sits inside it), legs are routed through a
visibility graph: coarse navigation nodes every 0.5° plus a fine mesh over narrow corridors, Dijkstra, then
string-pulled so the result has as few turns as the geometry allows. Built once per process (< 2 s), cached per leg.

ponytail: corridor meshes are listed by hand (CORRIDORS); add a box if a new chokepoint ever matters.
"""
import heapq
import math
from functools import lru_cache

from shapely.geometry import LineString, Point

from ..geo import India, dist_km

CORRIDORS = [("Siliguri corridor", (87.6, 25.9, 89.6, 27.2), 0.03)]
COARSE = (66.0, 6.0, 98.0, 37.5, 0.5)
_GRAPH = {}


def _clear_seg(G: India, a, b) -> bool:
    return not G.foreign.intersects(LineString([a, b]))


def _build(G: India):
    key = id(G)
    if key in _GRAPH:
        return _GRAPH[key]
    from shapely.prepared import prep
    near = prep(G.shape.simplify(0.05).buffer(0.6))   # nodes over India and its coastal waters only
    nodes = []
    x0, y0, x1, y1, step = COARSE
    y = y0
    while y <= y1:
        x = x0
        while x <= x1:
            if G.clear(x, y) and near.contains(Point(x, y)):
                nodes.append((round(x, 3), round(y, 3), step))
            x += step
        y += step
    for _, (cx0, cy0, cx1, cy1), s in CORRIDORS:
        y = cy0
        while y <= cy1:
            x = cx0
            while x <= cx1:
                if G.clear(x, y):
                    nodes.append((round(x, 3), round(y, 3), s))
                x += s
            y += s
    pts = [(n[0], n[1]) for n in nodes]
    adj = {i: [] for i in range(len(nodes))}
    cells = {}
    for i, (x, y, s) in enumerate(nodes):
        cells.setdefault((int(x // 0.5), int(y // 0.5)), []).append(i)
    for i, (x, y, s) in enumerate(nodes):
        cx, cy = int(x // 0.5), int(y // 0.5)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cells.get((cx + dx, cy + dy), ()):
                    if j <= i:
                        continue
                    xj, yj, sj = nodes[j]
                    r = 1.6 * max(s, sj)
                    if abs(x - xj) <= r and abs(y - yj) <= r and _clear_seg(G, pts[i], pts[j]):
                        d = dist_km(pts[i], pts[j])
                        adj[i].append((j, d))
                        adj[j].append((i, d))
    _GRAPH[key] = (pts, adj, cells)
    return _GRAPH[key]


def _attach(G: India, pts, cells, p, radius_deg=0.8):
    cx, cy = int(p[0] // 0.5), int(p[1] // 0.5)
    out = []
    for dx in (-2, -1, 0, 1, 2):
        for dy in (-2, -1, 0, 1, 2):
            for j in cells.get((cx + dx, cy + dy), ()):
                q = pts[j]
                if abs(q[0] - p[0]) <= radius_deg and abs(q[1] - p[1]) <= radius_deg and _clear_seg(G, p, q):
                    out.append((j, dist_km(p, q)))
    return out


def leg(G: India, a: tuple, b: tuple) -> list | None:
    """Border-safe polyline from a to b (both must be clear), or None."""
    return _leg(G, (round(a[0], 4), round(a[1], 4)), (round(b[0], 4), round(b[1], 4)))


@lru_cache(maxsize=4096)
def _leg_cached(gid: int, a: tuple, b: tuple):
    G = _GIDS[gid]
    if not G.clear(*a) or not G.clear(*b):
        return None
    if _clear_seg(G, a, b):
        return (a, b)
    pts, adj, cells = _build(G)
    sa, sb = _attach(G, pts, cells, a), _attach(G, pts, cells, b)
    if not sa or not sb:
        return None
    target = {j: d for j, d in sb}
    dist, prev = {}, {}
    heap = []
    for j, d in sa:
        if d < dist.get(j, math.inf):
            dist[j], prev[j] = d, None
            heapq.heappush(heap, (d + dist_km(pts[j], b), d, j))
    best, end = math.inf, None
    while heap:
        f, d, i = heapq.heappop(heap)
        if d > dist.get(i, math.inf) or f >= best:
            continue
        if i in target and d + target[i] < best:
            best, end = d + target[i], i
        for j, w in adj[i]:
            nd = d + w
            if nd < dist.get(j, math.inf):
                dist[j], prev[j] = nd, i
                heapq.heappush(heap, (nd + dist_km(pts[j], b), nd, j))
    if end is None:
        return None
    path = [b]
    i = end
    while i is not None:
        path.append(pts[i])
        i = prev[i]
    path.append(a)
    path.reverse()
    out = [path[0]]                       # string-pull: keep only the turns the geometry needs
    k = 0
    while k < len(path) - 1:
        nxt = len(path) - 1
        while nxt > k + 1 and not _clear_seg(G, path[k], path[nxt]):
            nxt -= 1
        out.append(path[nxt])
        k = nxt
    return tuple(out)


_GIDS: dict[int, India] = {}


def _leg(G: India, a, b):
    _GIDS[id(G)] = G
    r = _leg_cached(id(G), a, b)
    return list(r) if r else None


def route(G: India, waypoints: list) -> list | None:
    """Chain legs through the given waypoints; None if any leg can't be made safe."""
    out = []
    for a, b in zip(waypoints, waypoints[1:]):
        lg = leg(G, a, b)
        if lg is None:
            return None
        out += lg if not out else lg[1:]
    return out
