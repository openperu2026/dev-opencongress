def test_bills_list_returns_200_with_pagination(client, seeded_api_data):
    response = client.get("/api/v1/bills?page=1&per_page=1")
    body = response.get_json()

    assert response.status_code == 200
    assert len(body["items"]) == 1
    assert body["pagination"] == {
        "page": 1,
        "per_page": 1,
        "total": 2,
        "pages": 2,
    }


def test_bills_list_rejects_invalid_pagination(client, seeded_api_data):
    response = client.get("/api/v1/bills?per_page=101")

    assert response.status_code == 422


def test_bill_detail_by_period_and_pl_returns_200(client, seeded_api_data):
    response = client.get("/api/v1/bills/pl/2021/14864")
    body = response.get_json()

    assert response.status_code == 200
    assert body["id"] == "2021_14864"
    assert body["pley_id"] == "14864/2025-CR"
    assert body["ley_id"] is None
    assert body["author"]["full_name"] == "Diana Carolina Gonzales Delgado"
    assert body["bill_steps"][0]["step_id"] == 2
    assert body["bill_steps"][1]["step_id"] == 1


def test_bill_detail_by_period_and_pl_returns_404(client, seeded_api_data):
    response = client.get("/api/v1/bills/pl/2021/99999")

    assert response.status_code == 404


def test_bills_routes_are_in_swagger_json(client):
    response = client.get("/api/openapi.json")
    paths = response.get_json()["paths"]

    assert response.status_code == 200
    assert "/api/v1/bills" in paths
    assert "/api/v1/bills/pl/{period}/{pl_number}" in paths
    assert "/api/v1/bills/{bill_id}" not in paths
