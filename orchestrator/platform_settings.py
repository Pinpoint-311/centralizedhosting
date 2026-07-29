"""Security controls the portal can turn on and off.

These used to be environment variables only, so the Security posture panel was a
report rather than a control surface — turning on certificate monitoring meant
editing a container's environment. The values now live in ``SystemSetting`` and
the portal is authoritative: a saved value wins over the environment.

That authority is why the guardrails here matter. Two kinds:

**Preconditions.** A control that cannot possibly work is refused rather than
saved. Turning on ``REQUIRE_KMS`` without a reachable KMS would leave the panel
unable to write a secret at all; turning on signature verification without the
cosign binary would fail every rollout. A toggle whose promise the deployment
cannot keep is worse than no toggle.

**Weakening is deliberate.** Anything that turns a control OFF needs an explicit
confirmation and lands in the audit chain naming who did it. Nothing is blocked
— an operator who means it can always proceed — but it cannot happen by a stray
click, and afterwards there is a record of the decision.

Values are applied by mutating the process-wide ``settings`` object, so the rest
of the codebase keeps reading ``settings.cosign_verify`` with no changes. Each
worker refreshes on a short interval (see ``main.py``) so a change made on one
process reaches the others without a restart.
"""

import logging
from typing import Any, Callable

from sqlalchemy.orm import Session

from orchestrator.config import settings

logger = logging.getLogger(__name__)

SETTING_PREFIX = "control:"


def _kms_ready() -> tuple[bool, str]:
    """Is a cloud KMS actually usable — not merely named.

    ``_kms_provider()`` answers "google" even with nothing configured, so it
    cannot be the test here: requiring a KMS that isn't really there would leave
    the panel unable to write a single secret.
    """
    from orchestrator import encryption

    provider = encryption._kms_provider()
    configured = {
        "google": encryption._is_kms_available,
        "aws": lambda: bool(encryption._get_config_sync("AWS_KMS_KEY_ID")),
        "azure": lambda: bool(encryption._get_config_sync("AZURE_KEYVAULT_URL")),
    }.get(provider)

    if configured is None:
        return False, f"Unknown KMS provider {provider!r}; set KMS_PROVIDER first."
    if not configured():
        return False, (
            f"No {provider} KMS is configured, so requiring one would leave the "
            "panel unable to encrypt anything. Configure the KMS under Service "
            "providers first."
        )
    return True, ""


def _cosign_ready() -> tuple[bool, str]:
    from orchestrator import supply_chain

    if not supply_chain.cosign_available():
        return False, (
            f"The '{settings.cosign_binary}' binary is not on PATH, so no signature "
            "could be checked and every rollout would fail closed."
        )
    if not settings.cosign_key and not (settings.cosign_identity and settings.cosign_issuer):
        return False, (
            "Keyless verification needs COSIGN_IDENTITY and COSIGN_ISSUER (or set "
            "COSIGN_KEY). Without a trust anchor, verification would accept any signer."
        )
    return True, ""


def _backups_ready() -> tuple[bool, str]:
    from orchestrator import backups

    if not backups.s3_configured():
        return False, (
            "BACKUP_S3_* is not configured, so backups would be recorded as intent "
            "and never actually written. Configure the bucket and credentials first."
        )
    return True, ""


def _signed_images_ready() -> tuple[bool, str]:
    # Nothing to pre-check: digest pinning is a property of each release and is
    # enforced per deploy, so turning this on can never wedge the panel itself.
    return True, ""


# key         → the Settings attribute, and the portal's identifier
# label       → human name (matches the posture panel)
# precondition→ () -> (ok, why_not); checked only when ENABLING
# effect      → 'live' | 'rerender' | 'restart' — when the change takes hold
# confirm_off → weakening this needs an explicit confirmation
CONTROLS: list[dict[str, Any]] = [
    {
        "key": "require_kms", "label": "Require cloud KMS", "type": "bool",
        "precondition": _kms_ready, "effect": "live", "confirm_off": True,
    },
    {
        "key": "require_signed_images", "label": "Require signed images", "type": "bool",
        "precondition": _signed_images_ready, "effect": "live", "confirm_off": True,
    },
    {
        "key": "cosign_verify", "label": "Verify image signatures", "type": "bool",
        "precondition": _cosign_ready, "effect": "live", "confirm_off": True,
    },
    {
        "key": "backups_enabled", "label": "Backups", "type": "bool",
        "precondition": _backups_ready, "effect": "live", "confirm_off": True,
    },
    {
        "key": "ssl_check_enabled", "label": "Certificate expiry monitoring", "type": "bool",
        "effect": "live", "confirm_off": False,
    },
    {
        "key": "apply_stacks", "label": "Apply stacks", "type": "bool",
        # Turning this ON is the consequential direction: the next provision
        # stops rendering files and starts deploying containers for real.
        "effect": "live", "confirm_on": True, "confirm_off": True,
    },
    {
        "key": "waf_enabled", "label": "Web application firewall", "type": "bool",
        # Baked into every town's Caddy config, so saving re-renders the fleet.
        "effect": "rerender", "confirm_off": True,
    },
    {
        "key": "rate_limit_rpm", "label": "API rate limit (requests/min)", "type": "int",
        "min": 0, "max": 1_000_000, "effect": "live", "confirm_off": False,
    },
]

