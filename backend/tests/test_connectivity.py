"""Public-road connectivity: recorded responses, no upstream network in tests."""
import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import config
from app.db import SessionLocal
from app.http import TTLCache
from app.main import app
from app.services import connectivity as C

SOURCE = {"id": 1, "lat": 26.251101, "lon": 73.048897}
DESTINATION = {"id": 2, "lat": 25.813, "lon": 71.4823}


@pytest.fixture
def recorded():
    return json.loads((Path(__file__).resolve().parents[2] / "data/fixtures/valhalla_route.json").read_text())


@pytest.fixture
def provider(monkeypatch, recorded):
    calls = []

    async def reply(request):
        assert str(request.url) == C.ROUTE_URL and request.method == "POST"
        payload = json.loads(request.content)
        assert payload["costing_options"]["auto"] == {"shortest": True, "disable_hierarchy_pruning": True}
        assert payload["format"] == "osrm" and payload["shape_format"] == "geojson"
        assert len(payload["locations"]) == 2
        calls.append(request)
        await asyncio.sleep(0)
        return httpx.Response(200, json=recorded)

    client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    monkeypatch.setattr(C, "client", client)
    monkeypatch.setattr(C, "CACHE", TTLCache(8))
    monkeypatch.setattr(C, "_lock", asyncio.Lock())
    monkeypatch.setattr(C, "_next_request", 0)
    monkeypatch.setattr(config, "OFFLINE_MODE", False)
    return client, calls


def test_road_request_minimises_distance_and_coalesces_cached_pairs(provider, recorded):
    async def run():
        async with provider[0]:
            first, second = await asyncio.gather(C.road_route(SOURCE, DESTINATION), C.road_route(SOURCE, DESTINATION))
            third = await C.road_route(SOURCE, DESTINATION)
        assert first == second == third
        assert first["status"] == "available"
        assert first["geometry"] == recorded["routes"][0]["geometry"]
        assert first["road_distance_km"] == round(recorded["routes"][0]["distance"] / 1000, 1)
        assert len(provider[1]) == 1
    asyncio.run(run())


def test_offline_returns_no_fabricated_road_or_upstream_request(provider, monkeypatch):
    monkeypatch.setattr(config, "OFFLINE_MODE", True)
    async def run():
        async with provider[0]:
            result = await C.road_route(SOURCE, DESTINATION)
        assert result["status"] == "unavailable" and "geometry" not in result
        assert provider[1] == []
    asyncio.run(run())


def test_provider_rate_limit_backs_off_without_retrying(monkeypatch):
    calls = []
    async def busy(request):
        calls.append(request)
        return httpx.Response(429)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(busy)) as client:
            monkeypatch.setattr(C, "client", client)
            monkeypatch.setattr(C, "CACHE", TTLCache(8))
            monkeypatch.setattr(C, "_lock", asyncio.Lock())
            monkeypatch.setattr(C, "_next_request", 0)
            monkeypatch.setattr(config, "OFFLINE_MODE", False)
            assert (await C.road_route(SOURCE, DESTINATION))["status"] == "unavailable"
            assert (await C.road_route(SOURCE, DESTINATION))["status"] == "unavailable"
        assert len(calls) == 1
    asyncio.run(run())


def test_rejects_missing_invalid_and_out_of_region_geometry(recorded):
    with pytest.raises(C.RoadUnavailable):
        C._parse({"routes": []})
    for coordinates in [[], [[0, 0], [1, 1]], [[73, 26], [float("nan"), 26]], [[73, 26], [74, 26, 3]]]:
        body = copy.deepcopy(recorded)
        body["routes"][0]["geometry"]["coordinates"] = coordinates
        with pytest.raises(C.RoadUnavailable):
            C._parse(body)


@pytest.mark.parametrize("failure", ["timeout", "oversize", "redirect"])
def test_upstream_failure_never_returns_a_road_geometry(monkeypatch, failure):
    def fail(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("recorded timeout", request=request)
        if failure == "redirect":
            return httpx.Response(302, headers={"location": "https://example.invalid/route"})
        return httpx.Response(200, headers={"content-length": str(C.MAX_BYTES + 1)})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
            monkeypatch.setattr(C, "client", client)
            monkeypatch.setattr(C, "CACHE", TTLCache(8))
            monkeypatch.setattr(C, "_lock", asyncio.Lock())
            monkeypatch.setattr(C, "_next_request", 0)
            monkeypatch.setattr(config, "OFFLINE_MODE", False)
            result = await C.road_route(SOURCE, DESTINATION)
            assert result["status"] == "unavailable" and "geometry" not in result
    asyncio.run(run())


def test_only_existing_public_nearby_own_bases_are_routed(monkeypatch):
    calls = []
    async def fake(source, destination):
        calls.append((source["id"], destination["id"]))
        return {"status": "available"}
    monkeypatch.setattr(C, "road_route", fake)
    with SessionLocal() as db:
        source = db.execute(text("SELECT id FROM base WHERE code = 'VIJO'")).scalar_one()
        target = db.execute(text("""SELECT id FROM base WHERE side = 'OWN' AND base_type <> 'ALG' AND id <> :s
            ORDER BY ST_Distance(geom::geography, (SELECT geom::geography FROM base WHERE id = :s)), id LIMIT 1"""), {"s": source}).scalar_one()
        foreign = db.execute(text("SELECT id FROM base WHERE side = 'FOREIGN' LIMIT 1")).scalar_one()
        assert asyncio.run(C.connection(db, source, target))["status"] == "available"
        assert asyncio.run(C.connection(db, source, foreign)) is None
        assert asyncio.run(C.connection(db, source, source)) is None
        assert asyncio.run(C.connection(db, source, -1)) is None
        assert calls == [(source, target)]


def test_road_endpoint_requires_authentication():
    assert TestClient(app).get("/api/v1/bases/1/connections/2").status_code == 401
    assert TestClient(app).get("/api/v1/bases/1/connections").status_code == 401
