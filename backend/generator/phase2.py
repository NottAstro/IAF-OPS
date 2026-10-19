"""Phase 2 synthetic data (PHASE2_IMPLEMENTATION_PLAN P1): loadouts, airspace and threat zones, mission requests,
a synthetic base weather forecast and the eight scenarios (D55). Deterministic for SEED + SIM_EPOCH like the rest.

Data-sensitivity rules hold: every geometry is inside India and >= border_buffer_km from the boundary (I8, I15),
threat zones are generic border bands (ARCHITECTURE D31) and loadouts are generic category counts (D30).
"""
import json
import os
import math
import random
from datetime import datetime, timedelta, timezone

from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from app import config
from app.decide import config as D
from app.geo import bearing, dist_km, offset

MISSION_SCALE = float(os.environ.get("MISSION_SCALE", "1"))   # benchmark surge days (app/bench.py); 1 = normal

IST = timezone(timedelta(hours=5, minutes=30))
CENTRE = (78.9, 22.5)
OPERATIONAL = ("WAC", "SWAC", "CAC", "EAC", "SAC")


def R(kind: str, key) -> random.Random:
    return random.Random(f"{config.SEED}:p2:{kind}:{key}")


def ewkt(g) -> str:
    return f"SRID=4326;{g.wkt}"


def rect(cx: float, cy: float, w_km: float, h_km: float) -> Polygon:
    dx = w_km / 2 / (111.32 * math.cos(math.radians(cy)))
    dy = h_km / 2 / 110.57
    return box(cx - dx, cy - dy, cx + dx, cy + dy)


def circle(cx: float, cy: float, r_km: float, n: int = 36) -> Polygon:
    return Polygon([offset(cx, cy, r_km, 360 * i / n) for i in range(n)])


def mountain(lon: float, lat: float, elev: float | None = None) -> bool:
    if elev is not None:
        return elev >= D.MOUNTAIN_ELEVATION_M
    return (lat > 32.5 and lon < 80.5) or (lat > 26.9 and lon > 88.0) or (lat > 30.0 and 78.0 < lon < 81.0)