BY_KEY = {c["key"]: c for c in CONTROLS}


def _coerce(control: dict, raw: str) -> Any:
    if control["type"] == "bool":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if control["type"] == "int":
        return int(raw)
    return raw


def overrides(db: Session) -> dict[str, Any]:
    """Portal-set values, as stored. Absent keys fall back to the environment."""
    from orchestrator import providers

    out: dict[str, Any] = {}
    for control in CONTROLS:
        raw = providers.get_setting(db, f"{SETTING_PREFIX}{control['key']}")
        if raw is None or raw == "":
            continue
        try:
            out[control["key"]] = _coerce(control, raw)
        except ValueError:
            logger.warning("ignoring unusable stored value for %s", control["key"])
    return out


def apply(db: Session) -> dict[str, Any]:
    """Push stored values onto the process-wide settings object.

    Called at startup and on a short refresh so every worker converges, not just
    the one that handled the write.
    """
    values = overrides(db)
    for key, value in values.items():
        setattr(settings, key, value)
    return values


def describe(db: Session) -> list[dict[str, Any]]:
    """Every control with its value, where that value came from, and whether it
    could be turned on right now."""
    stored = overrides(db)
    out = []
    for control in CONTROLS:
        key = control["key"]
        value = stored.get(key, getattr(settings, key))
        precondition: Callable | None = control.get("precondition")
        can_enable, blocked_because = (True, "")
        if precondition and not value:
            can_enable, blocked_because = precondition()
        out.append({
            "key": key,
            "label": control["label"],
            "type": control["type"],
            "value": value,
            "source": "portal" if key in stored else "environment",
            "effect": control["effect"],
            "confirm_on": bool(control.get("confirm_on")),
            "confirm_off": bool(control.get("confirm_off")),
            "can_enable": can_enable,
            "blocked_because": blocked_because,
        })
    return out


class ControlError(ValueError):
    """The requested change cannot be made, with a reason for the operator."""


def set_control(db: Session, key: str, value: Any, actor: str,
                confirmed: bool = False) -> dict[str, Any]:
    """Save one control. Raises ControlError with a usable reason."""
    from orchestrator import audit, providers

    control = BY_KEY.get(key)
    if not control:
        raise ControlError(f"{key} is not a portal-controlled setting")

    if control["type"] == "bool":
        value = bool(value)
    elif control["type"] == "int":
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ControlError(f"{control['label']} must be a whole number") from None
        if not (control.get("min", 0) <= value <= control.get("max", 1_000_000)):
            raise ControlError(
                f"{control['label']} must be between {control.get('min', 0)} "
                f"and {control.get('max', 1_000_000)}")

    previous = getattr(settings, key)
    weakening = control["type"] == "bool" and previous and not value
    strengthening = control["type"] == "bool" and value and not previous

    if value and (precondition := control.get("precondition")):
        ok, why = precondition()
        if not ok:
            raise ControlError(why)

    needs_confirmation = (
        (weakening and control.get("confirm_off"))
        or (strengthening and control.get("confirm_on"))
    )
    if needs_confirmation and not confirmed:
        raise ControlError(
            f"Turning {control['label'].lower()} {'off' if weakening else 'on'} changes "
            "how the fleet is protected. Confirm to proceed."
        )

    providers.set_setting(db, f"{SETTING_PREFIX}{key}", str(value), is_secret=False)
    setattr(settings, key, value)
    audit.record(db, actor, "system.control_changed", None,
                 control=key, previous=previous, value=value, weakened=weakening)
    db.commit()
    logger.info("control %s set to %r by %s", key, value, actor)
    return {"key": key, "value": value, "effect": control["effect"]}
