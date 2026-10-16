# iaf-airops — native (Homebrew) setup. See README.md.
PY := .venv/bin/python
PG := /opt/homebrew/opt/postgresql@17/bin
NODE := export PATH="$$(ls -d $$HOME/.nvm/versions/node/v24*/bin | tail -1):$$PATH";

.PHONY: setup db pipeline osm stations seed dev stop test check netcheck curated

setup:            ## Python venv + all npm installs (needs: brew install postgresql@17 postgis osmium-tool; nvm Node 24)
	python3.13 -m venv .venv && .venv/bin/pip install -q -r backend/requirements.txt
	$(NODE) cd frontend && npm install --no-audit --no-fund
	$(NODE) cd wind && npm install --no-audit --no-fund

db:               ## start Postgres, create role + database + PostGIS, create schema
	brew services start postgresql@17
	$(PG)/psql -d postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='airops'" | grep -q 1 || $(PG)/psql -d postgres -c "CREATE ROLE airops LOGIN PASSWORD 'airops'"
	$(PG)/psql -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='airops'" | grep -q 1 || $(PG)/createdb -O airops airops
	$(PG)/psql -d airops -c "CREATE EXTENSION IF NOT EXISTS postgis" -c "GRANT ALL ON SCHEMA public TO airops"
	cd backend && ../$(PY) -m app.init_db

curated:          ## rebuild data/curated/*.csv from public seed lists + OurAirports
	$(PY) pipeline/build_curated.py

pipeline:         ## boundaries (GoI depiction), places, civil airports  (~8 min)
	$(PY) pipeline/run_pipeline.py

osm:              ## OSM roads / rail / telecom towers  (~4.6 GB download, ~40 min)
	$(PY) pipeline/osm.py

stations:         ## OSM railway stations via Overpass (~1 min)
	$(PY) pipeline/osm.py stations

seed:             ## regenerate all synthetic data (deterministic for SEED + SIM_EPOCH)
	cd backend && ../$(PY) -m generator

dev:              ## run wind sidecar + API + web together (Ctrl-C stops)
	bash scripts/dev.sh

stop:             ## stop anything listening on the wind / API / web ports
	@for p in 8787 $$(grep -E '^API_PORT=' .env | cut -d= -f2 | cut -d' ' -f1) 5173; do \
	  pid=$$(lsof -nP -iTCP:$$p -sTCP:LISTEN -t 2>/dev/null); \
	  if [ -n "$$pid" ]; then kill $$pid && echo "stopped :$$p"; fi; \
	done

test:             ## backend tests + self-checks
	cd backend && ../$(PY) -m app.live.classify && ../$(PY) -m pytest -q tests

check: test       ## + frontend typecheck
	$(NODE) cd frontend && npx tsc -b

netcheck:         ## probe every upstream in docs/API.md
	bash scripts/netcheck.sh
