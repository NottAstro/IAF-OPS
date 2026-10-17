# Benchmark — decision support (Phase 2)

_Generated 2026-10-18 00:40 by `python -m app.bench` in 10.4 min. Seeds 2026, 7, 42 × epochs 2026-10-17T06:00Z, 2026-01-12T01:30Z. Every number comes from SIMULATED data._

Machine: Intel64 Family 6 Model 198 Stepping 2, GenuineIntel, 20 logical CPUs, Python 3.12.13, OR-Tools 9.15.6755; solver with 1 worker and a fixed seed (deterministic).

## Planner by preset (normal days)

The first preset of each run also pays for warming the route cache, so its total time is the cold-start figure. Missions no single package can fly (each seeded day has a 6 h CAP and a flood-relief surge) are first split with the planner's checked fixes, as a planner would (D42); coverage counts each part as a mission.

| Method | Coverage | P1 | P2 | P3 | P4 | Violations | Solve ms (mean / p95) | Total ms (mean / p95) | Sorties | Fuel kL | Peak risk | Expected defects |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CP-SAT BALANCED | 90.3 % | 91 % | 90 % | 88 % | 96 % | 0 | 865 / 1,649 | 5,200 / 9,323 | 125 | 720 | 0.55 | 4.4 |
| CP-SAT MAX_COVERAGE | 90.3 % | 91 % | 90 % | 88 % | 96 % | 0 | 878 / 1,633 | 5,225 / 8,075 | 125 | 734 | 0.55 | 4.3 |
| CP-SAT MIN_RISK | 90.0 % | 91 % | 90 % | 87 % | 96 % | 0 | 871 / 1,760 | 6,354 / 10,092 | 125 | 753 | 0.55 | 4.4 |
| CP-SAT MIN_FUEL | 90.3 % | 91 % | 90 % | 88 % | 96 % | 0 | 853 / 1,653 | 5,088 / 9,178 | 124 | 689 | 0.55 | 4.4 |
| Greedy BALANCED | 90.0 % | 91 % | 90 % | 87 % | 96 % | 0 | 1,331 / 1,560 | 1,331 / 1,560 | — | — | — | — |

## Surge day (2.5× the normal mission load)

154 missions in the horizon instead of about 62: tails, crews, fuel and launch slots run short, so the choice of which missions to cover, and with what, matters.

| Method | Coverage | P1 | P2 | P3 | P4 | Violations | Solve ms (mean / p95) | Total ms (mean / p95) | Sorties | Fuel kL | Peak risk | Expected defects |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CP-SAT BALANCED | 85.1 % | 92 % | 82 % | 77 % | 100 % | 0 | 4,276 / 4,276 | 28,124 / 28,124 | 252 | 1,629 | 0.55 | 8.5 |
| CP-SAT MAX_COVERAGE | 85.1 % | 92 % | 82 % | 77 % | 100 % | 0 | 4,464 / 4,464 | 28,728 / 28,728 | 252 | 1,645 | 0.55 | 8.2 |
| CP-SAT MIN_RISK | 85.1 % | 92 % | 82 % | 77 % | 100 % | 0 | 4,294 / 4,294 | 28,674 / 28,674 | 251 | 1,716 | 0.55 | 8.5 |
| CP-SAT MIN_FUEL | 83.8 % | 92 % | 82 % | 73 % | 100 % | 0 | 4,478 / 4,478 | 29,816 / 29,816 | 250 | 1,524 | 0.55 | 8.0 |
| Greedy BALANCED | 83.8 % | 92 % | 78 % | 77 % | 100 % | 0 | 3,744 / 3,744 | 3,744 / 3,744 | — | — | — | — |

**Optimiser vs greedy (BALANCED, same candidates):** lexicographically better coverage in 2 of 7 runs, equal in 5, worse in 0; +3 missions covered in total. Greedy commits early to the cheapest option for each high-priority mission and can starve later missions of the same tails, crews, fuel or launch slots; CP-SAT trades them off jointly.

**Determinism:** identical BALANCED plan on a second run in 7 of 7 runs.

## Per run (BALANCED vs greedy)

| Seed | Epoch | Load | Missions | CP-SAT covered | P1 | P2 | P3 | Greedy covered | P1 | P2 | P3 | Tanker sorties | Solve ms | Total ms | Status |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2026 | 2026-10-17T06:00Z | 1.0× | 58 | 54 | 8/8 | 22/24 | 11/13 | 54 | 8 | 22 | 11 | 4 | 485 | 4,274 | OPTIMAL |
| 2026 | 2026-01-12T01:30Z | 1.0× | 65 | 59 | 14/15 | 16/18 | 15/17 | 59 | 14 | 16 | 15 | 4 | 1,304 | 9,323 | OPTIMAL |
| 7 | 2026-10-17T06:00Z | 1.0× | 72 | 68 | 15/15 | 24/26 | 20/22 | 68 | 15 | 24 | 20 | 4 | 882 | 6,895 | OPTIMAL |
| 7 | 2026-01-12T01:30Z | 1.0× | 68 | 62 | 7/8 | 21/25 | 22/23 | 61 | 7 | 21 | 21 | 1 | 388 | 3,074 | OPTIMAL |
| 42 | 2026-10-17T06:00Z | 1.0× | 63 | 55 | 8/11 | 16/18 | 22/24 | 55 | 8 | 16 | 22 | 5 | 480 | 3,084 | OPTIMAL |
| 42 | 2026-01-12T01:30Z | 1.0× | 76 | 65 | 6/7 | 29/32 | 17/23 | 65 | 6 | 29 | 17 | 5 | 1,649 | 4,551 | OPTIMAL |
| 2026 | 2026-10-17T06:00Z | 2.5× | 154 | 131 | 22/24 | 45/55 | 37/48 | 129 | 22 | 43 | 37 | 3 | 4,276 | 28,124 | OPTIMAL |

## Re-tasking

| Scenario | Runs | Proposal ms (mean / max) | Rungs | Packages kept | Summary (first run) |
|---|---:|---:|---|---:|---|
| Runway closed (busiest base, 30 h) | 6 | 2,817 / 3,917 | full, partial | 80 % | 4 swap, 3 moved, 4 dropped |
| Pop-up P1 casualty evacuation | 6 | 469 / 724 | partial | 98 % | 1 new |

Target (PRD NFR): a re-task proposal within 15 s of a disruption. "Packages kept" is the share of the committed plan the proposal leaves untouched (higher is more stable).

Raw rows: `docs/benchmark.csv` (planner) and `docs/benchmark_retask.csv` (re-tasking).


## Manual planning baseline (PS-8)

No manual sessions recorded yet. Run one from Planner → Manual baseline (a planner plans the same snapshot by hand against the clock, the real rules judge it, and the optimiser plans it too); this report then includes the results. Sessions are kept in `docs/manual_sessions.csv`.
