def test_congress_members_returns_200_with_metrics(client, seeded_api_data):
    response = client.get("/api/v1/congress-members?name=Diana&page=1&per_page=5")
    body = response.get_json()

    assert response.status_code == 200
    assert body["pagination"]["total"] == 1
    assert body["items"][0]["full_name"] == "Diana Carolina Gonzales Delgado"
    assert body["items"][0]["votes_in_election"] == 12345
    assert body["items"][0]["metrics"] == {
        "proyectos_de_ley_presentados": 2,
        "tasa_de_aprobacion_de_proyectos": 50.0,
    }


def test_congress_members_filters_party_and_region_partially(
    client,
    seeded_api_data,
):
    party_response = client.get("/api/v1/congress-members?party=Fuerza")
    region_response = client.get("/api/v1/congress-members?region=TACNA")

    assert party_response.status_code == 200
    assert party_response.get_json()["pagination"]["total"] == 1
    assert region_response.status_code == 200
    assert region_response.get_json()["pagination"]["total"] == 1


def test_congress_members_rejects_invalid_pagination(client, seeded_api_data):
    response = client.get("/api/v1/congress-members?page=0")

    assert response.status_code == 422


def test_congress_route_is_in_swagger_json(client):
    response = client.get("/api/openapi.json")
    paths = response.get_json()["paths"]

    assert response.status_code == 200
    assert "/api/v1/congress-members" in paths
