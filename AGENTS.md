# AGENTS.md: rules for agents building iaf-airops

You are building an SIH 2026 entry for problem statement **SIH26250** (Ministry of Defence / DSSC): "Air Power: Dynamic Air
Operations & Resource Optimisation". It has two layers:
- **Phase 1, the common picture:** an inventory system of record, realistic synthetic data, and a dark military map dashboard
  (MapLibre GL; 3D terrain by default, flat in the Weather view; navy + neon-blue theme).
- **Phase 2, decision support** ([docs/PHASE2_IMPLEMENTATION_PLAN.md](docs/PHASE2_IMPLEMENTATION_PLAN.md)): mission tasking, an
  optimising planner, dynamic re-tasking, explanations, forecasts, what-if / COA comparison, and an exercise mode. The tick
  simulator is back on (`SIM_ENABLED=true`, ARCHITECTURE D29), but only in the **Ops** map view; the Live view stays real data only.

These rules override your defaults. If a doc is silent or ambiguous, **ask; don't invent**.

## 1. Scope
- Build only what [docs/PRD.md](docs/PRD.md) (incl. §17, Phase 2) and the Phase 2 plan specify.
- **Decision-support code lives in `backend/app/decide/`.** Recommendations are advisory: nothing reaches the sortie tables
  without a human approval that is audited (plan commit, `decide/store.py`). Never write sorties from the planner directly.
- **Overview screens stay values-only** (FR-CMD-04). Scores, rankings and explanations appear only in the Planner.
- The planner's rules (minima, rest, risk levels, loadouts) are SIMULATED policy in `decide/config.py`; keep them there.
- Do not add features, layers or screens that aren't in the PRD. Propose them instead.

## 2. Doc map (read before you start a task)
| Task touches… | Read |
|---|---|
| What and why, requirement IDs, acceptance criteria | [docs/PRD.md](docs/PRD.md) |
| Tables, enums, views, invariants, generator, simulator | [docs/DATA_MODEL.md](docs/DATA_MODEL.md) |
| Modules, routes, live-air / weather / GIS pipelines, God's Eye ports, env, compose | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Any external URL, key, limit or licence | [docs/API.md](docs/API.md) |
| Anything visual, wording, symbols, SIM labelling | [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md) |
| What to build next, done-when checks | [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) (Phase 1), [docs/PHASE2_IMPLEMENTATION_PLAN.md](docs/PHASE2_IMPLEMENTATION_PLAN.md) (Phase 2) |

## 3. Stack (pinned)
| Area | Pinned choices |
|---|---|
| Frontend | Node 24, React 18, TypeScript strict, Vite 6, **MapLibre GL JS 5.24** (ARCHITECTURE D19), TanStack Query/Table, Zustand, React Router, React Hook Form + Zod, Lucide, @fontsource/b612(-mono) |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + GeoAlchemy2, psycopg 3, httpx, argon2-cffi, PyJWT |
| Decision support | **OR-Tools CP-SAT 9.15** (Apache-2.0: the only solver dependency; the model builder stays solver-agnostic), pyshp (pure-Python shapefiles, so Windows needs no GDAL) |
| Database | PostgreSQL 17 + PostGIS 3.5 (Docker `docker-compose.yml` on Windows; Homebrew on macOS) |
| Wind sidecar | Node 24, God's Eye wind server, `@meri-imperiumi/eccodes-wasm` |
| Tests | pytest (+ pytest-asyncio), vitest, one Playwright smoke |
| Lint | ruff, mypy, eslint, prettier, stylelint |

- No Resium. No CSS-in-JS. No new dependency without a one-line justification in the PR.
- Don't add a library for what a few lines can do.

## 4. Run commands
| Command | Does |
|---|---|
| `make setup` / `make db` | install deps / start Homebrew Postgres + create schema (no Docker, see ARCHITECTURE D10) |
| `make pipeline` / `make osm` | build static GIS tables (boundaries+places / OSM roads, rail, towers) |
| `make seed` | run the generator + post-generation checks |
| `make dev` | run wind sidecar (:8787) + API (:8010) + web (:5173) |
| `make test` | all tests |
| `make check` | lint + typecheck + tests |
| `make netcheck` | probe every upstream in API.md |

On Windows (ARCHITECTURE D32): `scripts\setup.ps1` (venv, npm, PostGIS in Docker, GIS pipeline, seed; `-Restore` loads a dump
from `scripts\dbdump.ps1` instead), `scripts\dev.ps1` (database + wind + API + web), `scripts\check.ps1` (tests + typecheck;
stop `dev.ps1` first: the running simulator writes to the same database).

## 5. Folder ownership and import rules
- **MapLibre code lives only under `frontend/src/map/`.** Features talk to the map through the Zustand store and `map/` APIs (`toggleTilt`), never by importing `maplibre-gl` directly.
- **React never holds map objects in state beyond the one instance in `MapView`.** There is exactly one map; it is created and removed in one effect, so it is StrictMode-safe.
- `frontend/src/vendor/godseye/` holds verbatim ports. It is used only through `map/` adapters.
- `backend/app/models.py` is the single schema source. The generator imports models; the pipeline is independent.
- Routers stay thin. Logic goes in services, `crud.py`, `live/`, `weather/`, `sim/` or `decide/`.
- `decide/snapshot.py` is the planner's only view of the world. The planner, validator, forecasts, what-if and re-tasking
  read an `OpsState`; what-if works on `clone()` and never writes. `decide/resources.py` is the one definition of "free" and
  "eligible": reuse it rather than re-deriving availability.
- Sortie creation goes through `services/sorties.py` (human sorties and plan commit alike); weapons reservation through `adjust_stock()`.
- `sim/reliability.py` is the simulated world's hidden defect law. `decide/` must never import it: the snag-risk model
  (`decide/predict.py`) learns only from `maintenance_event` + `sortie_aircraft.hsm_at_launch`. Only the evaluation tool
  `decide/model_card.py` may compare against it (D38).
