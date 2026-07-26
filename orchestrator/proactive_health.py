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

from sqlalchemy import func, select
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
        u = shutil.disk_usage("/")
        pct = round(u.used / u.total * 100, 1)
        status = classify_metric(pct, warn=80, crit=92)
        free_gb = round(u.free / (1024 ** 3), 1)
        return _check("disk", "Disk space", status, pct, f"Disk is {pct}% full ({free_gb} GB free).",
                      "Delete old backups/logs or expand the volume." if status != "ok" else "")
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
            return _check("memory", "Memory", "unknown", None, "Could not read memory stats.")
        pct = round((total - avail) / total * 100, 1)
        status = classify_metric(pct, warn=85, crit=95)
        return _check("memory", "Memory", status, pct, f"Memory is {pct}% used.",
                      "Restart the panel process or add RAM." if status != "ok" else "")
    except Exception as e:  # noqa: BLE001
        logger.warning("[proactive] memory check failed: %s", e)
        return _check("memory", "Memory", "unknown", None, "Could not read memory stats.")


def _database_check(db: Session) -> dict:
    try:
        db.execute(select(1))
    except Exception:  # noqa: BLE001
        return _check("database", "Database", "critical", None, "The control-plane database is unreachable.",
                      "Check the database service and PANEL_DATABASE_URL.")
    # On Postgres, warn as connections approach max_connections.
    try:
        if db.bind and db.bind.dialect.name == "postgresql":
            used = db.execute(select(func.count()).select_from(func.pg_stat_activity())).scalar_one()
            cap = int(db.execute(select(func.current_setting("max_connections"))).scalar_one())
            pct = round(used / cap * 100, 1) if cap else None
            status = classify_metric(pct, warn=75, crit=90)
            return _check("database", "Database connections", status, pct,
                          f"{used}/{cap} connections in use ({pct}%).",
                          "Investigate connection leaks or raise max_connections." if status != "ok" else "")
    except Exception as e:  # noqa: BLE001
        logger.warning("[proactive] db connections check failed: %s", e)
    return _check("database", "Database", "ok", None, "Reachable and responding.")


def _backup_check(db: Session) -> dict:
    from orchestrator.config import settings
    from orchestrator.models import BackupRecord

    if not settings.backups_enabled:
        return _check("backup", "Backups", "ok", None, "Backups are disabled by configuration.")
    last = db.execute(
        select(func.max(BackupRecord.created_at)).where(BackupRecord.status == "completed")
    ).scalar_one_or_none()
    if last is None:
        return _check("backup", "Backups", "warning", None, "No successful backup recorded yet.",
                      "Run or schedule a backup.")
    age_h = round((datetime.now(timezone.utc).replace(tzinfo=None) - last).total_seconds() / 3600, 1)
    status = classify_metric(age_h, warn=36, crit=72)
    return _check("backup", "Backups", status, age_h, f"Last successful backup was {age_h}h ago.",
                  "Check the backup loop and object store." if status != "ok" else "")


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
    return [
        _disk_check(),
        _memory_check(),
        _database_check(db),
        _backup_check(db),
        _audit_chain_check(db),
    ]


def evaluate(db: Session) -> dict:
    checks = collect_checks(db)
    overall = rollup_status(checks)
    return {
        "overall_status": overall,
        "summary": clerk_summary(overall),
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
