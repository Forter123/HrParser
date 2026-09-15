import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password
from app.db import Base, get_db
from app.models import User


@pytest.fixture()
def engine(tmp_path):
    db_path = tmp_path / f"test_{uuid.uuid4().hex}.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def SessionTest(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture()
def db_session(SessionTest):
    session = SessionTest()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def app_instance(SessionTest):
    # Import here so app.main (and its lifespan/worker) is only touched per-test.
    from app.main import app as fastapi_app

    def override_get_db():
        db = SessionTest()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


@pytest.fixture()
def client(app_instance):
    # Not used as a context manager -> lifespan (background Telegram poller) does not start.
    return TestClient(app_instance)


@pytest.fixture()
def make_user(SessionTest):
    def _make(email="hr@company.com", name="Test HR", password="secret123"):
        session = SessionTest()
        try:
            user = User(email=email, name=name, password_hash=hash_password(password))
            session.add(user)
            session.commit()
            session.refresh(user)
            return user
        finally:
            session.close()

    return _make


@pytest.fixture()
def logged_in_client(client, make_user):
    user = make_user()
    resp = client.post(
        "/login",
        data={"email": user.email, "password": "secret123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return client, user