- The validator (`decide/validate.py`) and the optimiser's rows (`decide/optimiser.py`) must mean the same thing for every
  limit (concurrency at start events for aircraft, crew, weapons, QRA; totals for fuel; slots for launches). Change both
  or neither (D40). Civil traffic is a cost, never a rule (D39).
- One package per mission is an invariant: split missions are separate part missions (D42), never several items for one
  mission id. Dependencies are one level (D41). Inside the planner the validator gets `cover=` (supporters outside the
  solve only); elsewhere it falls back to the committed plan.
- Test runs must not leave `manual_session` rows: the benchmark reports them as human baselines (D43).
- Reuse `crud_router`, `audit()`, `rbac.require()`, `DataTable` and `EntityForm` instead of writing one-off versions.
- The region bbox and border buffer come **only** from `shared/region.json`.

## 6. Conventions
- **Storage:** SI-like units (m, kg, L, kt) and UTC. Convert in the UI: IST primary, Zulu secondary.
- **Enums** are `VARCHAR + CHECK` and flow to TS via OpenAPI. No `any` in TS.
- **Mutations:** every mutating route is RBAC-checked and audited in the same transaction. Every `PATCH` requires `version`.
- **Copy:** UI copy follows DESIGN_SYSTEM §13. Sentence case; uppercase only for real codes.
- **Colours:** use CSS tokens from `styles/tokens.css` only. Map colours come from `map/colors.ts`.
- **Comments:** mark deliberate shortcuts with a `ponytail:` comment naming the ceiling and the upgrade path.

## 7. Testing rules
- **No live network in tests.** Use recorded fixtures in `data/fixtures/`.
- These suites must stay green:
  - RBAC matrix
  - audit-per-mutation
  - optimistic-lock 409
  - generator determinism + invariants + denylist
  - pipeline boundary tests
  - simulator soak (`SIM_ASSERT=1`), when the simulator is switched back on
  - classifier fixtures
- New non-trivial logic leaves one runnable test (the smallest one that would fail if the logic broke).

## 8. Data sensitivity rules
**MUST:**
- All people are **fictional**. Generated names are checked against `names_denylist.csv`. No photos.
- Every synthetic row has `is_simulated = true`. Every synthetic surface shows the SIM treatment (DESIGN_SYSTEM §9).
- Public facts (base locations, ORBAT, system names) carry a `source_ref` URL.
- Neighbour and other-service bases show **public information only**. They have no inventory rows (invariant I1).
- Do not add a classification banner (removed by the team, ARCHITECTURE D22). Keep the login disclaimer and SIM labels.

**MUST NOT:**
- Use real personnel, real airframe serials or any non-public information.
- Place synthetic radar, AD or comms sites using OSM `military=*`, God's Eye `names.json` or deployment reporting. Use the generator's rules only.
- Let simulated IAF tracks or sites come within `border_buffer_km` of the boundary, or let simulated unknowns cross it.
- Show real classification markings (RESTRICTED…TOP SECRET, NOFORN…), or the IAF roundel, fin flash or ensign. The official crest is allowed only where DESIGN_SYSTEM §10 places it (team decision, ARCHITECTURE D21), unaltered.
- Store or log personal data of real people.

## 9. Maps and boundaries
- **India must be shown as officially depicted by the Government of India.** Use the DataMeet SoI/composite outline and the Natural Earth India point-of-view file.
- **Clip every neighbour polygon** against the India outline (`ST_Difference`) before it is stored.
- **Never render third-party boundary or label layers:** no OSM raster tiles, Bing labels or Google 3D. The OpenFreeMap basemap is used for terrain features only; its `boundary`, `place`, `poi` and other label layers stay out of `map/style.ts` (ocean/sea names excepted). Every boundary and name comes from `/gis/tiles`.
- The boundary tests must pass before any map PR merges.

## 10. Licences and God's Eye ports
- God's Eye View (`../gods-eye-view`) is MIT. Every ported or adapted file starts with:
  ```
  // Portions derived from God's Eye View (<original path>),
  // Copyright (c) 2026 Bilawal Sidhu, MIT License. See THIRD_PARTY_NOTICES.md.
  ```
- `aircraftClass.js` ports also credit **skylight** (MIT).
- Add every port and dataset to `THIRD_PARTY_NOTICES.md` and the credits panel (API.md §10).
- **Never copy `src/hud.js` strings** (it contains a US classification banner) or God's Eye's CSS theme wholesale.
- The God's Eye `.glb` models are CC BY 4.0 and need their attribution. `names.json` is ODbL and may be used for validation only.
- Several feeds are **non-commercial** (OpenSky, adsb.fi, Open-Meteo free). Flag this if the project is ever productised.

## 11. Secrets and network
- Secrets live in `.env` only. Provider keys stay server-side and are proxied by FastAPI.
- `VITE_` variables are only for values that are public by design (none are needed now that Cesium ion is gone).
- Upstream proxies use a fixed host allow-list, timeouts and size caps. Never accept a user-supplied URL.
- On TLS-inspecting networks, set `HTTPS_CA_BUNDLE` instead of disabling verification.

## 12. Decision log
When you diverge from a doc, update the doc in the same PR and add a row to ARCHITECTURE §18. If a doc doesn't cover something, ask the team before deciding.

## 13. Definition of done and git
- Done means:
  - the "Done when" checks for the milestone pass
  - `make check` is green
  - docs are updated
  - SIM labels are present
  - licence headers are present
- One branch per milestone. Commit or push only when asked.
- Follow the commit and PR attribution lines your harness specifies.
