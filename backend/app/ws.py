"""WebSocket hub (FR-SIM-10, FR-AUTH-07). Envelope: {seq, topic, sim_ts, ts, data}; clients resync over REST on a gap."""
import asyncio
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .auth import COOKIE, decode
from .db import SessionLocal
from .models import AppUser

router = APIRouter()


class Hub:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.seq = 0
        self.last: dict[str, str] = {}

    async def broadcast(self, topic: str, data, sim_ts: str | None) -> None:
        self.seq += 1
        msg = json.dumps({"seq": self.seq, "topic": topic, "sim_ts": sim_ts, "ts": time.time(), "data": data}, default=str)
        if topic in ("sim.clock", "tracks.sim"):
            self.last[topic] = msg
        dead = []
        for ws in list(self.clients):
            try:
                await asyncio.wait_for(ws.send_text(msg), timeout=5)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


hub = Hub()


@router.websocket("/api/v1/ws")
async def ws_endpoint(ws: WebSocket):
    uid = decode(ws.cookies.get(COOKIE))
    with SessionLocal() as db:
        user = db.get(AppUser, uid) if uid else None
    if not user or not user.is_active:
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.clients.add(ws)
    for msg in hub.last.values():   # immediate snapshot: clock + current simulated tracks
        await ws.send_text(msg)
    try:
        while True:
            await ws.receive_text()   # keepalive pings from the client; nothing else is accepted
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)
