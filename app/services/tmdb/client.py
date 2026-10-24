import asyncio
from typing import Any

from app.core.base_client import BaseClient
from app.core.config import settings
from app.core.version import __version__

# Shared by every TMDBClient in the process: TMDB limits by IP, not by API key, and
# Stremio asks for every row at once, so per-call semaphores in the callers added up
# to hundreds of requests in flight and a wall of 429s. TMDB documents 20
# connections per IP alongside its ~50 requests/second.
_TMDB_CONNECTIONS = asyncio.Semaphore(20)
_next_request_at = 0.0


async def _wait_for_request_slot() -> None:
    # No lock needed: nothing awaits between reading and advancing the slot.
    global _next_request_at
    loop = asyncio.get_running_loop()
    now = loop.time()
    slot = max(now, _next_request_at)
    _next_request_at = slot + 1 / settings.TMDB_MAX_REQUESTS_PER_SECOND
    if slot > now:
        await asyncio.sleep(slot - now)


class TMDBClient(BaseClient):
    """
    Client for interacting with the TMDB API.
    """

    def __init__(self, api_key: str, language: str = "en-US", timeout: float = 10.0, max_retries: int = 3):
        headers = {
            "User-Agent": f"Watchly/{__version__} (+https://github.com/TimilsinaBimal/Watchly)",
            "Accept": "application/json",
        }
        super().__init__(
            base_url="https://api.themoviedb.org/3", timeout=timeout, max_retries=max_retries, headers=headers
        )
        self.api_key = api_key
        self.language = language

    async def _request(self, method: str, url: str, **kwargs) -> Any:
        """Override request to always include API key and language."""
        params = kwargs.get("params", {})
        if params is None:
            params = {}
        params["api_key"] = self.api_key
        params["language"] = self.language
        kwargs["params"] = params
        async with _TMDB_CONNECTIONS:
            await _wait_for_request_slot()
            return await super()._request(method, url, **kwargs)
