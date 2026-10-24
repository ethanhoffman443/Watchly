import asyncio

from app.core.constants import FULL_METADATA_ITEMS
from app.services.recommendation.metadata import RecommendationMetadata


class FakeTMDB:
    """Every title but `no_imdb` has an IMDb id; counts what each path costs."""

    def __init__(self, no_imdb: set[int] = frozenset()):
        self.no_imdb = no_imdb
        self.detail_calls: list[int] = []
        self.imdb_calls: list[int] = []

    async def get_movie_details(self, tmdb_id: int):
        self.detail_calls.append(tmdb_id)
        imdb = None if tmdb_id in self.no_imdb else f"tt{tmdb_id}"
        return {
            "id": tmdb_id,
            "title": f"full {tmdb_id}",
            "poster_path": "/p.jpg",
            "genres": [{"id": 18, "name": "Drama"}],
            "external_ids": {"imdb_id": imdb},
            "runtime": 100,
        }

    async def get_images_for_title(self, media_type, tmdb_id, language):
        return {"logo": "https://img/logo.png"}

    async def get_imdb_id(self, media_type: str, tmdb_id: int):
        self.imdb_calls.append(tmdb_id)
        return None if tmdb_id in self.no_imdb else f"tt{tmdb_id}"


def compact(tmdb_id: int) -> dict:
    return {"id": tmdb_id, "title": f"discover {tmdb_id}", "poster_path": "/p.jpg", "genre_ids": [27, 35]}


def run(tmdb: FakeTMDB, items: list[dict]) -> list[dict]:
    return asyncio.run(RecommendationMetadata.fetch_batch(tmdb, items, "movie"))


def test_only_the_head_of_a_row_pays_for_full_details():
    tmdb = FakeTMDB()
    items = [compact(i) for i in range(1, 251)]

    metas = run(tmdb, items)

    assert [m["id"] for m in metas] == [f"tt{i}" for i in range(1, 251)]
    assert tmdb.detail_calls == list(range(1, FULL_METADATA_ITEMS + 1))
    assert tmdb.imdb_calls == list(range(FULL_METADATA_ITEMS + 1, 251))
    assert metas[0]["runtime"] == "100 min"
    assert metas[-1]["genres"] == ["Horror", "Comedy"]
    assert metas[-1]["poster"].endswith("/p.jpg")


def test_titles_without_an_imdb_id_never_get_an_imdb_meta():
    # The full path keeps a tmdb: id that clean_meta drops; the light path skips it.
    tmdb = FakeTMDB(no_imdb={3, FULL_METADATA_ITEMS + 3})

    metas = run(tmdb, [compact(i) for i in range(1, FULL_METADATA_ITEMS + 6)])

    imdb_ids = [m["id"] for m in metas if m["id"].startswith("tt")]
    assert "tt3" not in imdb_ids
    assert f"tt{FULL_METADATA_ITEMS + 3}" not in imdb_ids
    assert len(imdb_ids) == FULL_METADATA_ITEMS + 3


def test_a_simkl_candidate_past_the_head_still_gets_a_title():
    """Simkl candidates carry ids and ratings but no title or poster."""
    tmdb = FakeTMDB()
    simkl_id = FULL_METADATA_ITEMS + 10
    items = [compact(i) for i in range(1, simkl_id)] + [{"id": simkl_id, "_imdb_id": f"tt{simkl_id}"}]

    metas = run(tmdb, items)

    assert metas[-1]["name"] == f"full {simkl_id}"
    assert simkl_id in tmdb.detail_calls
