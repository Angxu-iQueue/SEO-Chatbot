"""Client for the SEOmonitor API v3.

Only endpoints whose paths are confirmed against the public docs
(https://api-docs.seomonitor.com) are exposed here. Add more by following the
same pattern — every call goes through `_get`, so rate limiting, caching,
retries and error shaping are handled once.

Auth: the raw API token goes in the `Authorization` header. There is no
`Bearer` prefix. Get it from Account Settings > Edit Profile in SEOmonitor.

Documented limits: 10 requests/second, 1000 rows/request, 10,000 requests/day.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import requests

log = logging.getLogger(__name__)

BASE_URL = os.getenv("SEOMONITOR_BASE_URL", "https://apigw.seomonitor.com/v3")

# Abbreviations the API returns in `serp_data[].feature`. Expanded before the
# payload reaches the model so it never has to guess what "fsn" means.
SERP_FEATURES: dict[str, str] = {
    "aio": "AI Overview", "aib": "AI Button", "adt": "Ads Pack Top",
    "def": "Definitions", "dir": "Directions", "fsn": "Featured Snippet",
    "flt": "Flights", "htl": "Hotels", "img": "Images Pack", "job": "Jobs",
    "kng": "Knowledge Graph", "geo": "Local Pack", "shp": "Product Listing",
    "rcp": "Recipes", "qns": "Questions", "new": "Top Stories",
    "vid": "Video Carousel", "app": "Apps", "prd": "Product Grid",
    "plc": "Places", "pls": "Places Sites", "tst": "Top Sights Grid",
    "vdi": "Visual Digest", "dan": "Direct Answer", "fla": "Flights Airlines",
    "fls": "Flights Sites", "ttk": "Things to Know",
}


class SEOMonitorError(RuntimeError):
    """Raised for any non-2xx response, carrying the API's own message."""

    def __init__(self, status: int, message: str, details: list[str] | None = None):
        self.status = status
        self.details = details or []
        super().__init__(f"[{status}] {message}")


class _TokenBucket:
    """Blocking rate limiter. Keeps us under the documented 10 req/s ceiling."""

    def __init__(self, rate_per_sec: float, burst: int):
        self._rate = rate_per_sec
        self._capacity = burst
        self._tokens = float(burst)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._updated) * self._rate
                )
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                time.sleep((1 - self._tokens) / self._rate)


class _TTLCache:
    """Small in-process cache. Rank data updates daily, so short TTLs are safe
    and they keep an interactive chat session well inside the daily quota."""

    def __init__(self, ttl_seconds: int = 900, max_entries: int = 512):
        self._ttl = ttl_seconds
        self._max = max_entries
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            hit = self._store.get(key)
            if not hit:
                return None
            expires_at, value = hit
            # >= not >, so a zero TTL expires immediately and behaviour does not
            # depend on clock resolution (Windows time.time() is ~15ms coarse).
            if time.time() >= expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if len(self._store) >= self._max:
                oldest = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest]
            self._store[key] = (time.time() + self._ttl, value)


def default_window(days: int = 30) -> tuple[str, str]:
    """(start_date, end_date) as YYYY-MM-DD — the format every endpoint wants."""
    end = date.today()
    return (end - timedelta(days=days)).isoformat(), end.isoformat()


