def test_health_endpoint_returns_200(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "version": "v1"}


def test_swagger_json_exists(client):
    response = client.get("/api/openapi.json")
    body = response.get_json()

    assert response.status_code == 200
    assert body["info"]["title"] == "OpenPeru API"
    assert "/api/v1/health" in body["paths"]
    assert body["components"]["securitySchemes"]["bearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "API key",
    }
    assert body["security"] == [{"bearerAuth": []}]
