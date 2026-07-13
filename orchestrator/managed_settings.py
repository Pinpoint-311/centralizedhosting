"""State-set policy the town runs under in managed mode.

The rule for what belongs here: the state owns *infrastructure, security, and
legal/compliance POLICY*; the town keeps *content, identity, and day-to-day
operations*. These settings are pushed to the town instance, which (in managed
mode) applies them and shows them read-only in its admin console — "Managed by
your state".

Two important nuances:

- **OPRA / public-records requests:** the retention/anonymization *policy* is
  state-set (below), but towns still *operate* their own records-request
  handling — receiving, fulfilling, and exporting for a specific OPRA request.
  Those operations are NOT locked; only the policy is.
- **Legal hold is shared (`scope: "shared"`):** either the state OR the town can
  place a hold, and the effective hold is the logical OR — neither party can
  clear the other's. The state places its hold here; the town places its own in
  its console; the town reports its hold back via telemetry.

`scope` is `"state"` (state-only policy, locked for the town) or `"shared"`
(both may act). Add a field to CATALOG and it flows through the panel UI, the
API, and the provisioning push with no other changes.
"""

# key            → the setting name delivered to the town
# label          → human name in the panel
# type           → int | bool | str | enum
# default        → panel default
# help           → one line of guidance
# group          → panel grouping
CATALOG = [
    # --- Records & legal ---
    {
        "key": "retention_days",
        "label": "Data retention (days)",
        "type": "int",
        "default": 2555,  # ~7 years, a common public-records floor
        "help": "How long resident requests are kept before purge. Set to your records schedule.",
        "group": "Records & legal",
    },
    {
        "key": "legal_hold",
        "label": "Legal hold (state-placed)",
        "type": "bool",
        "default": False,
        "help": "Suspend all deletion/purge for litigation or records hold. Shared: "
                "the town can also place its own hold; the effective hold is either one.",
        "group": "Records & legal",
        "scope": "shared",
    },
    {
        "key": "audit_retention_days",
        "label": "Audit-log retention (days)",
        "type": "int",
        "default": 3650,
        "help": "How long the town's tamper-evident audit log is retained.",
        "group": "Records & legal",
    },
    # --- Privacy ---
    {
        "key": "pii_anonymization",
        "label": "Anonymize PII after closure",
        "type": "bool",
        "default": True,
        "help": "Strip resident PII from closed requests after the retention window.",
        "group": "Privacy",
    },
    # --- Security posture ---
    {
        "key": "session_timeout_minutes",
        "label": "Staff session timeout (min)",
        "type": "int",
        "default": 60,
        "help": "Idle timeout for municipal staff sessions.",
        "group": "Security",
    },
    {
        "key": "password_min_length",
        "label": "Minimum password length",
        "type": "int",
        "default": 14,
        "help": "For towns not using SSO.",
        "group": "Security",
    },
    {
        "key": "require_mfa",
        "label": "Require MFA for staff",
        "type": "bool",
        "default": True,
        "help": "Enforce multi-factor for all municipal staff logins.",
        "group": "Security",
    },
    # --- Compliance ---
    {
        "key": "accessibility_statement_url",
        "label": "Accessibility statement URL",
        "type": "str",
        "default": "",
        "help": "Link to the accessibility conformance statement (WCAG).",
        "group": "Compliance",
    },
    {
        "key": "log_shipping_target",
        "label": "Central log/SIEM target",
        "type": "str",
        "default": "",
        "help": "Where PII-scrubbed logs ship for central monitoring.",
        "group": "Compliance",
    },
]

_BY_KEY = {s["key"]: s for s in CATALOG}


def catalog() -> list[dict]:
    """CATALOG with `scope` defaulted to 'state' where unspecified."""
    return [{**s, "scope": s.get("scope", "state")} for s in CATALOG]


def defaults() -> dict:
    return {s["key"]: s["default"] for s in CATALOG}


def normalize(raw: dict | None) -> dict:
    """Merge stored overrides onto defaults, coercing to the declared type and
    dropping unknown keys."""
    out = defaults()
    for k, v in (raw or {}).items():
        spec = _BY_KEY.get(k)
        if not spec:
            continue
        try:
            if spec["type"] == "int":
                out[k] = int(v)
            elif spec["type"] == "bool":
                out[k] = bool(v)
            else:
                out[k] = str(v)
        except (TypeError, ValueError):
            continue
    return out
