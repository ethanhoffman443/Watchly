RECOMMENDATIONS_CATALOG_NAME: str = "Top Picks For You"
DEFAULT_CATALOG_LIMIT: int = 250
# Stremio asks for the next page with skip=<items received so far> and stops at an
# empty page, so any size works; 100 matches stremio-core's own CATALOG_PAGE_SIZE.
CATALOG_PAGE_SIZE: int = 100
# Candidates enriched per row, as a share of the row limit. Enrichment drops titles
# TMDB has no IMDb id for and titles the user watched (Trakt/Simkl users only show up
# as watched once the IMDb id is known), so trimming to exactly the limit came up short.
ENRICH_HEADROOM: float = 1.2
# Only the head of a row gets the full detail + logo lookups; the rest is built from
# the discover payload plus an IMDb id. A full lookup is two TMDB calls per title, and
# 250-title rows at that rate ran into TMDB's per-IP limit on a cold home screen.
FULL_METADATA_ITEMS: int = 40
# Random rows rebuild this often instead of every CATALOG_REFRESH_INTERVAL_SECONDS,
# otherwise "random" would be the same list for a day.
RANDOM_CATALOG_REFRESH_SECONDS: int = 3600

DEFAULT_CONCURRENCY_LIMIT: int = 30

DEFAULT_MINIMUM_RATING_FOR_THEME_BASED_MOVIE: float = 7.2
DEFAULT_MINIMUM_RATING_FOR_THEME_BASED_TV: float = 6.8


# Bumped whenever the scoring maths changes, so cached profiles built by older
# code get dropped on read instead of being served with stale numbers until TTL.
# Lives here rather than in profile/constants.py because user_cache reads it, and
# importing anything under app.services.profile pulls in ProfileService via that
# package's __init__ — a cycle.
# v2: Trakt/Simkl items are scored by ScoringService instead of a flat 50.0.
# v3: the sampler sorts by score, so a capped sample is the strongest items
#     rather than an arbitrary slice of the library, and its quota split favours
#     rated titles over watchlist entries.
# v4: Stremio profiles sample up to 200 items instead of 30.
PROFILE_SCORING_VERSION: int = 4

# cache keys
LIBRARY_ITEMS_KEY: str = "watchly:library_items:{token}"
NUVIO_REFRESH_LOCK_KEY: str = "watchly:nuvio_refresh:{token}"
PROFILE_KEY: str = "watchly:profile:{token}:{content_type}"
WATCHED_SETS_KEY: str = "watchly:watched_sets:{token}:{content_type}"
CATALOG_KEY: str = "watchly:catalog:{token}:{type}:{id}"
# Versioned because the manifest embeds the addon version: a deploy orphans the old
# entries rather than serving a stale version string until the TTL runs out.
MANIFEST_KEY: str = "watchly:manifest:{version}:{token}"

# The manifest is rebuilt on save and by the catalog updater, so this is only a
# backstop against an invalidation being missed.
MANIFEST_CACHE_TTL_SECONDS: int = 86400

# Bounded TTL for per-user caches (library items, profile, watched sets,
# library hash, last-build timestamp). Refreshed on every read so an active
# user's data effectively never expires, but a stale install gets cleaned up
# by Redis instead of growing forever. The user's main token key is NOT
# subject to this — that follows TOKEN_TTL_SECONDS.
USER_CACHE_TTL_SECONDS: int = 60 * 60 * 24 * 90  # 90 days


# Declaring skip is what makes Stremio page a catalog; without it a row is whatever
# the first response holds.
SKIP_EXTRA: dict = {"name": "skip"}
HOME_EXTRA: list[dict] = [SKIP_EXTRA]
DISCOVER_ONLY_EXTRA: list[dict] = [
    {"name": "genre", "isRequired": True, "options": ["All"], "optionsLimit": 1},
    SKIP_EXTRA,
]

# Genre options of the Random row besides the genre names themselves. "My genres" is
# what the row shows with no genre picked; it is only offered once some are saved.
RANDOM_MY_GENRES: str = "My genres"
RANDOM_ANY_GENRE: str = "Any genre"


# Single source of truth for the "Discovery" preference. Every threshold is a
# TMDB /discover filter (vote_count/vote_average), so each mode is pushed into the
# query AND re-checked post-fetch with no contradiction. "Reach" is expressed via
# vote_count — a stable, queryable proxy — instead of TMDB's volatile, unfilterable
# popularity score: high floor = mainstream/widely-seen, low ceiling = hidden gem.
DISCOVERY_SETTINGS: dict = {
    "mainstream": {
        "vote_average.gte": 6.2,
        "vote_count.gte": 1500,
    },
    "balanced": {
        "vote_average.gte": 6.7,
        "vote_count.gte": 250,
    },
    "gems": {
        "vote_average.gte": 7.2,
        "vote_count.gte": 150,
        "vote_count.lte": 4000,
    },
    "all": {
        "vote_average.gte": 5.0,
        "vote_count.gte": 50,
    },
}
