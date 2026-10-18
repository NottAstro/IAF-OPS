from fastapi import APIRouter, Depends, HTTPException

from .. import config
from ..auth import current_user
from ..http import TTLCache, client
from . import feeds

router = APIRouter(prefix="/live", tags=["live"])
enrich_cache = TTLCache(4096)


def parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        w, s, e, n = (float(x) for x in bbox.split(","))
    except ValueError:
        raise HTTPException(422, "bbox must be w,s,e,n")
    return w, s, e, n


@router.get("/aircraft")
def aircraft(bbox: str = "", user: dict = Depends(current_user)):
    box = parse_bbox(bbox) if bbox else config.BBOX
    feeds.report_view(box)
    tracks = feeds.snapshot(box)
    return {"tracks": tracks, "count": len(tracks), "status": feeds.STATUS}


@router.get("/status")
def status(user: dict = Depends(current_user)):
    return {"providers": feeds.STATUS, "tracks": len(feeds.TRACKS), "military_registry": len(feeds.MILITARY)}


@router.get("/aircraft/{hex_id}/enrich")
async def enrich(hex_id: str, callsign: str = "", user: dict = Depends(current_user)):
    """adsbdb type/registration/operator + route (on click only, 24 h cache incl. misses)."""
    async def fetch():
        out = {}
        r = await client.get(f"https://api.adsbdb.com/v0/aircraft/{hex_id}")
        if r.status_code == 200:
            out["aircraft"] = (r.json().get("response") or {}).get("aircraft")
        if callsign:
            r = await client.get(f"https://api.adsbdb.com/v0/callsign/{callsign}")
            if r.status_code == 200:
                out["route"] = (r.json().get("response") or {}).get("flightroute")
        return out
    try:
        return await enrich_cache.get(f"{hex_id}:{callsign}", 86400, fetch)
    except Exception:
        return {}


@router.get("/aircraft/{hex_id}/trail")
async def trail(hex_id: str, user: dict = Depends(current_user)) -> list[dict]:
    """Latest 120 observed positions, only since this server first saw the aircraft; ts is UTC epoch seconds."""
    return list(feeds.TRAILS.get(hex_id.lower(), ()))
