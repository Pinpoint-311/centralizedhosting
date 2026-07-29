"""Discover new upstream builds of the Pinpoint 311 app.

This module only ever *reads*. It resolves the configured channel tag to an
immutable digest, pulls the build's metadata out of the image's own OCI labels,
and files an ``UpstreamCandidate``. Deploying is a separate, operator-initiated
act (``api/upstream.py`` → ``Release`` → the existing canary rollout).

Three properties make this safe to run unattended:

**The source is not user-supplied.** The registry host and repository come from
``BACKEND_IMAGE``/``FRONTEND_IMAGE``. No endpoint takes a URL, an image name, or
a host, so no request can be steered somewhere else — an SSRF in a control plane
that holds fleet-wide credentials would be a serious hole.

**The stamp is bound to the artifact.** ``db_revision``/``min_db_revision`` are
read from the labels of the exact digest that will be deployed, and that digest
is what cosign verified. Deriving them from a repo checkout instead would let
the deployed image and the compatibility claim drift apart.

**Discovery cannot deploy.** Nothing here writes a Release, touches a tenant, or
runs a container. The worst a hostile registry response can do is file a
candidate a human then declines.
"""

import logging
import re
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.config import settings
from orchestrator.models import UpstreamCandidate, UpstreamStatus, utcnow

logger = logging.getLogger(__name__)

LABEL_PREFIX = "org.pinpoint311.app"

# OCI + Docker media types, newest first. Multi-arch builds publish an index;
# single-arch publish a manifest directly. We accept both.
_INDEX_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)
_MANIFEST_TYPES = (
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
)
_ACCEPT = ", ".join(_INDEX_TYPES + _MANIFEST_TYPES)

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
# Tags are ours (a config value), but they land in a URL path — keep them to the
# registry's own grammar so a stray value can't traverse or inject.
_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")


class UpstreamError(RuntimeError):
    """Upstream could not be reached or answered with something unusable."""


def split_image(image: str) -> tuple[str, str]:
    """``ghcr.io/owner/name`` -> ``("ghcr.io", "owner/name")``.

    A reference with no registry host is Docker Hub by convention; we reject it
    rather than silently reaching a registry the operator did not configure.
    """
    head, _, rest = image.partition("/")
    if not rest or ("." not in head and ":" not in head and head != "localhost"):
        raise UpstreamError(
            f"{image!r} has no registry host; set BACKEND_IMAGE/FRONTEND_IMAGE to a "
            "fully qualified reference such as ghcr.io/owner/name"
        )
    return head, rest.split("@")[0].split(":")[0]


def _auth_headers(registry: str, repository: str, client: httpx.Client) -> dict[str, str]:
    """Registry pull token. GHCR issues one anonymously for public packages and
    accepts a read:packages PAT for private ones."""
    token = settings.upstream_registry_token.strip()
    if registry != "ghcr.io":
        # Other registries use the same bearer dance but different token hosts;
        # send the configured credential and let the registry decide.
        return {"Authorization": f"Bearer {token}"} if token else {}

    params = {"scope": f"repository:{repository}:pull", "service": "ghcr.io"}
    headers = {}
    if token:
        # GHCR takes the PAT base64'd as a basic credential on the token endpoint.
        import base64

        basic = base64.b64encode(f"v:{token}".encode()).decode()
        headers["Authorization"] = f"Basic {basic}"
    resp = client.get(f"https://{registry}/token", params=params, headers=headers)
    if resp.status_code != 200:
        raise UpstreamError(
            f"registry refused a pull token for {repository} ({resp.status_code}). "
            "For a private package set UPSTREAM_REGISTRY_TOKEN to a read:packages token."
        )
    issued = resp.json().get("token")
    if not issued:
        raise UpstreamError("registry token response contained no token")
    return {"Authorization": f"Bearer {issued}"}


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=settings.upstream_registry_timeout,
        # A registry that redirects us elsewhere is not a registry we follow
        # blindly; blob downloads below opt in explicitly for their CDN hop.
        follow_redirects=False,
    )


