import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from orchestrator.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = _make_engine(settings.panel_database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def _reconcile_added_columns() -> tuple[list[str], list[str]]:
    """Add columns that exist on the models but not yet in the database.

    ``create_all`` only ever CREATEs missing *tables* — it never ALTERs an
    existing one. Without this, shipping a new column means every upgraded
    deployment raises ``no such column`` the first time that column is read,
    while a fresh install works fine, so the breakage only ever shows up in
    production.

    Scope is deliberately narrow: additive columns that are nullable, or
    non-nullable with a scalar default we can express as DDL. Anything else
    (drops, renames, type changes, NOT NULL without a default) is reported and
    skipped — those need a real migration, not a startup shim.

    Returns ``(applied, skipped)``. A non-empty ``skipped`` means the database
    is NOT at the model schema, and the caller must not claim otherwise.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    applied: list[str] = []
    skipped: list[str] = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue  # create_all just made it, with every column
            present = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                col_type = column.type.compile(engine.dialect)
                default = getattr(column.default, "arg", None)
                # A server_default is DDL the database applies itself, so it can
                # backfill an existing row — the clearest signal the column is
                # safe to add here rather than in a migration.
                server_default = getattr(column.server_default, "arg", None)
                if server_default is not None:
                    server_default = str(getattr(server_default, "text", server_default))
                if column.nullable:
                    ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}"
                elif server_default is not None:
                    ddl = (f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type} "
                           f"NOT NULL DEFAULT '{server_default}'")
                elif isinstance(default, (str, int, float, bool)):
                    literal = f"'{default}'" if isinstance(default, str) else (
                        str(int(default)) if isinstance(default, bool) else str(default)
                    )
                    ddl = (f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type} "
                           f"NOT NULL DEFAULT {literal}")
                else:
                    skipped.append(f"{table.name}.{column.name}")
                    continue
                conn.execute(text(ddl))
                applied.append(f"{table.name}.{column.name}")
    if applied:
        logger.warning("Added missing columns on startup: %s", ", ".join(applied))
    return applied, skipped


def _alembic_config():
    from pathlib import Path

    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    # script_location in the ini is relative to the working directory; pin it to
    # the package so migrations resolve no matter where the process is started.
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.panel_database_url)
    return cfg


def init_db() -> None:
    """Bring the database to the current schema.

    Alembic owns the schema from here on. Three cases:

    * **Fresh database** — build straight from the models and stamp head. This
      is also the path a test suite takes after dropping its tables, so the
      branch keys on a real table rather than on ``alembic_version``, which
      ``drop_all`` leaves behind.
    * **Pre-Alembic deployment** — tables exist but nothing tracks revisions.
      Bridge it additively (missing tables + missing columns) and adopt it at
      head. This is the one and only job of the column reconciler.
    * **Tracked database** — run the migrations.
    """
    from alembic import command
    from sqlalchemy import inspect

    from orchestrator import models  # noqa: F401  (register tables)

    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    # 'tenants' is the oldest core table — its absence means there is no schema.
    schema_present = "tenants" in names
    tracked = "alembic_version" in names
    cfg = _alembic_config()

    if not schema_present:
        Base.metadata.create_all(engine)
        command.stamp(cfg, "head")
    elif not tracked:
        logger.warning("Adopting a pre-Alembic database: reconciling to baseline.")
        Base.metadata.create_all(engine)
        _applied, skipped = _reconcile_added_columns()
        if skipped:
            # Stamping here would tell Alembic the schema is current when it is
            # not, and every later migration would build on a false baseline.
            # Refuse to start instead.
            raise RuntimeError(
                "Cannot adopt this database automatically — these columns need a manual "
                f"migration first: {', '.join(skipped)}. "
                "Add them (any value is fine for existing rows), then restart."
            )
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")

    # Seed the canonical service taxonomy (idempotent).
    from orchestrator import taxonomy

    db = SessionLocal()
    try:
        taxonomy.seed(db)
    finally:
        db.close()


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
