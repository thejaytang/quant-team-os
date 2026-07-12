import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ALLOW_LOCAL_AUTH_FALLBACK", "true")
os.environ.setdefault("ALLOW_LOCAL_POLICY_FALLBACK", "true")
os.environ.setdefault("ALLOW_LOCAL_SECRET_FALLBACK", "true")
os.environ.setdefault("ALLOW_TEMPORAL_FALLBACK", "true")
os.environ.setdefault("ALLOW_AGENT_FALLBACK", "true")
os.environ.setdefault("ALLOW_MATURE_TOOL_FALLBACK", "true")
os.environ.setdefault("ENABLE_MINIO_UPLOAD", "false")

from app.db.models import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with Session() as session:
        yield session
