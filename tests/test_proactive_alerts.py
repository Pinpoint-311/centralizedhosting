"""Leading-indicator warnings become fleet alerts, not just log lines.

A warning that only reaches stdout is invisible to anyone not tailing container
logs — so a disk filling up would surface as an outage rather than the warning
the proactive engine exists to produce.
"""

from orchestrator import insights, proactive_health
from orchestrator.models import Alert
from tests.conftest import HEADERS


def _force(monkeypatch, key, status, label="Disk space", message="Disk is 95% full.", action="Expand it."):
    """Pin the engine's output so the alert layer can be tested on its own."""
    monkeypatch.setattr(proactive_health, "evaluate", lambda db: {
        "overall_status": status,
        "summary": {"level": status, "label": "x", "detail": "y"},
        "checks": [{"key": key, "label": label, "status": status,
                    "value": 95, "message": message, "action": action}],
        "timestamp": "2026-01-01T00:00:00+00:00",
    })


def test_a_crossing_opens_a_control_plane_alert(client, db, monkeypatch):
    _force(monkeypatch, "disk", "warning")
    new = insights.evaluate_proactive_alerts(db)
    db.commit()

    assert len(new) == 1
    alert = new[0]
    assert alert.kind == "proactive:disk" and alert.severity == "warning"
    # Fleet-wide, not attributed to any one town.
    assert alert.tenant_id is None
    assert "Disk is 95% full." in alert.message and "Expand it." in alert.message

    listed = client.get("/api/alerts", headers=HEADERS).json()
    assert any(a["kind"] == "proactive:disk" for a in listed)


def test_it_does_not_open_a_duplicate_while_one_is_open(client, db, monkeypatch):
    _force(monkeypatch, "disk", "warning")
    assert len(insights.evaluate_proactive_alerts(db)) == 1
    db.commit()
    assert insights.evaluate_proactive_alerts(db) == []  # second pass adds nothing
    db.commit()
    assert db.query(Alert).filter(Alert.kind == "proactive:disk").count() == 1


def test_an_open_alert_is_updated_when_the_check_worsens(client, db, monkeypatch):
    _force(monkeypatch, "disk", "warning")
    insights.evaluate_proactive_alerts(db)
    db.commit()

    _force(monkeypatch, "disk", "critical", message="Disk is 99% full.")
    insights.evaluate_proactive_alerts(db)
    db.commit()

    alert = db.query(Alert).filter(Alert.kind == "proactive:disk").one()
    assert alert.severity == "critical" and "99%" in alert.message


def test_recovery_closes_the_alert(client, db, monkeypatch):
    """Otherwise stale alerts pile up and train operators to ignore the list."""
    _force(monkeypatch, "disk", "warning")
    insights.evaluate_proactive_alerts(db)
    db.commit()

    _force(monkeypatch, "disk", "ok", message="Disk is 20% full.", action="")
    insights.evaluate_proactive_alerts(db)
    db.commit()

    alert = db.query(Alert).filter(Alert.kind == "proactive:disk").one()
    assert alert.acknowledged_at is not None and alert.acknowledged_by == "system"


def test_healthy_checks_never_open_an_alert(client, db, monkeypatch):
    _force(monkeypatch, "memory", "ok", label="Memory", message="Memory is 20% used.", action="")
    assert insights.evaluate_proactive_alerts(db) == []
