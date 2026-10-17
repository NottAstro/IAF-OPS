# Benchmark — decision support (Phase 2)

_Generated 2026-10-17 20:22 by `python -m app.bench` in 5.4 min. Seeds 2026, 7, 42 × epochs 2026-10-17T06:00Z, 2026-01-12T01:30Z. Every number comes from SIMULATED data._

Machine: Intel64 Family 6 Model 198 Stepping 2, GenuineIntel, 20 logical CPUs, Python 3.12.13, OR-Tools 9.15.6755; solver with 1 worker and a fixed seed (deterministic).

## Planner by preset (normal days)

The first preset of each run also pays for warming the route cache, so its total time is the cold-start figure.

| Method | Coverage | P1 | P2 | P3 | P4 | Violations | Solve ms (mean / p95) | Total ms (mean / p95) | Sorties | Fuel kL | Peak risk | Expected defects |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CP-SAT BALANCED | 93.1 % | 91 % | 93 % | 91 % | 97 % | 0 | 473 / 851 | 3,662 / 5,443 | 102 | 647 | 0.51 | 3.5 |
| CP-SAT MAX_COVERAGE | 93.1 % | 91 % | 93 % | 91 % | 97 % | 0 | 499 / 894 | 2,526 / 4,428 | 102 | 663 | 0.51 | 3.4 |
| CP-SAT MIN_RISK | 93.1 % | 91 % | 93 % | 91 % | 97 % | 0 | 508 / 1,057 | 2,591 / 4,392 | 103 | 689 | 0.51 | 3.6 |
| CP-SAT MIN_FUEL | 93.1 % | 91 % | 93 % | 91 % | 97 % | 0 | 474 / 878 | 2,532 / 4,523 | 102 | 616 | 0.55 | 3.6 |
| Greedy BALANCED | 92.5 % | 91 % | 93 % | 89 % | 97 % | 0 | 612 / 729 | 612 / 729 | — | — | — | — |

## Surge day (2.5× the normal mission load)

144 missions in the horizon instead of about 58: tails, crews, fuel and launch slots run short, so the choice of which missions to cover, and with what, matters.

| Method | Coverage | P1 | P2 | P3 | P4 | Violations | Solve ms (mean / p95) | Total ms (mean / p95) | Sorties | Fuel kL | Peak risk | Expected defects |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CP-SAT BALANCED | 85.4 % | 95 % | 84 % | 74 % | 100 % | 0 | 2,609 / 2,609 | 19,050 / 19,050 | 225 | 1,562 | 0.55 | 7.6 |
| CP-SAT MAX_COVERAGE | 85.4 % | 95 % | 84 % | 74 % | 100 % | 0 | 2,654 / 2,654 | 16,874 / 16,874 | 225 | 1,578 | 0.55 | 7.3 |
| CP-SAT MIN_RISK | 85.4 % | 95 % | 84 % | 74 % | 100 % | 0 | 2,712 / 2,712 | 14,062 / 14,062 | 225 | 1,586 | 0.55 | 7.6 |
| CP-SAT MIN_FUEL | 85.4 % | 95 % | 84 % | 74 % | 100 % | 0 | 2,664 / 2,664 | 16,349 / 16,349 | 225 | 1,470 | 0.55 | 7.3 |
| Greedy BALANCED | 84.0 % | 95 % | 80 % | 74 % | 100 % | 0 | 1,744 / 1,744 | 1,744 / 1,744 | — | — | — | — |

**Optimiser vs greedy (BALANCED, same candidates):** lexicographically better coverage in 3 of 7 runs, equal in 4, worse in 0; +4 missions covered in total. Greedy commits early to the cheapest option for each high-priority mission and can starve later missions of the same tails, crews, fuel or launch slots; CP-SAT trades them off jointly.

**Determinism:** identical BALANCED plan on a second run in 7 of 7 runs.

## Per run (BALANCED vs greedy)

| Seed | Epoch | Load | Missions | CP-SAT covered | P1 | P2 | P3 | Greedy covered | P1 | P2 | P3 | Tanker sorties | Solve ms | Total ms | Status |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2026 | 2026-10-17T06:00Z | 1.0× | 52 | 50 | 5/5 | 20/21 | 12/13 | 50 | 5 | 20 | 12 | 4 | 295 | 3,550 | OPTIMAL |
| 2026 | 2026-01-12T01:30Z | 1.0× | 58 | 53 | 10/11 | 14/15 | 15/17 | 53 | 10 | 14 | 15 | 4 | 749 | 5,443 | OPTIMAL |
| 7 | 2026-10-17T06:00Z | 1.0× | 66 | 64 | 13/13 | 21/22 | 21/22 | 64 | 13 | 21 | 21 | 3 | 519 | 4,619 | OPTIMAL |
| 7 | 2026-01-12T01:30Z | 1.0× | 60 | 56 | 6/6 | 16/19 | 22/23 | 55 | 6 | 16 | 21 | 1 | 184 | 1,859 | OPTIMAL |
| 42 | 2026-10-17T06:00Z | 1.0× | 56 | 51 | 5/7 | 14/15 | 23/24 | 51 | 5 | 14 | 23 | 3 | 239 | 1,590 | OPTIMAL |
| 42 | 2026-01-12T01:30Z | 1.0× | 68 | 61 | 4/5 | 25/26 | 18/23 | 60 | 4 | 25 | 17 | 4 | 851 | 4,912 | OPTIMAL |
| 2026 | 2026-10-17T06:00Z | 2.5× | 144 | 123 | 20/21 | 41/49 | 35/47 | 121 | 20 | 39 | 35 | 2 | 2,609 | 19,050 | OPTIMAL |

## Re-tasking

| Scenario | Runs | Proposal ms (mean / max) | Rungs | Packages kept | Summary (first run) |
|---|---:|---:|---|---:|---|
| Runway closed (busiest base, 30 h) | 6 | 1,884 / 2,741 | full, partial | 76 % | 2 swap, 3 moved, 5 dropped |
| Pop-up P1 casualty evacuation | 6 | 210 / 273 | partial | 98 % | 1 new |

Target (PRD NFR): a re-task proposal within 15 s of a disruption. "Packages kept" is the share of the committed plan the proposal leaves untouched (higher is more stable).

Raw rows: `docs/benchmark.csv` (planner) and `docs/benchmark_retask.csv` (re-tasking).
