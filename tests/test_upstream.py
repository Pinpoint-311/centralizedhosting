"""Pulling app updates from upstream.

Discovery is automatic; deployment is not. These pin the seam: a check can file
a candidate but can never publish a Release or touch a town, and approval is the
operator act that turns a proposal into something the rollout engine will deploy.
"""

import pytest

from orchestrator import upstream
from orchestrator.config import settings
from orchestrator.models import Release, UpstreamCandidate, UpstreamStatus
from tests.conftest import HEADERS

BACKEND_DIGEST = "sha256:" + "a" * 64
FRONTEND_DIGEST = "sha256:" + "b" * 64

STAMP = {
    "org.pinpoint311.app.version": "1.3.0",
    "org.pinpoint311.app.git_sha": "c" * 40,
    "org.pinpoint311.app.db_revision": "d4e5f6a7b8c9",
    "org.pinpoint311.app.min_db_revision": "c3d4e5f6a7b8",
}


@pytest.fixture()
def fake_registry(monkeypatch):
    """Stand in for GHCR: the channel tag resolves to a fixed digest pair and
    the backend image carries a full build stamp."""
    state = {"labels": dict(STAMP), "backend_digest": BACKEND_DIGEST}

    def resolve(image, tag):
        digest = state["backend_digest"] if "backend" in image else FRONTEND_DIGEST
        return digest, {"mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "config": {"digest": "sha256:" + "0" * 64}}

    monkeypatch.setattr(upstream, "resolve_digest", resolve)
    monkeypatch.setattr(upstream, "image_labels",
                        lambda image, digest, manifest: dict(state["labels"]))
    return state


def _check(client):
    r = client.post("/api/upstream/check", headers=HEADERS)
    assert r.status_code == 200, r.text
    return r.json()


def test_check_files_a_candidate_and_deploys_nothing(client, db, fake_registry):
    body = _check(client)
    assert body["new"] is True
    c = body["candidate"]
    assert c["version"] == "1.3.0"
    assert c["backend_digest"] == BACKEND_DIGEST
    assert c["db_revision"] == "d4e5f6a7b8c9"
    assert c["min_db_revision"] == "c3d4e5f6a7b8"
    assert c["status"] == UpstreamStatus.AVAILABLE

    # The whole point of the seam: discovery publishes nothing.
    assert db.query(Release).count() == 0
    assert client.get("/api/rollouts", headers=HEADERS).json() == []


def test_repeated_checks_on_an_unchanged_tag_are_idempotent(client, db, fake_registry):
    _check(client)
    second = _check(client)
    assert second["new"] is False
    assert db.query(UpstreamCandidate).count() == 1


def test_a_moved_tag_supersedes_the_unreviewed_candidate(client, db, fake_registry):
    first = _check(client)["candidate"]["id"]
    fake_registry["backend_digest"] = "sha256:" + "e" * 64
    fake_registry["labels"]["org.pinpoint311.app.version"] = "1.4.0"

    second = _check(client)
    assert second["new"] is True
    assert db.get(UpstreamCandidate, first).status == UpstreamStatus.SUPERSEDED
    # Only one thing is ever awaiting review, so there's no ambiguity about
    # which build "approve" means.
    pending = client.get("/api/upstream/status", headers=HEADERS).json()["pending"]
    assert pending["version"] == "1.4.0"


def test_approval_publishes_a_release_pinned_to_the_reviewed_digest(client, db, fake_registry):
    candidate_id = _check(client)["candidate"]["id"]

    r = client.post(f"/api/upstream/candidates/{candidate_id}/approve",
                    json={"note": "reviewed changelog"}, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == UpstreamStatus.APPROVED

    release = db.query(Release).one()
    assert release.version == "1.3.0"
    # The digest the operator reviewed is the digest that will be deployed.
    assert release.backend_digest == BACKEND_DIGEST
    assert release.frontend_digest == FRONTEND_DIGEST
    assert release.db_revision == "d4e5f6a7b8c9"
    assert release.min_db_revision == "c3d4e5f6a7b8"

    # Still not deployed — approval only makes it eligible for a rollout.
    assert client.get("/api/rollouts", headers=HEADERS).json() == []


def test_a_rejected_build_is_not_offered_again(client, db, fake_registry):
    candidate_id = _check(client)["candidate"]["id"]
    r = client.post(f"/api/upstream/candidates/{candidate_id}/reject",
                    json={"note": "waiting on the security review"}, headers=HEADERS)
    assert r.status_code == 200

    again = _check(client)
    assert again["new"] is False
    assert again["candidate"]["status"] == UpstreamStatus.REJECTED
    assert client.get("/api/upstream/status", headers=HEADERS).json()["pending"] is None
    # And it cannot be approved without an explicit re-review.
    assert client.post(f"/api/upstream/candidates/{candidate_id}/approve",
                       json={}, headers=HEADERS).status_code == 409


def test_unsigned_build_is_blocked_when_signatures_are_enforced(client, fake_registry, monkeypatch):
    """COSIGN_VERIFY on means a build that cannot be verified must not become a
    Release, however long it has been sitting in the queue."""
    candidate_id = _check(client)["candidate"]["id"]
    monkeypatch.setattr(settings, "cosign_verify", True)
    monkeypatch.setattr(upstream, "verify_signatures",
                        lambda b, f: (False, "no matching signatures"))

    r = client.post(f"/api/upstream/candidates/{candidate_id}/approve",
                    json={}, headers=HEADERS)
    assert r.status_code == 422
    assert "signature" in r.json()["detail"].lower()

    listed = client.get("/api/upstream/candidates", headers=HEADERS).json()[0]
    assert listed["status"] == UpstreamStatus.AVAILABLE  # still awaiting review
    assert any("signature" in b.lower() for b in listed["blockers"])


def test_signature_is_rechecked_at_approval_not_trusted_from_discovery(
    client, fake_registry, monkeypatch
):
    """A candidate can sit for days. The verdict that gates the release is the
    one taken when it is accepted."""
    monkeypatch.setattr(settings, "cosign_verify", True)
    monkeypatch.setattr(upstream, "verify_signatures", lambda b, f: (True, "signature verified"))
    candidate_id = _check(client)["candidate"]["id"]

    # Trust anchor rotates; the same artifact no longer verifies.
    monkeypatch.setattr(upstream, "verify_signatures", lambda b, f: (False, "cert expired"))
    r = client.post(f"/api/upstream/candidates/{candidate_id}/approve",
                    json={}, headers=HEADERS)
    assert r.status_code == 422 and "cert expired" in r.json()["detail"]


def test_unstamped_build_cannot_be_approved_without_an_explicit_window(
    client, fake_registry
):
    """An image predating label stamping carries no db_revision. Publishing it
    with a null revision would disable the canary's migration gate, so the
    operator has to state the window instead."""
    fake_registry["labels"] = {"org.pinpoint311.app.version": "0.9.0"}
    candidate_id = _check(client)["candidate"]["id"]

    listed = client.get("/api/upstream/candidates", headers=HEADERS).json()[0]
    assert listed["stamp_complete"] is False
    assert any("migration stamp" in b for b in listed["blockers"])

    assert client.post(f"/api/upstream/candidates/{candidate_id}/approve",
                       json={}, headers=HEADERS).status_code == 422

    r = client.post(f"/api/upstream/candidates/{candidate_id}/approve",
                    json={"db_revision": "d4e5f6a7b8c9",
                          "min_db_revision": "c3d4e5f6a7b8"}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["db_revision"] == "d4e5f6a7b8c9"


def test_approval_is_recorded_in_the_audit_chain(client, fake_registry):
    candidate_id = _check(client)["candidate"]["id"]
    client.post(f"/api/upstream/candidates/{candidate_id}/approve",
                json={"note": "ok"}, headers=HEADERS)
    actions = {e["action"] for e in client.get("/api/audit", headers=HEADERS).json()}
    assert {"upstream.candidate_found", "upstream.approved", "release.published"} <= actions


def test_check_reports_a_registry_outage_as_an_upstream_problem(client, monkeypatch):
    def boom(image, tag):
        raise upstream.UpstreamError("registry returned 503")

    monkeypatch.setattr(upstream, "resolve_digest", boom)
    r = client.post("/api/upstream/check", headers=HEADERS)
    assert r.status_code == 502 and "503" in r.json()["detail"]


def test_status_surfaces_fleet_drift(client, db, fake_registry):
    from tests.conftest import make_tenant, provision

    for i in range(2):
        t = make_tenant(client, slug=f"drift-{i}", name=f"Drift {i}")
        provision(client, t["id"])
    tenants = db.query(__import__("orchestrator.models", fromlist=["Tenant"]).Tenant).all()
    tenants[0].running_version = "1.2.0"
    tenants[1].running_version = "1.3.0"
    db.commit()

    status = client.get("/api/upstream/status", headers=HEADERS).json()
    assert status["fleet_drift"] is True
    assert status["fleet_versions"] == ["1.2.0", "1.3.0"]


# ---- the registry client's own guardrails ---------------------------------


def test_image_without_a_registry_host_is_refused():
    """A bare name would silently resolve to Docker Hub — a registry the
    operator never configured."""
    with pytest.raises(upstream.UpstreamError, match="no registry host"):
        upstream.split_image("pinpoint-311-backend")


def test_split_image_keeps_host_and_repository():
    assert upstream.split_image("ghcr.io/pinpoint-311/pinpoint-311-backend") == (
        "ghcr.io", "pinpoint-311/pinpoint-311-backend")


def test_a_tag_that_is_not_a_tag_never_reaches_the_url(monkeypatch):
    """The channel is a config value, but it lands in a URL path — keep it to
    the registry's grammar so nothing can traverse out of it."""
    for bad in ("../../etc/passwd", "latest/../../v2", "tag with space", ""):
        with pytest.raises(upstream.UpstreamError):
            upstream.resolve_digest("ghcr.io/o/n", bad)


def test_unverifiable_signature_is_never_reported_as_verified(monkeypatch):
    """With COSIGN_VERIFY off, the answer is 'not enforced' — never a pass. A
    green check the deployment didn't earn is worse than no check."""
    monkeypatch.setattr(settings, "cosign_verify", False)
    ok, detail = upstream.verify_signatures("img@sha256:x", "img2@sha256:y")
    assert ok is False and "disabled" in detail
