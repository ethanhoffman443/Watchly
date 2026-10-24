import asyncio
import math
import random
from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.core.constants import ENRICH_HEADROOM, RANDOM_ANY_GENRE, RANDOM_MY_GENRES
from app.core.settings import UserSettings
from app.services.recommendation.filtering import RecommendationFiltering, apply_discover_filters
from app.services.recommendation.utils import content_type_to_mtype
from app.services.tmdb.genre import MOVIE_GENRE_TO_ID_MAP, SERIES_GENRE_TO_ID_MAP
from app.services.tmdb.service import TMDBService

RANDOM_CATALOG_ID = "watchly.random"
# TMDB refuses discover pages past 500.
TMDB_MAX_DISCOVER_PAGE = 500
# Extra pages on top of the row's need: some come back short and some titles are
# already watched or appear on two pages.
PAGE_SLACK = 1.5


def random_catalog_id(content_type: str, genre: str | None) -> str:
    """The id a Random row is built and cached under for the genre picked in Stremio.

    Each pick is its own pool, so paging through one genre never mixes in another.
    """
    if genre in (None, RANDOM_MY_GENRES):
        return RANDOM_CATALOG_ID
    if genre == RANDOM_ANY_GENRE:
        return f"{RANDOM_CATALOG_ID}.any"
    genre_map = MOVIE_GENRE_TO_ID_MAP if content_type == "movie" else SERIES_GENRE_TO_ID_MAP
    if genre not in genre_map:
        raise HTTPException(status_code=400, detail=f"Unknown genre for {content_type}.")
    return f"{RANDOM_CATALOG_ID}.g{genre_map[genre]}"


def random_genre_ids(catalog_id: str, content_type: str, user_settings: UserSettings) -> list[int]:
    """Genres a Random row id draws from; empty means any genre."""
    variant = catalog_id.removeprefix(RANDOM_CATALOG_ID).lstrip(".")
    if variant == "any":
        return []
    if variant.startswith("g"):
        return [int(variant[1:])]
    saved = user_settings.random_movie_genres if content_type == "movie" else user_settings.random_series_genres
    return [int(g) for g in saved]


class RandomService:
    """Titles drawn uniformly at random from everything that passes the user's filters."""

    def __init__(self, tmdb_service: TMDBService, user_settings: UserSettings):
        self.tmdb_service = tmdb_service
        self.user_settings = user_settings

    async def get_random_picks(
        self, content_type: str, genre_ids: list[int], watched_tmdb: set[int], limit: int
    ) -> list[dict[str, Any]]:
        mtype = content_type_to_mtype(content_type)

        # A genre the user asked for here beats the same genre in their exclusions.
        excluded = [
            g for g in RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
            if g not in genre_ids
        ]
        params: dict[str, Any] = {"sort_by": "popularity.desc"}
        if genre_ids:
            params["with_genres"] = "|".join(str(g) for g in genre_ids)
        if excluded:
            params["without_genres"] = "|".join(str(g) for g in excluded)
        params = apply_discover_filters(params, self.user_settings)

        # Page 1 is needed anyway for total_pages; sampling pages uniformly from a
        # fixed sort is what makes every matching title equally likely, rather than
        # the popular end of the list showing up every time.
        first = await self.tmdb_service.get_discover(mtype, page=1, **params)
        total_pages = min(first.get("total_pages", 1), TMDB_MAX_DISCOVER_PAGE)
        wanted = math.ceil(limit * ENRICH_HEADROOM * PAGE_SLACK / 20)
        pages = random.sample(range(1, total_pages + 1), k=min(wanted, total_pages))

        results = await asyncio.gather(
            *(self.tmdb_service.get_discover(mtype, page=p, **params) for p in pages if p != 1),
            return_exceptions=True,
        )
        failed = sum(1 for r in results if isinstance(r, Exception))
        if failed:
            logger.warning(f"Random {content_type}: {failed}/{len(results)} discover pages failed")

        pages_data = [first] if 1 in pages else []
        pages_data += [r for r in results if not isinstance(r, Exception)]

        candidates: dict[int, dict[str, Any]] = {}
        for page in pages_data:
            for item in page.get("results", []):
                if item.get("id") and item["id"] not in watched_tmdb:
                    candidates[item["id"]] = item

        picks = list(candidates.values())
        random.shuffle(picks)
        return picks
