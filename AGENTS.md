# AGENTS.md: rules for agents building iaf-airops

You are building **Phase 1** of an SIH 2026 entry for problem statement **SIH26250** (Ministry of Defence / DSSC). Phase 1 has four parts:
- an inventory management system
- realistic synthetic data
- a dark military map dashboard (MapLibre GL; 3D terrain by default, flat in the Weather view; navy + neon-blue theme)
- a tick simulator, **switched off for Phase 1** (`SIM_ENABLED=false`, ARCHITECTURE D20): the map shows only real/public data

These rules override your defaults. If a doc is silent or ambiguous, **ask; don't invent**.

## 1. Scope
- Build only what [docs/PRD.md](docs/PRD.md) specifies.
- **Do not write decision-support code:** no optimisation, scheduling solvers, recommendation, scoring/ranking or predictive models. That is Phase 2. Leave clean data and APIs, nothing more.
- Do not add features, layers or screens that aren't in the PRD. Propose them instead.

## 2. Doc map (read before you start a task)
| Task touches… | Read |
|---|---|
| What and why, requirement IDs, acceptance criteria | [docs/PRD.md](docs/PRD.md) |
| Tables, enums, views, invariants, generator, simulator | [docs/DATA_MODEL.md](docs/DATA_MODEL.md) |
| Modules, routes, live-air / weather / GIS pipelines, God's Eye ports, env, compose | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Any external URL, key, limit or licence | [docs/API.md](docs/API.md) |
| Anything visual, wording, symbols, SIM labelling | [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md) |
| What to build next, done-when checks | [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) |

## 3. Stack (pinned)
| Area | Pinned choices |
|---|---|
| Frontend | Node 24, React 18, TypeScript strict, Vite 6, **MapLibre GL JS 5.24** (ARCHITECTURE D19), TanStack Query/Table, Zustand, React Router, React Hook Form + Zod, Lucide, @fontsource/b612(-mono) |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async) + GeoAlchemy2, asyncpg, Alembic, httpx, argon2-cffi, PyJWT, structlog |
| Database | PostgreSQL 16 + PostGIS 3.4 |
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

## 5. Folder ownership and import rules
- **MapLibre code lives only under `frontend/src/map/`.** Features talk to the map through the Zustand store and `map/` APIs (`toggleTilt`), never by importing `maplibre-gl` directly.
- **React never holds map objects in state beyond the one instance in `MapView`.** There is exactly one map; it is created and removed in one effect, so it is StrictMode-safe.
- `frontend/src/vendor/godseye/` holds verbatim ports. It is used only through `map/` adapters.
- `backend/app/models.py` is the single schema source. The generator imports models; the pipeline is independent.
- Routers stay thin. Logic goes in services, `crud.py`, `live/`, `weather/` or `sim/`.
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
