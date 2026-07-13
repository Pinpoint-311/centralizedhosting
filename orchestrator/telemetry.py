"""B4 — telemetry sanitizer.

The telemetry endpoint is the one surface the panel scrapes fleet-wide, so it
gets a hard regression guard on this side too (mirror of plan A5): only
allowlisted metadata keys survive, and any key that even smells like PII is
stripped recursively before a snapshot is stored.
"""

import re
from typing import Any

ALLOWED_TOP_LEVEL_KEYS = {
    "version",
    "git_sha",
    "db_revision",
    "min_db_revision",
    "uptime_seconds",
    "started_at",
    "timestamp",
    "request_counts",
    "integration_health",
    "api_usage",
    "cost",
    "queue_depth",
    "status",
    "request_stats",  # aggregate 311 counts (metadata only): totals + by_category
    "legal_hold",     # town's own legal-hold flag (shared hold: effective = state OR town)
}

_PII_KEY_PATTERN = re.compile(
    r"(email|phone|first_name|last_name|full_name|address|street|ssn|dob|"
    r"birth|resident|citizen|reporter|password|secret|token|credential|"
    r"latitude|longitude|lat$|lon$|lng$)",
    re.IGNORECASE,
)


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if not _PII_KEY_PATTERN.search(str(k))}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def sanitize_telemetry(raw: dict[str, Any]) -> dict[str, Any]:
    """Allowlist top-level keys, then recursively strip PII-shaped keys."""
    picked = {k: v for k, v in raw.items() if k in ALLOWED_TOP_LEVEL_KEYS}
    return _scrub(picked)


def contains_pii_keys(payload: Any) -> bool:
    """True if any key anywhere in the structure matches the PII pattern."""
    if isinstance(payload, dict):
        return any(
            _PII_KEY_PATTERN.search(str(k)) or contains_pii_keys(v) for k, v in payload.items()
        )
    if isinstance(payload, list):
        return any(contains_pii_keys(v) for v in payload)
    return False
