import os

# IMPORTANT: Set test environment variables BEFORE importing any app modules.
# This ensures get_settings() and database engine use the test configuration.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:?cache=shared")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only-do-not-use-in-prod")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DEBUG", "true")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.database import Base, engine, get_db
from app.core.security import get_current_active_technician
from app.models.user import User, UserRole

# Ensure ALL models are imported/registered on Base before create_all (in-memory test DB)
# (ont, customer, olt, telemetry register their tables)
from app.models import customer as _c, olt as _o, ont as _ont, telemetry as _t


# Create all tables for tests (using metadata, bypassing alembic)
Base.metadata.create_all(bind=engine)

# Override the get_db dependency to use the same engine (test DB)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

# Override auth for tests - always provide a technician user (no real JWT needed in tests)
def _override_get_current_user():
    # Return a synthetic active technician
    class FakeUser:
        id = 1
        username = "testtech"
        role = UserRole.TECHNICIAN
        is_active = True
        full_name = "Test Technician"
        email = None
        hashed_password = "x"
    return FakeUser()

app.dependency_overrides[get_current_active_technician] = _override_get_current_user


@pytest.fixture(scope="session")
def client() -> TestClient:
    """FastAPI test client for making requests to the app."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_db_between_tests():
    """Autouse fixture: ensures DB is clean before and after each test.
    Deletes all rows from tables (respecting FK order) so tests are isolated.
    """
    # Pre-test clean + ensure (force recreate for :memory: stability in pytest)
    try:
        Base.metadata.drop_all(bind=engine)
    except Exception:
        pass
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    finally:
        db.close()

    # Extra safety: many code paths (including the new unified ingest service)
    # have defensive create_all, but we also ensure here after the drop.
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass

    yield

    # Post-test cleanup
    db = TestingSessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="function")
def db_session():
    """Provide a DB session for tests that need direct DB access."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
