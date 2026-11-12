from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import STATIC_DIR_ENV
from app.main import create_app
from app.web import CONTENT_SECURITY_POLICY


def test_api_responses_carry_security_headers(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    headers = response.headers
    assert headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert "frame-ancestors 'none'" in CONTENT_SECURITY_POLICY
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["cache-control"] == "no-store"


def test_without_a_build_only_the_api_is_served(client: TestClient) -> None:
    assert client.get("/").status_code == 404


@pytest.fixture
def ui_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    build = tmp_path / "dist"
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text("<!doctype html><title>DWH</title>", encoding="utf-8")
    (build / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setenv(STATIC_DIR_ENV, str(build))
    with TestClient(create_app(tmp_path / "data")) as client:
        yield client


def test_built_ui_is_served_with_spa_fallback(ui_client: TestClient) -> None:
    root = ui_client.get("/")
    assert root.status_code == 200 and "<title>DWH</title>" in root.text
    assert root.headers["x-frame-options"] == "DENY" and "cache-control" not in root.headers
    assert ui_client.get("/assets/app.js").text == "console.log(1)"
    deep = ui_client.get("/analyses/7")  # client-side route
    assert deep.status_code == 200 and "<title>DWH</title>" in deep.text
    assert ui_client.get("/api/health").json()["status"] == "ok"


def test_unknown_api_paths_and_traversal_stay_404(ui_client: TestClient) -> None:
    missing = ui_client.get("/api/does-not-exist")
    assert missing.status_code == 404 and missing.json() == {"detail": "Kaynak bulunamadı."}
    # Paths outside the build never reach the disk: the SPA shell (or 404) comes back instead.
    leaked = ui_client.get("/..%2F..%2Fdata%2Fdwhcr.db")
    assert leaked.status_code in (200, 404) and "SQLite" not in leaked.text
