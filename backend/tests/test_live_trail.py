"""Observed trail append, bounding and expiry. In-memory fixtures only; no upstream requests."""
import pytest

from app.live import feeds


@pytest.fixture
def tracks(monkeypatch):
    monkeypatch.setattr(feeds, "TRACKS", {})
    monkeypatch.setattr(feeds, "TRAILS", {})
    return {"hex": "abc123", "lat": 28.5, "lon": 77.1, "alt_m": 3000, "ts": 1000.0}


def test_trail_appends_new_positions_and_ignores_duplicate_or_older_snapshots(tracks):
    feeds.merge([dict(tracks)])
    feeds.merge([{**tracks, "ts": 1001.0, "lon": 77.2}])
    feeds.merge([{**tracks, "ts": 1001.0, "lon": 77.2}, {**tracks, "ts": 999.0}])
    assert list(feeds.TRAILS["abc123"]) == [
        {k: tracks[k] for k in ("lat", "lon", "alt_m", "ts")},
        {"lat": 28.5, "lon": 77.2, "alt_m": 3000, "ts": 1001.0},
    ]


def test_trail_caps_at_latest_n_observations_and_isolated_by_hex(tracks):
    feeds.merge([{**tracks, "hex": "def456", "alt_m": None}])
    for i in range(feeds.TRAIL_LIMIT + 8):
        feeds.merge([{**tracks, "ts": 1000.0 + i, "lon": 77.1 + i / 1000}])
    trail = list(feeds.TRAILS["abc123"])
    assert len(trail) == feeds.TRAIL_LIMIT
    assert trail[0]["ts"] == 1008.0
    assert trail[-1]["ts"] == 1000.0 + feeds.TRAIL_LIMIT + 7
    assert len(feeds.TRAILS["def456"]) == 1
    assert feeds.TRAILS["def456"][0]["alt_m"] is None


def test_pruning_expires_trail_with_track_and_reappearance_starts_fresh(tracks):
    feeds.merge([dict(tracks), {**tracks, "hex": "def456", "ts": 1100.0}])
    feeds.prune(1120.0)
    assert "abc123" in feeds.TRAILS  # exactly 120 seconds is still retained
    feeds.prune(1121.0)
    assert "abc123" not in feeds.TRACKS and "abc123" not in feeds.TRAILS
    assert "def456" in feeds.TRACKS and "def456" in feeds.TRAILS
    feeds.merge([{**tracks, "ts": 1122.0}])
    assert len(feeds.TRAILS["abc123"]) == 1
