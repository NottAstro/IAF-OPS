"""Settings from the repo-root .env (see .env.example for what each value does)."""
import json
import os
from pathlib import Path

import truststore
from dotenv import load_dotenv

truststore.inject_into_ssl()  # OS trust store: works on TLS-inspecting networks without disabling verification
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name, default).split(" #")[0].strip()
    return "" if v.startswith("#") else v  # python-dotenv reads `KEY=   # note` as the note


DATABASE_URL = _env("DATABASE_URL", "postgresql+psycopg://airops:airops@localhost:5432/airops")
JWT_SECRET = _env("JWT_SECRET") or "dev-only-secret"
JWT_TTL_HOURS = int(_env("JWT_TTL_HOURS", "8"))
DEMO_PASSWORD = _env("DEMO_PASSWORD", "Vayu@2026")
SEED = int(_env("SEED", "2026"))
SIM_ENABLED = _env("SIM_ENABLED", "true").lower() == "true"
SIM_TICK_SECONDS = float(_env("SIM_TICK_SECONDS", "5"))
SIM_SPEED = float(_env("SIM_SPEED", "10"))
SIM_ASSERT = _env("SIM_ASSERT", "0") == "1"
SIM_PROGRAMME_SCALE = float(_env("SIM_PROGRAMME_SCALE", "0.5"))  # routine flying vs. capacity left for planned missions
ADSB_PROVIDERS = [p.strip() for p in _env("ADSB_PROVIDERS", "adsb.lol,adsb.fi,opensky").split(",") if p.strip()]
ADSB_MAX_CIRCLES = int(_env("ADSB_MAX_CIRCLES", "4"))
OPENSKY_CLIENT_ID = _env("OPENSKY_CLIENT_ID")
OPENSKY_CLIENT_SECRET = _env("OPENSKY_CLIENT_SECRET")
OWM_API_KEY = _env("OWM_API_KEY")
AWC_USER_AGENT = _env("AWC_USER_AGENT", "iaf-airops/0.1")
WIND_URL = _env("WIND_URL", "http://localhost:8787")
CORS_ORIGINS = [o.strip() for o in _env("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
HTTPS_CA_BUNDLE = _env("HTTPS_CA_BUNDLE")
OFFLINE_MODE = _env("OFFLINE_MODE", "false").lower() == "true"
LOG_LEVEL = _env("LOG_LEVEL", "info").upper()

REGION = json.loads((ROOT / "shared" / "region.json").read_text())
BBOX = (REGION["west"], REGION["south"], REGION["east"], REGION["north"])  # lon/lat
BORDER_BUFFER_KM = REGION["border_buffer_km"]

HTTP_VERIFY = HTTPS_CA_BUNDLE or True
