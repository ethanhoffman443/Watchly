from fastapi.testclient import TestClient

from app.core.app import app
from app.services.recommendation.catalog_service import catalog_service

client = TestClient(app)


def serve_row(monkeypatch, size: int) -> list:
    seen = []

    async def fake_get_catalog(token, content_type, catalog_id, genre=None):
        seen.append(genre)
        return {"metas": [{"id": f"tt{i}", "type": "movie", "name": str(i)} for i in range(size)]}, {}

    monkeypatch.setattr(catalog_service, "get_catalog", fake_get_catalog)
    return seen


def ids(path: str) -> list[str]:
    response = client.get(path)
    assert response.status_code == 200
    return [m["id"] for m in response.json()["metas"]]


def test_a_long_row_is_served_one_page_at_a_time(monkeypatch):
    serve_row(monkeypatch, 250)

    first = ids("/abc/catalog/movie/watchly.rec.json")
    second = ids("/abc/catalog/movie/watchly.rec/skip=100.json")
    third = ids("/abc/catalog/movie/watchly.rec/skip=200.json")

    assert len(first) == len(second) == 100
    assert len(third) == 50
    assert len(set(first + second + third)) == 250


def test_paging_past_the_end_is_an_empty_uncached_page(monkeypatch):
    """Stremio stops asking for pages once one comes back empty."""
    serve_row(monkeypatch, 250)

    response = client.get("/abc/catalog/movie/watchly.rec/skip=250.json")

    assert response.json() == {"metas": []}
    assert response.headers["Cache-Control"] == "no-cache"


def test_a_genre_with_an_ampersand_survives_the_path(monkeypatch):
    seen = serve_row(monkeypatch, 150)

    page = ids("/abc/catalog/series/watchly.random/genre=Action%20%26%20Adventure&skip=100.json")

    assert seen == ["Action & Adventure"]
    assert len(page) == 50


def test_a_bad_skip_is_rejected(monkeypatch):
    serve_row(monkeypatch, 10)

    assert client.get("/abc/catalog/movie/watchly.rec/skip=-5.json").status_code == 400
    assert client.get("/abc/catalog/movie/watchly.rec/skip=lots.json").status_code == 400
