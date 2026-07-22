"""TLS certificate expiry probe for fleet SSL alerting.

Opens a TLS connection to a town's public host, reads the leaf certificate, and
reports how many days remain before it expires. Public transport metadata only
— it never touches the app or resident data. All failures return ``None`` (an
unreachable host or handshake error is data for the alerter, not an exception).
"""

import socket
import ssl
from datetime import datetime, timezone

from orchestrator.config import settings

_CERT_TIME_FMT = "%b %d %H:%M:%S %Y %Z"


def days_until_expiry(host: str, port: int = 443, timeout: float | None = None) -> int | None:
    """Days until ``host``'s TLS certificate expires, or None if it can't be
    determined (DNS failure, connection refused, handshake error, …)."""
    timeout = settings.ssl_check_timeout_seconds if timeout is None else timeout
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
    except Exception:  # noqa: BLE001 — any failure is "unknown", not an error
        return None
    not_after = cert.get("notAfter") if cert else None
    if not not_after:
        return None
    try:
        expires = datetime.strptime(not_after, _CERT_TIME_FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (expires - datetime.now(timezone.utc)).days
