from urllib.parse import parse_qsl

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError

from app.core.constants import CATALOG_PAGE_SIZE
from app.core.security import TOKEN_PATTERN
from app.services.recommendation.catalog_service import catalog_service

router = APIRouter()


class CatalogExtra(BaseModel):
    """Stremio's extra path segment, e.g. `genre=Horror&skip=100`."""

    genre: str | None = None
    skip: int = Field(default=0, ge=0)


@router.get("/{token}/catalog/{type}/{id}.json")
@router.get("/{token}/catalog/{type}/{id}/{extra}.json")
async def get_catalog(
    request: Request, response: Response, type: str, id: str, token: str, extra: str | None = None
) -> dict:
    if type not in ("movie", "series"):
        raise HTTPException(status_code=400, detail="Invalid content type. Must be 'movie' or 'series'.")

    if not TOKEN_PATTERN.match(token):
        raise HTTPException(status_code=400, detail="Invalid token.")

    # Parsed from the raw path: the decoded `extra` has already turned the %26 in
    # genres like "Action & Adventure" into a separator.
    raw_extra = request.scope["raw_path"].decode().rsplit("/", 1)[-1].removesuffix(".json") if extra else ""
    try:
        params = CatalogExtra(**dict(parse_qsl(raw_extra)))
    except ValidationError:
        raise HTTPException(status_code=400, detail="Invalid catalog extra.")

    recommendations, headers = await catalog_service.get_catalog(token, type, id, params.genre)

    for key, value in headers.items():
        response.headers[key] = value

    # The whole row is built and cached in one go; Stremio pages through it with skip.
    metas = recommendations.get("metas", [])
    page = {**recommendations, "metas": metas[params.skip : params.skip + CATALOG_PAGE_SIZE]}

    # If recommendations are empty, avoid caching the empty payload aggressively.
    if not page["metas"]:
        response.headers["Cache-Control"] = "no-cache"

    return page
