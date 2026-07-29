"""Uptime monitoring — the app's health uptime endpoints, ported.

Same records, same aggregation and the same response shapes the app's
OperationsPanel consumes (stats cards + 48h timeline).
"""

from tests.conftest import HEADERS


def test_check_now_records_every_service(client):
    r = client.post("/api/system/uptime/check-now", headers=HEADERS).json()
    assert r["checked"] == 3
    assert set(r["results"]) == {"database", "secret_encryption", "audit_chain"}
    for svc in r["results"].values():
        assert svc["status"] == "healthy"
        assert isinstance(svc["response_time_ms"], int)


def test_stats_aggregate_over_the_apps_three_periods(client):
    client.post("/api/system/uptime/check-now", headers=HEADERS)
    stats = client.get("/api/system/uptime/stats", headers=HEADERS).json()["services"]
    assert set(stats) == {"database", "secret_encryption", "audit_chain"}
    for periods in stats.values():
        assert set(periods) == {"24h", "7d", "30d"}
        assert periods["24h"]["uptime_percent"] == 100.0
        assert periods["24h"]["healthy"] == periods["24h"]["checks"]


def test_history_groups_by_service_newest_first(client):
    client.post("/api/system/uptime/check-now", headers=HEADERS)
    client.post("/api/system/uptime/check-now", headers=HEADERS)
    h = client.get("/api/system/uptime/history?hours=48", headers=HEADERS).json()
    assert h["period_hours"] == 48 and h["since"]
    checks = h["services"]["database"]
    assert len(checks) == 2
    assert {"status", "response_time_ms", "error", "checked_at"} == set(checks[0])
    # Newest first, as the app's timeline expects.
    assert checks[0]["checked_at"] >= checks[1]["checked_at"]


def test_history_window_is_capped_at_seven_days(client):
    h = client.get("/api/system/uptime/history?hours=99999", headers=HEADERS).json()
    assert h["period_hours"] == 168


def test_empty_history_before_any_check(client):
    assert client.get("/api/system/uptime/stats", headers=HEADERS).json()["services"] == {}
    assert client.get("/api/system/uptime/history", headers=HEADERS).json()["services"] == {}
