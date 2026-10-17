# iaf-airops: Air Operations Picture and Decision Support (SIH26250)

A prototype for Smart India Hackathon 2026, problem statement **SIH26250** ("Air Power – Dynamic Air Operations & Resource Optimisation", MoD / DSSC).

**The common picture (Phase 1)**
- a synthetic-but-realistic **inventory system of record** (full CRUD, roles, audit trail)
- a dark, military-styled **3D map dashboard** of South Asia
- live public feeds: ADS-B, METAR/TAF, forecasts, weather overlays, wind

**Decision support (Phase 2)** ([plan](docs/PHASE2_IMPLEMENTATION_PLAN.md), [requirements](docs/PRD.md#17-phase-2-decision-support-sih26250-dynamic-air-operations-and-resource-optimisation))
- **Missions**: prioritised (P1–P4) tasking with windows, areas, requirements and an approval workflow
- **Planner**: assigns base, aircraft, tails, crew and a generic loadout to every mission with OR-Tools CP-SAT; P1 coverage first, then P2…; respects serviceability, QRA posture, crew currency / rest / qualifications / instrument rating, weather minima, range, border buffer, threat risk, airspace, weapons and fuel. Every package explains itself; every uncovered mission says why and what would fix it
- **Dynamic re-tasking**: the committed plan is re-checked every 12 s; a closed runway, a grounded fleet, a weather front or a pop-up P1 becomes a re-task proposal (usually < 1 s) that changes as little as possible; a person commits it
- **Air-to-air refuelling** (tanker legs when a package can't reach or hold), **runway launch rates**, **in-flight re-roling** of airborne packages for urgent pop-ups, and **civil-traffic deconfliction** (busy terminal areas and live ADS-B density cost more)
- **Package dependencies and split missions**: barrier CAPs fly only under their AEW&C orbit; a 6-hour patrol or a flood-relief surge no single package can fly is offered a checked split (reliefs or parts from several bases) that a planner applies with one click
- **Manual planning baseline** (Planner → Manual baseline): plan by hand against the clock with the real rules as referee; results sit beside the optimiser's in the benchmark (PS-8)
- **Public airspace** (optional): `python -m app.decide.airspace_import` with `OPENAIP_API_KEY` adds published prohibited / restricted / danger and civil terminal airspace
- **Predictive maintenance**: a snag-risk model learned from the maintenance log ([model card](docs/MODEL_CARD_SNAG_RISK.md)) gives P1/P2 packages the most reliable tails and feeds the forecasts
- **What-if and COA comparison**, **72 h forecasts**, and an **exercise mode** for directing staff (scenario injects, after-action report)
- **Measured**: [benchmark](docs/BENCHMARK.md) over several seeded days and a surge day (`python -m app.bench`)
- the tick simulator flies the committed plan in the **Ops** map view; the Live view stays real data only

> **All operational data is SIMULATED.** Base names and locations are public (Wikipedia, OurAirports). Everything inside a base (aircraft, crew, fuel, stores, AD, radar) is generated. All people are fictional.

Docs: [PRD](docs/PRD.md) · [Data model](docs/DATA_MODEL.md) · [Architecture](docs/ARCHITECTURE.md) · [Free APIs](docs/API.md) · [Design system](docs/DESIGN_SYSTEM.md) · [Build plan](docs/IMPLEMENTATION_PLAN.md) · [Agent rules](AGENTS.md)

## Run it

**Windows (PowerShell, Docker Desktop running):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # venv (Python 3.12 via uv), npm, PostGIS in Docker, boundaries, seed (~10 min)
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1     # database + wind :8787 + API :8010 + web :5173
powershell -ExecutionPolicy Bypass -File scripts\check.ps1   # backend tests + typecheck + vitest (stop dev.ps1 first)
```
To skip the boundary pipeline on a second machine: `scripts\dbdump.ps1` on the first, copy `data\dumps\airops.dump`, then `scripts\setup.ps1 -Restore`.

**Phase 2 in five minutes:** sign in as `airhq` → **Planner** → *Generate plan* → open a package ("Why this package") and an uncovered mission ("What would fix it") → *Commit plan* → **Map → Ops** to see the routes. Sign in as `admin` in another browser → **Exercise** → start *Runway closure and pop-up tasking* (×60) → back in the Planner, review and commit each re-task proposal → **Exercise → After-action report**.

**macOS, already set up on this machine:**
```bash
make dev          # wind sidecar :8787 + API :8010 + web :5173
```
Then open **http://localhost:5173**.
- Password for every demo user: the `DEMO_PASSWORD` in `.env`.
- Demo users:

| User | Role / scope |
|---|---|
| `admin` | Admin |
| `airhq` | Command HQ (all) |
| `wac.hq`, `eac.hq` | Command HQ (one command) |
| `cdr.viax`, `cdr.vetz`, `cdr.vijo` | Base Commander |
| `viewer` | Viewer |

**From scratch (macOS):**
```bash
brew install postgresql@17 postgis osmium-tool      # + nvm with Node 24, Python 3.13
cp .env.example .env                                # then add the keys (see comments in the file)
make setup        # venv + npm installs
make db           # start Postgres, create DB + PostGIS + schema
make pipeline     # official GoI boundaries, districts, places, civil airports  (~8 min)
make osm          # OSM roads / rail / telecom towers  (~4.6 GB download)
make seed         # synthetic inventory + 90 days of history  (~15 s)
make dev
```

Other commands:
- `make test`: API, RBAC, audit, invariant and boundary checks
- `make check`: `make test` plus the frontend typecheck
- `make netcheck`: probe every upstream before a demo

## What's where
| Path | What |
|---|---|
| `backend/app/` | FastAPI: auth, RBAC, generic CRUD, base summary, overview, live-air poller, weather proxies, simulator, WebSocket |
| `backend/app/decide/` | Phase 2 decision engine: snapshot, feasibility (incl. tanker legs), CP-SAT optimiser, assignment, validator, explanations, re-tasking monitor (incl. in-flight re-role), snag-risk model (`predict.py`, `model_card.py`), civil traffic (`traffic.py`), forecasts, what-if, exercise |
| `backend/app/bench.py` | benchmark harness → `docs/BENCHMARK.md` (overwrites the database; dev only) |
| `backend/app/routers/ops.py`, `exercise.py` | Phase 2 API under `/api/v1/ops/…` |
| `backend/generator/` | deterministic synthetic data generator (`SEED`, `SIM_EPOCH`) |
| `pipeline/` | curated CSV builder, boundary pipeline, OSM pipeline |
| `frontend/src/` | React + TypeScript + MapLibre GL. `map/` holds the map code (style, symbols, wind); `features/`, `pages/` the screens |
| `wind/` | Node sidecar running God's Eye View's GFS/ECMWF wind server |
| `data/curated/` | public seed lists (bases, squadrons, types, AD/radar names) with source URLs. **VERIFY** flags are still set |

## Troubleshooting
- **"The 3D map couldn't start"**: the browser has no WebGL. Use Chrome or Edge with hardware acceleration on.
- **Port 8000 is taken** by another app on this machine, so the API runs on `API_PORT=8010` (`.env`).
- **Campus network**: the map needs `tiles.openfreemap.org` (basemap + fonts) and `s3.amazonaws.com` (terrain); `make netcheck` probes them. TLS-inspected HTTPS is trusted through the macOS keychain (`truststore`).
- **Wind layer unavailable**: the wind sidecar isn't running (`cd wind && npm start`).

Third-party code and data: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
