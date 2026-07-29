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


def _reconcile_added_columns() -> list[str]:
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
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    applied: list[str] = []
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
                if column.nullable:
                    ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}"
                elif isinstance(default, (str, int, float, bool)):
                    literal = f"'{default}'" if isinstance(default, str) else (
                        str(int(default)) if isinstance(default, bool) else str(default)
                    )
                    ddl = (f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type} "
                           f"NOT NULL DEFAULT {literal}")
                else:
                    logger.error(
                        "Schema drift needs a manual migration: %s.%s is NOT NULL with no "
                        "scalar default and cannot be added automatically.",
                        table.name, column.name,
                    )
                    continue
                conn.execute(text(ddl))
                applied.append(f"{table.name}.{column.name}")
    if applied:
        logger.warning("Added missing columns on startup: %s", ", ".join(applied))
    return applied


def init_db() -> None:
    from orchestrator import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    _reconcile_added_columns()

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
