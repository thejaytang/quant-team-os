"""add performance indexes

Adds the indexes newly declared on the ORM models (created_at on every
timestamped table, agent_run_id on tool_calls) to databases that were created
before those indexes existed. Fresh databases already get them via
``Base.metadata.create_all`` in 0001, so this migration only fills the gap for
existing installations. It is driven by the model metadata so it stays in sync
with the declared indexes and is idempotent.

Revision ID: 0002_add_performance_indexes
Revises: 0001_initial
Create Date: 2026-07-09
"""

from alembic import op
from sqlalchemy import inspect

from app.db.models import Base

revision = "0002_add_performance_indexes"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {idx["name"] for idx in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in present:
                index.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {idx["name"] for idx in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name in present:
                index.drop(bind=bind)