def resolve_digest(image: str, tag: str) -> tuple[str, dict[str, Any]]:
    """Resolve ``image:tag`` to its immutable digest and manifest body.

    The digest comes from the registry's own ``Docker-Content-Digest`` header,
    which is what makes the later cosign check meaningful: we verify and deploy
    the same bytes, never the tag, which can be repointed at any time.
    """
    if not _TAG_RE.match(tag):
        raise UpstreamError(f"{tag!r} is not a valid image tag")
    registry, repository = split_image(image)

    with _client() as client:
        headers = {**_auth_headers(registry, repository, client), "Accept": _ACCEPT}
        url = f"https://{registry}/v2/{repository}/manifests/{tag}"
        resp = client.get(url, headers=headers)
        if resp.status_code == 404:
            raise UpstreamError(f"{image}:{tag} does not exist in the registry")
        if resp.status_code != 200:
            raise UpstreamError(f"registry returned {resp.status_code} for {image}:{tag}")

        digest = resp.headers.get("Docker-Content-Digest", "")
        if not _DIGEST_RE.match(digest):
            raise UpstreamError(
                f"registry did not return a usable content digest for {image}:{tag}; "
                "refusing to deploy an unpinnable reference"
            )
        return digest, resp.json()


def _blob(client: httpx.Client, registry: str, repository: str,
          headers: dict[str, str], digest: str) -> dict[str, Any]:
    if not _DIGEST_RE.match(digest):
        raise UpstreamError(f"{digest!r} is not a sha256 digest")
    # Registries hand blobs off to a CDN, so this hop follows redirects. The URL
    # we start from is still built from configured values only.
    resp = client.get(
        f"https://{registry}/v2/{repository}/blobs/{digest}",
        headers=headers,
        follow_redirects=True,
    )
    if resp.status_code != 200:
        raise UpstreamError(f"could not fetch blob {digest[:19]}… ({resp.status_code})")
    return resp.json()


def image_labels(image: str, digest: str, manifest: dict[str, Any]) -> dict[str, str]:
    """Read the OCI labels of a digest-pinned image.

    For a multi-arch index this descends into the first real platform manifest —
    every architecture of one build carries the same stamp, because CI derives it
    once per build (see the app's build-publish workflow).
    """
    registry, repository = split_image(image)
    with _client() as client:
        headers = {**_auth_headers(registry, repository, client), "Accept": _ACCEPT}

        if manifest.get("mediaType") in _INDEX_TYPES or "manifests" in manifest:
            child = next(
                (m for m in manifest.get("manifests", [])
                 # attestation/signature entries ride in the index too; skip them
                 if (m.get("platform") or {}).get("os") not in (None, "unknown")),
                None,
            )
            if not child:
                raise UpstreamError("image index contained no platform manifest")
            manifest = _blob_manifest(client, registry, repository, headers, child["digest"])

        config_digest = (manifest.get("config") or {}).get("digest")
        if not config_digest:
            raise UpstreamError("image manifest has no config descriptor")
        config = _blob(client, registry, repository, headers, config_digest)

    labels = (config.get("config") or {}).get("Labels") or {}
    return {str(k): str(v) for k, v in labels.items() if v is not None}


def _blob_manifest(client: httpx.Client, registry: str, repository: str,
                   headers: dict[str, str], digest: str) -> dict[str, Any]:
    resp = client.get(
        f"https://{registry}/v2/{repository}/manifests/{digest}", headers=headers)
    if resp.status_code != 200:
        raise UpstreamError(f"could not fetch platform manifest ({resp.status_code})")
    return resp.json()


def _stamp_from_labels(labels: dict[str, str]) -> dict[str, str | None]:
    return {
        "version": labels.get(f"{LABEL_PREFIX}.version")
        or labels.get("org.opencontainers.image.version"),
        "git_sha": labels.get(f"{LABEL_PREFIX}.git_sha")
        or labels.get("org.opencontainers.image.revision"),
        "db_revision": labels.get(f"{LABEL_PREFIX}.db_revision"),
        "min_db_revision": labels.get(f"{LABEL_PREFIX}.min_db_revision"),
    }


def verify_signatures(backend_ref: str, frontend_ref: str) -> tuple[bool, str]:
    """cosign verdict for both digest-pinned refs.

    With COSIGN_VERIFY off this reports "not enforced" rather than a pass — a
    candidate must never display a green check the deployment didn't earn.
    """
    if not settings.cosign_verify:
        return False, "signature verification is disabled (COSIGN_VERIFY=false)"
    from orchestrator import supply_chain

    ok, details = supply_chain.verify_refs([backend_ref, frontend_ref])
    return ok, " | ".join(details)


