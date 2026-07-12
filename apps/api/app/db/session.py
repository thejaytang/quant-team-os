from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Base


def make_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db(bind_engine=None) -> None:
    active_engine = bind_engine or engine
    Base.metadata.create_all(active_engine)
    if active_engine.url.get_backend_name() == "sqlite":
        _sqlite_add_missing_columns(active_engine)


def _sqlite_add_missing_columns(active_engine) -> None:
    columns = {
        "external_connections": {
            "infisical_secret_path": "TEXT",
            "secret_version": "VARCHAR(128)",
            "created_by_user_id": "VARCHAR(128) DEFAULT 'local_user'",
        },
        "agent_runs": {
            "workflow_id": "VARCHAR(255)",
            "langfuse_trace_id": "VARCHAR(255)",
        },
        "dataset_specs": {
            "dataset_version": "VARCHAR(255)",
            "dvc_rev": "VARCHAR(255)",
        },
        "strategy_cards": {
            "workflow_id": "VARCHAR(255)",
        },
        "backtest_runs": {
            "dataset_version": "VARCHAR(255)",
        },
        "approval_requests": {
            "workflow_id": "VARCHAR(255)",
        },
        "artifacts": {
            "minio_bucket": "VARCHAR(128) DEFAULT 'qto-artifacts'",
            "object_key": "TEXT DEFAULT ''",
            "mlflow_run_id": "VARCHAR(255)",
            "dvc_rev": "VARCHAR(255)",
        },
    }
    inspector = inspect(active_engine)
    with active_engine.begin() as conn:
        for table, wanted in columns.items():
            if table not in inspector.get_table_names():
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, ddl_type in wanted.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    with session_scope() as db:
        yield db
