"""Upgrading an existing deployment must not break on a new column.

create_all only ever CREATEs missing tables — it never ALTERs an existing one.
Without reconciliation, shipping a column works on a fresh install and raises
"no such column" on every upgraded one, so the failure only appears in
production. These tests pin the reconciler.
"""

import sqlite3

import pytest
from sqlalchemy import create_engine, inspect, text


@pytest.fixture()
def legacy_db(tmp_path, monkeypatch):
    """A database at the pre-upgrade schema: platform_config without any of the
    boundary/retention columns, holding a row an operator already saved."""
    path = tmp_path / "legacy.db"
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE platform_config (
        id VARCHAR(32) PRIMARY KEY, platform_name VARCHAR(120), tagline VARCHAR(160),
        logo_url TEXT, primary_color VARCHAR(9), support_email VARCHAR(255),
        org_legal_name VARCHAR(255), org_type VARCHAR(32), jurisdiction VARCHAR(160),
        contact_name VARCHAR(255), contact_email VARCHAR(255), contact_phone VARCHAR(64),
        address TEXT, website VARCHAR(255), updated_at DATETIME, updated_by VARCHAR(150))""")
    con.execute("INSERT INTO platform_config (id, org_type, org_legal_name) "
                "VALUES ('default', 'state', 'NJ Office of Innovation')")
    con.commit()
    con.close()
    return path


def _reconcile_against(path, monkeypatch):
    """Point the engine at the legacy DB and run the startup reconciliation."""
    from orchestrator import db as db_module

    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.Base.metadata.create_all(engine)
    applied, skipped = db_module._reconcile_added_columns()
    return engine, applied, skipped


def test_new_columns_are_added_to_an_existing_table(legacy_db, monkeypatch):
    engine, applied, _skipped = _reconcile_against(legacy_db, monkeypatch)
    assert any("platform_config.retention_state_code" == a for a in applied)

    cols = {c["name"] for c in inspect(engine).get_columns("platform_config")}
    assert {"boundary", "boundary_label", "retention_state_code",
            "retention_days_override", "retention_mode"} <= cols


def test_existing_rows_survive_and_get_the_model_default(legacy_db, monkeypatch):
    engine, _a, _s = _reconcile_against(legacy_db, monkeypatch)
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT org_legal_name, retention_state_code, retention_mode, boundary "
            "FROM platform_config WHERE id='default'"
        )).one()
    assert row[0] == "NJ Office of Innovation"   # pre-existing data untouched
    assert row[1] == "NJ" and row[2] == "anonymize"  # NOT NULL cols got their default
    assert row[3] is None                        # nullable col added empty


def test_reconciliation_is_idempotent(legacy_db, monkeypatch):
    _, first, _s = _reconcile_against(legacy_db, monkeypatch)
    assert first, "expected the first pass to add columns"
    from orchestrator import db as db_module

    assert db_module._reconcile_added_columns() == ([], [])  # second pass is a no-op


def test_fresh_database_needs_no_reconciliation(tmp_path, monkeypatch):
    """create_all builds complete tables, so a new install adds nothing."""
    engine, applied, _skipped = _reconcile_against(tmp_path / "fresh.db", monkeypatch)
    assert applied == []
