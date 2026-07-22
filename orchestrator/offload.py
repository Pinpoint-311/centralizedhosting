"""Municipality offload — hand a town its whole instance to self-host.

Generates a standalone deployment bundle (compose + env + Caddyfile + a
migration runbook) that a town runs on its OWN servers, un-managed, with all of
its data. Nothing here touches resident data beyond dumping the town's own
database for the town to take with it; the state retains the managed copy
(read-only) until the town confirms it's live and asks to decommission.
"""

import subprocess
import tarfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from orchestrator import stack
from orchestrator.config import settings
from orchestrator.models import Tenant

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    keep_trailing_newline=True,
    autoescape=False,
)


def bundle_dir(tenant: Tenant) -> Path:
    return settings.tenant_root / tenant.slug / "offload"


def bundle_archive_path(tenant: Tenant) -> Path:
    return settings.tenant_root / tenant.slug / f"{tenant.slug}-selfhost-bundle.tar.gz"


def _version(tenant: Tenant) -> str:
    return tenant.running_version or tenant.target_version or "latest"


def build_bundle(tenant: Tenant, secrets: dict[str, str], *, includes_data: bool = False,
                 backend_digest: str | None = None, frontend_digest: str | None = None) -> list[str]:
    """Render the standalone self-host bundle to the tenant's offload dir.
    Returns the list of file names written (relative to the bundle dir)."""
    target = bundle_dir(tenant)
    target.mkdir(parents=True, exist_ok=True)
    version = _version(tenant)

    ctx = {
        "tenant": tenant,
        "version": version,
        "external_host": tenant.external_host,
        "backend_ref": stack._image_ref(settings.backend_image, version, backend_digest),
        "frontend_ref": stack._image_ref(settings.frontend_image, version, frontend_digest),
        "secrets": secrets,
        "includes_data": includes_data,
    }

    files = {
        "docker-compose.yml": "selfhost/docker-compose.yml.j2",
        ".env": "selfhost/env.j2",
        "Caddyfile": "selfhost/Caddyfile.j2",
        "MIGRATION_RUNBOOK.md": "selfhost/RUNBOOK.md.j2",
    }
    written = []
    for name, tpl in files.items():
        (target / name).write_text(_env.get_template(tpl).render(**ctx))
        written.append(name)
    (target / ".env").chmod(0o600)  # holds the town's secrets
    return written


def export_data(tenant: Tenant) -> bool:
    """Dump the town's DB + uploads into the bundle's data/ dir. Only possible
    on the managed host with the stack running (APPLY_STACKS=true); best-effort.
    Returns True if a data snapshot was produced."""
    if not settings.apply_stacks:
        return False
    data_dir = bundle_dir(tenant) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    project = f"pp311-{tenant.slug}"
    db_container = f"{project}-db-1"
    db_name = tenant.db_name or "pp311"
    try:
        dump = subprocess.run(
            ["docker", "exec", db_container, "pg_dump", "-U", "township", db_name],
            capture_output=True, timeout=1800,
        )
        if dump.returncode != 0:
            return False
        (data_dir / "dump.sql").write_bytes(dump.stdout)
        return True
    except Exception:
        return False


def package(tenant: Tenant, includes_data: bool = False) -> Path:
    """Tar+gzip the bundle dir into a single downloadable archive. Returns its path."""
    src = bundle_dir(tenant)
    archive = bundle_archive_path(tenant)
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(src.parent)))
    return archive


def preview(tenant: Tenant, secrets: dict[str, str], *, includes_data: bool = False) -> dict:
    """Render the bundle to strings (secrets masked) without writing — for a
    'what will I get' preview in the UI."""
    version = _version(tenant)
    ctx = {
        "tenant": tenant,
        "version": version,
        "external_host": tenant.external_host,
        "backend_ref": stack._image_ref(settings.backend_image, version, None),
        "frontend_ref": stack._image_ref(settings.frontend_image, version, None),
        "secrets": {k: "••••••••" for k in secrets},
        "includes_data": includes_data,
    }
    return {
        "compose": _env.get_template("selfhost/docker-compose.yml.j2").render(**ctx),
        "env": _env.get_template("selfhost/env.j2").render(**ctx),
        "runbook": _env.get_template("selfhost/RUNBOOK.md.j2").render(**ctx),
    }
