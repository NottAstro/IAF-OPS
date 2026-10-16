# iaf-airops: Air Ops Picture & Inventory (SIH26250, Phase 1)

A prototype for Smart India Hackathon 2026, problem statement **SIH26250** ("Air Power – Dynamic Air Operations & Resource Optimisation", MoD / DSSC). It has four parts:
- a synthetic-but-realistic **inventory system of record** (full CRUD, roles, audit trail)
- a dark, military-styled **3D map dashboard** of South Asia
- a tick simulator (switched off for Phase 1; the map shows only real/public data)
- live public feeds: ADS-B, METAR/TAF, forecasts, weather overlays, wind

> **All operational data is SIMULATED.** Base names and locations are public (Wikipedia, OurAirports). Everything inside a base (aircraft, crew, fuel, stores, AD, radar) is generated. All people are fictional.

Docs: [PRD](docs/PRD.md) · [Data model](docs/DATA_MODEL.md) · [Architecture](docs/ARCHITECTURE.md) · [Free APIs](docs/API.md) · [Design system](docs/DESIGN_SYSTEM.md) · [Build plan](docs/IMPLEMENTATION_PLAN.md) · [Agent rules](AGENTS.md)

## Run it

**Already set up on this machine:**
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
