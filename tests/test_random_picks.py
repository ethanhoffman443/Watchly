import asyncio

import pytest
from fastapi import HTTPException

from app.core.constants import RANDOM_ANY_GENRE, RANDOM_MY_GENRES
from app.core.settings import get_default_settings
from app.services.catalog_definitions import get_random_catalogs
from app.services.recommendation.random_picks import RandomService, random_catalog_id, random_genre_ids

HORROR, COMEDY, DRAMA = 27, 35, 18


class FakeTMDB:
    """A discover endpoint with `total_pages` pages; past the end it is empty, like TMDB."""

    def __init__(self, total_pages: int):
        self.total_pages = total_pages
        self.calls: list[dict] = []

    async def get_discover(self, media_type, page=1, **params):
        self.calls.append({"page": page, **params})
        if page > self.total_pages or page > 500:
            return {"page": page, "total_pages": self.total_pages, "results": []}
        results = [{"id": page * 100 + i, "title": f"{page}-{i}"} for i in range(20)]
        return {"page": page, "total_pages": self.total_pages, "results": results}


def picks(tmdb: FakeTMDB, genre_ids: list[int], settings=None, watched=frozenset(), limit=250):
    service = RandomService(tmdb, settings or get_default_settings())
    return asyncio.run(service.get_random_picks("movie", genre_ids, set(watched), limit))


def test_a_full_row_is_drawn_from_across_the_whole_result_set():
    tmdb = FakeTMDB(total_pages=1000)

    result = picks(tmdb, [])

    pages = [c["page"] for c in tmdb.calls]
    assert len(result) >= 250
    assert len(pages) == len(set(pages))
    # TMDB caps discover at page 500, so a sample from 1000 pages would ask for dead ones.
    assert max(pages) <= 500
    assert max(pages) > 100


def test_a_small_result_set_is_returned_whole_without_asking_past_its_end():
    tmdb = FakeTMDB(total_pages=3)

    result = picks(tmdb, [HORROR])

    assert {c["page"] for c in tmdb.calls} == {1, 2, 3}
    assert len(result) == 60


def test_several_genres_match_any_of_them_and_beat_an_exclusion():
    settings = get_default_settings()
    settings.excluded_movie_genres = [str(HORROR), str(DRAMA)]
    tmdb = FakeTMDB(total_pages=1)

    picks(tmdb, [HORROR, COMEDY], settings)

    assert tmdb.calls[0]["with_genres"] == f"{HORROR}|{COMEDY}"
    assert tmdb.calls[0]["without_genres"] == str(DRAMA)


def test_watched_titles_are_left_out():
    tmdb = FakeTMDB(total_pages=1)

    result = picks(tmdb, [], watched={100, 101})

    assert {100, 101}.isdisjoint(c["id"] for c in result)
    assert len(result) == 18


def test_the_stremio_genre_pick_decides_the_pool():
    settings = get_default_settings()
    settings.random_movie_genres = [str(HORROR), str(COMEDY)]

    saved = random_catalog_id("movie", None)
    assert random_catalog_id("movie", RANDOM_MY_GENRES) == saved
    assert random_genre_ids(saved, "movie", settings) == [HORROR, COMEDY]
    assert random_genre_ids(random_catalog_id("movie", RANDOM_ANY_GENRE), "movie", settings) == []
    assert random_genre_ids(random_catalog_id("movie", "Drama"), "movie", settings) == [DRAMA]
    assert random_genre_ids(random_catalog_id("series", "Sci-Fi & Fantasy"), "series", settings) == [10765]


def test_an_unknown_genre_is_a_bad_request():
    with pytest.raises(HTTPException) as err:
        random_catalog_id("series", "Science Fiction")  # a movie genre name only
    assert err.value.status_code == 400


def test_the_manifest_rows_page_and_offer_the_right_genres():
    settings = get_default_settings()
    settings.excluded_movie_genres = [str(HORROR)]
    settings.random_series_genres = ["16"]

    rows = {c["type"]: c for c in get_random_catalogs(settings)}

    movie_genre, movie_skip = rows["movie"]["extra"]
    series_genre, _ = rows["series"]["extra"]
    assert movie_skip == {"name": "skip"}
    assert movie_genre["isRequired"] is False
    assert movie_genre["options"][0] == RANDOM_ANY_GENRE
    assert "Horror" not in movie_genre["options"]
    assert series_genre["options"][:2] == [RANDOM_MY_GENRES, RANDOM_ANY_GENRE]


def test_a_discover_only_random_row_requires_a_genre():
    settings = get_default_settings()
    config = next(c for c in settings.catalogs if c.id == "watchly.random")
    config.display_at_home = False
    config.enabled_series = False

    (row,) = get_random_catalogs(settings)

    assert row["extra"][0]["isRequired"] is True
