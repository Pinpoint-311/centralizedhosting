"""Central compliance audit trail (B6): every provisioning, rollout, secret,
lifecycle, and break-glass action lands here. Detail payloads are metadata
only — never secret values, never resident data.

The trail is **tamper-evident**: entries form a hash chain (each entry's hash
binds its content to the previous entry's hash), so any insertion, deletion, or
edit of a past record breaks the chain and is detectable via `verify_chain`.
For government production, ship these entries to WORM/SIEM storage as well —
the chain proves integrity, off-host storage proves availability.
"""

import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orchestrator.models import AuditLog


def _hash_entry(seq: int, actor: str, action: str, tenant_id: str | None,
                detail: dict, created_at: str, previous_hash: str) -> str:
    payload = json.dumps(
        {
            "seq": seq,
            "actor": actor,
            "action": action,
            "tenant_id": tenant_id,
            "detail": detail,
            "created_at": created_at,
            "previous_hash": previous_hash,
        },
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def record(
    db: Session,
    actor: str,
    action: str,
    tenant_id: str | None = None,
    **detail,
) -> AuditLog:
    last = db.execute(
        select(AuditLog).order_by(AuditLog.seq.desc()).limit(1)
    ).scalar_one_or_none()
    seq = (last.seq + 1) if last else 1
    previous_hash = last.entry_hash if last else "GENESIS"

    entry = AuditLog(
        seq=seq,
        actor=actor,
        action=action,
        tenant_id=tenant_id,
        detail=detail,
        previous_hash=previous_hash,
    )
    # created_at is assigned by the column default at flush; compute the hash
    # from the same value that lands in the row.
    from orchestrator.models import utcnow

    entry.created_at = utcnow()
    entry.entry_hash = _hash_entry(
        seq, actor, action, tenant_id, detail, entry.created_at.isoformat(), previous_hash
    )
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db: Session) -> dict:
    """Recompute the hash chain and report the first break, if any."""
    entries = db.execute(select(AuditLog).order_by(AuditLog.seq)).scalars().all()
    expected_prev = "GENESIS"
    for e in entries:
        if e.previous_hash != expected_prev:
            return {"ok": False, "broken_at_seq": e.seq, "reason": "previous_hash mismatch"}
        recomputed = _hash_entry(
            e.seq, e.actor, e.action, e.tenant_id, e.detail,
            e.created_at.isoformat(), e.previous_hash,
        )
        if recomputed != e.entry_hash:
            return {"ok": False, "broken_at_seq": e.seq, "reason": "entry_hash mismatch (content altered)"}
        expected_prev = e.entry_hash
    return {"ok": True, "entries": len(entries)}


def count(db: Session) -> int:
    return db.execute(select(func.count(AuditLog.id))).scalar_one()
