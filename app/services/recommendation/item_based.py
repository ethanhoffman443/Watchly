import asyncio
from typing import Any

from loguru import logger

from app.services.recommendation.filtering import RecommendationFiltering, filter_by_genres, filter_items_by_settings
from app.services.recommendation.utils import content_type_to_mtype, resolve_tmdb_id
from app.services.simkl import simkl_service
from app.services.tmdb.service import TMDBService


class ItemBasedService:
    """
    Handles item-based recommendations (Because you watched/loved).
    """

    def __init__(self, tmdb_service: Any, user_settings: Any = None):
        self.tmdb_service: TMDBService = tmdb_service
        self.user_settings = user_settings

    async def get_recommendations_for_item(
        self,
        item_id: str,
        content_type: str,
        watched_tmdb: set[int] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Candidates similar to one title: TMDB recommendations first, then similar, then Simkl."""
        tmdb_id = await resolve_tmdb_id(item_id, self.tmdb_service)
        if not tmdb_id:
            return []

        # Exclude source item
        watched_tmdb = watched_tmdb.copy() if watched_tmdb else set()
        watched_tmdb.add(tmdb_id)

        mtype = content_type_to_mtype(content_type)

        tasks = [self._fetch_candidates_from_simkl(item_id, mtype), self._fetch_candidates(tmdb_id, mtype, limit)]
        simkl_result, tmdb_result = await asyncio.gather(*tasks, return_exceptions=True)
        if isinstance(simkl_result, Exception):
            logger.warning(f"item-based simkl candidate fetch failed for {item_id}: {simkl_result}")
            simkl_candidates: list = []
        else:
            simkl_candidates = simkl_result
        if isinstance(tmdb_result, Exception):
            logger.warning(f"item-based tmdb candidate fetch failed for {item_id}: {tmdb_result}")
            candidates: list = []
        else:
            candidates = tmdb_result

        # Apply global settings filter (years, popularity)
        candidates = filter_items_by_settings(candidates, self.user_settings)

        # extend candidates always include simkl candidates
        candidates = simkl_candidates + candidates

        excluded_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
        return filter_by_genres(candidates, watched_tmdb, excluded_ids)

    async def _fetch_candidates_from_simkl(self, imdb_id: str, mtype: str):
        # check if user_settings has simkl api key or not
        logger.info("Fetching recommendations from Simkl")
        simkl_api_key = self.user_settings.simkl_api_key
        if not simkl_api_key:
            logger.warning("Simkl API key not found. Using TMDB for recommendations")
            return []
        return await simkl_service.get_recommendations(imdb_id, mtype, simkl_api_key)

    async def _fetch_candidates(self, tmdb_id: int, mtype: str, limit: int) -> list[dict[str, Any]]:
        """TMDB recommendations, topped up with /similar until the row can be filled.

        /recommendations rarely runs past two or three pages, so a full row leans on
        /similar, which goes much deeper. Pages are fetched in batches so a title with
        a short similar list stops early instead of paying for empty pages.
        """
        combined = {}

        async def fetch_and_combine(fetch_method, source_name, pages: range) -> bool:
            results = await asyncio.gather(
                *[fetch_method(tmdb_id, mtype, page=p) for p in pages],
                return_exceptions=True,
            )
            exhausted = False
            for res in results:
                if isinstance(res, Exception):
                    logger.warning(f"Error fetching {source_name} for {tmdb_id}: {res}")
                    continue
                if res.get("page", 0) >= res.get("total_pages", 0):
                    exhausted = True
                for item in res.get("results", []):
                    item_id = item.get("id")
                    if item_id:
                        combined[item_id] = item
            return exhausted

        await fetch_and_combine(self.tmdb_service.get_recommendations, "recommendations", range(1, 4))

        target = int(limit * 1.5)
        for start in range(1, 16, 5):
            if len(filter_items_by_settings(combined.values(), self.user_settings)) >= target:
                break
            if await fetch_and_combine(self.tmdb_service.get_similar, "similar", range(start, start + 5)):
                break

        # Caller re-applies filter_items_by_settings, so return the merged set.
        return list(combined.values())
