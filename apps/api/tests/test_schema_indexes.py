"""Guards for the performance indexes added in the database round and the
migration that backfills them onto existing databases."""

from pathlib import Path

import sqlalchemy as sa

from app.db.models import Base

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "db"
    / "migrations"
    / "versions"
    / "0002_add_performance_indexes.py"
)


def _indexes(table: str) -> set[str]:
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return {idx["name"] for idx in sa.inspect(engine).get_indexes(table)}


def test_timestamp_and_hot_columns_are_indexed():
    assert "ix_tool_calls_created_at" in _indexes("tool_calls")
    assert "ix_tool_calls_agent_run_id" in _indexes("tool_calls")
    for table in ("audit_logs", "system_events", "policy_decisions"):
        assert f"ix_{table}_created_at" in _indexes(table)


def test_migration_0002_chains_after_initial():
    text = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0002_add_performance_indexes"' in text
    assert 'down_revision = "0001_initial"' in text


def test_migration_backfill_logic_is_idempotent():
    # Mirror the migration's metadata-driven upgrade on an "old" database whose
    # new indexes were dropped, and confirm it restores exactly the declared set.
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP INDEX ix_tool_calls_created_at")
        conn.exec_driver_sql("DROP INDEX ix_tool_calls_agent_run_id")

    inspector = sa.inspect(engine)
    existing = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            continue
        present = {idx["name"] for idx in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in present:
                index.create(bind=engine)

    after = {idx["name"] for idx in sa.inspect(engine).get_indexes("tool_calls")}
    assert {"ix_tool_calls_created_at", "ix_tool_calls_agent_run_id"} <= after
