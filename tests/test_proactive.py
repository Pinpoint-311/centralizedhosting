"""Proactive (leading-indicator) health engine, ported from the app."""

from orchestrator import proactive_health as ph
from tests.conftest import HEADERS


def test_classify_metric_thresholds():
    assert ph.classify_metric(50, 80, 92) == "ok"
    assert ph.classify_metric(85, 80, 92) == "warning"
    assert ph.classify_metric(95, 80, 92) == "critical"
    assert ph.classify_metric(None, 80, 92) == "unknown"


def test_rollup_takes_worst_and_unknown_never_escalates():
    checks = [{"status": "ok"}, {"status": "unknown"}, {"status": "warning"}]
    assert ph.rollup_status(checks) == "warning"
    assert ph.rollup_status([{"status": "ok"}, {"status": "unknown"}]) == "ok"
    assert ph.rollup_status([{"status": "warning"}, {"status": "critical"}]) == "critical"


def test_endpoint_reports_all_checks(client):
    r = client.get("/api/system/proactive", headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["overall_status"] in ("ok", "warning", "critical")
    # The app's check keys, plus the control plane's audit-chain addition.
    keys = {c["key"] for c in body["checks"]}
    assert keys == {"disk", "memory", "db_connections", "backup", "audit_chain"}
    assert "label" in body["summary"]


def test_audit_chain_check_ok_on_fresh_db(client, db):
    # A fresh chain is intact -> the audit_chain check is ok.
    result = ph.evaluate(db)
    audit_check = next(c for c in result["checks"] if c["key"] == "audit_chain")
    assert audit_check["status"] == "ok"
