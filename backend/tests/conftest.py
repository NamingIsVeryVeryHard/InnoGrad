"""Tests never inherit local model credentials or contact configured services."""

import pytest
from fastapi.testclient import TestClient

from app.db import Base
from app.main import create_app
from app.seed import seed


@pytest.fixture(autouse=True)
def isolate_agent_configuration(monkeypatch):
    monkeypatch.setenv("AI_MODE", "rules")
    monkeypatch.setenv("TEACHER_AGENT_MODE", "rules")
    monkeypatch.setenv("REVIEW_WORKFLOW", "manual")
    for key in ("AI_API_KEY", "AI_BASE_URL", "AI_MODEL"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def app_env(tmp_path):
    """Isolated FastAPI app, seeded SQLite DB, and authenticated role clients."""
    app = create_app(f"sqlite:///{tmp_path / 'test.db'}", tmp_path / "files")
    app.state.test_file_root = tmp_path / "files"
    Base.metadata.create_all(app.state.engine)
    clients, ids = {}, {}
    for username, password in seed(app.state.sessions).items():
        client = TestClient(app)
        resp = client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        assert resp.status_code == 200
        client.headers["X-CSRF-Token"] = resp.json()["csrf_token"]
        clients[username], ids[username] = client, resp.json()["user"]["id"]
    yield app, clients, ids
    app.state.engine.dispose()
