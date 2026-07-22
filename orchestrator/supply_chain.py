"""Supply-chain admission: verify container image signatures with cosign.

``REQUIRE_SIGNED_IMAGES`` already refuses to deploy a mutable tag (digest
pinning). This adds the next control: when ``COSIGN_VERIFY`` is on, each pinned
``image@sha256:…`` reference is checked against a cosign/sigstore signature
before the stack is rendered/applied, and provisioning fails closed if a
signature is missing or invalid.

Two modes:

- **keyless** (Fulcio/Rekor) — verify the signing certificate's identity
  (``COSIGN_IDENTITY``, matched as a regex) and OIDC issuer (``COSIGN_ISSUER``).
- **key-based** — verify against a public key (``COSIGN_KEY``: a path, KMS URI,
  or ``k8s://`` reference cosign understands).

The actual ``cosign verify`` invocation is isolated in ``_run_cosign`` so tests
can substitute it; everything above it is deployment-agnostic policy.
"""

import shutil
import subprocess

from orchestrator.config import settings


def cosign_available() -> bool:
    return shutil.which(settings.cosign_binary) is not None


def _run_cosign(ref: str) -> tuple[bool, str]:
    """Run `cosign verify <ref>` with the configured trust policy. Returns
    (ok, detail). Isolated for test substitution."""
    if not cosign_available():
        return False, f"cosign binary '{settings.cosign_binary}' not found on PATH"

    cmd = [settings.cosign_binary, "verify"]
    if settings.cosign_key:
        cmd += ["--key", settings.cosign_key]
    else:
        # Keyless verification requires both trust anchors — refuse to run an
        # unconstrained verify (which would accept any signer).
        if not (settings.cosign_identity and settings.cosign_issuer):
            return False, (
                "keyless cosign verify needs COSIGN_IDENTITY and COSIGN_ISSUER "
                "(or set COSIGN_KEY for key-based verification)"
            )
        cmd += [
            "--certificate-identity-regexp", settings.cosign_identity,
            "--certificate-oidc-issuer", settings.cosign_issuer,
        ]
    cmd.append(ref)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"cosign invocation failed: {exc}"
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "verification failed").strip()[-500:]
    return True, "signature verified"


def verify_image(ref: str) -> tuple[bool, str]:
    """Verify one image reference. A digest-pinned ref (image@sha256:…) is
    required for a meaningful signature check."""
    if "@sha256:" not in ref:
        return False, f"{ref} is not digest-pinned; cannot verify a mutable tag"
    ok, detail = _run_cosign(ref)
    return ok, f"{ref.split('@')[0]}: {detail}"


def verify_refs(refs: list[str]) -> tuple[bool, list[str]]:
    """Verify several refs; ok only if all pass. Returns (ok, per-ref details)."""
    details: list[str] = []
    ok_all = True
    for ref in refs:
        ok, detail = verify_image(ref)
        ok_all = ok_all and ok
        details.append(detail)
    return ok_all, details
