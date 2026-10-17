# Benchmark — decision support (Phase 2)

_Generated 2026-10-18 01:32 by `python -m app.bench` in 7.6 min. Seeds 2026, 7, 42 × epochs 2026-10-17T06:00Z, 2026-01-12T01:30Z. Every number comes from SIMULATED data._

Machine: Intel64 Family 6 Model 198 Stepping 2, GenuineIntel, 20 logical CPUs, Python 3.12.13, OR-Tools 9.15.6755; solver with 1 worker and a fixed seed (deterministic).

## Planner by preset (normal days)

The first preset of each run also pays for warming the route cache, so its total time is the cold-start figure. Missions no single package can fly (each seeded day has a 6 h CAP and a flood-relief surge) are first split with the planner's checked fixes, as a planner would (D42); coverage counts each part as a mission.

| Method | Coverage | P1 | P2 | P3 | P4 | Violations | Solve ms (mean / p95) | Total ms (mean / p95) | Sorties | Fuel kL | Peak risk | Expected defects |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CP-SAT BALANCED | 89.2 % | 91 % | 86 % | 88 % | 96 % | 0 | 772 / 1,399 | 3,615 / 5,947 | 118 | 711 | 0.55 | 4.2 |
| CP-SAT MAX_COVERAGE | 89.2 % | 91 % | 86 % | 88 % | 96 % | 0 | 772 / 1,464 | 3,626 / 5,902 | 118 | 726 | 0.55 | 4.1 |
| CP-SAT MIN_RISK | 88.9 % | 91 % | 86 % | 87 % | 96 % | 0 | 754 / 1,454 | 4,078 / 6,856 | 118 | 743 | 0.55 | 4.2 |
| CP-SAT MIN_FUEL | 89.2 % | 91 % | 86 % | 88 % | 96 % | 0 | 742 / 1,423 | 3,599 / 5,555 | 118 | 682 | 0.55 | 4.2 |
| Greedy BALANCED | 88.9 % | 91 % | 86 % | 87 % | 96 % | 0 | 1,071 / 1,249 | 1,071 / 1,249 | — | — | — | — |

## Surge day (2.5× the normal mission load)

154 missions in the horizon instead of about 62: tails, crews, fuel and launch slots run short, so the choice of which missions to cover, and with what, matters.

| Method | Coverage | P1 | P2 | P3 | P4 | Violations | Solve ms (mean / p95) | Total ms (mean / p95) | Sorties | Fuel kL | Peak risk | Expected defects |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CP-SAT BALANCED | 85.1 % | 92 % | 82 % | 77 % | 100 % | 0 | 3,763 / 3,763 | 16,404 / 16,404 | 264 | 1,644 | 0.55 | 9.2 |
| CP-SAT MAX_COVERAGE | 85.1 % | 92 % | 82 % | 77 % | 100 % | 0 | 3,813 / 3,813 | 16,838 / 16,838 | 264 | 1,664 | 0.55 | 9.0 |
| CP-SAT MIN_RISK | 85.1 % | 92 % | 82 % | 77 % | 100 % | 0 | 3,778 / 3,778 | 16,292 / 16,292 | 263 | 1,727 | 0.55 | 9.2 |
| CP-SAT MIN_FUEL | 85.1 % | 92 % | 82 % | 77 % | 100 % | 0 | 3,842 / 3,842 | 16,591 / 16,591 | 264 | 1,561 | 0.55 | 8.9 |
| Greedy BALANCED | 83.8 % | 92 % | 78 % | 77 % | 100 % | 0 | 2,854 / 2,854 | 2,854 / 2,854 | — | — | — | — |

**Optimiser vs greedy (BALANCED, same candidates):** lexicographically better coverage in 2 of 7 runs, equal in 5, worse in 0; +3 missions covered in total. Greedy commits early to the cheapest option for each high-priority mission and can starve later missions of the same tails, crews, fuel or launch slots; CP-SAT trades them off jointly.

**Determinism:** identical BALANCED plan on a second run in 7 of 7 runs.

## Per run (BALANCED vs greedy)

| Seed | Epoch | Load | Missions | CP-SAT covered | P1 | P2 | P3 | Greedy covered | P1 | P2 | P3 | Tanker sorties | Solve ms | Total ms | Status |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2026 | 2026-10-17T06:00Z | 1.0× | 58 | 54 | 8/8 | 22/24 | 11/13 | 54 | 8 | 22 | 11 | 4 | 434 | 2,737 | OPTIMAL |
| 2026 | 2026-01-12T01:30Z | 1.0× | 65 | 59 | 14/15 | 16/18 | 15/17 | 59 | 14 | 16 | 15 | 4 | 1,266 | 5,947 | OPTIMAL |
| 7 | 2026-10-17T06:00Z | 1.0× | 71 | 66 | 15/15 | 22/25 | 20/22 | 66 | 15 | 22 | 20 | 4 | 798 | 4,479 | OPTIMAL |
| 7 | 2026-01-12T01:30Z | 1.0× | 67 | 60 | 7/8 | 19/24 | 22/23 | 59 | 7 | 19 | 21 | 1 | 343 | 2,365 | OPTIMAL |
| 42 | 2026-10-17T06:00Z | 1.0× | 62 | 53 | 8/11 | 14/17 | 22/24 | 53 | 8 | 14 | 22 | 5 | 391 | 2,384 | OPTIMAL |
| 42 | 2026-01-12T01:30Z | 1.0× | 75 | 63 | 6/7 | 27/31 | 17/23 | 63 | 6 | 27 | 17 | 5 | 1,399 | 3,776 | OPTIMAL |
| 2026 | 2026-10-17T06:00Z | 2.5× | 154 | 131 | 22/24 | 45/55 | 37/48 | 129 | 22 | 43 | 37 | 3 | 3,763 | 16,404 | OPTIMAL |

## Re-tasking

| Scenario | Runs | Proposal ms (mean / max) | Rungs | Packages kept | Summary (first run) |
|---|---:|---:|---|---:|---|
| Runway closed (busiest base, 30 h) | 6 | 2,376 / 3,405 | full, partial | 81 % | 4 swap, 3 moved, 4 dropped |
| Pop-up P1 casualty evacuation | 6 | 378 / 549 | partial | 98 % | 1 new |

Target (PRD NFR): a re-task proposal within 15 s of a disruption. "Packages kept" is the share of the committed plan the proposal leaves untouched (higher is more stable).

Raw rows: `docs/benchmark.csv` (planner) and `docs/benchmark_retask.csv` (re-tasking).


## Manual planning baseline (PS-8)

No manual sessions recorded yet. Run one from Planner → Manual baseline (a planner plans the same snapshot by hand against the clock, the real rules judge it, and the optimiser plans it too); this report then includes the results. Sessions are kept in `docs/manual_sessions.csv`.