def generate(conn, W, t0: datetime, G, cmd_id: dict, own: dict, types: dict) -> dict:
    out = {}
    # ------------------------------------------------------------------ generic loadouts + type compatibility
    lrows, tl = [], []
    for code, (name, fams, items, pen, rad, desc) in D.LOADOUTS.items():
        lid = W.next_id("loadout_config")
        lrows.append(dict(id=lid, code=code, name=name, role_family=",".join(fams), items=json.dumps(items),
                          fuel_penalty_pct=pen, radius_factor=rad, description=desc))
        for t in types.values():
            if t["in_service"] and t["_family"] in fams and (code not in D.LOADOUT_ROLES or t["role"] in D.LOADOUT_ROLES[code]):
                tl.append(dict(id=W.next_id("type_loadout"), aircraft_type_id=t["id"], loadout_id=lid))
    W.insert("loadout_config", lrows)
    W.insert("type_loadout", tl)

    # ------------------------------------------------------------------ airspace: training areas, exercise ranges, restricted areas
    zones = []
    fighter_bases = sorted(c for c, b in own.items() if "FIGHTER" in (b["role_tags"] or []) and b["base_type"] != "ALG")
    train_bases = sorted(c for c, b in own.items() if b["base_type"] == "TRAINING_ESTABLISHMENT")
    training = {}
    for code in fighter_bases + train_bases:
        b, rng = own[code], R("ta", code)
        for _ in range(40):
            c = G.place_near(rng, b["_lon"], b["_lat"], 50, 120)
            if c:
                poly = rect(*c, rng.uniform(35, 50), rng.uniform(25, 35))
                if G.inner.contains(poly):
                    training[code] = poly
                    zones.append(dict(code=f"SIM-TA-{code}", name=f"Training area {b['name'].replace('Air Force Station ', '')}",
                                      kind="TRAINING_AREA", geom=ewkt(poly), lower_m=1500, upper_m=12000,
                                      capacity_packages=2, base_id=b["id"]))
                    break
    ranges: dict[str, list] = {c: [] for c in OPERATIONAL}
    for cmd in OPERATIONAL:
        cands = [c for c in fighter_bases if own[c]["_cmd"] == cmd] or [c for c in sorted(own) if own[c]["_cmd"] == cmd]
        rng = R("range", cmd)
        for i in range(2 if cmd in ("WAC", "SWAC", "EAC") else 1):
            b = own[cands[(i * 3) % len(cands)]]
            for _ in range(60):
                c = G.place_near(rng, b["_lon"], b["_lat"], 70, 180)
                if c:
                    poly = rect(*c, 25, 20)
                    if G.inner.contains(poly) and all(not poly.intersects(z) for z in training.values()):
                        ranges[cmd].append(poly)
                        zones.append(dict(code=f"SIM-RNG-{cmd}-{i + 1}", name=f"Exercise range {cmd}-{i + 1} (synthetic)",
                                          kind="DANGER", geom=ewkt(poly), lower_m=0, upper_m=9000, capacity_packages=1,
                                          base_id=None))
                        break
    for i, (lon, lat, name) in enumerate([(78.1, 27.2, "Agra–Mathura"), (85.3, 23.4, "Ranchi"), (80.9, 21.2, "Nagpur east"),
                                          (75.9, 22.7, "Indore"), (77.4, 23.2, "Bhopal")]):
        if all(dist_km((lon, lat), (b["_lon"], b["_lat"])) > 45 for b in own.values()) and G.ok(lon, lat):
            zones.append(dict(code=f"SIM-R-{i + 1:02d}", name=f"Restricted area {name} (synthetic)", kind="RESTRICTED",
                              geom=ewkt(circle(lon, lat, 18)), lower_m=0, upper_m=15000, capacity_packages=0, base_id=None))
    W.insert("airspace_zone", [dict(id=W.next_id("airspace_zone"), **z, is_simulated=True) for z in zones], geom=("geom",))

    # ------------------------------------------------------------------ threat: generic border-proximity bands (D31)
    india = G.shape
    deg = lambda km: km / 100.0  # noqa: E731  (≈ km at Indian latitudes; generous, like geo.BUFFER_DEG)
    prev, trows = None, []
    line = G.control_line if G.control_line is not None else G.hostile_border   # de facto LoC / LAC (D33)
    for i, (km, risk, name) in enumerate(D.BORDER_BANDS):
        band = line.buffer(deg(km)).intersection(india)
        ring = band.difference(prev) if prev is not None else band
        prev = band if prev is None else unary_union([prev, band])
        ring = ring.simplify(0.01, preserve_topology=True)
        polys = [g for g in getattr(ring, "geoms", [ring]) if g.geom_type == "Polygon" and g.area > 1e-4]
        if polys:
            trows.append(dict(id=W.next_id("threat_zone"), code=f"SIM-BAND-{i + 1}", name=name, kind="BORDER_BAND",
                              geom=ewkt(MultiPolygon(polys)), risk_level=risk, is_simulated=True))
    W.insert("threat_zone", trows, geom=("geom",))

    # ------------------------------------------------------------------ mission requests: two IST days
    places = conn.execute("""SELECT name, ST_X(geom), ST_Y(geom), population FROM gis_place WHERE country_code = 'IN'
                             AND population >= 300000 ORDER BY population DESC""").fetchall()
    hostile = G.border_samples(40, hostile_only=True, control=True)

    def from_line(p) -> float:
        return line.distance(Point(p)) * 100 if line is not None else 999.0
    by_cmd = {c: sorted(k for k, b in own.items() if b["_cmd"] == c) for c in OPERATIONAL}

    def nearest_cmd(x, y):
        return min((b for b in own.values() if b["_cmd"] in OPERATIONAL), key=lambda b: dist_km((x, y), (b["_lon"], b["_lat"])))["_cmd"]

    border_by_cmd = {c: [] for c in OPERATIONAL}
    for p in hostile:
        border_by_cmd[nearest_cmd(*p)].append(p)
    remote = sorted(k for k, b in own.items() if b["base_type"] in ("ALG", "FBSU", "HELIBASE") or (b["elevation_m"] or 0) > 2500)

    def place_name(x, y):
        best = min(places, key=lambda p: dist_km((x, y), (p[1], p[2])))
        return best[0]

    def inward(rng, cmd, kmin, kmax):
        """A point kmin..kmax behind the de facto LoC / LAC in the command's sector (and at least kmin from all of it)."""
        pts = border_by_cmd.get(cmd) or []
        for _ in range(80):
            if pts:
                bp = rng.choice(pts)
                c = offset(*bp, rng.uniform(kmin, kmax), bearing(bp, CENTRE) + rng.uniform(-20, 20))
            else:
                b = own[rng.choice(by_cmd[cmd])]
                c = G.place_near(rng, b["_lon"], b["_lat"], kmin, kmax + 60)
            if c and G.ok(*c) and (not pts or from_line(c) >= kmin * 0.85):
                return c
        return None

    def window(rng, day0, kind):
        night = rng.random() < {"AIR_DEFENCE_PATROL": 0.3, "RECCE_ISR": 0.35, "AEW_SUPPORT": 0.3, "CASEVAC": 0.3,
                                "TRAINING": 0.15, "AAR_SUPPORT": 0.2}.get(kind, 0.0)
        start_h = rng.uniform(19, 26) if night else rng.uniform(6.5, 15.5)
        length = {"AIR_DEFENCE_PATROL": (2.5, 4), "RECCE_ISR": (3, 5), "AEW_SUPPORT": (4, 6), "AAR_SUPPORT": (2.5, 3.5),
                  "AIRLIFT": (4, 7), "HADR": (5, 7), "CASEVAC": (2, 3), "STRIKE_EXERCISE": (1.5, 2.5),
                  "CAS_EXERCISE": (1.5, 2.5), "TRAINING": (2.5, 4)}[kind]
        ws = day0 + timedelta(hours=start_h)
        return ws, ws + timedelta(hours=rng.uniform(*length))

    missions, seq = [], {}
    day0 = datetime.combine(t0.astimezone(IST).date(), datetime.min.time(), IST)
    for d in range(2):
        day = day0 + timedelta(days=d)
        for cmd in OPERATIONAL:
            for kind, (pw, roles, (nmin, nmax), on_min, rate) in D.MISSION_TEMPLATES.items():
                rng = R("msn", f"{cmd}:{kind}:{day.date()}")
                rate = rate * (0.5 if cmd in ("CAC", "SAC") and kind in ("AIR_DEFENCE_PATROL", "RECCE_ISR", "AEW_SUPPORT") else 1) * \
                    MISSION_SCALE
                n = int(rate) + (1 if rng.random() < rate - int(rate) else 0)
                for _ in range(n):
                    target, target_base, elev = None, None, None
                    if kind in ("AIR_DEFENCE_PATROL", "AEW_SUPPORT", "AAR_SUPPORT"):
                        target = inward(rng, cmd, *{"AIR_DEFENCE_PATROL": (70, 130), "AEW_SUPPORT": (130, 220),
                                                    "AAR_SUPPORT": (150, 250)}[kind])
                    elif kind == "RECCE_ISR":
                        target = inward(rng, cmd, 45, 95)
                    elif kind in ("AIRLIFT", "CASEVAC"):
                        pool = [c for c in remote if own[c]["_cmd"] == cmd] or [c for c in by_cmd[cmd]]
                        tb = own[rng.choice(pool)]
                        target_base, target, elev = tb, (tb["_lon"], tb["_lat"]), tb["elevation_m"]
                    elif kind == "HADR":
                        cands = [p for p in places if nearest_cmd(p[1], p[2]) == cmd and G.ok(p[1], p[2])]
                        if cands:
                            p = rng.choice(cands[:25])
                            target = G.place_near(rng, p[1], p[2], 5, 30) or (p[1], p[2])
                    elif kind in ("STRIKE_EXERCISE", "CAS_EXERCISE"):
                        if ranges[cmd]:
                            c = rng.choice(ranges[cmd]).centroid
                            target = (c.x, c.y)
                    elif kind == "TRAINING":
                        cands = [c for c in by_cmd[cmd] if c in training]
                        if cands:
                            c = training[rng.choice(cands)].centroid
                            target = (c.x, c.y)
                    if not target or not G.ok(*target):   # I8/I15: ALGs inside the border buffer are skipped too
                        continue
                    prio = rng.choices(D.PRIORITIES, pw)[0]
                    ws, we = window(rng, day, kind)
                    if we < t0 + timedelta(hours=2):        # day 0: only windows still plannable at seed time
                        continue
                    seq[kind] = seq.get(kind, 0) + 1
                    short, label = D.MISSION_LABEL[kind]
                    quals = ["MOUNTAIN_FLYING"] if mountain(*target, elev) and kind in ("AIRLIFT", "CASEVAC", "HADR") else []
                    nreq = rng.randint(nmin, nmax)
                    where = target_base["name"].replace("Air Force Station ", "") if target_base else place_name(*target)
                    missions.append(dict(
                        id=W.next_id("mission"), code=f"SIM-{short}-{cmd}-{seq[kind]:03d}",
                        name=f"{label} {'to' if target_base else 'near'} {where}", mission_type=kind, priority=prio,
                        window_start=ws, window_end=we, status="REQUESTED" if rng.random() < 0.12 else "APPROVED",
                        requesting_command_id=cmd_id[cmd], target_geom=f"SRID=4326;POINT({target[0]:.5f} {target[1]:.5f})",
                        target_base_id=target_base["id"] if target_base else None, required_aircraft=nreq,
                        eligible_roles=roles, loadout_code=None, on_station_min=on_min, min_quals=quals,
                        max_risk="HIGH" if kind == "RECCE_ISR" else "MED", outcome="NONE", on_station_achieved_min=0,
                        approved_at=t0 - timedelta(hours=rng.uniform(1, 12)), depends_on_id=None, is_simulated=True,
                        source="SYNTHETIC"))
    # D41: barrier CAPs under AEW&C cover, inside an AEW orbit's window and needing it on station the whole time
    cmd_of = {i: c for c, i in cmd_id.items()}
    for a in [x for x in missions if x["mission_type"] == "AEW_SUPPORT" and x["status"] == "APPROVED"]:
        rng = R("dep", a["code"])
        if rng.random() > 0.7:
            continue
        cmd = cmd_of[a["requesting_command_id"]]
        target = inward(rng, cmd, 70, 130)
        ws = a["window_start"] + timedelta(minutes=rng.uniform(60, 120))
        we = min(a["window_end"], ws + timedelta(hours=rng.uniform(2.0, 3.0)))
        if not target or not G.ok(*target) or we - ws < timedelta(minutes=90) or we < t0 + timedelta(hours=2):
            continue
        pw, roles, (nmin, _), on_min, _ = D.MISSION_TEMPLATES["AIR_DEFENCE_PATROL"]
        seq["AIR_DEFENCE_PATROL"] = seq.get("AIR_DEFENCE_PATROL", 0) + 1
        missions.append(dict(
            id=W.next_id("mission"), code=f"SIM-CAP-{cmd}-{seq['AIR_DEFENCE_PATROL']:03d}",
            name=f"Barrier CAP under AEW&C cover near {place_name(*target)}", mission_type="AIR_DEFENCE_PATROL",
            priority=a["priority"] if a["priority"] in ("P1", "P2") else "P2", window_start=ws, window_end=we, status="APPROVED",
            requesting_command_id=a["requesting_command_id"], target_geom=f"SRID=4326;POINT({target[0]:.5f} {target[1]:.5f})",
            target_base_id=None, required_aircraft=nmin, eligible_roles=roles, loadout_code=None, on_station_min=on_min,
            min_quals=[], max_risk="MED", outcome="NONE", on_station_achieved_min=0, approved_at=a["approved_at"],
            depends_on_id=a["id"], is_simulated=True, source="SYNTHETIC"))
    # D42: two missions no single package can fly, on day 0: a 6 h continuous CAP (needs reliefs) and a disaster-relief
    # surge needing more utility helicopters than any one base holds (needs parts from several bases)
    rng = R("split", str(day0.date()))
    for kind, cmd, need, hold, length, label, kmin, kmax in (
            ("AIR_DEFENCE_PATROL", "WAC", 2, 360, 8.0, "Continuous CAP (6 h)", 70, 130),
            ("HADR", "WAC", 28, 60, 6.0, "Flood relief surge (Yamuna plains)", None, None)):
        if kind == "HADR":                       # Yamuna flood plain: in reach of the helicopter bases at Sarsawa and Hindan
            target = (77.55, 29.4)
        else:
            target = inward(rng, cmd, kmin, kmax)
        ws = max(t0 + timedelta(hours=2), day0 + timedelta(hours=9))
        if not target or not G.ok(*target):
            continue
        pw, roles, _, _, _ = D.MISSION_TEMPLATES[kind]
        short = D.MISSION_LABEL[kind][0]
        seq[kind] = seq.get(kind, 0) + 1
        missions.append(dict(
            id=W.next_id("mission"), code=f"SIM-{short}-{cmd}-{seq[kind]:03d}", name=f"{label} near {place_name(*target)}",
            mission_type=kind, priority="P1" if kind == "AIR_DEFENCE_PATROL" else "P2", window_start=ws,
            window_end=ws + timedelta(hours=length), status="APPROVED", requesting_command_id=cmd_id[cmd],
            target_geom=f"SRID=4326;POINT({target[0]:.5f} {target[1]:.5f})", target_base_id=None, required_aircraft=need,
            eligible_roles=roles if kind == "AIR_DEFENCE_PATROL" else ["UTILITY_HELO"], loadout_code=None, on_station_min=hold,
            min_quals=[], max_risk="MED", outcome="NONE", on_station_achieved_min=0, approved_at=t0 - timedelta(hours=2),
            depends_on_id=None, is_simulated=True, source="SYNTHETIC"))
    # D55: flying training at the trainer bases the crash scenario hits (Hawk waves at Bidar, Kiran at Hakimpet), so the
    # scenario has packages to break whenever it is started in the two generated days
    pw, _, _, on_min, _ = D.MISSION_TEMPLATES["TRAINING"]
    for code, role, hours, label in (("VOBR", "TRAINER_ADVANCED", (8, 10.5, 13, 15.5, 18, 20.5, 22.5), "Hawk"),
                                     ("VOHK", "TRAINER_INTERMEDIATE", (9, 13.5, 17, 21), "Kiran")):
        if code not in own:
            continue
        b, rng = own[code], R("trg", code)
        area = training.get(code)
        target = (area.centroid.x, area.centroid.y) if area else G.place_near(rng, b["_lon"], b["_lat"], 20, 45)
        if not target or not G.ok(*target):
            continue
        for d in range(2):
            for h in hours:
                ws = day0 + timedelta(days=d, hours=h)
                if ws < t0 + timedelta(minutes=60):
                    continue
                seq["TRAINING"] = seq.get("TRAINING", 0) + 1
                missions.append(dict(
                    id=W.next_id("mission"), code=f"SIM-TRG-{own[code]['_cmd']}-{seq['TRAINING']:03d}",
                    name=f"{label} training wave, {b['name'].replace('Air Force Station ', '')}", mission_type="TRAINING",
                    priority="P3" if rng.random() < 0.3 else "P4", window_start=ws, window_end=ws + timedelta(hours=2.5),
                    status="APPROVED", requesting_command_id=cmd_id.get(own[code]["_cmd"]),
                    target_geom=f"SRID=4326;POINT({target[0]:.5f} {target[1]:.5f})", target_base_id=None,
                    required_aircraft=2, eligible_roles=[role], loadout_code=None, on_station_min=on_min, min_quals=[],
                    max_risk="MED", outcome="NONE", on_station_achieved_min=0, approved_at=t0 - timedelta(hours=6),
                    depends_on_id=None, is_simulated=True, source="SYNTHETIC"))
    W.insert("mission", missions, geom=("target_geom",))
    out["missions"] = len(missions)

    # ------------------------------------------------------------------ synthetic base forecast, 72 h hourly
    wx = []
    start = t0.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    for code in sorted(own):
        b, rng = own[code], R("wx", code)
        lon, lat = b["_lon"], b["_lat"]
        plains = 24 <= lat <= 31.5 and 74 <= lon <= 89          # Indo-Gangetic plain: night / morning fog
        east = lon > 89                                          # north-east: frequent low cloud
        hills = mountain(lon, lat, b["elevation_m"])
        state = 0
        for h in range(74):
            ts = start + timedelta(hours=h)
            hr = ts.astimezone(IST).hour
            fog = plains and (hr >= 23 or hr <= 8)
            p_bad = 0.05 + (0.22 if fog else 0) + (0.12 if east else 0) + (0.10 if hills and 12 <= hr <= 18 else 0)
            target = 0
            u = rng.random()
            if u < p_bad:
                target = 2 if rng.random() < 0.55 else (3 if rng.random() < 0.35 else 1)
            elif u < p_bad + 0.08:
                target = 1
            state = target if rng.random() < 0.45 else state          # persistence between hours
            cat = ("VFR", "MVFR", "IFR", "LIFR")[state]
            ceiling, vis = {0: (None, rng.uniform(8000, 10000)), 1: (rng.uniform(1100, 2900), rng.uniform(5000, 8000)),
                            2: (rng.uniform(550, 950), rng.uniform(1700, 4800)),
                            3: (rng.uniform(150, 450), rng.uniform(300, 1500))}[state]
            wind = rng.uniform(2, 14) + (8 if hills else 0)
            wx.append((b["id"], ts, round(ceiling, -1) if ceiling else None, round(vis, -1), round(wind),
                       round(wind + rng.uniform(4, 12)) if wind > 12 else None, round(rng.uniform(0, 359), -1), cat,
                       "SYNTHETIC", t0, True))
    W.copy("wx_base_forecast", ["base_id", "valid_ts", "ceiling_ft", "vis_m", "wind_kt", "gust_kt", "wind_dir", "flight_cat",
                                "source", "fetched_at", "is_simulated"], wx)

    # ------------------------------------------------------------------ scenarios (D55): one incident each, eight categories
    def toward(code, km):
        """A point km in from the de facto border on the line to a western base: a generic threat area for that sector."""
        b, pts = own.get(code), border_by_cmd.get("WAC") or []
        if not b or not pts:
            return None
        bp = min(pts, key=lambda q: dist_km(q, (b["_lon"], b["_lat"])))
        c = offset(*bp, km, bearing(bp, (b["_lon"], b["_lat"])))
        return c if G.ok(*c) else None
    west = toward("VIAX", 55) or (75.3, 31.6)
    base = lambda key, label, d: dict(key=key, label=label, kind="base", default=d)                       # noqa: E731
    choice = lambda key, label, opts, d, unit="": dict(key=key, label=label, kind="choice", options=opts, default=d,  # noqa: E731
                                                       unit=unit)
    hidden = lambda key, d: dict(key=key, kind="hidden", default=d)                                       # noqa: E731
    scenarios = [
        dict(code="trainer-crash", name="Trainer jet crash at Bidar", category="ACCIDENT", intensity="LOW",
             summary="1 Hawk lost, runway closed 4 h",
             description="A Hawk crashes on the runway during training. The runway closes while the wreck is cleared, and the "
                         "ejected pilot needs picking up.",
             lead="A {type} crashed on the runway at {base_name}. The runway is closed for about {hours} h and the ejected "
                  "pilot needs picking up.",
             params=[base("base", "Base", "VOBR"), dict(key="type", label="Aircraft type", kind="type", default="Hawk 132"),
                     choice("hours", "Runway closed for", [2, 4, 6, 8, 12], 4, "h"), choice("lost", "Aircraft lost", [1, 2], 1)],
             presets={"LOW": {"hours": 4, "lost": 1}, "MEDIUM": {"hours": 6, "lost": 1}, "HIGH": {"hours": 8, "lost": 2},
                      "SEVERE": {"hours": 12, "lost": 2}},
             injects=[dict(offset_min=0, kind="AIRCRAFT_LOST", params={"base": "{base}", "type": "{type}", "count": "{lost}"}),
                      dict(offset_min=0, kind="RUNWAY_CLOSED", params={"base": "{base}", "hours": "{hours}"}),
                      dict(offset_min=0, kind="MISSION_POPUP", params={"mission_type": "CASEVAC", "priority": "P1",
                           "near_base": "{base}", "offset_km": 18, "bearing": 0, "window_h": 3, "place": "the crash site"})]),
        dict(code="runway-closure", name="Runway closure at Halwara", category="INFRASTRUCTURE", intensity="MEDIUM",
             summary="Runway closed 6 h", description="The runway surface fails during the afternoon launch window.",
             lead="{base_name}'s runway surface failed. It is closed for {hours} h.",
             params=[base("base", "Base", "VIHX"), choice("hours", "Runway closed for", [2, 6, 12, 24], 6, "h")],
             presets={"LOW": {"hours": 2}, "MEDIUM": {"hours": 6}, "HIGH": {"hours": 12}, "SEVERE": {"hours": 24}},
             injects=[dict(offset_min=0, kind="RUNWAY_CLOSED", params={"base": "{base}", "hours": "{hours}"})]),
        dict(code="avalanche", name="Avalanche casualty in Ladakh", category="URGENT_TASKING", intensity="MEDIUM",
             summary="Urgent P1 casualty evacuation",
             description="An avalanche hits a high post. Casualties need evacuation to hospital.",
             lead="An avalanche hit a high post near {base_name}. {casualties} casualties must reach hospital within {window_h} h.",
             params=[base("base", "Nearest base", "VI57"), choice("casualties", "Casualties", [1, 3, 6], 3),
                     choice("window_h", "Must reach hospital within", [2, 3, 4], 3, "h"), hidden("required", 1)],
             presets={"LOW": {"casualties": 1, "window_h": 4, "required": 1}, "MEDIUM": {"casualties": 3, "window_h": 3, "required": 1},
                      "HIGH": {"casualties": 6, "window_h": 3, "required": 2}, "SEVERE": {"casualties": 6, "window_h": 2, "required": 2}},
             injects=[dict(offset_min=0, kind="MISSION_POPUP", params={"mission_type": "CASEVAC", "priority": "P1",
                           "near_base": "{base}", "offset_km": 30, "bearing": 120, "window_h": "{window_h}",
                           "required": "{required}", "place": "a high post"}),
                      dict(offset_min=0, kind="MISSION_POPUP", params={"mission_type": "HADR", "priority": "P2",
                           "near_base": "{base}", "offset_km": 30, "bearing": 120, "window_h": 6, "required": 1,
                           "place": "the avalanche post (supply drop)"})]),
        dict(code="monsoon-front", name="Eastern monsoon front", category="WEATHER", intensity="MEDIUM",
             summary="Assam bases below flying minima 8 h", description="Low cloud and heavy rain over Assam.",
             lead="Low cloud and heavy rain put {bases_name} below safe flying minima for {hours} h.",
             params=[dict(key="bases", label="Bases", kind="bases", default=["VETZ", "VEJT", "VECA", "VEMN"]),
                     choice("cat", "Conditions", ["MVFR", "IFR", "LIFR"], "IFR"), choice("hours", "Lasts", [4, 8, 12], 8, "h")],
             presets={"LOW": {"cat": "MVFR", "hours": 4}, "MEDIUM": {"cat": "IFR", "hours": 8}, "HIGH": {"cat": "IFR", "hours": 12},
                      "SEVERE": {"cat": "LIFR", "hours": 12}},
             injects=[dict(offset_min=0, kind="WX_FRONT", params={"bases": "{bases}", "cat": "{cat}", "hours": "{hours}"}),
                      dict(offset_min=0, kind="MISSION_POPUP", params={"mission_type": "HADR", "priority": "P2",
                           "near_base": "VEJT", "offset_km": 40, "bearing": 220, "window_h": "{hours}",
                           "place": "flooded villages south-west of Jorhat"})]),
        dict(code="fuel-disruption", name="Fuel supply disruption", category="LOGISTICS", intensity="MEDIUM",
             summary="Western bases lose most of their usable fuel",
             description="A contaminated batch of fuel is quarantined and the convoys are held: the western bases lose most "
                         "of their usable stock until the next delivery.",
             lead="A contaminated fuel batch is quarantined at {bases_name} and convoys are held {hours} h; usable stock is "
                  "down {loss_pct}%.",
             params=[dict(key="bases", label="Bases", kind="bases", default=["VIHX", "VIAX", "VISA"]),
                     choice("loss_pct", "Usable fuel lost", [60, 80, 90], 80, "%"), choice("hours", "Next delivery in", [12, 24, 48], 24, "h")],
             presets={"LOW": {"loss_pct": 60, "hours": 12}, "MEDIUM": {"loss_pct": 80, "hours": 24},
                      "HIGH": {"loss_pct": 90, "hours": 24}, "SEVERE": {"loss_pct": 90, "hours": 48}},
             injects=[dict(offset_min=0, kind="FUEL_DELAY", params={"bases": "{bases}", "loss_pct": "{loss_pct}", "hours": "{hours}"})]),
        dict(code="fleet-grounding", name="Su-30MKI fleet grounding", category="EQUIPMENT", intensity="HIGH",
             summary="Type grounded 48 h at 3 bases", description="A defect is found; the type is grounded for inspection.",
             lead="A defect grounds every {type} at {bases_name} for {hours} h.",
             params=[dict(key="type", label="Aircraft type", kind="type", default="Su-30MKI"),
                     dict(key="bases", label="Bases", kind="bases", default=["VIHX", "VISA", "VETZ"]),
                     choice("hours", "Grounded for", [24, 48, 72], 48, "h")],
             presets={"LOW": {"hours": 24, "bases": ["VIHX"]}, "MEDIUM": {"hours": 48, "bases": ["VIHX", "VISA"]},
                      "HIGH": {"hours": 48, "bases": ["VIHX", "VISA", "VETZ"]}, "SEVERE": {"hours": 72, "bases": ["VIHX", "VISA", "VETZ"]}},
             injects=[dict(offset_min=0, kind="AIRCRAFT_GROUNDING", params={"type": "{type}", "bases": "{bases}", "count": "all",
                                                                            "hours": "{hours}"})]),
        dict(code="radar-outage", name="Radar network outage", category="SURVEILLANCE", intensity="HIGH",
             summary="Bathinda radars offline", description="Radars at a base go offline, opening a coverage gap.",
             lead="Radars at {base_name} went offline, leaving a coverage gap for about {hours} h.",
             params=[base("base", "Base", "VIBT"), choice("hours", "Offline for", [2, 6, 12], 6, "h"), hidden("window_h", 6)],
             presets={"LOW": {"hours": 2, "window_h": 4}, "MEDIUM": {"hours": 6, "window_h": 6}, "HIGH": {"hours": 6, "window_h": 6},
                      "SEVERE": {"hours": 12, "window_h": 12}},
             injects=[dict(offset_min=0, kind="RADAR_DOWN", params={"base": "{base}", "hours": "{hours}"}),
                      dict(offset_min=0, kind="MISSION_POPUP", params={"mission_type": "AEW_SUPPORT", "priority": "P1",
                           "near_base": "{base}", "offset_km": 0, "window_h": "{window_h}", "place": "the radar gap"}),
                      dict(offset_min=0, kind="MISSION_POPUP", params={"mission_type": "AIR_DEFENCE_PATROL", "priority": "P2",
                           "near_base": "{base}", "offset_km": 30, "bearing": 45, "window_h": 4, "place": "the radar gap"})]),
        dict(code="air-attack", name="Western sector air attack", category="HOSTILE_ACTION", intensity="SEVERE",
             summary="Forward base hit: runway and radar out",
             description="Unknown aircraft strike a forward base in the western sector.",
             lead="Unknown aircraft struck {base_name}. Runway cratered for {hours} h, radars down, and a threat zone covers "
                  "the sector.",
             params=[base("base", "Base hit", "VIAX"), choice("hours", "Runway out for", [6, 12, 24], 12, "h"),
                     hidden("fuel_loss_pct", 30)],
             presets={"LOW": {"hours": 6, "fuel_loss_pct": 0}, "MEDIUM": {"hours": 12, "fuel_loss_pct": 0},
                      "HIGH": {"hours": 12, "fuel_loss_pct": 30}, "SEVERE": {"hours": 24, "fuel_loss_pct": 30}},
             injects=[dict(offset_min=0, kind="BASE_STRIKE", params={"base": "{base}", "hours": "{hours}",
                                                                     "fuel_loss_pct": "{fuel_loss_pct}"}),
                      dict(offset_min=0, kind="THREAT_ZONE", params={"lon": round(west[0], 4), "lat": round(west[1], 4),
                           "radius_km": 35, "risk": 0.8, "hours": 6, "name": "Unknown air activity, western sector (exercise)"}),
                      dict(offset_min=0, kind="MISSION_POPUP", params={"mission_type": "AIR_DEFENCE_PATROL", "priority": "P1",
                           "near_base": "{base}", "offset_km": 25, "bearing": 270, "window_h": 4, "max_risk": "HIGH",
                           "place": "the western sector"}),
                      dict(offset_min=0, kind="MISSION_POPUP", params={"mission_type": "AEW_SUPPORT", "priority": "P2",
                           "near_base": "{base}", "offset_km": 50, "bearing": 135, "window_h": 6, "place": "the western sector"}),
                      dict(offset_min=0, kind="MISSION_POPUP", params={"mission_type": "RECCE_ISR", "priority": "P2",
                           "target_base": "{base}", "window_h": 4})]),
    ]
    W.insert("scenario", [dict(id=W.next_id("scenario"), code=s["code"], name=s["name"], category=s["category"],
                               intensity=s["intensity"], summary=s["summary"], description=s["description"], lead=s["lead"],
                               speed=60, injects=json.dumps(s["injects"]), params=json.dumps(s["params"]),
                               intensity_presets=json.dumps(s["presets"]), version=1, is_simulated=True) for s in scenarios])
    out.update(zones=len(zones), threat_bands=len(trows), wx_rows=len(wx), scenarios=len(scenarios))
    return out
