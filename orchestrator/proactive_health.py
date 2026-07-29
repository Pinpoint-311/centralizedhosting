"""Proactive (leading-indicator) health checks for the control plane.

Ported from the Pinpoint 311 app's services/proactive_health.py — same pure,
unit-testable threshold classifier and the same {key,label,status,value,
message,action} check shape — with the collectors adapted to what the control
plane actually runs: disk, memory, database, backup freshness, the tamper-
evident audit chain, and the secret-encryption backend. (The app's redis/celery
collectors are dropped; the control plane runs neither.)

Warns *before* something fails. The classifier is pure; each collector does I/O
defensively and degrades to "unknown" rather than raising.
"""

import logging
import shutil
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_SEVERITY = {"ok": 0, "unknown": 0, "warning": 1, "critical": 2}


def classify_metric(value: Optional[float], warn: float, crit: float, *, higher_is_worse: bool = True) -> str:
    if value is None:
        return "unknown"
    if higher_is_worse:
        if value >= crit:
            return "critical"
        if value >= warn:
            return "warning"
    else:
        if value <= crit:
            return "critical"
        if value <= warn:
            return "warning"
    return "ok"


def rollup_status(checks: list[dict]) -> str:
    worst = "ok"
    for c in checks:
        if _SEVERITY.get(c.get("status"), 0) > _SEVERITY.get(worst, 0):
            worst = c["status"]
    return worst


def clerk_summary(overall: str) -> dict:
    table = {
        "ok": {"level": "ok", "label": "All systems normal",
               "detail": "The control plane is healthy; towns are unaffected."},
        "warning": {"level": "warning", "label": "Minor issue — worth a look",
                    "detail": "Running normally, but an early-warning check crossed a threshold."},
        "critical": {"level": "critical", "label": "Needs attention",
                     "detail": "An early-warning check is critical — act before it causes downtime."},
    }
    return table.get(overall, table["ok"])


def is_worse(new_status: str, old_status: Optional[str]) -> bool:
    return _SEVERITY.get(new_status, 0) > _SEVERITY.get(old_status or "ok", 0)


def _check(key: str, label: str, status: str, value, message: str, action: str = "") -> dict:
    return {"key": key, "label": label, "status": status, "value": value, "message": message, "action": action}


def _disk_check() -> dict:
    try:
        usage = shutil.disk_usage("/")
        pct = round(usage.used / usage.total * 100, 1)
        status = classify_metric(pct, warn=80, crit=92)
        free_gb = round(usage.free / (1024 ** 3), 1)
        return _check(
            "disk", "Disk space", status, pct,
            f"Disk is {pct}% full ({free_gb} GB free).",
            "Delete old backups/logs or expand the volume before it fills." if status != "ok" else "",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[proactive] disk check failed: %s", e)
        return _check("disk", "Disk space", "unknown", None, "Could not read disk usage.")


def _memory_check() -> dict:
    try:
        total = avail = None
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1])
                if total is not None and avail is not None:
                    break
        if not total or avail is None:
            return _check("memory", "Memory", "unknown", None, "Could not read memory usage.")
        pct = round((1 - avail / total) * 100, 1)
        status = classify_metric(pct, warn=85, crit=95)
        return _check(
            "memory", "Memory", status, pct,
            f"Memory is {pct}% used.",
            "Restart heavy services or add RAM; sustained high memory can crash containers." if status != "ok" else "",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[proactive] memory check failed: %s", e)
        return _check("memory", "Memory", "unknown", None, "Could not read memory usage.")


def _db_connection_check(db: Session) -> dict:
    """The app's _db_connection_check. On SQLite there is no connection pool to
    exhaust, so it degrades to a reachability probe rather than reporting a
    percentage it can't measure."""
    try:
        if db.bind is not None and db.bind.dialect.name != "postgresql":
            db.execute(select(1))
            return _check("db_connections", "Database", "ok", None, "Database reachable.")
        used = db.execute(text("SELECT count(*) FROM pg_stat_activity")).scalar()
        max_conn = int(db.execute(text("SHOW max_connections")).scalar())
        pct = round(used / max_conn * 100, 1) if max_conn else None
        status = classify_metric(pct, warn=75, crit=90)
        return _check(
            "db_connections", "Database connections", status, pct,
            f"{used} of {max_conn} connections in use ({pct}%).",
            "Check for connection leaks or raise the pool/limit before it's exhausted." if status != "ok" else "",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[proactive] db connection check failed: %s", e)
        return _check("db_connections", "Database connections", "unknown", None,
                      "Could not read connection stats.")


def _backup_age_check(db: Session) -> dict:
    """The app's _backup_age_check, reading the panel's own backup catalog."""
    from orchestrator.config import settings
    from orchestrator.models import BackupRecord

    try:
        if not settings.backups_enabled:
            return _check("backup", "Backup freshness", "ok", None,
                          "Backups are disabled by configuration.")
        last = db.execute(
            select(func.max(BackupRecord.created_at)).where(BackupRecord.status == "completed")
        ).scalar_one_or_none()
        if not last:
            return _check(
                "backup", "Backup freshness", "warning", None,
                "No database backup found yet.",
                "Run a backup now so a fresh restore point exists.",
            )
        hours = (datetime.now(timezone.utc).replace(tzinfo=None) - last).total_seconds() / 3600
        status = classify_metric(round(hours, 1), warn=36, crit=72)
        return _check(
            "backup", "Backup freshness", status, round(hours, 1),
            f"Last backup was {round(hours)}h ago.",
            "Backups are stale — verify the backup task is running." if status != "ok" else "",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[proactive] backup age check failed: %s", e)
        return _check("backup", "Backup freshness", "unknown", None, "Could not read backup status.")


def _audit_chain_check(db: Session) -> dict:
    from orchestrator import audit

    chain = audit.verify_chain(db)
    if chain.get("ok"):
        return _check("audit_chain", "Audit chain", "ok", chain.get("entries", 0),
                      f"{chain.get('entries', 0)} entries chained and intact.")
    return _check("audit_chain", "Audit chain", "critical", chain.get("broken_at_seq"),
                  f"Tamper-evident chain broke at #{chain.get('broken_at_seq')}.",
                  "Investigate immediately — the audit log may have been altered.")


def collect_checks(db: Session) -> list[dict]:
    """Run all proactive checks. Never raises; failed probes return 'unknown'."""
    return [
        _disk_check(),
        _memory_check(),
        _db_connection_check(db),
        _backup_age_check(db),
        # Control-plane addition: the app has no tamper-evident audit chain, and
        # a broken one is exactly the sort of thing to surface before an audit.
        _audit_chain_check(db),
    ]


def evaluate(db: Session) -> dict:
    """Full proactive-health evaluation for the API/alerting layers."""
    checks = collect_checks(db)
    overall = rollup_status(checks)
    return {
        "overall_status": overall,
        "summary": clerk_summary(overall),
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
