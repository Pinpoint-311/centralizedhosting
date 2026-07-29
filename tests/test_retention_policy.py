"""State records-retention policy — the app's retention endpoints, ported.

The state table and get_all_states/get_retention_policy are the app's verbatim;
these pin the endpoint behaviour on top of them.
"""

from orchestrator.retention_policy import get_all_states, get_retention_policy
from tests.conftest import HEADERS


def test_state_table_is_the_apps(client):
    states = get_all_states()
    assert len(states) == 51  # 50 states + DC
    nj = next(s for s in states if s["code"] == "NJ")
    assert nj["retention_years"] == 7 and "OPRA" in nj["public_records_law"]
    assert states == sorted(states, key=lambda x: x["name"])


def test_default_policy_and_effective_days(client):
    p = client.get("/api/system/retention/policy", headers=HEADERS).json()
    assert p["state_code"] == "NJ"
    assert p["override_days"] is None
    assert p["effective_days"] == p["policy"]["retention_days"] == 2555
    assert p["mode"] == "anonymize"


def test_states_endpoint(client):
    states = client.get("/api/system/retention/states", headers=HEADERS).json()
    assert len(states) == 51 and {"code", "name", "retention_days"} <= set(states[0])


def test_change_state_and_mode(client):
    r = client.post("/api/system/retention/policy", json={"state_code": "tx", "mode": "delete"},
                    headers=HEADERS).json()
    assert r["state_code"] == "TX" and r["mode"] == "delete"  # normalised to upper
    p = client.get("/api/system/retention/policy", headers=HEADERS).json()
    assert p["effective_days"] == get_retention_policy("TX")["retention_days"]


def test_unknown_state_is_rejected(client):
    """The app's guard for this never fires — get_retention_policy echoes the
    input code back, so a typo is silently accepted and falls back to DEFAULT.
    The panel checks the table directly, so a typo is a 400."""
    r = client.post("/api/system/retention/policy", json={"state_code": "ZZ"}, headers=HEADERS)
    assert r.status_code == 400 and "Unknown state code" in r.json()["detail"]
    # A real state and the explicit DEFAULT sentinel both still work.
    assert client.post("/api/system/retention/policy", json={"state_code": "CA"},
                       headers=HEADERS).status_code == 200


def test_override_bounds_and_clearing(client):
    # Below a year is refused.
    r = client.post("/api/system/retention/policy", json={"override_days": 100}, headers=HEADERS)
    assert r.status_code == 400 and "at least 365" in r.json()["detail"]
    # A valid override applies and wins over the state default.
    client.post("/api/system/retention/policy", json={"override_days": 3650}, headers=HEADERS)
    assert client.get("/api/system/retention/policy", headers=HEADERS).json()["effective_days"] == 3650
    # 0 is the explicit "clear the override" signal.
    client.post("/api/system/retention/policy", json={"override_days": 0}, headers=HEADERS)
    p = client.get("/api/system/retention/policy", headers=HEADERS).json()
    assert p["override_days"] is None and p["effective_days"] == p["policy"]["retention_days"]


def test_invalid_mode_rejected(client):
    r = client.post("/api/system/retention/policy", json={"mode": "shred"}, headers=HEADERS)
    assert r.status_code == 400 and "anonymize" in r.json()["detail"]
