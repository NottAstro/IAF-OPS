"""Smallest checks that fail if RBAC, audit, locking, validation, invariants or boundaries break.
Needs a seeded database (make seed). Background tasks are not started (no lifespan)."""
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import config
from app.db import SessionLocal
from app.main import app
from app.sim.invariants import check

client = TestClient(app)


def login(username: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={"username": username, "password": config.DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return c


def scalar(sql: str, **p):
    with SessionLocal() as s:
        return s.execute(text(sql), p).scalar()


def an_available_aircraft(base_code: str) -> dict:
    with SessionLocal() as s:
        r = s.execute(text("""SELECT a.id, a.version FROM aircraft a JOIN base b ON b.id = a.home_base_id
            WHERE b.code = :c AND a.status = 'AVAILABLE' AND a.current_base_id = a.home_base_id
            AND NOT EXISTS (SELECT 1 FROM sortie_aircraft sa JOIN sortie so ON so.id = sa.sortie_id
                            WHERE sa.aircraft_id = a.id AND so.status IN ('PLANNED','CREWED','READY','AIRBORNE','ON_STATION','RTB'))
            LIMIT 1"""), {"c": base_code}).mappings().first()
    assert r, f"no available aircraft at {base_code}"
    return dict(r)


def test_unauthenticated_is_rejected():
    assert client.get("/api/v1/bases").status_code == 401


def test_rbac_viewer_and_other_base_cannot_edit():
    a = an_available_aircraft("VIAX")
    viewer = login("viewer")
    assert viewer.patch(f"/api/v1/inv/aircraft/{a['id']}", json={"status": "STANDBY", "version": a["version"]}).status_code == 403
    other = login("cdr.vetz")
    assert other.patch(f"/api/v1/inv/aircraft/{a['id']}", json={"status": "STANDBY", "version": a["version"]}).status_code == 403


def test_base_commander_edit_writes_exactly_one_audit_row_and_locks():
    a = an_available_aircraft("VIAX")
    cdr = login("cdr.viax")
    before = scalar("SELECT count(*) FROM audit_log WHERE entity_type='aircraft' AND entity_id=:i AND actor_type='USER'", i=a["id"])
    r = cdr.patch(f"/api/v1/inv/aircraft/{a['id']}", json={"status": "STANDBY", "version": a["version"]})
    assert r.status_code == 200, r.text
    after = scalar("SELECT count(*) FROM audit_log WHERE entity_type='aircraft' AND entity_id=:i AND actor_type='USER'", i=a["id"])
    assert after == before + 1
    stale = cdr.patch(f"/api/v1/inv/aircraft/{a['id']}", json={"status": "AVAILABLE", "version": a["version"]})
    assert stale.status_code == 409                      # optimistic lock
    assert cdr.patch(f"/api/v1/inv/aircraft/{a['id']}", json={"status": "AVAILABLE", "version": r.json()["version"]}).status_code == 200


def test_validation_rules():
    admin = login("admin")
    fs = admin.get("/api/v1/inv/fuel-storage?page_size=1").json()["items"][0]
    r = admin.patch(f"/api/v1/inv/fuel-storage/{fs['id']}", json={"current_l": fs["capacity_l"] + 1, "version": fs["version"]})
    assert r.status_code == 422                          # fuel within capacity (I5)
    foreign = scalar("SELECT id FROM base WHERE side = 'FOREIGN' LIMIT 1")
    r = admin.patch(f"/api/v1/inv/fuel-storage/{fs['id']}", json={"base_id": foreign, "version": fs["version"]})
    assert r.status_code == 422                          # inventory only at OWN bases (I1)


def test_audit_log_is_append_only():
    with SessionLocal() as s:
        try:
            s.execute(text("UPDATE audit_log SET action = action WHERE id = (SELECT min(id) FROM audit_log)"))
            s.commit()
            raised = False
        except Exception:
            s.rollback()
            raised = True
    assert raised


def test_simulator_invariants_hold():
    with SessionLocal() as s:
        check(s)


def test_official_boundary_depiction():
    pts = {"Gilgit": (74.31, 35.92), "Aksai Chin": (79.3, 35.2), "Tawang": (91.87, 27.59)}
    for name, (x, y) in pts.items():
        assert scalar("SELECT ST_Contains(geom, ST_SetSRID(ST_Point(:x,:y),4326)) FROM gis_admin_area "
                      "WHERE level='ADM0' AND country_iso3='IND'", x=x, y=y), name
    assert not scalar("SELECT ST_Contains(geom, ST_SetSRID(ST_Point(91.13, 29.65),4326)) FROM gis_admin_area "
                      "WHERE level='ADM0' AND country_iso3='IND'")


def test_aircraft_by_type_matches_the_list():
    c = login("viewer")
    types = c.get("/api/v1/inv/aircraft/by-type").json()
    assert types and len({t["id"] for t in types}) == len(types)
    t = max(types, key=lambda x: x["total"])
    listed = c.get(f"/api/v1/inv/aircraft?aircraft_type_id={t['id']}&page_size=1").json()["total"]
    assert t["total"] + t["retired"] == listed
    assert t["serviceable"] + t["maintenance"] + t["unserviceable"] + t["depot"] == t["total"] and t["qra"] <= t["serviceable"]
    one_base = c.get("/api/v1/inv/aircraft/by-type?home_base_id=1").json()
    assert sum(x["total"] for x in one_base) < sum(x["total"] for x in types)


def test_boundary_tiles_render_even_without_osm_tables():
    r = login("viewer").get("/api/v1/gis/tiles/4/11/6.pbf")  # central India; gis_line_lo may be absent (no `make osm`)
    assert r.status_code == 200 and b"admin" in r.content, r.status_code


def test_synthetic_sites_stay_inside_buffer():
    from app.geo import load_india
    from shapely import wkb
    with SessionLocal() as s:
        G = load_india(s)
        for (g,) in s.execute(text("SELECT ST_AsBinary(geom) FROM air_defence_battery UNION ALL SELECT ST_AsBinary(geom) FROM radar_site")):
            assert G.inner.contains(wkb.loads(bytes(g)))
