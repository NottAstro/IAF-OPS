"""Synthetic data generator (DATA_MODEL §8). Run from backend/:  ../.venv/bin/python -m generator

Wipes and rebuilds every operational table (GIS tables from the pipeline are kept).
Deterministic for a fixed SEED + SIM_EPOCH (env). Prints a checksum; run twice to compare.
"""
import csv
import math
import os
import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
from shapely import wkb

from app import config
from app.geo import dist_km, load_india
from app.init_db import init_db
from app.security import hash_password

from . import config as C

CURATED = config.ROOT / "data" / "curated"
DSN = config.DATABASE_URL.replace("+psycopg", "")
SEED = config.SEED
OPERATIONAL_TABLES = [
    "sortie_crew", "sortie_aircraft", "fuel_transaction", "duty_roster_entry", "stock_level", "stock_item",
    "warehouse", "ground_asset", "ground_crew_strength", "aircrew_posting", "aircrew_qualification",
    "aircrew_type_hours", "sortie", "mission", "aircraft", "aircrew", "qra_posture", "squadron", "parking_facility",
    "fuel_storage", "runway", "air_defence_battery", "radar_site", "comms_link", "comms_node", "ad_system_type",
    "radar_type", "app_user", "base", "aircraft_type", "command", "alert", "kpi_snapshot", "sim_state", "audit_log",
]


def R(kind: str, key) -> random.Random:
    """Per-entity sub-seed: adding one base never reshuffles another (DATA_MODEL §8.2)."""
    return random.Random(f"{SEED}:{kind}:{key}")


def pick(rng: random.Random, weighted: list[tuple]) -> str:
    return rng.choices([w[0] for w in weighted], [w[1] for w in weighted])[0]


def pt(lon: float, lat: float) -> str:
    return f"SRID=4326;POINT({lon:.6f} {lat:.6f})"


def read(name: str) -> list[dict]:
    return list(csv.DictReader(open(CURATED / name, encoding="utf-8")))


