"""Benchmark harness (PHASE2_IMPLEMENTATION_PLAN §13 / P10): writes docs/BENCHMARK.md and docs/benchmark.csv.

For every (seed, epoch) it regenerates the synthetic world, then measures
- the planner under each preset: coverage by priority, solve and total time, validator violations, sorties, fuel,
  route risk, expected defects;
- a greedy baseline on the same candidates (priority order, cheapest option that still validates), to show what the
  CP-SAT optimiser adds;
- determinism (the same plan twice);
- re-tasking: commit the BALANCED plan, then (a) close the busiest runway, (b) pop up a P1 casualty evacuation, and
  time the monitor's proposal, its rung and how much of the plan it kept;
- a surge day (MISSION_SCALE × the normal mission load) where tails, crews and launch slots run short, which is where
  optimising jointly should beat greedy.

    python -m app.bench                        # 3 seeds × 2 epochs (~10 min)
    python -m app.bench --quick                # 1 seed × 1 epoch
DEV ONLY: overwrites the database for every run and reseeds the default (seed 2026, 2026-10-17T06:00Z) at the end.
"""
import argparse
import csv
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
DOCS = BACKEND.parent / "docs"
PRESETS = ["BALANCED", "MAX_COVERAGE", "MIN_RISK", "MIN_FUEL"]
SEEDS = [2026, 7, 42]
EPOCHS = ["2026-10-17T06:00:00+00:00",          # October, late morning IST
          "2026-01-12T01:30:00+00:00"]          # January, 07:00 IST: north-Indian winter fog season
DEFAULT = (2026, "2026-10-17T06:00:00+00:00")
SURGE = 2.5
USER = {"id": 1, "role": "ADMIN"}


def regen(seed: int, epoch: str, scale: float = 1.0) -> float:
    t0 = time.perf_counter()
    subprocess.run([sys.executable, "-m", "generator"], cwd=BACKEND, check=True, capture_output=True,
                   env={**os.environ, "SEED": str(seed), "SIM_EPOCH": epoch, "MISSION_SCALE": str(scale)})
    from .decide import predict
    predict._CACHE.clear()                       # new database, model ids restart at 1
    return time.perf_counter() - t0


def greedy(st, preset: str) -> dict:
    """Priority order, then window; for each mission the cheapest candidate that can be crewed and still validates."""
    from .decide import feasibility as F, planner as P
    from .decide.assign import Ledger, assign
    from .decide.validate import validate
    t0 = time.perf_counter()
    cands, _ = F.generate(st, preset)
    led, acc, covered = Ledger(), [], {}
    for m in sorted(st.missions.values(), key=lambda m: (m.priority, m.window_start, m.id)):
        for c in sorted(cands.get(m.id, []), key=lambda c: (c.cost, c.idx)):
            a = assign(st, c, led)
            if isinstance(a, str):
                continue
            led.take(c, a)
            if c.support is not None:
                s = assign(st, c.support, led)
                if isinstance(s, str):
                    led.release(c, a)
                    continue
                a.support = s
                led.take(c.support, s)
            sp = P.specs(c, a, str(m.id))
            if validate(st, acc + sp):
                led.release(c, a)
                if a.support is not None:
                    led.release(c.support, a.support)
                continue
            acc += sp
            covered[m.id] = c
            break
    groups: dict = {}                            # same rule as the planner: parts of a split mission all or nothing (D42)
    for mid, m in st.missions.items():
        if m.parent is not None:
            groups.setdefault(m.parent, []).append(mid)
    for kids in groups.values():
        if not all(k in covered for k in kids):
            for k in kids:
                covered.pop(k, None)
    by = {p: 0 for p in ("P1", "P2", "P3", "P4")}
    for mid in covered:
        by[st.missions[mid].priority] += 1
    return {"covered": len(covered), "by": by, "ms": int((time.perf_counter() - t0) * 1000)}


def apply_splits() -> int:
    """Plan once and apply every checked split fix offered (reliefs, parts from several bases). -> splits applied."""
    from datetime import datetime as _dt
    from .db import SessionLocal
    from .decide import planner as P, snapshot as S, split as SP
    from . import models as M
    with SessionLocal() as db:
        res = P.plan(S.build(db), "BALANCED", workers=1, seed=0)
        n = 0
        for u in res.unmet:
            f = next((f for f in u["fixes"] if f["kind"].startswith("SPLIT_")), None)
            if f:
                SP.apply(db, USER, db.get(M.Mission, u["mission_id"]), f["kind"], f["parts"], _dt.fromisoformat(f["t0"]), f.get("sizes"))
                n += 1
        db.commit()
    return n


