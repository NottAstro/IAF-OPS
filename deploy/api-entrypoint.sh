#!/bin/sh
# First start: schema, GIS boundaries (downloads ~70 MB once, cached in a volume), synthetic seed. Then the API.
set -e
cd /app/backend
echo "waiting for the database..."
python - <<'PY'
import time, psycopg, os
dsn = os.environ["DATABASE_URL"].replace("+psycopg", "")
for _ in range(60):
    try:
        psycopg.connect(dsn).close()
        break
    except Exception:
        time.sleep(2)
else:
    raise SystemExit("database not reachable")
PY
python -m app.init_db
count() {
  python -c "import os, psycopg; c = psycopg.connect(os.environ['DATABASE_URL'].replace('+psycopg', '')); print(c.execute(\"SELECT to_regclass('$1') IS NOT NULL AND (SELECT count(*) FROM $1) > 0\").fetchone()[0])" 2>/dev/null || echo False
}
if [ "$(count gis_admin_area)" != "True" ]; then
  echo "first start: GIS pipeline (official boundaries, places, airports; ~5 min)"
  python /app/pipeline/run_pipeline.py
fi
if [ "$(count base)" != "True" ]; then
  echo "first start: synthetic data"
  python -m generator
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8010 --proxy-headers
