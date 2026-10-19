"""FastAPI app: REST under /api/v1, WebSocket at /api/v1/ws, background tasks (METAR, ADS-B, simulator)."""
import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import HTTPException as FHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config, crud
from .auth import router as auth_router
from .live import feeds
from .live.routes import router as live_router
from .routers import alerts, bases, exercise as exercise_router, gis, ops, overview, people, scenarios as scenarios_router, sim as sim_router, transfers as transfers_router
from .sim.engine import Simulator
from .weather import metar
from .weather.routes import router as wx_router, wind_router
from .ws import hub, router as ws_router

logging.basicConfig(level=config.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


def _warm_models() -> None:
    from .db import SessionLocal
    from .decide import predict
    with SessionLocal() as db:
        predict.current(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.sim = Simulator(hub)
    tasks = []
    if not config.OFFLINE_MODE:
        from .weather import forecast as wx_forecast
        tasks.append(asyncio.create_task(metar.poll_loop()))
        tasks.append(asyncio.create_task(wx_forecast.poll_loop()))
        tasks += feeds.start()
    from .decide import monitor as plan_monitor   # Phase 2: re-tasking monitor (acts only while a plan is committed)
    tasks.append(asyncio.create_task(plan_monitor.loop(hub)))
    tasks.append(asyncio.create_task(asyncio.to_thread(_warm_models)))   # D38: train the snag-risk model once if missing
    if config.SIM_ENABLED:
        tasks.append(asyncio.create_task(app.state.sim.run()))
    else:  # Phase 1 without simulation: alerts still evaluate current data
        from .sim import alerts as alert_rules
        tasks.append(asyncio.create_task(alert_rules.loop(hub)))
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="iaf-airops API", version="0.1.0", lifespan=lifespan,
              description="SIH26250 Phase-1 prototype. All operational data is SIMULATED.")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex[:12]
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin not in config.CORS_ORIGINS:
        return JSONResponse({"error": {"code": 403, "message": "Cross-site request blocked."}}, status_code=403)
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.exception_handler(FHTTPException)
async def http_error(request: Request, exc: FHTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
    return JSONResponse(jsonable_encoder({"error": {"code": exc.status_code, **detail}}), status_code=exc.status_code)


API = "/api/v1"
for r in (auth_router, ops.router, exercise_router.router, scenarios_router.router, transfers_router.router, crud.router, bases.router, overview.router, people.router,
          alerts.router, gis.router, sim_router.router, live_router, wx_router, wind_router):
    app.include_router(r, prefix=API)
app.include_router(ws_router)


@app.get(f"{API}/healthz")
def healthz():
    from sqlalchemy import text
    from .db import engine
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    return {"db": "ok", "offline_mode": config.OFFLINE_MODE}
