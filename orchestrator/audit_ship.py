"""Off-host audit shipping: WORM journal + SIEM forwarding.

The audit trail is already tamper-evident on-host (a SHA-256 hash chain in
``audit_log``). For government production the entries also need to live
somewhere the panel operators can't reach and can't rewrite:

- **WORM journal** (``AUDIT_WORM_PATH``) — every entry is appended as one NDJSON
  line, carrying its ``entry_hash``/``previous_hash`` so the chain is verifiable
  off-host too. Point this at an append-only / object-lock–backed mount (S3
  Object Lock, a WORM volume, an immutable log bucket).
- **SIEM** (``AUDIT_SIEM_URL``) — each entry is POSTed as an ECS-shaped JSON
  event (Splunk HEC / Elastic / any HTTP collector), optionally bearer-authed
  with ``AUDIT_SIEM_TOKEN``.

Both are strictly **best-effort**: a shipping failure is swallowed so it can
never block or roll back an operator action. The on-host chain remains the
source of integrity truth; shipping provides off-host availability.
"""

import json
import logging
from pathlib import Path

from orchestrator.config import settings

logger = logging.getLogger(__name__)


def _entry_dict(entry) -> dict:
    return {
        "seq": entry.seq,
        "actor": entry.actor,
        "action": entry.action,
        "tenant_id": entry.tenant_id,
        "detail": entry.detail,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "previous_hash": entry.previous_hash,
        "entry_hash": entry.entry_hash,
    }


def _ecs_event(rec: dict) -> dict:
    """Shape an audit record as an ECS-ish security event for the SIEM."""
    return {
        "@timestamp": rec["created_at"],
        "event": {
            "kind": "event",
            "category": ["configuration"],
            "action": rec["action"],
            "sequence": rec["seq"],
        },
        "user": {"name": rec["actor"]},
        "service": {"name": "pinpoint311-orchestrator"},
        "labels": {"tenant_id": rec["tenant_id"], "entry_hash": rec["entry_hash"]},
        "pp311": rec,
    }


def _append_worm(rec: dict) -> None:
    path = Path(settings.audit_worm_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Append-only: never open for truncate/rewrite. The medium (object-lock /
    # WORM mount) enforces immutability; we only ever add lines.
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, separators=(",", ":"), sort_keys=True, default=str) + "\n")


def _post_siem(rec: dict) -> None:
    import httpx

    headers = {"Content-Type": "application/json"}
    if settings.audit_siem_token:
        headers["Authorization"] = f"Bearer {settings.audit_siem_token}"
    httpx.post(settings.audit_siem_url, json=_ecs_event(rec), headers=headers, timeout=5.0)


def ship_entry(entry) -> None:
    """Ship one freshly-recorded audit entry off-host. Best-effort; swallows all
    errors so it can never affect the operator action that produced the entry."""
    if not (settings.audit_worm_path or settings.audit_siem_url):
        return
    rec = _entry_dict(entry)
    if settings.audit_worm_path:
        try:
            _append_worm(rec)
        except Exception:  # noqa: BLE001
            logger.warning("audit WORM append failed for seq=%s", rec.get("seq"), exc_info=True)
    if settings.audit_siem_url:
        try:
            _post_siem(rec)
        except Exception:  # noqa: BLE001
            logger.warning("audit SIEM ship failed for seq=%s", rec.get("seq"), exc_info=True)
