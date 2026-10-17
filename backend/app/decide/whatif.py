"""What-if and COA comparison (PHASE2_IMPLEMENTATION_PLAN §7.7). Deltas are applied to a copy of the snapshot and the
planner runs on it: nothing is written to the database."""
from datetime import timedelta

from shapely.geometry import Polygon
from shapely.prepared import prep

from ..geo import offset
from . import config as D
from . import planner as P
from .snapshot import Mission, OpsState, Zone

DELTAS = {
    "GROUND_TYPE": "Ground aircraft of a type (fleet grounding)",
    "CLOSE_RUNWAY": "Close a runway for some hours",
    "WX_FRONT": "Weather front over bases",
    "THREAT_ZONE": "Activate a threat zone",
    "MISSION_SURGE": "Mission surge",
    "FUEL_DELAY": "Fuel shortfall at a base",
    "BASE_ATTACK": "Base under attack (runway closed, aircraft damaged)",
}
WX_ROWS = {"MVFR": (2000, 6000), "IFR": (700, 3000), "LIFR": (300, 1000)}


def _base(st: OpsState, code: str):
    b = next((b for b in st.bases.values() if b.code == (code or "").upper()), None)
    if b is None:
        raise ValueError(f"Unknown base {code}")
    return b


def apply(st: OpsState, deltas: list[dict], prefer: set | None = None) -> list[str]:
    """prefer: aircraft the baseline plan uses; a grounding takes those first so its effect on the plan shows."""
    prefer = prefer or set()
    notes = []
    for d in deltas:
        k, p = d.get("kind"), d.get("params", {})
        start = st.now + timedelta(hours=float(p.get("from_h", 0)))
        end = start + timedelta(hours=float(p.get("hours", 24)))
        if k == "GROUND_TYPE":
            tname = p.get("type", "")
            ty = next((t for t in st.types.values() if t.name.lower() == tname.lower()), None)
            if ty is None:
                raise ValueError(f"Unknown aircraft type {tname}")
            ids = sorted((a for a in st.aircraft.values() if a.type_id == ty.id and a.status != "QRA"
                          and (not p.get("base") or st.bases[a.base_id].code == p["base"].upper())),
                         key=lambda a: (a.id not in prefer, a.id))
            n = int(p.get("count", 1))
            for a in ids[:n]:
                st.aircraft.pop(a.id)
            notes.append(f"{min(n, len(ids))} {ty.name} grounded" + (f" at {p['base'].upper()}" if p.get("base") else ""))
        elif k in ("CLOSE_RUNWAY", "BASE_ATTACK"):
            b = _base(st, p.get("base"))
            b.closed_windows.append((start, end))
            notes.append(f"{b.code} runway closed {start:%H:%M}–{end:%H:%M}Z")
            if k == "BASE_ATTACK":
                ids = sorted(i for (bid, _), xs in st.by_base_type.items() if bid == b.id for i in xs)
                for i in ids[: max(1, int(len(ids) * float(p.get("damage", 0.3))))]:
                    st.aircraft.pop(i, None)
                notes.append(f"{int(len(ids) * float(p.get('damage', 0.3)))} aircraft damaged at {b.code}")
        elif k == "WX_FRONT":
            cat = p.get("cat", "IFR")
            ceil, vis = WX_ROWS.get(cat, WX_ROWS["IFR"])
            for code in p.get("bases", []):
                b = _base(st, code)
                rows = [r for r in st.wx.get(b.id, []) if not (start <= r[0] < end)]
                t = start
                while t < end:
                    rows.append((t, ceil, vis, 18, 28, 180, cat, "EXERCISE"))
                    t += timedelta(hours=1)
                st.wx[b.id] = sorted(rows, key=lambda r: r[0])
            notes.append(f"{cat} at {', '.join(x.upper() for x in p.get('bases', []))} for {p.get('hours', 24)} h")
        elif k == "THREAT_ZONE":
            lon, lat, r = float(p["lon"]), float(p["lat"]), float(p.get("radius_km", 40))
            poly = Polygon([offset(lon, lat, r, 360 * i / 36) for i in range(36)])
            st.threats.append(Zone(-len(st.threats) - 1, "WHATIF", p.get("name", "What-if threat zone"), "EXERCISE_SAM",
                                   poly, prep(poly), float(p.get("risk", 0.9)), 0, start, end))
            notes.append(f"Threat zone r={r:.0f} km risk {float(p.get('risk', 0.9)):.1f}")
        elif k == "MISSION_SURGE":
            f = float(p.get("factor", 1.5))
            src = sorted(st.missions.values(), key=lambda m: m.id)
            extra = int(round((f - 1) * len(src)))
            for i in range(extra):
                m = src[(i * 7) % len(src)]
                shift = timedelta(minutes=45 * ((i % 3) + 1))
                nid = -(i + 1)
                st.missions[nid] = Mission(nid, f"{m.code}-S{i + 1}", m.name + " (surge)", m.mission_type, m.priority, "APPROVED",
                                           m.window_start + shift, m.window_end + shift, m.command_id, m.target,
                                           m.target_base_id, m.required, m.roles, m.loadout_code, m.on_station_min,
                                           m.min_quals, m.max_risk)
            notes.append(f"+{extra} missions (surge ×{f:g})")
        elif k == "FUEL_DELAY":
            b = _base(st, p.get("base"))
            f = st.fuel.get(b.id)
            if f:
                f["current_l"] *= 1 - float(p.get("loss_pct", 40)) / 100
                f["replenish_eta"] = None
            notes.append(f"{b.code} ATF down {p.get('loss_pct', 40)}%, delivery delayed")
        else:
            raise ValueError(f"Unknown delta {k}")
    st.index()
    return notes


