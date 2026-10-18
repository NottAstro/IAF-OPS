"""Air tasking order (ARCHITECTURE D46, PRD FR-PLN-14): a plan as the order the bases fly from: one entry per package
with callsigns, tails, crew, timings, route waypoints, loadout, tanker meeting point and the planner's notes (weather,
threat, civil traffic, snag risk, dependencies, waves). Theatre-wide or for one base; JSON for the print view, CSV for
spreadsheets. A plan that isn't committed yet comes out marked DRAFT. Everything in it is SIMULATED.
"""
import csv
import io
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import config as D
from . import store

NOTES = ("Weather", "Route risk", "Civil traffic", "Snag risk", "Depends on", "Part of", "Launch", "Night", "Qualifications")


def _dm(lon: float, lat: float) -> str:
    """28°42′N 077°21′E (degrees and minutes, the way a route card reads)."""
    def f(v, w, pos, neg):
        a = abs(v)
        return f"{int(a):0{w}d}°{int(round((a - int(a)) * 60)) % 60:02d}′{pos if v >= 0 else neg}"
    return f"{f(lat, 2, 'N', 'S')} {f(lon, 3, 'E', 'W')}"


def _near(db: Session, pts: list) -> list[str | None]:
    """Nearest named place (within 30 km) for each waypoint, one query."""
    if not pts:
        return []
    rows = db.execute(text("""SELECT w.i, p.name, p.d FROM unnest(CAST(:xs AS float8[]), CAST(:ys AS float8[])) WITH ORDINALITY AS w(x, y, i)
                              LEFT JOIN LATERAL (SELECT name, ST_Distance(g.geom::geography, ST_SetSRID(ST_Point(w.x, w.y), 4326)::geography) d
                                                 FROM gis_place g ORDER BY g.geom <-> ST_SetSRID(ST_Point(w.x, w.y), 4326) LIMIT 1) p ON true
                              ORDER BY w.i"""), {"xs": [float(p[0]) for p in pts], "ys": [float(p[1]) for p in pts]}).all()
    return [r[1] if r[2] is not None and r[2] <= 30000 else None for r in rows]


def build(db: Session, pid: int, base_id: int | None = None) -> dict:
    v = store.serialise(db, pid)
    p = v["plan"]
    items = [i for i in v["items"] if i["status"] != "REJECTED" and (base_id is None or i["base"]["id"] == base_id
                                                                  or (i.get("support") or {}).get("base", {}) and i["support"]["base"]["id"] == base_id)]
    sids = [i["sortie"]["id"] for i in items if i.get("sortie")] + [i["support"]["sortie"]["id"] for i in items
                                                                     if i.get("support") and i["support"].get("sortie")]
    calls: dict = {}
    for sid, cs in db.execute(text("SELECT sortie_id, callsign FROM sortie_aircraft WHERE sortie_id = ANY(:s) ORDER BY formation_pos"),
                              {"s": sids or [0]}):
        calls.setdefault(sid, []).append(cs)
    lo_names = dict(db.execute(text("SELECT code, name FROM loadout_config")).all())
    out = []
    for n, i in enumerate(sorted(items, key=lambda x: (x["launch_ts"], x["mission"]["priority"])), start=1):
        sc = i.get("score") or {}
        route = [tuple(c) for c in (i.get("route") or [])]
        turns = route if len(route) <= 12 else route[:: max(1, len(route) // 10)] + [route[-1]]
        names = _near(db, turns)
        rows = {r["label"]: r for r in (i.get("explanation") or {}).get("rows", [])}
        sup = i.get("support")
        out.append({
            "serial": f"{n:03d}", "mission": i["mission"]["code"], "name": i["mission"].get("name"), "priority": i["mission"]["priority"],
            "task": i["mission"]["mission_type"], "base": i["base"]["code"], "recovery": (i.get("recovery_base") or i["base"])["code"],
            "type": i["type"]["name"], "n": i["n_aircraft"], "callsigns": calls.get((i.get("sortie") or {}).get("id"), []),
            "sortie": (i.get("sortie") or {}).get("code"), "tails": [a["tail_no"] for a in i["aircraft"]],
            "crew": [{"position": c["position"], "rank": c["rank"], "name": c["name"], "callsign": c.get("callsign")} for c in i["crew"]],
            "loadout": lo_names.get(i.get("loadout_code"), i.get("loadout_code")),
            "brief": (i["launch_ts"] - timedelta(minutes=D.BRIEF_MIN)).isoformat(), "launch": i["launch_ts"].isoformat(),
            "on_station": i["on_station_ts"].isoformat() if i.get("on_station_ts") else None, "off_station": sc.get("off_station"),
            "land": i["recovery_ts"].isoformat(),
            "waypoints": [{"n": k + 1, "pos": _dm(*pt), "lon": round(pt[0], 4), "lat": round(pt[1], 4), "near": nm}
                          for k, (pt, nm) in enumerate(zip(turns, names))],
            "fuel_l": i.get("fuel_l"), "risk": i.get("risk"),
            "tanker": {"base": sup["base"]["code"] if sup.get("base") else None, "type": (sup.get("type") or {}).get("name"),
                       "tails": [a["tail_no"] for a in sup["aircraft"]], "rv": _dm(*sup["rv"]), "rv_start": sup["rv_start"],
                       "rv_end": sup["rv_end"], "launch": sup["launch_ts"],
                       "callsigns": calls.get((sup.get("sortie") or {}).get("id"), [])} if sup else None,
            "notes": [{"label": k, "value": rows[k]["value"], "note": rows[k].get("note", "")} for k in NOTES if k in rows],
        })
    base = db.execute(text("SELECT code, name FROM base WHERE id = :b"), {"b": base_id}).first() if base_id else None
    return {"plan": {"id": p["id"], "kind": p["kind"], "status": p["status"], "horizon_start": p["horizon_start"],
                     "horizon_end": p["horizon_end"], "committed_at": p["committed_at"], "preset": p["preset"]},
            "draft": p["status"] != "COMMITTED", "scope": f"{base.code} {base.name}" if base else "Theatre",
            "issued": db.execute(text("SELECT sim_now()")).scalar(), "packages": out,
            "uncovered": [{"mission": u["mission"]["code"], "priority": u["mission"]["priority"],
                           "reason": (u["reasons"] or [{}])[0].get("text")} for u in v["unmet"]] if base_id is None else [],
            "simulated": True}


def to_csv(ato: dict) -> str:
    buf = io.StringIO()
    buf.write("# SIMULATED air tasking order - synthetic data, not for operational use\n")
    w = csv.writer(buf)
    w.writerow(["serial", "mission", "priority", "task", "base", "type", "n", "callsigns", "tails", "brief", "launch", "on_station",
                "off_station", "land", "recovery", "loadout", "tanker", "tanker_rv", "waypoints"])
    for p in ato["packages"]:
        t = p["tanker"]
        w.writerow([p["serial"], p["mission"], p["priority"], p["task"], p["base"], p["type"], p["n"], " ".join(p["callsigns"]),
                    " ".join(p["tails"]), p["brief"], p["launch"], p["on_station"], p["off_station"], p["land"], p["recovery"],
                    p["loadout"], f"{t['type']} {t['base']}" if t else "", f"{t['rv']} {t['rv_start']}" if t else "",
                    " / ".join(f"{x['pos']}{' ' + x['near'] if x['near'] else ''}" for x in p["waypoints"])])
    return buf.getvalue()
