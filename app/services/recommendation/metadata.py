import asyncio
from typing import Any

from loguru import logger

from app.core.constants import DEFAULT_CONCURRENCY_LIMIT, FULL_METADATA_ITEMS
from app.services.poster_ratings.factory import PosterProvider, poster_ratings_factory
from app.services.tmdb.genre import movie_genres, series_genres


class RecommendationMetadata:
    """
    Handles fetching and formatting metadata for Stremio.
    """

    @staticmethod
    def extract_year(item: dict[str, Any]) -> int | None:
        """Extract year from TMDB item."""
        date_str = item.get("release_date") or item.get("first_air_date")
        if not date_str:
            ri = item.get("releaseInfo")
            if isinstance(ri, str) and len(ri) >= 4 and ri[:4].isdigit():
                return int(ri[:4])
            return None
        try:
            return int(date_str[:4])
        except Exception:
            return None

    @classmethod
    async def format_for_stremio(
        cls, details: dict[str, Any], media_type: str, user_settings: Any = None, logo_url: str | None = None
    ) -> dict[str, Any] | None:
        """Format TMDB details into Stremio metadata object."""
        external_ids = details.get("external_ids", {})
        imdb_id = external_ids.get("imdb_id")
        tmdb_id_raw = details.get("id")

        if imdb_id:
            stremio_id = imdb_id
        elif tmdb_id_raw:
            stremio_id = f"tmdb:{tmdb_id_raw}"
        else:
            return None

        title = details.get("title") or details.get("name")
        if not title:
            return None

        # Base Fields
        genres_full = details.get("genres", []) or []
        release_date = details.get("release_date") or details.get("first_air_date") or ""

        stremio_type = "series" if media_type in ["tv", "series"] else "movie"
        meta_data = {
            "id": stremio_id,
            "imdb_id": imdb_id,
            "type": stremio_type,
            "name": title,
            "poster": cls._get_poster_url(details, stremio_id, user_settings, stremio_type),
            "background": cls._get_backdrop_url(details),
            "description": details.get("overview"),
            "releaseInfo": release_date[:4] if release_date else None,
            "imdbRating": str(details.get("vote_average", "")),
            "genres": [g.get("name") for g in genres_full if isinstance(g, dict)],
            "vote_average": details.get("vote_average"),
            "vote_count": details.get("vote_count"),
            "popularity": details.get("popularity"),
            "original_language": details.get("original_language"),
            "_external_ids": external_ids,
            "_tmdb_id": tmdb_id_raw,
            "genre_ids": [g.get("id") for g in genres_full if isinstance(g, dict) and g.get("id") is not None],
        }
        if logo_url:
            meta_data["logo"] = logo_url

        # Extensions
        runtime_str = cls._extract_runtime_string(details)
        if runtime_str:
            meta_data["runtime"] = runtime_str

        if media_type == "movie":
            coll = details.get("belongs_to_collection")
            if isinstance(coll, dict):
                meta_data["_collection_id"] = coll.get("id")

        # Cast & Crew
        cast = details.get("credits", {}).get("cast", []) or []
        meta_data["_top_cast_ids"] = [c.get("id") for c in cast[:3] if isinstance(c, dict) and c.get("id")]

        # Keywords & Credits for similarity re-ranking
        if details.get("keywords"):
            meta_data["keywords"] = details.get("keywords")
        if details.get("credits"):
            meta_data["credits"] = details.get("credits")

        return meta_data

    @staticmethod
    def _get_poster_url(details: dict, item_id: str, user_settings: Any, media_type: str) -> str | None:
        """Resolve poster URL using poster rating provider if configured, otherwise TMDB."""
        path = details.get("poster_path")
        poster_url = f"https://image.tmdb.org/t/p/w500{path}"

        poster_rating = getattr(user_settings, "poster_rating", None)
        if poster_rating and (poster_rating.api_key or poster_rating.url_template):
            try:
                provider_enum = PosterProvider(poster_rating.provider)
                custom_url = poster_ratings_factory.get_poster_url(
                    provider_enum,
                    poster_rating.api_key,
                    "imdb",
                    item_id,
                    fallback=poster_url,
                    url_template=poster_rating.url_template,
                    language=user_settings.language,
                    media_type=media_type,
                )
                # A custom template returns None for TMDB-only items; keep TMDB poster then.
                if custom_url:
                    poster_url = custom_url
            except ValueError as e:
                logger.warning(f"Error getting poster URL for item ID {item_id}: {e}")

        return poster_url

    @staticmethod
    def _get_backdrop_url(details: dict) -> str | None:
        """Construct full TMDB backdrop URL."""
        path = details.get("backdrop_path")
        return f"https://image.tmdb.org/t/p/original{path}" if path else None

    @staticmethod
    def _extract_runtime_string(details: dict) -> str | None:
        """Extract and format runtime from either movie or TV format."""
        runtime = details.get("runtime")
        if not runtime and details.get("episode_run_time"):
            runtime = details.get("episode_run_time")[0]
        return f"{runtime} min" if runtime else None

    @classmethod
    async def fetch_batch(
        cls,
        tmdb_service: Any,
        items: list[dict[str, Any]],
        media_type: str,
        user_settings: Any = None,
    ) -> list[dict[str, Any]]:
        """Format candidates as Stremio metas, keeping their order.

        The first FULL_METADATA_ITEMS get full details and a logo. The rest only need
        an IMDb id on top of what discover already returned; Simkl candidates carry no
        title or poster, so they always take the full path.
        """
        valid_items = [it for it in items if it.get("id")]
        full_items = [it for i, it in enumerate(valid_items) if i < FULL_METADATA_ITEMS or not cls._has_listing(it)]
        full_ids = {it["id"] for it in full_items}
        light_items = [it for it in valid_items if it["id"] not in full_ids]

        full_metas, light_metas = await asyncio.gather(
            cls._fetch_full(tmdb_service, full_items, media_type, user_settings),
            cls._fetch_light(tmdb_service, light_items, media_type, user_settings),
        )
        by_id = {**full_metas, **light_metas}
        return [by_id[it["id"]] for it in valid_items if it["id"] in by_id]

    @staticmethod
    def _has_listing(item: dict[str, Any]) -> bool:
        return bool((item.get("title") or item.get("name")) and item.get("poster_path"))

    @classmethod
    async def _fetch_full(
        cls, tmdb_service: Any, items: list[dict[str, Any]], media_type: str, user_settings: Any
    ) -> dict[int, dict[str, Any]]:
        query_type = "movie" if media_type == "movie" else "tv"
        sem = asyncio.Semaphore(DEFAULT_CONCURRENCY_LIMIT)
        language = getattr(user_settings, "language", None) or "en-US"

        async def _one(tid: int) -> dict[str, Any] | None:
            async with sem:
                try:
                    if query_type == "movie":
                        details = await tmdb_service.get_movie_details(tid)
                    else:
                        details = await tmdb_service.get_tv_details(tid)
                except Exception:
                    return None
                if not details:
                    return None
                try:
                    imgs = await tmdb_service.get_images_for_title(query_type, details["id"], language=language)
                except Exception:
                    imgs = {}
            return await cls.format_for_stremio(details, media_type, user_settings, logo_url=imgs.get("logo") or None)

        metas = await asyncio.gather(*(_one(it["id"]) for it in items))
        return {it["id"]: meta for it, meta in zip(items, metas) if meta}

    @classmethod
    async def _fetch_light(
        cls, tmdb_service: Any, items: list[dict[str, Any]], media_type: str, user_settings: Any
    ) -> dict[int, dict[str, Any]]:
        genre_names = movie_genres if media_type == "movie" else series_genres

        async def _one(item: dict[str, Any]) -> dict[str, Any] | None:
            imdb_id = item.get("_imdb_id") or (item.get("external_ids") or {}).get("imdb_id")
            if not imdb_id:
                imdb_id = await tmdb_service.get_imdb_id(media_type, item["id"])
            if not imdb_id:
                return None
            genres = item.get("genres") or [
                {"id": gid, "name": genre_names[gid]} for gid in item.get("genre_ids", []) if gid in genre_names
            ]
            details = {**item, "external_ids": {"imdb_id": imdb_id}, "genres": genres}
            return await cls.format_for_stremio(details, media_type, user_settings)

        metas = await asyncio.gather(*(_one(it) for it in items))
        return {it["id"]: meta for it, meta in zip(items, metas) if meta}