@dataclass
class SEOMonitorClient:
    api_key: str = field(default_factory=lambda: os.environ.get("SEOMONITOR_API_KEY", ""))
    base_url: str = BASE_URL
    timeout: int = 30
    max_retries: int = 3

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("SEOMONITOR_API_KEY is not set")
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": self.api_key, "Accept": "application/json"}
        )
        self._bucket = _TokenBucket(rate_per_sec=8, burst=8)  # headroom under 10/s
        self._cache = _TTLCache(ttl_seconds=int(os.getenv("SEOMONITOR_CACHE_TTL", "900")))

    # ---------------------------------------------------------------- internals

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        cache_key = f"{path}?{sorted(params.items())}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            log.debug("cache hit %s", path)
            return cached

        url = f"{self.base_url}{path}"
        backoff = 1.0
        for attempt in range(1, self.max_retries + 1):
            self._bucket.acquire()
            resp = self._session.get(url, params=params, timeout=self.timeout)

            if resp.status_code == 200:
                data = resp.json()
                self._cache.set(cache_key, data)
                return data

            if resp.status_code == 429 and attempt < self.max_retries:
                log.warning("429 from %s, backing off %.1fs", path, backoff)
                time.sleep(backoff)
                backoff *= 2
                continue

            try:
                err = resp.json().get("error", {})
                raise SEOMonitorError(
                    resp.status_code,
                    err.get("message", resp.reason),
                    err.get("details"),
                )
            except ValueError:
                raise SEOMonitorError(resp.status_code, resp.text[:200] or resp.reason)

        raise SEOMonitorError(429, "Rate limit exceeded after retries")

    # ------------------------------------------------------------------- public

    def tracked_campaigns(
        self, campaign_ids: str | None = None, company_id: int | None = None
    ) -> Any:
        """All tracked campaigns, with visibility, health and objective status.

        Start here — every other endpoint needs a campaign_id.
        """
        return self._get(
            "/dashboard/v3.0/campaigns/tracked",
            {"campaign_ids": campaign_ids, "company_id": company_id},
        )

    def keywords(
        self,
        campaign_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
        group_id: int | None = None,
        keyword_ids: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
        order_by: str | None = None,
        order_direction: str | None = None,
    ) -> Any:
        """Rank Tracker keywords: rankings, search volume, SERP features,
        AI Overview presence, traffic and SEO Opportunity score."""
        if not start_date or not end_date:
            start_date, end_date = default_window()
        return self._get(
            "/rank-tracker/v3.0/keywords",
            {
                "campaign_id": campaign_id,
                "start_date": start_date,
                "end_date": end_date,
                "group_id": group_id,
                "keyword_ids": keyword_ids,
                "search": search,
                "limit": min(limit, 1000),
                "offset": offset,
                "order_by": order_by,
                "order_direction": order_direction,
            },
        )

    def group_daily_visibility(
        self,
        campaign_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
        group_id: int | None = None,
        keyword_ids: str | None = None,
        domain: str | None = None,
    ) -> Any:
        """Day-by-day visibility for a keyword group — the series to use for
        'is visibility up or down' questions."""
        if not start_date or not end_date:
            start_date, end_date = default_window(90)
        return self._get(
            "/rank-tracker/v3.0/groups/daily-visibility",
            {
                "campaign_id": campaign_id,
                "start_date": start_date,
                "end_date": end_date,
                "group_id": group_id,
                "keyword_ids": keyword_ids,
                "domain": domain,
            },
        )

    def topic_overview(self, campaign_id: int, keyword: str) -> Any:
        """Research-database view of a keyword: volume, YoY, SERP features,
        click share and visibility. Works for keywords you don't track."""
        return self._get(
            "/research/v3.0/topic-overview",
            {"campaign_id": campaign_id, "keyword": keyword},
        )

    def domain_overview(
        self, campaign_id: int, url: str, gap_analysis: str | None = None
    ) -> Any:
        """Aggregate search/traffic/visibility for any domain in the research
        database — this is the competitor-comparison endpoint."""
        return self._get(
            "/research/v3.0/domain-overview",
            {"campaign_id": campaign_id, "url": url, "gap_analysis": gap_analysis},
        )

    def keyword_vault_overview(self, campaign_id: int, list_id: str) -> Any:
        """Aggregated metrics for a saved Keyword Vault list."""
        return self._get(
            "/keyword-vault/v3.0/get-overview-data",
            {"campaign_id": campaign_id, "list": list_id},
        )


# --------------------------------------------------------------- normalisation

def expand_serp_features(payload: Any) -> Any:
    """Rewrite SERP feature codes to full names, in place, at any depth.

    Cheap insurance against the model inventing a meaning for `vdi`.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "feature" and isinstance(value, str):
                payload[key] = SERP_FEATURES.get(value.lower(), value)
            else:
                expand_serp_features(value)
    elif isinstance(payload, list):
        for item in payload:
            expand_serp_features(item)
    return payload


def compact_keywords(payload: Any, keep: int = 25) -> list[dict[str, Any]]:
    """Strip a keywords response down to what an answer actually needs.

    Raw responses are ~40 fields per keyword. Sending 50 of those costs more
    context than the rest of the prompt combined and measurably degrades the
    answer, so flatten to the fields the model reasons over.
    """
    rows = payload if isinstance(payload, list) else [payload]
    out = []
    for row in rows[:keep]:
        if not isinstance(row, dict):
            continue
        ranking = row.get("ranking_data") or {}
        desktop = ranking.get("desktop") or {}
        mobile = ranking.get("mobile") or {}
        search = row.get("search_data") or {}
        opp = row.get("opportunity") or {}
        aio = (row.get("ai_overview") or {}).get("desktop") or {}
        out.append(
            {
                "keyword": row.get("keyword"),
                "keyword_id": row.get("keyword_id"),
                "intent": row.get("search_intent"),
                "search_volume": search.get("search_volume"),
                "yoy": search.get("year_over_year"),
                "rank_desktop": desktop.get("rank"),
                "trend_desktop": desktop.get("trend"),
                "rank_mobile": mobile.get("rank"),
                "opportunity_score": opp.get("score"),
                "difficulty_top_10": opp.get("difficulty_top_10"),
                "extra_monthly_sessions": opp.get("additional_monthly_sessions"),
                "ai_overview_present": aio.get("any_brand_present"),
                "ai_overview_cites_us": aio.get("my_brand_present"),
                "landing_page": ((row.get("landing_pages") or {}).get("desktop") or {}).get("current"),
            }
        )
    return out