def run_one(seed: int, epoch: str, scale: float = 1.0) -> tuple[list, list]:
    from .db import SessionLocal
    from .decide import exercise as EX, monitor, planner as P, snapshot as S, store
    rows, rt = [], []
    splits = apply_splits()                      # as a planner would: apply the checked split fixes first (D42)
    with SessionLocal() as db:
        t0 = time.perf_counter()
        st = S.build(db)
        build_ms = int((time.perf_counter() - t0) * 1000)
    of = {p: sum(1 for m in st.missions.values() if m.priority == p) for p in ("P1", "P2", "P3", "P4")}
    plans = {}
    for preset in PRESETS:
        res = P.plan(st.clone(), preset, workers=1, seed=0)
        k = res.kpis
        plans[preset] = res
        rows.append({"seed": seed, "epoch": epoch, "scale": scale, "splits": splits, "method": f"CP-SAT {preset}", "missions": k["missions"], "covered": k["covered"],
                     **{f"{p}_cov": k["by_priority"][p]["covered"] for p in of}, **{f"{p}_of": of[p] for p in of},
                     "solve_ms": k["solve_ms"], "total_ms": res.total_ms, "build_ms": build_ms, "violations": k["violations"],
                     "sorties": k["sorties"], "tankers": k.get("tanker_sorties", 0), "flying_h": k["flying_hours"], "fuel_kl": round(k["fuel_l"] / 1000, 1),
                     "risk_peak": k["risk_peak"], "snag_expected": k.get("snag_expected"), "status": k["solver_status"]})
    g = greedy(st.clone(), "BALANCED")
    rows.append({"seed": seed, "epoch": epoch, "scale": scale, "method": "Greedy BALANCED", "missions": len(st.missions), "covered": g["covered"],
                 **{f"{p}_cov": g["by"][p] for p in of}, **{f"{p}_of": of[p] for p in of}, "solve_ms": g["ms"], "total_ms": g["ms"],
                 "build_ms": build_ms, "violations": 0, "status": "GREEDY"})
    again = P.plan(st.clone(), "BALANCED", workers=1, seed=0)
    same = [(i["mission_id"], i["base_id"], i["launch_ts"], tuple(i["aircraft_ids"])) for i in again.items] == \
           [(i["mission_id"], i["base_id"], i["launch_ts"], tuple(i["aircraft_ids"])) for i in plans["BALANCED"].items]
    rows[0]["deterministic"] = same
    # ---- re-tasking on the committed BALANCED plan
    with SessionLocal() as db:
        pid = P.store(db, plans["BALANCED"], preset="BALANCED", user=USER)
        db.commit()
        ch = store.commit(db, pid, USER)
        db.commit()
    for name, kind, params in (("Runway closed (busiest base, 30 h)", "RUNWAY_CLOSED", {"base": "AUTO", "hours": 30}),
                               ("Pop-up P1 casualty evacuation", "MISSION_POPUP", {"mission_type": "CASEVAC", "priority": "P1",
                                                                                     "target_base": "AUTO", "window_h": 3})):
        with SessionLocal() as db:
            EX.inject(db, USER, kind, params, record=False)
            db.commit()
        t0 = time.perf_counter()
        out = monitor.check_once(USER, force=True)
        ms = int((time.perf_counter() - t0) * 1000)
        prop = out.get("proposal") or {}
        c = prop.get("changes") or {}
        moved = sum(c.get(x, 0) for x in ("SWAP", "MOVED", "NEW", "DIVERT", "REROLE"))
        kept, dropped = c.get("KEPT", 0), c.get("DROPPED", 0)
        rt.append({"seed": seed, "epoch": epoch, "scale": scale, "scenario": name, "issues": len(out.get("disruptions", [])), "check_ms": ms,
                   "proposal_ms": prop.get("ms"), "rung": prop.get("rung"), "kept": kept, "changed": moved, "dropped": dropped,
                   "stability": round(kept / max(1, kept + moved + dropped), 3) if prop else None,
                   "summary": prop.get("summary", "no change needed"), "committed": ch.get("NEW", 0) + ch.get("KEPT", 0)})
        if prop:
            with SessionLocal() as db:
                store.commit(db, prop["plan_id"], USER)
                db.commit()
    return rows, rt


def pct(a, b):
    return 100 * a / b if b else 100.0


