"""Per-town Compose stack rendering + (optional) apply.

ORCHESTRATOR_PLAN.md deployment shape, MVP shortcut: "panel renders per-town
Compose stacks on managed hosts; graduate to k8s later." This module is the
deploy driver behind B2/B3 — replace it with a Helm/GitOps writer when the
fleet moves to Kubernetes.

Hosted-manifest hardening (plan A2): the rendered stack pins image tags,
sets MANAGED_MODE=true, and mounts NO Docker socket and runs NO watchtower —
upgrades come only from this panel.
"""

import shutil
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from orchestrator.config import settings
from orchestrator.models import Tenant

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    keep_trailing_newline=True,
    autoescape=False,
)


def tenant_dir(tenant: Tenant) -> Path:
    return settings.tenant_root / tenant.slug


def caddy_sites_dir() -> Path:
    return settings.tenant_root / "_caddy"


def render_stack(tenant: Tenant, secrets: dict[str, str], version: str) -> Path:
    """Write the town's compose dir + host-Caddy site block. Idempotent —
    re-rendering with the same inputs produces the same files."""
    target = tenant_dir(tenant)
    target.mkdir(parents=True, exist_ok=True)

    context = {
        "tenant": tenant,
        "version": version,
        "backend_image": settings.backend_image,
        "frontend_image": settings.frontend_image,
        "external_host": tenant.external_host,
        "secrets": secrets,
    }

    compose = _env.get_template("docker-compose.yml.j2").render(**context)
    (target / "docker-compose.yml").write_text(compose)

    env_file = _env.get_template("env.j2").render(**context)
    env_path = target / ".env"
    env_path.write_text(env_file)
    env_path.chmod(0o600)  # holds injected platform secrets

    caddy_sites_dir().mkdir(parents=True, exist_ok=True)
    site = _env.get_template("caddy-site.j2").render(**context)
    (caddy_sites_dir() / f"{tenant.slug}.caddy").write_text(site)

    return target


def apply_stack(tenant: Tenant) -> str:
    """`docker compose up -d` for the town. Only called when APPLY_STACKS=true."""
    result = subprocess.run(
        ["docker", "compose", "--project-name", f"pp311-{tenant.slug}", "up", "-d", "--wait"],
        cwd=tenant_dir(tenant),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"compose up failed for {tenant.slug}: {result.stderr[-2000:]}")
    return result.stdout[-2000:]


def down_stack(tenant: Tenant, remove_volumes: bool = False) -> None:
    cmd = ["docker", "compose", "--project-name", f"pp311-{tenant.slug}", "down"]
    if remove_volumes:
        cmd.append("--volumes")
    subprocess.run(cmd, cwd=tenant_dir(tenant), capture_output=True, text=True, timeout=600)


def remove_rendered_stack(tenant: Tenant) -> None:
    shutil.rmtree(tenant_dir(tenant), ignore_errors=True)
    site = caddy_sites_dir() / f"{tenant.slug}.caddy"
    site.unlink(missing_ok=True)
