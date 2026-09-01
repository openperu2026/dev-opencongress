from backend.config import settings


def test_api_auth_allows_requests_when_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "API_AUTH_ENABLED", False)

    response = client.get("/api/v1/health")

    assert response.status_code == 200


def test_api_auth_rejects_missing_key(client, monkeypatch):
    monkeypatch.setattr(settings, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "API_KEY", "test-secret")

    response = client.get("/api/v1/health")

    assert response.status_code == 401
    assert response.get_json()["message"]["error"]["code"] == "api_key_required"


def test_api_auth_rejects_invalid_key(client, monkeypatch):
    monkeypatch.setattr(settings, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "API_KEY", "test-secret")

    response = client.get(
        "/api/v1/health",
        headers={"Authorization": "Bearer wrong-secret"},
    )

    assert response.status_code == 403
    assert response.get_json()["message"]["error"]["code"] == "invalid_api_key"


def test_api_auth_allows_valid_key(client, monkeypatch):
    monkeypatch.setattr(settings, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "API_KEY", "test-secret")

    response = client.get(
        "/api/v1/health",
        headers={"Authorization": "Bearer test-secret"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "version": "v1"}


def test_api_auth_rejects_enabled_auth_without_configured_key(client, monkeypatch):
    monkeypatch.setattr(settings, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "API_KEY", None)

    response = client.get(
        "/api/v1/health",
        headers={"Authorization": "Bearer test-secret"},
    )

    assert response.status_code == 500
    assert response.get_json()["message"]["error"]["code"] == "api_key_not_configured"