def _table(rows: list, q) -> list:
    out = ["| Method | Coverage | P1 | P2 | P3 | P4 | Violations | Solve ms (mean / p95) | Total ms (mean / p95) | Sorties | Fuel kL | Peak risk | Expected defects |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for method in [f"CP-SAT {p}" for p in PRESETS] + ["Greedy BALANCED"]:
        rs = [r for r in rows if r["method"] == method]
        if not rs:
            continue
        cov = pct(sum(r["covered"] for r in rs), sum(r["missions"] for r in rs))
        pr = {p: pct(sum(r[f"{p}_cov"] for r in rs), sum(r[f"{p}_of"] for r in rs)) for p in ("P1", "P2", "P3", "P4")}
        s, t = [r["solve_ms"] for r in rs], [r["total_ms"] for r in rs]
        mean = lambda k: statistics.mean([r[k] for r in rs if r.get(k) is not None]) if any(r.get(k) is not None for r in rs) else None  # noqa: E731
        f = lambda v, d=0: "—" if v is None else f"{v:,.{d}f}"  # noqa: E731
        out.append(f"| {method} | {cov:.1f} % | {pr['P1']:.0f} % | {pr['P2']:.0f} % | {pr['P3']:.0f} % | {pr['P4']:.0f} % | "
                   f"{sum(r['violations'] for r in rs)} | {statistics.mean(s):,.0f} / {q(s):,.0f} | {statistics.mean(t):,.0f} / {q(t):,.0f} | "
                   f"{f(mean('sorties'))} | {f(mean('fuel_kl'))} | {f(mean('risk_peak'), 2)} | {f(mean('snag_expected'), 1)} |")
    return out


MANUAL_COLS = ["id", "started_at", "planner", "sim_time", "missions", "checks", "elapsed_s", "manual_covered", "manual_p1",
               "manual_p2", "optimiser_covered", "optimiser_p1", "optimiser_p2", "optimiser_ms"]


def manual_sessions() -> list[dict]:
    """Finished manual planning sessions (D43) from the database, merged into docs/manual_sessions.csv, which outlives
    reseeds (this harness and Admin → Regenerate both wipe the database)."""
    from .db import SessionLocal
    path = DOCS / "manual_sessions.csv"
    rows = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            rows = {(r["id"], r["started_at"]): r for r in csv.DictReader(f)}
    try:
        with SessionLocal() as db:
            for r in db.execute(text("""SELECT ms.id, ms.started_at, ms.sim_time, ms.missions, ms.checks, ms.result, u.display_name
                                        FROM manual_session ms LEFT JOIN app_user u ON u.id = ms.user_id
                                        WHERE ms.finished_at IS NOT NULL AND ms.result IS NOT NULL""")):
                res = r.result
                man, opt = res["manual"], res["optimiser"]
                rows[(str(r.id), r.started_at.isoformat())] = {
                    "id": r.id, "started_at": r.started_at.isoformat(), "planner": r.display_name, "sim_time": r.sim_time.isoformat(),
                    "missions": r.missions, "checks": r.checks, "elapsed_s": res["elapsed_s"], "manual_covered": man["covered"],
                    "manual_p1": man["by_priority"]["P1"]["covered"], "manual_p2": man["by_priority"]["P2"]["covered"],
                    "optimiser_covered": opt["covered"], "optimiser_p1": opt["by_priority"]["P1"]["covered"],
                    "optimiser_p2": opt["by_priority"]["P2"]["covered"], "optimiser_ms": opt["total_ms"]}
    except Exception:                            # no table yet (older database): keep what the CSV has
        pass
    out = sorted(rows.values(), key=lambda r: str(r["started_at"]))
    if out:
        DOCS.mkdir(exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=MANUAL_COLS)
            w.writeheader()
            w.writerows(out)
    return out


def _manual_section(ms: list[dict]) -> list[str]:
    out = ["", "## Manual planning baseline (PS-8)", ""]
    if not ms:
        return out + ["No manual sessions recorded yet. Run one from Planner → Manual baseline (a planner plans the same snapshot "
                      "by hand against the clock, the real rules judge it, and the optimiser plans it too); this report then "
                      "includes the results. Sessions are kept in `docs/manual_sessions.csv`.", ""]
    n = len(ms)
    f = lambda k: [float(r[k]) for r in ms]  # noqa: E731
    out += [f"{n} session(s). By hand: mean {statistics.mean(f('elapsed_s')) / 60:.1f} min to plan, "
            f"{statistics.mean(f('manual_covered')):.1f} missions covered on average; optimiser on the same snapshots: "
            f"{statistics.mean(f('optimiser_ms')) / 1000:.1f} s, {statistics.mean(f('optimiser_covered')):.1f} covered.", "",
            "| Started | Planner | Missions | Time by hand | Optimiser time | Covered by hand / optimiser | P1 | P2 | Checks |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in ms:
        out.append(f"| {str(r['started_at'])[:16]} | {r['planner'] or '—'} | {r['missions']} | {float(r['elapsed_s']) / 60:.1f} min | "
                   f"{float(r['optimiser_ms']) / 1000:.1f} s | {r['manual_covered']} / {r['optimiser_covered']} | "
                   f"{r['manual_p1']} / {r['optimiser_p1']} | {r['manual_p2']} / {r['optimiser_p2']} | {r['checks']} |")
    return out + [""]


def report(rows: list, rt: list, seeds: list, epochs: list, wall_s: float, manual: list | None = None) -> str:
    import ortools
    q = lambda xs, f=0.95: sorted(xs)[min(len(xs) - 1, int(f * len(xs)))] if xs else 0  # noqa: E731
    out = ["# Benchmark — decision support (Phase 2)", "",
           f"_Generated {datetime.now():%Y-%m-%d %H:%M} by `python -m app.bench` in {wall_s / 60:.1f} min. "
           f"Seeds {', '.join(map(str, seeds))} × epochs {', '.join(e[:16] + 'Z' for e in epochs)}. Every number comes from "
           "SIMULATED data._", "",
           f"Machine: {platform.processor() or platform.machine()}, {os.cpu_count()} logical CPUs, Python {platform.python_version()}, "
           f"OR-Tools {ortools.__version__}; solver with 1 worker and a fixed seed (deterministic).", "",
           "## Planner by preset (normal days)", "",
           "The first preset of each run also pays for warming the route cache, so its total time is the cold-start figure. "
           "Missions no single package can fly (each seeded day has a 6 h CAP and a flood-relief surge) are first split with "
           "the planner's checked fixes, as a planner would (D42); coverage counts each part as a mission."]
    normal = [r for r in rows if r.get("scale", 1.0) == 1.0]
    surge = [r for r in rows if r.get("scale", 1.0) != 1.0]
    out += [""] + _table(normal, q)
    if surge:
        out += ["", f"## Surge day ({surge[0]['scale']}× the normal mission load)", "",
                f"{surge[0]['missions']} missions in the horizon instead of about {round(surge[0]['missions'] / surge[0]['scale'])}: "
                "tails, crews, fuel and launch slots run short, so the choice of which missions to cover, and with what, matters.", ""]
        out += _table(surge, q)
    cp = [r for r in rows if r["method"] == "CP-SAT BALANCED"]
    gr = [r for r in rows if r["method"] == "Greedy BALANCED"]
    if cp and gr:
        lex = lambda r: tuple(r[f"{p}_cov"] for p in ("P1", "P2", "P3", "P4"))  # noqa: E731
        better = sum(1 for a, b in zip(cp, gr) if lex(a) > lex(b))
        worse = sum(1 for a, b in zip(cp, gr) if lex(a) < lex(b))
        out += ["", f"**Optimiser vs greedy (BALANCED, same candidates):** lexicographically better coverage in {better} of {len(cp)} "
                f"runs, equal in {len(cp) - better - worse}, worse in {worse}; {sum(a['covered'] - b['covered'] for a, b in zip(cp, gr)):+d} "
                "missions covered in total. Greedy commits early to the cheapest option for each high-priority mission and "
                "can starve later missions of the same tails, crews, fuel or launch slots; CP-SAT trades them off jointly.",
                "", f"**Determinism:** identical BALANCED plan on a second run in {sum(1 for r in cp if r.get('deterministic'))} of {len(cp)} runs."]
    out += ["", "## Per run (BALANCED vs greedy)", "",
            "| Seed | Epoch | Load | Missions | CP-SAT covered | P1 | P2 | P3 | Greedy covered | P1 | P2 | P3 | Tanker sorties | Solve ms | Total ms | Status |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r, g in zip(cp, gr):
        out.append(f"| {r['seed']} | {r['epoch'][:16]}Z | {r.get('scale', 1.0)}× | {r['missions']} | {r['covered']} | {r['P1_cov']}/{r['P1_of']} | "
                   f"{r['P2_cov']}/{r['P2_of']} | {r['P3_cov']}/{r['P3_of']} | {g['covered']} | {g['P1_cov']} | {g['P2_cov']} | {g['P3_cov']} | "
                   f"{r.get('tankers', 0)} | {r['solve_ms']:,} | {r['total_ms']:,} | {r['status']} |")
    out += ["", "## Re-tasking", "", "| Scenario | Runs | Proposal ms (mean / max) | Rungs | Packages kept | Summary (first run) |",
            "|---|---:|---:|---|---:|---|"]
    for name in dict.fromkeys(r["scenario"] for r in rt):
        rs = [r for r in rt if r["scenario"] == name and r.get("scale", 1.0) == 1.0] or [r for r in rt if r["scenario"] == name]
        ms = [r["proposal_ms"] for r in rs if r["proposal_ms"] is not None]
        rungs = ", ".join(sorted({r["rung"] for r in rs if r["rung"]})) or "—"
        stab = [r["stability"] for r in rs if r["stability"] is not None]
        out.append(f"| {name} | {len(rs)} | {(statistics.mean(ms) if ms else 0):,.0f} / {(max(ms) if ms else 0):,} | {rungs} | "
                   f"{(100 * statistics.mean(stab) if stab else 100):.0f} % | {rs[0]['summary']} |")
    out += ["", "Target (PRD NFR): a re-task proposal within 15 s of a disruption. \"Packages kept\" is the share of the committed "
            "plan the proposal leaves untouched (higher is more stable).", "",
            "Raw rows: `docs/benchmark.csv` (planner) and `docs/benchmark_retask.csv` (re-tasking).", ""]
    out += _manual_section(manual or [])
    return "\n".join(out)


def _load(path: Path) -> list[dict]:
    """A benchmark CSV back as typed rows (numbers, booleans, empty -> None)."""
    def cast(v: str):
        if v == "":
            return None
        if v in ("True", "False"):
            return v == "True"
        for f in (int, float):
            try:
                return f(v)
            except ValueError:
                pass
        return v
    with open(path, encoding="utf-8") as f:
        return [{k: cast(v) for k, v in r.items()} for r in csv.DictReader(f)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default=",".join(map(str, SEEDS)))
    ap.add_argument("--epochs", default=",".join(EPOCHS))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--report-only", action="store_true", help="rebuild BENCHMARK.md from the CSVs of the last run")
    a = ap.parse_args()
    if a.report_only:
        rows, rt = _load(DOCS / "benchmark.csv"), _load(DOCS / "benchmark_retask.csv")
        seeds = list(dict.fromkeys(int(r["seed"]) for r in rows))
        epochs = list(dict.fromkeys(r["epoch"] for r in rows))
        (DOCS / "BENCHMARK.md").write_text(report(rows, rt, seeds, epochs, 0, manual_sessions()), encoding="utf-8")
        print(f"wrote {DOCS / 'BENCHMARK.md'} from the CSVs")
        return
    seeds = [int(x) for x in a.seeds.split(",")][:1 if a.quick else None]
    epochs = a.epochs.split(",")[:1 if a.quick else None]
    t0 = time.perf_counter()
    ms = manual_sessions()                       # before the first reseed wipes them
    rows, rt = [], []
    runs = [(s, e, 1.0) for s in seeds for e in epochs] + [(seeds[0], epochs[0], SURGE)]
    try:
        for seed, epoch, scale in runs:
            gen_s = regen(seed, epoch, scale)
            r, x = run_one(seed, epoch, scale)
            rows += r
            rt += x
            b = next(v for v in r if v["method"] == "CP-SAT BALANCED")
            g = next(v for v in r if v["method"] == "Greedy BALANCED")
            print(f"seed {seed} {epoch[:16]} ×{scale}: generated in {gen_s:.0f} s, BALANCED {b['covered']}/{b['missions']} in "
                  f"{b['total_ms']} ms (greedy {g['covered']}); re-task {[v['proposal_ms'] for v in x]} ms", flush=True)
    finally:
        regen(*DEFAULT)
    DOCS.mkdir(exist_ok=True)
    cols = sorted({k for r in rows for k in r}, key=lambda k: list(rows[0]).index(k) if k in rows[0] else 99)
    with open(DOCS / "benchmark.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    with open(DOCS / "benchmark_retask.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rt[0]))
        w.writeheader()
        w.writerows(rt)
    (DOCS / "BENCHMARK.md").write_text(report(rows, rt, seeds, epochs, time.perf_counter() - t0, ms), encoding="utf-8")
    print(f"wrote {DOCS / 'BENCHMARK.md'}")


if __name__ == "__main__":
    main()