class Writer:
    def __init__(self, conn):
        self.conn, self.ids = conn, defaultdict(int)

    def next_id(self, table: str) -> int:
        self.ids[table] += 1
        return self.ids[table]

    def insert(self, table: str, rows: list[dict], geom: tuple = ()) -> None:
        if not rows:
            return
        cols = list(rows[0])
        ph = ",".join(f"ST_GeomFromEWKT(%({c})s)" if c in geom else f"%({c})s" for c in cols)
        with self.conn.cursor() as cur:
            cur.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph})", rows)

    def copy(self, table: str, cols: list[str], rows: list[tuple]) -> None:
        with self.conn.cursor() as cur, cur.copy(f"COPY {table} ({','.join(cols)}) FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)


def main() -> None:
    t0 = datetime.fromisoformat(os.environ["SIM_EPOCH"]) if os.environ.get("SIM_EPOCH") else \
        datetime.now(timezone.utc).replace(second=0, microsecond=0)
    init_db()
    conn = psycopg.connect(DSN)
    W = Writer(conn)
    conn.execute(f"TRUNCATE {', '.join(OPERATIONAL_TABLES)} RESTART IDENTITY CASCADE")

    # ------------------------------------------------------------------ geography (from the GIS pipeline)
    G = load_india(conn)
    inner, place_near, border_samples = G.inner, G.place_near, G.border_samples

    # ------------------------------------------------------------------ commands + bases
    cmd_id = {}
    rows = []
    for code, (name, hq, lon, lat, op) in C.COMMANDS.items():
        cmd_id[code] = W.next_id("command")
        rows.append(dict(id=cmd_id[code], code=code, name=name, hq_name=hq, hq_geom=pt(lon, lat), is_operational=op,
                         is_simulated=False, source="PUBLIC",
                         source_ref="https://en.wikipedia.org/wiki/List_of_Indian_Air_Force_stations"))
    W.insert("command", rows, geom=("hq_geom",))

    bases: dict[str, dict] = {}  # code -> base dict (+ helper keys)

    def add_base(code, d):
        d["id"] = W.next_id("base")
        bases[code] = d

    for r in read("iaf_bases.csv"):
        code = r["icao"] or r["ident"]
        rng = R("base", code)
        add_base(code, dict(code=code, iata=r["iata"] or None, name=r["name"], country_iso3="IND", side="OWN",
                            operator="IAF", base_type=r["base_type"], command_id=cmd_id[r["command"]],
                            wing=r["wing"] or None, role_tags=r["role_tags"].split(","),
                            geom=pt(float(r["lon"]), float(r["lat"])),
                            elevation_m=float(r["elevation_m"]) if r["elevation_m"] else None,
                            ops_status="LIMITED" if rng.random() < 0.04 else "OPERATIONAL", affiliation="FRIEND",
                            public_notes=None, wikipedia_url=r["source_url"], ourairports_id=r["ident"],
                            is_simulated=False, source="PUBLIC", source_ref=r["source_url"],
                            _lon=float(r["lon"]), _lat=float(r["lat"]), _cmd=r["command"], _size=r["size_class"]))
    for r in read("other_indian_mil.csv"):
        code = r["icao"] or r["ident"]
        add_base(code, dict(code=code, iata=None, name=r["name"], country_iso3="IND", side="OTHER_INDIAN_MIL",
                            operator=r["operator"], base_type="OTHER_INDIAN_MIL", command_id=None, wing=None,
                            role_tags=None, geom=pt(float(r["lon"]), float(r["lat"])),
                            elevation_m=float(r["elevation_m"]) if r["elevation_m"] else None, ops_status="OPERATIONAL",
                            affiliation="FRIEND", public_notes=r["public_notes"], wikipedia_url=r["source_url"],
                            ourairports_id=r["ident"], is_simulated=False, source="PUBLIC", source_ref=r["source_url"],
                            _lon=float(r["lon"]), _lat=float(r["lat"]), _cmd=None, _size="S"))
    for r in read("neighbour_bases.csv"):
        code = r["icao"] or r["ident"]
        joint = "joint" in r["public_notes"].lower() or r["operator"] == "CIVIL_JOINT"
        add_base(code, dict(code=code, iata=None, name=r["name"], country_iso3=r["country_iso3"], side="FOREIGN",
                            operator=r["operator"], base_type="FOREIGN_JOINT_USE" if joint else "FOREIGN_MILITARY",
                            command_id=None, wing=None, role_tags=None, geom=pt(float(r["lon"]), float(r["lat"])),
                            elevation_m=float(r["elevation_m"]) if r["elevation_m"] else None, ops_status="OPERATIONAL",
                            affiliation="HOSTILE" if r["country_iso3"] in ("PAK", "CHN") else "NEUTRAL",
                            public_notes=r["public_notes"], wikipedia_url=r["source_url"], ourairports_id=r["ident"],
                            is_simulated=False, source="PUBLIC", source_ref=r["source_url"],
                            _lon=float(r["lon"]), _lat=float(r["lat"]), _cmd=None, _size="S"))
    W.insert("base", [{k: v for k, v in b.items() if not k.startswith("_")} for b in bases.values()], geom=("geom",))
    own = {c: b for c, b in bases.items() if b["side"] == "OWN"}
    by_ident = {b["ourairports_id"]: b for b in bases.values()}

    # ------------------------------------------------------------------ runways (public dimensions, synthetic status)
    surf = {"ASP": "ASPHALT", "CON": "CONCRETE", "GRV": "GRAVEL", "GRA": "GRAVEL", "GRS": "GRASS", "TUR": "GRASS"}
    rows = []
    for r in csv.DictReader(open(config.ROOT / "data" / "raw" / "runways.csv", encoding="utf-8")):
        b = by_ident.get(r["airport_ident"])
        if not b or r["closed"] == "1":
            continue
        line = None
        if r["le_latitude_deg"] and r["he_latitude_deg"]:
            line = (f"SRID=4326;LINESTRING({r['le_longitude_deg']} {r['le_latitude_deg']},"
                    f"{r['he_longitude_deg']} {r['he_latitude_deg']})")
        rows.append(dict(id=W.next_id("runway"), base_id=b["id"], designator=f"{r['le_ident']}/{r['he_ident']}".strip("/"),
                         length_m=round(float(r["length_ft"]) * 0.3048) if r["length_ft"] else None,
                         width_m=round(float(r["width_ft"]) * 0.3048) if r["width_ft"] else None,
                         surface=surf.get(r["surface"][:3].upper(), "UNKNOWN"),
                         heading_true_deg=float(r["le_heading_degT"]) if r["le_heading_degT"] else None,
                         lighted=r["lighted"] == "1", geom=line,
                         status="UNDER_REPAIR" if b["side"] == "OWN" and R("rwy", r["id"]).random() < 0.03 else "OPEN",
                         is_simulated=False, source="PUBLIC", source_ref="https://ourairports.com/data/"))
    W.insert("runway", rows, geom=("geom",))

    # ------------------------------------------------------------------ aircraft types
    types: dict[str, dict] = {}
    rows = []
    for r in read("aircraft_types.csv"):
        t = dict(id=W.next_id("aircraft_type"), name=r["name"], icao_type=r["icao_type"], variant=r["variant"],
                 manufacturer=r["manufacturer"], category=r["category"], role=r["role"],
                 seats_pilot=int(r["seats_pilot"]), seats_other=int(r["seats_other"]),
                 max_fuel_kg=float(r["max_fuel_kg"]), burn_kg_per_h=float(r["burn_kg_per_h"]),
                 cruise_kt=float(r["cruise_kt"]), endurance_h=float(r["endurance_h"]),
                 combat_radius_km=float(r["combat_radius_km"]) or None, slot_size=r["slot_size"],
                 maint_interval_h=int(r["maint_interval_h"]), turnaround_min=int(r["turnaround_min"]),
                 serial_prefix=r["serial_prefix"], sidc_function=r["sidc_function"],
                 in_service=r["in_service"] == "1", is_simulated=False, source="PUBLIC",
                 source_ref="https://en.wikipedia.org/wiki/List_of_active_Indian_military_aircraft")
        rows.append(t)
        types[t["name"]] = dict(t, _target=int(r["target_fleet"]), _family=C.ROLE_FAMILY[r["role"]][0],
                                _tag=C.ROLE_FAMILY[r["role"]][1])
    W.insert("aircraft_type", rows)

    def crew_family(t):
        return "fighter2" if t["_family"] == "fighter" and t["seats_other"] > 0 else t["_family"]

    # ------------------------------------------------------------------ squadrons (real public ORBAT + SIM flights)
    squads: list[dict] = []
    real = defaultdict(list)
    for r in read("iaf_squadrons.csv"):
        b = by_ident[r["home_base_ident"]]
        real[r["aircraft_type"]].append(dict(number=r["number"], name=r["name"] or None, type=r["aircraft_type"],
                                             base=b["code"], source_ref=r["source_url"], is_simulated=False,
                                             source="PUBLIC"))
    for tname, t in types.items():
        target, fam = t["_target"], t["_family"]
        if target <= 0:
            continue
        cap = C.ROLE_UE_CAP.get(t["role"], C.UE_CAP[fam])
        rs = real.get(tname, [])
        left = target
        for i, s in enumerate(rs):
            ue = min(cap, math.ceil(left / (len(rs) - i)))
            s["ue"] = ue
            left -= ue
            squads.append(s)
        n = 0
        while left > 0:  # remainder -> SIM flights at bases with the matching role tag
            n += 1
            rng = R("simflight", f"{tname}:{n}")
            cands = sorted(c for c, b in own.items() if t["_tag"] in b["role_tags"] and b["base_type"] != "ALG")
            cands = cands or sorted(c for c, b in own.items() if "TRANSPORT" in b["role_tags"])
            base = rng.choice(cands)
            ue = min(cap, left)
            squads.append(dict(number=f"SIM {tname} Flt {n}", name=None, type=tname, base=base, ue=ue,
                               source_ref=None, is_simulated=True, source="SYNTHETIC"))
            left -= ue
    uas = types["Small UAS (generic)"]
    for code in sorted(own):
        b = own[code]
        if b["base_type"] != "ALG" and ({"FIGHTER", "HELO"} & set(b["role_tags"])):
            squads.append(dict(number=f"SIM UAS Flt {code}", name=None, type=uas["name"], base=code,
                               ue=R("uas", code).randint(2, 10), source_ref=None, is_simulated=True, source="SYNTHETIC"))
    rows = []
    for s in squads:
        s["id"] = W.next_id("squadron")
        t = types[s["type"]]
        rows.append(dict(id=s["id"], number=s["number"], name=s["name"], role=t["role"], aircraft_type_id=t["id"],
                         home_base_id=own[s["base"]]["id"], wing=own[s["base"]]["wing"], unit_establishment=s["ue"],
                         is_simulated=s["is_simulated"], source=s["source"], source_ref=s["source_ref"]))
    W.insert("squadron", rows)

    # ------------------------------------------------------------------ airframes
    maint_bases = sorted(c for c, b in own.items() if b["base_type"] == "BASE_REPAIR_DEPOT")
    serial = defaultdict(lambda: 9000)
    aircraft: list[dict] = []
    for s in squads:
        t = types[s["type"]]
        fam = t["_family"]
        sv = C.SERVICEABILITY_BY_TYPE.get(t["name"], C.SERVICEABILITY[fam])
        y0, y1 = C.SERVICE_WINDOW.get(t["name"], (2000, 2020))
        for i in range(s["ue"]):
            serial[t["serial_prefix"]] += 1
            tail = f"{t['serial_prefix']}{serial[t['serial_prefix']]}"
            rng = R("aircraft", tail)
            year = rng.randint(y0, y1)
            years = max(0.3, t0.year - year + rng.random())
            hours = years * rng.uniform(*C.ANNUAL_HOURS[fam]) * rng.lognormvariate(0, 0.25)
            since = rng.uniform(0, t["maint_interval_h"])
            home = own[s["base"]]
            cur_base = home["id"]
            u = rng.random()
            if u < 0.03 and maint_bases and fam != "uas":
                status, cur_base = "DEPOT", own[rng.choice(maint_bases)]["id"]
            elif u < sv:
                status = "STANDBY" if rng.random() < 0.12 else "AVAILABLE"
            else:
                status = pick(rng, [("MAINT_SCHEDULED", 60), ("MAINT_UNSCHEDULED", 30), ("AOG", 10)])
            ac = dict(id=W.next_id("aircraft"), tail_no=tail, aircraft_type_id=t["id"], squadron_id=s["id"],
                      home_base_id=home["id"], current_base_id=cur_base, status=status, status_reason=None,
                      readiness_min=30 if status == "STANDBY" else None, airframe_hours=round(hours, 1),
                      hours_since_maint=round(since, 1),
                      next_maint_due_hours=round(hours - since + t["maint_interval_h"], 1),
                      next_maint_due_date=None,
                      maint_eta=t0 + timedelta(hours=rng.uniform(4, 96)) if status.startswith("MAINT") or status == "AOG" else None,
                      fuel_kg=round(t["max_fuel_kg"] * (rng.uniform(0.6, 1.0) if status in ("AVAILABLE", "STANDBY") else rng.uniform(0, 0.3))),
                      induction_year=year, last_sortie_at=None, _fam=fam, _type=t, _squad=s, _home=s["base"])
            aircraft.append(ac)
    # detachments: fighters to another fighter base of the same command, helicopters to ALGs
    for ac in aircraft:
        rng = R("detach", ac["tail_no"])
        if ac["status"] == "AVAILABLE" and ac["_fam"] in ("fighter", "helo") and rng.random() < C.DETACHED_FRACTION:
            home = own[ac["_home"]]
            want = "ALG" if ac["_fam"] == "helo" else None
            cands = sorted(c for c, b in own.items() if b["_cmd"] == home["_cmd"] and c != ac["_home"] and (
                b["base_type"] == want if want else "FIGHTER" in b["role_tags"]))
            if cands:
                ac["current_base_id"] = own[rng.choice(cands)]["id"]

    # ------------------------------------------------------------------ QRA posture
    qra_rows = []
    fighters_at = defaultdict(lambda: defaultdict(list))
    for ac in aircraft:
        if ac["_fam"] == "fighter" and ac["current_base_id"] == own[ac["_home"]]["id"]:
            fighters_at[ac["_home"]][ac["_type"]["name"]].append(ac)
    for code in sorted(fighters_at):
        b = own[code]
        if b["_cmd"] in ("TC", "MC"):
            continue
        tname = max(sorted(fighters_at[code]), key=lambda n: len(fighters_at[code][n]))
        ready = 5 if b["_cmd"] in ("WAC", "SWAC", "EAC") else 15
        qra_rows.append(dict(id=W.next_id("qra_posture"), base_id=b["id"], aircraft_type_id=types[tname]["id"],
                             required_aircraft=2, readiness_min=ready, active=True))
        for ac in [a for a in fighters_at[code][tname] if a["status"] in ("AVAILABLE", "STANDBY")][:2]:
            ac["status"], ac["readiness_min"] = "QRA", ready
    W.insert("aircraft", [{k: v for k, v in a.items() if not k.startswith("_")} for a in aircraft])
    W.insert("qra_posture", qra_rows)
    qra_bases = {r["base_id"]: r for r in qra_rows}

    # ------------------------------------------------------------------ parking (slots = ceil(home aircraft x 1.2))
    rows = []
    home_by_size = defaultdict(lambda: defaultdict(int))
    for ac in aircraft:
        home_by_size[ac["_home"]][ac["_type"]["slot_size"]] += 1
    for code in sorted(own):
        b = own[code]
        rng = R("parking", code)
        sizes = home_by_size.get(code) or {"M": 2, "L": 1}
        for size, n in sorted(sizes.items()):
            slots = math.ceil(n * 1.2) + rng.randint(1, 3)
            if size == "M" and "FIGHTER" in b["role_tags"]:
                has = math.ceil(slots * 0.65)
                kinds = [("HAS", has), ("OPEN_APRON", slots - has)]
            else:
                kinds = [({"S": "HELIPAD", "M": "OPEN_APRON", "L": "TRANSPORT_APRON", "XL": "TRANSPORT_APRON"}[size], slots)]
            for kind, n_slots in kinds:
                if n_slots > 0:
                    rows.append(dict(id=W.next_id("parking_facility"), base_id=b["id"], kind=kind, slot_size=size,
                                     slots_total=n_slots, slots_unserviceable=int(rng.random() < 0.15)))
        rows.append(dict(id=W.next_id("parking_facility"), base_id=b["id"], kind="MAINT_HANGAR", slot_size="L",
                         slots_total=rng.randint(1, 4), slots_unserviceable=0))
    W.insert("parking_facility", rows)

    # ------------------------------------------------------------------ aircrew (fictional), careers, quals
    first = [r["first_name"] for r in read("names_first.csv")]
    last = [r["last_name"] for r in read("names_last.csv")]
    calls = [r["word"] for r in read("callsign_words.csv")]
    deny = {r["full_name"].lower() for r in read("names_denylist.csv")}
    crew: list[dict] = []
    type_hours, quals, postings = [], [], []
    pools = defaultdict(lambda: defaultdict(list))  # squad id -> role -> [crew]

    def make_person(key, rank, role, stream, squad, base_code, ctype):
        rng = R("crew", key)
        while True:
            fn, ln = rng.choice(first), rng.choice(last)
            if f"{fn} {ln}".lower() not in deny:
                break
        yrs = rng.uniform(*C.YEARS_BY_RANK[rank])
        commission = (t0 - timedelta(days=yrs * 365.25)).date()
        dob = commission - timedelta(days=rng.uniform(21, 23.5) * 365.25)
        med = pick(rng, C.MEDICAL_MIX)
        med_valid = (t0 + timedelta(days=rng.uniform(3, 28) if med == "FIT_FULL_EXPIRING" else rng.uniform(40, 365))).date()
        med = "FIT_FULL" if med == "FIT_FULL_EXPIRING" else med
        duty = pick(rng, C.DUTY_MIX)
        if med == "TEMP_UNFIT":
            duty = rng.choice(["OFF_DUTY", "SICK"])
        cid = W.next_id("aircrew")
        suffix = {"PILOT": "F(P)", "WSO": "F(N)", "NAVIGATOR": "F(N)", "FLIGHT_ENGINEER": "F(FE)",
                  "LOADMASTER": "F(LM)", "FLIGHT_GUNNER": "F(FG)", "RPA_PILOT": "F(P)", "PAYLOAD_OPERATOR": "F(PO)"}[role]
        p = dict(id=cid, service_no=f"SIM-{20000 + cid}-{suffix}", rank=rank, first_name=fn, last_name=ln,
                 callsign=rng.choice(calls), date_of_birth=dob, commission_date=commission, aircrew_role=role,
                 stream=stream, squadron_id=squad["id"] if squad else None, base_id=own[base_code]["id"],
                 appointment=None, ops_category="FULLY_OPERATIONAL", instrument_rating="GREEN",
                 medical_status=med, medical_valid_until=med_valid, duty_status=duty,
                 rest_started_at=t0 - timedelta(hours=rng.uniform(1, 9)) if duty == "CREW_REST" else None,
                 total_hours=0.0, night_hours=0.0, instrument_hours=0.0, _rng=rng, _years=yrs, _type=ctype,
                 _base=base_code, _hist_hours=0.0, _last=None)
        # career: training types then (maybe) MiG-21, then current type
        rate = C.HOURS_PER_YEAR[stream] if role in ("PILOT", "RPA_PILOT") else C.HOURS_PER_YEAR[stream] * 0.8
        total = max(40.0, yrs * rate * rng.lognormvariate(0, 0.2))
        career = []
        if role == "PILOT":
            if stream == "FIGHTER":
                career = [("PC-7 Mk II", 55, "VODG"), ("Kiran", 80, "VODG"), ("Hawk 132", 100, "VOBR")]
                if commission.year < 2022 and ctype["name"] in ("Su-30MKI", "MiG-29", "Jaguar", "Mirage 2000") and rng.random() < 0.4:
                    career.append(("MiG-21 Bison", round(total * 0.3), "VIBK"))
            elif stream == "TRANSPORT":
                career = [("PC-7 Mk II", 55, "VODG"), ("Kiran", 40, "VODG"), ("Do-228", 60, "VOYK")]
            elif stream == "HELICOPTER":
                career = [("PC-7 Mk II", 55, "VODG"), ("Cheetah/Chetak", 80, "VOHK")]
        elif role == "RPA_PILOT":
            career = [("PC-7 Mk II", 55, "VODG")]
        d = commission
        for tname, h, bcode in career:
            if tname == ctype["name"]:
                continue
            span = timedelta(days=max(120, h * 4))
            postings.append(dict(aircrew_id=cid, squadron_id=None, base_id=own[bcode]["id"],
                                 aircraft_type_id=types[tname]["id"], appointment="Trainee" if h < 150 else "Line pilot",
                                 from_date=d, to_date=d + span))
            type_hours.append(dict(aircrew_id=cid, aircraft_type_id=types[tname]["id"], hours=float(h),
                                   captain_hours=float(h) * 0.5, night_hours=h * 0.1, instrument_hours=h * 0.05,
                                   last_flown_at=datetime.combine(d + span, datetime.min.time(), timezone.utc)))
            total = max(total, sum(x[1] for x in career) + 20)
            d = d + span
        prior = sum(h for tname, h, _ in career if tname != ctype["name"])
        cur_h = max(15.0, total - prior)
        postings.append(dict(aircrew_id=cid, squadron_id=squad["id"] if squad else None, base_id=own[base_code]["id"],
                             aircraft_type_id=ctype["id"], appointment=None, from_date=max(d, (t0 - timedelta(days=rng.uniform(200, 1200))).date()),
                             to_date=None))
        p["_cur_hours"] = cur_h
        p["_prior"] = prior
        return p

    for s in squads:
        t = types[s["type"]]
        fam = crew_family(t)
        stream = C.STREAM[fam]
        members = []
        for role, ratio in C.CREW_RATIO[fam]:
            n = max(1, round(s["ue"] * ratio))
            for i in range(n):
                if role in ("PILOT", "RPA_PILOT") and i == 0 and s["ue"] >= 6:
                    rank = "WG_CDR"
                elif role in ("PILOT", "RPA_PILOT") and i <= 2 and s["ue"] >= 6:
                    rank = "SQN_LDR"
                else:
                    rank = pick(R("rank", f"{s['number']}:{role}:{i}"), [("FLT_LT", 45), ("FG_OFFR", 40), ("SQN_LDR", 15)])
                p = make_person(f"{s['number']}:{role}:{i}", rank, role, stream, s, s["base"], t)
                if rank == "WG_CDR":
                    p["appointment"] = "Commanding Officer"
                elif rank == "SQN_LDR" and i <= 2:
                    p["appointment"] = "Flight Commander"
                if fam == "trainer":
                    p["ops_category"] = "INSTRUCTOR"
                members.append(p)
                pools[s["id"]][role].append(p)
        crew.extend(members)
    for code in sorted(own):  # station commanders (Gp Capt) at main stations
        b = own[code]
        if b["base_type"] in ("AIR_FORCE_STATION", "TRAINING_ESTABLISHMENT", "BASE_REPAIR_DEPOT"):
            here = [s for s in squads if s["base"] == code and types[s["type"]]["_family"] in ("fighter", "transport", "helo", "trainer")]
            t = types[here[0]["type"]] if here else types["Do-228"]
            p = make_person(f"stncdr:{code}", "GP_CAPT", "PILOT", C.STREAM[crew_family(t)], None, code, t)
            p["appointment"] = "Station Commander"
            crew.append(p)

    # ------------------------------------------------------------------ 90-day sortie history
    sorties, s_ac, s_crew = [], [], []
    rest_until: dict[int, datetime] = {}
    rr = defaultdict(int)
    seq = defaultdict(int)
    positions = {"fighter": [("PILOT", "CAPTAIN")], "fighter2": [("PILOT", "CAPTAIN"), ("WSO", "WSO")],
                 "transport": [("PILOT", "CAPTAIN"), ("PILOT", "CO_PILOT"), ("NAVIGATOR", "NAVIGATOR"),
                               ("FLIGHT_ENGINEER", "FLIGHT_ENGINEER"), ("LOADMASTER", "LOADMASTER")],
                 "helo": [("PILOT", "CAPTAIN"), ("PILOT", "CO_PILOT"), ("FLIGHT_ENGINEER", "FLIGHT_ENGINEER")],
                 "trainer": [("PILOT", "INSTRUCTOR")], "uav": [("RPA_PILOT", "RPA_PILOT"), ("PAYLOAD_OPERATOR", "PAYLOAD_OPERATOR")],
                 "uas": [("RPA_PILOT", "RPA_PILOT")]}
    ist = timezone(timedelta(hours=5, minutes=30))
    for ac in aircraft:
        if ac["status"] == "DEPOT":
            continue
        t, fam, s = ac["_type"], ac["_fam"], ac["_squad"]
        cfam = crew_family(t)
        rng = R("history", ac["tail_no"])
        base_id = own[s["base"]]["id"]
        for day in range(C.HISTORY_DAYS, 0, -1):
            if rng.random() >= C.SORTIE_RATE[fam]:
                continue
            dday = (t0 - timedelta(days=day)).astimezone(ist).date()
            hour = rng.uniform(19, 23) if rng.random() < 0.15 else rng.uniform(7, 17)
            launch = datetime.combine(dday, datetime.min.time(), ist) + timedelta(hours=hour)
            if launch >= t0 - timedelta(hours=2):
                continue
            dur = rng.uniform(*C.SORTIE_HOURS[fam])
            status = pick(rng, [("COMPLETED", 95), ("CANCELLED", 4), ("ABORTED", 1)])
            if status == "ABORTED":
                dur *= 0.3
            seq[s["base"]] += 1
            sid = W.next_id("sortie")
            mtype = "AAR_SUPPORT" if t["role"] == "TANKER" else "AEW_SUPPORT" if t["role"] == "AEW_C" else pick(rng, C.MISSION_MIX[fam])
            rec = launch + timedelta(hours=dur)
            sorties.append((sid, f"SIM-{s['base']}-H{seq[s['base']]:05d}", "SIM_PROGRAMME", mtype,
                            pick(rng, C.PRIORITY_MIX), base_id, base_id, status, launch,
                            None if status == "CANCELLED" else launch, rec,
                            None if status == "CANCELLED" else rec,
                            "CREW_UNAVAILABLE" if status == "CANCELLED" else None,
                            t["burn_kg_per_h"] * dur, 0 if status == "CANCELLED" else t["burn_kg_per_h"] * dur,
                            {"fighter": 7000, "transport": 7500, "helo": 1500, "uav": 5000}.get(fam, 3000)))
            s_ac.append((sid, ac["id"], f"{rng.choice(calls)}{rng.randint(1, 9)}{rng.randint(1, 9)}", 1))
            if status == "CANCELLED":
                continue
            night = dur if hour >= 19 else 0.0
            for role, position in positions[cfam]:
                pool = pools[s["id"]].get(role) or []
                for _ in range(len(pool)):
                    p = pool[rr[(s["id"], role)] % len(pool)]
                    rr[(s["id"], role)] += 1
                    if rest_until.get(p["id"], datetime.min.replace(tzinfo=timezone.utc)) <= launch and \
                            p["medical_status"] != "TEMP_UNFIT" and p["duty_status"] not in ("LEAVE", "COURSE") or len(pool) == 1:
                        rest_until[p["id"]] = rec + timedelta(hours=10)
                        s_crew.append((sid, p["id"], ac["id"], position, round(dur, 2), round(night, 2)))
                        p["_hist_hours"] += dur
                        p["night_hours"] += night
                        p["_last"] = rec if not p["_last"] or rec > p["_last"] else p["_last"]
                        break
            ac["last_sortie_at"] = rec

    # finish crew rows: hours, categories, quals
    rows = []
    for p in crew:
        rng, t = p["_rng"], p["_type"]
        cur_h = p["_cur_hours"] + p["_hist_hours"]
        total = p["_prior"] + cur_h
        p["total_hours"] = round(total, 1)
        p["night_hours"] = round(total * rng.uniform(0.1, 0.2) + p["night_hours"], 1)
        p["instrument_hours"] = round(total * rng.uniform(0.05, 0.1), 1)
        p["instrument_rating"] = "WHITE" if total < 500 else "GREEN" if total < 1500 else "MASTER_GREEN"
        if p["ops_category"] != "INSTRUCTOR":
            p["ops_category"] = ("UNDER_CONVERSION" if cur_h < 100 else "SEMI_OPERATIONAL" if cur_h < 300 else
                                 "FLIGHT_LEAD" if cur_h >= 600 and p["stream"] == "FIGHTER" and p["aircrew_role"] == "PILOT"
                                 else "FULLY_OPERATIONAL")
        last = p["_last"] or (t0 - timedelta(days=rng.uniform(5, 50)))
        type_hours.append(dict(aircrew_id=p["id"], aircraft_type_id=t["id"], hours=round(cur_h, 1),
                               captain_hours=round(cur_h * (0.6 if p["rank"] != "FG_OFFR" else 0.2), 1),
                               night_hours=round(cur_h * 0.15, 1), instrument_hours=round(cur_h * 0.07, 1),
                               last_flown_at=last))
        aw = lambda: (t0 - timedelta(days=rng.uniform(30, 2000))).date()  # noqa: E731
        q = []
        if p["aircrew_role"] == "PILOT":
            if p["ops_category"] == "INSTRUCTOR" or (p["rank"] != "FG_OFFR" and rng.random() < 0.15):
                q.append(("QFI", None, (t0 + timedelta(days=rng.uniform(-10, 900))).date()))
            if rng.random() < 0.7:
                q.append(("NIGHT", t["id"], None))
            if p["stream"] == "FIGHTER":
                if cur_h > 600:
                    q.append(("FORMATION_LEAD_2", t["id"], None))
                if cur_h > 1000:
                    q.append(("FORMATION_LEAD_4", t["id"], None))
                if t["name"] in ("Su-30MKI", "Rafale", "Mirage 2000", "Tejas Mk1") and rng.random() < 0.6:
                    q.append(("AAR_RECEIVER", t["id"], None))
                if rng.random() < 0.5:
                    q.append(("LOW_LEVEL", t["id"], None))
                if p["ops_category"] in ("FULLY_OPERATIONAL", "FLIGHT_LEAD"):
                    q.append(("QRA_CLEARED", t["id"], None))
            if p["stream"] == "HELICOPTER":
                if rng.random() < 0.5:
                    q.append(("NVG", t["id"], (t0 + timedelta(days=rng.uniform(-5, 365))).date()))
                if rng.random() < 0.3:
                    q.append(("SAR", t["id"], None))
            if p["stream"] in ("HELICOPTER", "TRANSPORT") and own[p["_base"]]["_cmd"] in ("WAC", "EAC") and rng.random() < 0.6:
                q.append(("MOUNTAIN_FLYING", t["id"], (t0 + timedelta(days=rng.uniform(-5, 700))).date()))
            if p["stream"] == "TRANSPORT" and rng.random() < 0.4:
                q.append(("PARA_DROP", t["id"], None))
        for code, tid, exp in q:
            quals.append(dict(aircrew_id=p["id"], code=code, aircraft_type_id=tid, awarded_on=aw(), expires_on=exp))
        rows.append({k: v for k, v in p.items() if not k.startswith("_")})
    # QRA crews: two fit, current fighter pilots per QRA base
    qra_crew = defaultdict(int)
    for p in rows:
        b = own_id = p["base_id"]
        if own_id in qra_bases and p["aircrew_role"] == "PILOT" and p["stream"] == "FIGHTER" and \
                p["medical_status"] == "FIT_FULL" and p["appointment"] != "Station Commander" and qra_crew[b] < 2 and \
                p["ops_category"] in ("FULLY_OPERATIONAL", "FLIGHT_LEAD"):
            p["duty_status"] = "QRA"
            qra_crew[b] += 1
    W.insert("aircrew", rows)
    for i, r in enumerate(type_hours):
        r["id"] = i + 1
    W.insert("aircrew_type_hours", type_hours)
    W.insert("aircrew_qualification", [dict(id=i + 1, **q) for i, q in enumerate(quals)])
    W.insert("aircrew_posting", [dict(id=i + 1, **p) for i, p in enumerate(postings)])
    W.copy("sortie", ["id", "code", "origin", "mission_type", "priority", "departure_base_id", "recovery_base_id",
                      "status", "planned_launch_ts", "actual_launch_ts", "planned_recovery_ts", "actual_recovery_ts",
                      "cancel_reason", "fuel_planned_kg", "fuel_used_kg", "cruise_alt_m"], sorties)
    W.copy("sortie_aircraft", ["sortie_id", "aircraft_id", "callsign", "formation_pos"], s_ac)
    W.copy("sortie_crew", ["sortie_id", "aircrew_id", "aircraft_id", "position", "hours_logged", "night_hours"], s_crew)
    conn.execute("UPDATE aircraft a SET last_sortie_at = x.ts FROM (SELECT sa.aircraft_id, max(s.actual_recovery_ts) ts "
                 "FROM sortie_aircraft sa JOIN sortie s ON s.id = sa.sortie_id GROUP BY 1) x WHERE x.aircraft_id = a.id")

    # ------------------------------------------------------------------ ground crew, vehicles, GSE
    home_count = defaultdict(int)
    fam_at = defaultdict(set)
    for ac in aircraft:
        home_count[ac["_home"]] += 1
        fam_at[ac["_home"]].add(ac["_fam"])
    gc, assets = [], []
    vseq = 0
    for code in sorted(own):
        b = own[code]
        rng = R("ground", code)
        n = home_count.get(code, 0)
        scale = 0.2 if b["base_type"] == "ALG" else 1.0
        armed = bool(fam_at[code] & {"fighter", "uav"}) or any(
            types[s["type"]]["role"] == "ATTACK_HELO" for s in squads if s["base"] == code)
        trades = {k: v * n for k, v in C.GROUND_PER_AIRCRAFT.items() if k != "ARMAMENT" or armed}
        trades.update({k: v * scale for k, v in C.GROUND_FIXED.items()})
        for trade, auth in trades.items():
            auth = max(1, round(auth))
            for shift, share in (("A", 0.4), ("B", 0.35), ("C", 0.25)):
                a = max(1, round(auth * share))
                held = max(1, round(a * rng.uniform(0.85, 1.0)))
                leave = round(held * rng.uniform(0.03, 0.1))
                gc.append(dict(id=W.next_id("ground_crew_strength"), base_id=b["id"], trade=trade, shift=shift,
                               authorised=a, held=held, on_duty=held - leave if shift == "A" else 0,
                               standby=round(held * 0.3) if shift == "B" else 0, on_leave=leave))
        cold = (b["elevation_m"] or 0) > 2500 or b["_lat"] > 32
        transport = "TRANSPORT" in b["role_tags"]
        fighter = "FIGHTER" in b["role_tags"]
        spec = [("VEHICLE", "FUEL_BOWSER", math.ceil(n / 8) + 1), ("VEHICLE", "CRASH_FIRE_TENDER", rng.randint(2, 4)),
                ("VEHICLE", "AMBULANCE", 2), ("VEHICLE", "TOW_TRACTOR", math.ceil(n / 6) + 1),
                ("VEHICLE", "RUNWAY_SWEEPER", 1 + (b["_size"] == "L")), ("VEHICLE", "TROOP_CARRIER", 3),
                ("VEHICLE", "UTILITY_TRUCK", 4), ("VEHICLE", "STAFF_CAR", 2), ("VEHICLE", "MOBILE_ATC", 1),
                ("VEHICLE", "HYDRANT_DISPENSER", 2 if b["_size"] == "L" else 0),
                ("VEHICLE", "CARGO_LOADER", rng.randint(2, 4) if transport else 0),
                ("VEHICLE", "SNOW_CLEARER", 2 if cold else 0),
                ("GSE", "GPU", math.ceil(n / 4) + 1), ("GSE", "AIR_START_UNIT", math.ceil(n / 6) if fighter else 0),
                ("GSE", "HYDRAULIC_RIG", math.ceil(n / 8) + 1), ("GSE", "NITROGEN_CART", 2), ("GSE", "OXYGEN_CART", 2),
                ("GSE", "WEAPON_LOADER", math.ceil(n / 6) if armed else 0), ("GSE", "AIRCRAFT_JACK", math.ceil(n / 6) + 1),
                ("GSE", "ENGINE_STAND", 2), ("GSE", "AC_COOLING_CART", math.ceil(n / 8) if fighter else 0),
                ("GSE", "TOW_BAR", math.ceil(n / 4) + 1), ("GSE", "DEICER", 1 if cold else 0)]
        if b["base_type"] == "ALG":
            spec = [(c, t, min(k, 1)) for c, t, k in spec if t in ("FUEL_BOWSER", "CRASH_FIRE_TENDER", "AMBULANCE", "GPU", "SNOW_CLEARER", "MOBILE_ATC")]
        for cls, atype, k in spec:
            for _ in range(k):
                vseq += 1
                assets.append(dict(id=W.next_id("ground_asset"), base_id=b["id"], asset_class=cls, asset_type=atype,
                                   reg_or_serial=f"SIM-{'V' if cls == 'VEHICLE' else 'G'}{vseq:05d}",
                                   status=pick(rng, [("SERVICEABLE", 90), ("UNSERVICEABLE", 6), ("UNDER_REPAIR", 4)]),
                                   capacity_l=rng.choice([12000, 16000, 20000]) if atype == "FUEL_BOWSER" else None,
                                   last_service_date=(t0 - timedelta(days=rng.uniform(5, 180))).date()))
    W.insert("ground_crew_strength", gc)
    W.insert("ground_asset", assets)

    # ------------------------------------------------------------------ fuel
    fuel, txns = [], []
    for code in sorted(own):
        b = own[code]
        rng = R("fuel", code)
        tags = set(b["role_tags"])
        if b["base_type"] == "ALG":
            kind = "alg"
        elif "MAINT" in tags:
            kind = "maint"
        elif "TRAINING" in tags and "FIGHTER" not in tags:
            kind = "training"
        elif "FIGHTER" in tags:
            kind = "fighter_L" if b["_size"] == "L" else "fighter"
        elif "TRANSPORT" in tags:
            kind = "transport_L" if b["_size"] == "L" else "transport"
        elif "HELO" in tags:
            kind = "helo"
        else:
            kind = "other"
        atf = rng.uniform(*C.ATF_CAPACITY_ML[kind]) * 1e6
        grades = [("ATF", atf, "BULK_UNDERGROUND" if kind != "alg" else "BLADDER"),
                  ("DIESEL_HSD", atf * rng.uniform(0.05, 0.1), "ABOVE_GROUND")]
        if kind == "training":
            grades.append(("AVGAS", rng.uniform(20e3, 50e3), "ABOVE_GROUND"))
        for grade, cap, tank in grades:
            cap = round(cap, -3)
            cur_l = round(cap * rng.uniform(0.5, 0.9), -2)
            fid = W.next_id("fuel_storage")
            fuel.append(dict(id=fid, base_id=b["id"], grade=grade, kind=tank, capacity_l=cap, current_l=cur_l,
                             reserve_l=round(cap * C.FUEL_RESERVE), reorder_l=round(cap * C.FUEL_REORDER),
                             tank_count=rng.randint(2, 8) if kind != "alg" else 2, replenish_eta=None))
            bal = cur_l
            for d in range(3):  # last 3 days of issues, walking the balance backwards
                q = round(cap * rng.uniform(0.02, 0.05), -1)
                txns.append(dict(fuel_storage_id=fid, ts=t0 - timedelta(days=d, hours=rng.uniform(1, 20)),
                                 kind="ISSUE_AIRCRAFT" if grade != "DIESEL_HSD" else "ISSUE_VEHICLE",
                                 quantity_l=q, balance_after_l=bal, aircraft_id=None, sortie_id=None, actor="SIMULATOR"))
                bal += q
            txns.append(dict(fuel_storage_id=fid, ts=t0 - timedelta(days=3, hours=6), kind="RECEIPT",
                             quantity_l=round(cap * 0.2, -2), balance_after_l=bal, aircraft_id=None, sortie_id=None,
                             actor="SIMULATOR"))
    W.insert("fuel_storage", fuel)
    W.insert("fuel_transaction", [dict(id=i + 1, **t) for i, t in enumerate(sorted(txns, key=lambda x: (x["fuel_storage_id"], x["ts"])))])

    # ------------------------------------------------------------------ warehouses + stock (generic armament only)
    items = []
    for tname in sorted(types):
        t = types[tname]
        if t["in_service"] and t["_target"] > 0:
            for cat, label in (("ENGINE_SPARES", "engine module"), ("AIRFRAME_SPARES", "airframe spares kit"),
                               ("AVIONICS_SPARES", "avionics LRU"), ("TYRES_BRAKES", "wheel/brake assembly")):
                items.append(dict(part_no=f"SIM-{t['serial_prefix']}-{cat[:3]}-{t['id']:02d}",
                                  nomenclature=f"{tname} {label} (generic)", category=cat, unit="EA", aircraft_type_id=t["id"]))
    for cat, label, unit in (("CONSUMABLES", "Hydraulic fluid", "L"), ("CONSUMABLES", "Seal / O-ring kit", "EA"),
                             ("POL_PACKED", "Turbine engine oil", "L"), ("POL_PACKED", "Grease, aviation", "KG"),
                             ("GSE_SPARES", "GSE spares kit", "EA"), ("MEDICAL", "Medical stores pack", "EA"),
                             ("RATIONS", "Field rations", "EA"),
                             ("ARMAMENT_AAM_BVR", "AAM, beyond visual range (generic)", "EA"),
                             ("ARMAMENT_AAM_WVR", "AAM, within visual range (generic)", "EA"),
                             ("ARMAMENT_PGM", "Precision-guided munition (generic)", "EA"),
                             ("ARMAMENT_BOMB_UNGUIDED", "Bomb, unguided (generic)", "EA"),
                             ("ARMAMENT_ROCKET", "Rocket pod (generic)", "EA"),
                             ("ARMAMENT_GUN_AMMO", "Gun ammunition (generic)", "ROUNDS"),
                             ("ARMAMENT_CHAFF_FLARE", "Chaff / flare cartridges (generic)", "EA")):
        items.append(dict(part_no=f"SIM-GEN-{cat[:12]}-{len(items):03d}", nomenclature=label, category=cat,
                          unit=unit, aircraft_type_id=None))
    for i, it in enumerate(items):
        it["id"] = i + 1
    W.insert("stock_item", items)
    whs, levels = [], []
    for code in sorted(own):
        b = own[code]
        rng = R("stores", code)
        n = home_count.get(code, 0)
        armed = bool(fam_at[code] & {"fighter", "uav"})
        kinds = ["GENERAL", "AVIATION_SPARES", "MEDICAL", "RATIONS"] + (["POL_PACKED"] if b["_size"] != "S" else []) + \
                (["ARMAMENT_STORE"] if armed else [])
        if b["base_type"] == "ALG":
            kinds = ["GENERAL", "RATIONS"]
        type_ids = {ac["_type"]["id"] for ac in aircraft if ac["_home"] == code}
        for k in kinds:
            wid = W.next_id("warehouse")
            whs.append(dict(id=wid, base_id=b["id"], name=f"{k.replace('_', ' ').title()} store",
                            kind=k, capacity_m3=round(rng.uniform(500, 6000) * ({"S": 0.3, "M": 0.7, "L": 1.0}[b["_size"]]), -1),
                            utilisation_pct=round(rng.uniform(40, 92), 1),
                            status="DEGRADED" if rng.random() < 0.04 else "OPERATIONAL"))
            for it in items:
                cat = it["category"]
                ok = (k == "AVIATION_SPARES" and it["aircraft_type_id"] in type_ids) or \
                     (k == "ARMAMENT_STORE" and cat.startswith("ARMAMENT")) or \
                     (k == "GENERAL" and cat in ("CONSUMABLES", "GSE_SPARES")) or \
                     (k == "POL_PACKED" and cat == "POL_PACKED") or (k == "MEDICAL" and cat == "MEDICAL") or \
                     (k == "RATIONS" and cat == "RATIONS")
                if not ok:
                    continue
                scale = max(1, n) * (500 if it["unit"] in ("L", "KG", "ROUNDS") else 0.5)
                reorder = max(2, round(scale))
                below = rng.random() < 0.05
                levels.append(dict(warehouse_id=wid, stock_item_id=it["id"],
                                   qty_on_hand=round(reorder * (rng.uniform(0.2, 0.9) if below else rng.uniform(1.1, 2.6))),
                                   qty_reserved=0, reorder_level=reorder, max_level=reorder * 3,
                                   last_receipt_at=t0 - timedelta(days=rng.uniform(3, 60))))
    W.insert("warehouse", whs)
    W.insert("stock_level", [dict(id=i + 1, **lv) for i, lv in enumerate(levels)])

    # ------------------------------------------------------------------ AD / radar / comms: synthetic positions
    ad_types = {r["name"]: dict(id=i + 1, **r) for i, r in enumerate(read("ad_system_types.csv"))}
    W.insert("ad_system_type", [dict(id=t["id"], name=n, category=t["category"], max_range_km=float(t["max_range_km"]),
                                     max_alt_m=float(t["max_alt_m"]), is_simulated=False, source="PUBLIC",
                                     source_ref="docs/DATA_MODEL.md §8.12 (approximate public figures, VERIFY)")
                                for n, t in ad_types.items()])
    rd_types = {r["name"]: dict(id=i + 1, **r) for i, r in enumerate(read("radar_types.csv"))}
    W.insert("radar_type", [dict(id=t["id"], name=n, category=t["category"], max_range_km=float(t["max_range_km"]),
                                 is_simulated=False, source="PUBLIC",
                                 source_ref="docs/DATA_MODEL.md §8.12 (approximate public figures, VERIFY)")
                            for n, t in rd_types.items()])
    op_bases = [b for b in own.values() if b["_cmd"] not in ("TC", "MC")]

    def nearest_base(x, y):
        return min(op_bases, key=lambda b: dist_km((x, y), (b["_lon"], b["_lat"])))

    ad, radars, nodes = [], [], []
    for code in sorted(own):  # point defence around fighter / forward bases
        b = own[code]
        if not ({"FIGHTER"} & set(b["role_tags"])) or b["_cmd"] in ("TC",):
            continue
        rng = R("pointdef", code)
        forward = b["base_type"] == "FBSU" or b["_cmd"] in ("WAC", "SWAC", "EAC")
        choices = [("Igla-S", 30), ("L/70 40 mm AD gun", 25), ("ZU-23-2 twin 23 mm", 15), ("Akash", 15), ("SPYDER-SR", 15)]
        picks = [pick(rng, choices) for _ in range(rng.randint(1, 3))] + (["Counter-drone system (generic)"] if forward else [])
        for name in picks:
            loc = place_near(rng, b["_lon"], b["_lat"], 2, 8)
            if loc:
                launchers = {"AD_GUN": 4, "VSHORADS": 6, "C_UAS": 2}.get(ad_types[name]["category"], 4)
                ad.append(dict(type=name, base=b["id"], cmd=b["command_id"], loc=loc, launchers=launchers, rng=rng))
    border = border_samples(150)
    lr_count = defaultdict(int)
    sector = lambda x, y: "NORTH" if y >= 32 else "WEST" if x < 77 else "CENTRAL" if x < 88 else "EAST"  # noqa: E731
    for i, (x, y) in enumerate(border):
        rng = R("border", i)
        sec = sector(x, y)
        if i % 2 == 0:  # area SAM every ~300 km
            name = "S-400 Triumf (Sudarshan Chakra)" if lr_count[sec] == 0 and sec != "CENTRAL" else \
                pick(rng, [("MR-SAM (Barak-8)", 35), ("Akash-NG", 25), ("SPYDER-MR", 20), ("S-125 Pechora (upgraded)", 20)])
            lr_count[sec] += name.startswith("S-400")
            loc = place_near(rng, x, y, 30, 80)
            if loc:
                nb = nearest_base(*loc)
                ad.append(dict(type=name, base=None, cmd=nb["command_id"], loc=loc, launchers=rng.randint(4, 8), rng=rng))
        name = ["Arudhra (MPR)", "Rohini (3D CAR)", "Ashwini (LLTR)", "THD-1955", "EL/M-2084"][i % 5]
        loc = place_near(rng, x, y, 20, 60)
        if loc:
            radars.append(dict(type=name, base=nearest_base(*loc)["id"], loc=loc, rng=rng))
    west = [p for p in border if p[0] < 76 and p[1] < 33]
    for j, (x, y) in enumerate(west[:: max(1, len(west) // 3)][:3]):
        rng = R("aerostat", j)
        loc = place_near(rng, x, y, 40, 90)
        if loc:
            radars.append(dict(type="Aerostat EL/M-2083", base=nearest_base(*loc)["id"], loc=loc, rng=rng))
    for code in sorted(own):  # low-level radars around fighter bases
        b = own[code]
        if "FIGHTER" in b["role_tags"] and b["_cmd"] not in ("TC", "MC") and b["base_type"] != "ALG":
            rng = R("llr", code)
            for _ in range(rng.randint(1, 2)):
                loc = place_near(rng, b["_lon"], b["_lat"], 10, 30)
                if loc:
                    radars.append(dict(type=rng.choice(["Aslesha (LLLR)", "Ashwini (LLTR)"]), base=b["id"], loc=loc, rng=rng))
    rows = []
    for i, a in enumerate(ad):
        rng = a["rng"]
        st = pick(rng, [("OPERATIONAL", 90), ("DEGRADED", 6), ("MAINTENANCE", 4)])
        rows.append(dict(id=i + 1, code=f"SIM-AD-{i + 1:03d}", ad_system_type_id=ad_types[a["type"]]["id"],
                         protected_base_id=a["base"], command_id=a["cmd"], geom=pt(*a["loc"]), status=st,
                         readiness_min=rng.choice([5, 10, 15, 30]), launchers_total=a["launchers"],
                         launchers_ready=a["launchers"] if st == "OPERATIONAL" else max(0, a["launchers"] - rng.randint(1, 3))))
    W.insert("air_defence_battery", rows, geom=("geom",))
    W.insert("radar_site", [dict(id=i + 1, code=f"SIM-RDR-{i + 1:03d}", radar_type_id=rd_types[r["type"]]["id"],
                                 base_id=r["base"], geom=pt(*r["loc"]), antenna_height_m=round(r["rng"].uniform(6, 30), 1),
                                 status=pick(r["rng"], [("OPERATIONAL", 92), ("DEGRADED", 5), ("MAINTENANCE", 3)]))
                            for i, r in enumerate(radars)], geom=("geom",))
    hq_nodes = {}
    for code in sorted(own):
        b = own[code]
        if b["base_type"] == "ALG":
            continue
        rng = R("comms", code)
        for ntype in ("DATALINK_GS", "VUHF_RELAY"):
            loc = place_near(rng, b["_lon"], b["_lat"], 1, 3)
            if loc:
                nodes.append(dict(node_type=ntype, base=b["id"], loc=loc, rng=rng, cmd=b["_cmd"]))
    for code, (name, hq, lon, lat, op) in C.COMMANDS.items():
        rng = R("hqcomms", code)
        for ntype in ("SATCOM_GS", "C2_NODE", "NETWORK_HUB"):
            loc = place_near(rng, lon, lat, 3, 15)
            if loc:
                nodes.append(dict(node_type=ntype, base=None, loc=loc, rng=rng, cmd=code))
                if ntype == "C2_NODE":
                    hq_nodes[code] = len(nodes)
    for i, r in enumerate(radars[::3]):
        rng = R("hf", i)
        loc = place_near(rng, r["loc"][0], r["loc"][1], 5, 10)
        if loc:
            nodes.append(dict(node_type="HF_STATION", base=r["base"], loc=loc, rng=rng, cmd=None))
    W.insert("comms_node", [dict(id=i + 1, code=f"SIM-COM-{i + 1:03d}", node_type=n["node_type"], base_id=n["base"],
                                 geom=pt(*n["loc"]), status=pick(n["rng"], [("UP", 94), ("DEGRADED", 4), ("DOWN", 2)]))
                            for i, n in enumerate(nodes)], geom=("geom",))
    links = []
    for i, n in enumerate(nodes):
        if n["node_type"] == "DATALINK_GS" and n["cmd"] in hq_nodes:
            links.append(dict(id=len(links) + 1, node_a_id=i + 1, node_b_id=hq_nodes[n["cmd"]],
                              medium="SATCOM" if own_by_id(own, n["base"])["_lat"] > 32 else "FIBRE", status="UP"))
    W.insert("comms_link", links)

    # ------------------------------------------------------------------ missions (Phase-2-ready, light)
    rows = []
    for i, (code, mtype, prio, name) in enumerate([
            ("WAC", "AIR_DEFENCE_PATROL", "P1", "Northern sector air defence patrol"),
            ("WAC", "RECCE_ISR", "P2", "Ladakh ISR coverage"), ("SWAC", "AIR_DEFENCE_PATROL", "P2", "Western sector CAP"),
            ("EAC", "AIR_DEFENCE_PATROL", "P1", "Eastern sector air defence patrol"),
            ("EAC", "AIRLIFT", "P2", "ALG maintenance airlift, Arunachal"), ("CAC", "AIRLIFT", "P3", "Inter-command logistics"),
            ("SAC", "RECCE_ISR", "P3", "Maritime ISR support"), ("WAC", "AIRLIFT", "P2", "Ladakh logistics airlift")]):
        rows.append(dict(id=i + 1, code=f"SIM-MSN-{i + 1:03d}", name=name, mission_type=mtype, priority=prio,
                         window_start=t0 - timedelta(hours=6), window_end=t0 + timedelta(days=2), status="ACTIVE",
                         requesting_command_id=cmd_id[code]))
    W.insert("mission", rows)

    # ------------------------------------------------------------------ users + sim state
    pw = hash_password(config.DEMO_PASSWORD)
    users = [("admin", "Exercise Controller", "ADMIN", None, None), ("airhq", "Air HQ Ops", "COMMAND_HQ", None, None),
             ("wac.hq", "WAC Ops", "COMMAND_HQ", None, "WAC"), ("eac.hq", "EAC Ops", "COMMAND_HQ", None, "EAC"),
             ("viewer", "Observer", "VIEWER", None, None)]
    users += [(f"cdr.{c.lower()}", f"Station Commander {own[c]['name'].replace('Air Force Station ', '')}",
               "BASE_COMMANDER", c, None) for c in C.DEMO_BASE_COMMANDERS]
    W.insert("app_user", [dict(id=i + 1, username=u, display_name=d, password_hash=pw, role=r,
                               base_id=own[b]["id"] if b else None, command_id=cmd_id[c] if c else None,
                               is_active=True, failed_logins=0, is_simulated=False, source="SYNTHETIC")
                          for i, (u, d, r, b, c) in enumerate(users)])
    conn.execute("INSERT INTO sim_state (id, seed, sim_epoch, sim_now, tick_no, speed, paused) VALUES (1, %s, %s, %s, 0, %s, false)",
                 (SEED, t0, t0, config.SIM_SPEED))

    # fix sequences after explicit ids
    for (tbl,) in conn.execute("SELECT table_name FROM information_schema.columns WHERE table_schema='public' "
                               "AND column_name='id' AND column_default LIKE 'nextval%%'").fetchall():
        conn.execute(f"SELECT setval(pg_get_serial_sequence('{tbl}','id'), coalesce((SELECT max(id) FROM {tbl}), 0) + 1, false)")
    conn.commit()
    checks(conn, types, inner)
    conn.close()


def own_by_id(own, base_id):
    return next(b for b in own.values() if b["id"] == base_id)


def checks(conn, types, inner) -> None:
    """Post-generation checks (DATA_MODEL §8.15). Fail the seed on any violation."""
    failures = []
    counts = dict(conn.execute("SELECT t.name, count(*) FROM aircraft a JOIN aircraft_type t ON t.id = a.aircraft_type_id GROUP BY 1"))
    for name, t in types.items():
        tgt = t["_target"]
        if tgt > 0 and abs(counts.get(name, 0) - tgt) > max(1, 0.1 * tgt):
            failures.append(f"fleet {name}: {counts.get(name, 0)} vs target {tgt}")
    bad = conn.execute("SELECT count(*) FROM aircraft a JOIN base b ON b.id = a.home_base_id WHERE b.side <> 'OWN'").fetchone()[0]
    if bad:
        failures.append(f"{bad} aircraft at non-OWN bases")
    deny = {r["full_name"].lower() for r in read("names_denylist.csv")}
    hits = [n for (n,) in conn.execute("SELECT lower(first_name || ' ' || last_name) FROM aircrew") if n in deny]
    if hits:
        failures.append(f"denylisted names generated: {hits[:5]}")
    for tbl in ("air_defence_battery", "radar_site", "comms_node"):
        for (g,) in conn.execute(f"SELECT ST_AsBinary(geom) FROM {tbl}"):
            if not inner.contains(wkb.loads(g)):
                failures.append(f"{tbl}: site outside the India buffer")
                break
    for tbl in ("base", "squadron", "aircraft_type"):
        n = conn.execute(f"SELECT count(*) FROM {tbl} WHERE source='PUBLIC' AND source_ref IS NULL").fetchone()[0]
        if n:
            failures.append(f"{tbl}: {n} PUBLIC rows without source_ref")
    summary = conn.execute("""SELECT (SELECT count(*) FROM base WHERE side='OWN'), (SELECT count(*) FROM squadron),
        (SELECT count(*) FROM aircraft), (SELECT count(*) FROM aircrew), (SELECT count(*) FROM sortie),
        (SELECT count(*) FROM air_defence_battery), (SELECT count(*) FROM radar_site), (SELECT count(*) FROM comms_node)""").fetchone()
    print("bases %d | squadrons %d | aircraft %d | aircrew %d | sorties %d | AD %d | radars %d | comms %d" % summary)
    parts = []
    for tbl in ("base", "squadron", "aircraft", "aircrew", "sortie", "sortie_crew", "fuel_storage", "air_defence_battery", "radar_site"):
        parts.append(conn.execute(f"SELECT md5(string_agg((to_jsonb(t) - 'created_at' - 'updated_at')::text, '|' ORDER BY id)) FROM {tbl} t").fetchone()[0])
    print("checksum", __import__("hashlib").md5("".join(parts).encode()).hexdigest())
    if failures:
        raise SystemExit("post-generation checks FAILED:\n  " + "\n  ".join(failures))
    print("post-generation checks: PASS")


if __name__ == "__main__":
    main()