def summary(st: OpsState, res: P.PlanResult) -> dict:
    return {"kpis": res.kpis,
            "items": {st.missions[i["mission_id"]].code: {"base": st.bases[i["base_id"]].code,
                                                          "type": st.types[i["aircraft_type_id"]].name,
                                                          "launch": i["launch_ts"].isoformat(), "priority": st.missions[i["mission_id"]].priority}
                      for i in res.items},
            "unmet": [{"code": st.missions[u["mission_id"]].code, "priority": st.missions[u["mission_id"]].priority,
                       "name": st.missions[u["mission_id"]].name, "reason": u["reasons"][0]["text"] if u["reasons"] else "",
                       "example": (u["reasons"][0]["examples"] or [""])[0] if u["reasons"] else "",
                       "fix": u["fixes"][0]["text"] if u["fixes"] else ""} for u in res.unmet]}


def compare(st: OpsState, deltas: list[dict], presets: list[str]) -> dict:
    """Baseline vs scenario (deltas), or COA comparison (several presets on the same snapshot)."""
    out = {"deltas": deltas, "notes": [], "runs": []}
    base = P.plan(st.clone(), presets[0])
    out["runs"].append({"label": "Baseline" if deltas else presets[0].replace("_", " ").title(), "preset": presets[0],
                        **summary(base.st, base)})
    used = {a for i in base.items for a in i["aircraft_ids"]}
    if deltas:
        st2 = st.clone()
        out["notes"] = apply(st2, deltas, used)
        res = P.plan(st2, presets[0])
        out["runs"].append({"label": "What-if", "preset": presets[0], **summary(st2, res)})
    for pr in presets[1:]:
        st3 = st.clone()
        if deltas:
            apply(st3, deltas, used)
        res = P.plan(st3, pr)
        out["runs"].append({"label": pr.replace("_", " ").title(), "preset": pr, **summary(st3, res)})
    a, b = out["runs"][0], out["runs"][-1]
    out["changed"] = sorted({k for k in set(a["items"]) | set(b["items"])
                             if a["items"].get(k, {}).get("base") != b["items"].get(k, {}).get("base")})
    return out