def probe() -> dict[str, Any]:
    """Look at the channel tag and describe the build sitting on it.

    Pure read — no database, no writes. ``check()`` layers persistence on top.
    """
    channel = settings.upstream_channel
    backend_digest, backend_manifest = resolve_digest(settings.backend_image, channel)
    frontend_digest, frontend_manifest = resolve_digest(settings.frontend_image, channel)

    labels = image_labels(settings.backend_image, backend_digest, backend_manifest)
    stamp = _stamp_from_labels(labels)
    # The frontend carries the same version stamp but no schema of its own.
    frontend_labels = image_labels(settings.frontend_image, frontend_digest, frontend_manifest)

    backend_ref = f"{settings.backend_image}@{backend_digest}"
    frontend_ref = f"{settings.frontend_image}@{frontend_digest}"
    sig_ok, sig_detail = verify_signatures(backend_ref, frontend_ref)

    version = stamp["version"] or (stamp["git_sha"] or backend_digest[7:19])
    frontend_version = _stamp_from_labels(frontend_labels)["version"]
    mismatch = (
        frontend_version and stamp["version"] and frontend_version != stamp["version"]
    )

    return {
        "channel": channel,
        "backend_image": settings.backend_image,
        "frontend_image": settings.frontend_image,
        "backend_digest": backend_digest,
        "frontend_digest": frontend_digest,
        "version": version,
        "git_sha": stamp["git_sha"],
        "db_revision": stamp["db_revision"],
        "min_db_revision": stamp["min_db_revision"],
        "stamp_complete": bool(stamp["version"] and stamp["db_revision"]),
        "signature_verified": sig_ok,
        "signature_detail": sig_detail,
        "version_mismatch": (
            f"frontend reports {frontend_version}, backend reports {stamp['version']}"
            if mismatch else None
        ),
    }


def _existing(db: Session, backend_digest: str, frontend_digest: str) -> UpstreamCandidate | None:
    return db.execute(
        select(UpstreamCandidate).where(
            UpstreamCandidate.backend_digest == backend_digest,
            UpstreamCandidate.frontend_digest == frontend_digest,
        )
    ).scalar_one_or_none()


def check(db: Session, actor: str = "system") -> dict[str, Any]:
    """Check upstream and file a candidate when the channel moved.

    Idempotent by digest pair: polling every hour on an unchanged tag creates
    nothing and re-decides nothing. A digest an operator already rejected stays
    rejected — re-offering it would train people to click through the gate.
    """
    from orchestrator import audit

    found = probe()
    candidate = _existing(db, found["backend_digest"], found["frontend_digest"])
    if candidate:
        # Refresh the signature verdict — cosign may have been enabled, or a key
        # rotated, since this row was written.
        candidate.signature_verified = found["signature_verified"]
        candidate.signature_detail = found["signature_detail"]
        db.commit()
        return {"new": False, "candidate_id": candidate.id, "status": candidate.status, **found}

    # Anything still awaiting review is stale once a newer build lands.
    for stale in db.execute(
        select(UpstreamCandidate).where(UpstreamCandidate.status == UpstreamStatus.AVAILABLE)
    ).scalars():
        stale.status = UpstreamStatus.SUPERSEDED

    candidate = UpstreamCandidate(
        backend_image=found["backend_image"],
        frontend_image=found["frontend_image"],
        backend_digest=found["backend_digest"],
        frontend_digest=found["frontend_digest"],
        channel=found["channel"],
        version=found["version"],
        git_sha=found["git_sha"],
        db_revision=found["db_revision"],
        min_db_revision=found["min_db_revision"],
        stamp_complete=found["stamp_complete"],
        signature_verified=found["signature_verified"],
        signature_detail=found["signature_detail"],
    )
    db.add(candidate)
    audit.record(db, actor, "upstream.candidate_found", None,
                 version=candidate.version, backend_digest=candidate.backend_digest,
                 signature_verified=candidate.signature_verified)
    db.commit()
    logger.info("upstream candidate %s (%s) filed for review",
                candidate.version, candidate.backend_digest[:19])
    return {"new": True, "candidate_id": candidate.id, "status": candidate.status, **found}


def compare_url(candidate: UpstreamCandidate, previous_sha: str | None) -> str | None:
    """GitHub compare link for the reviewer. Display only — never fetched."""
    repo = settings.upstream_repo.strip()
    if not repo or not candidate.git_sha:
        return None
    if previous_sha and previous_sha != candidate.git_sha:
        return f"https://github.com/{repo}/compare/{previous_sha}...{candidate.git_sha}"
    return f"https://github.com/{repo}/commit/{candidate.git_sha}"
