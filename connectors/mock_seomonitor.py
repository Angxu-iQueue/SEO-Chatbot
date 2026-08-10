"""A fake SEOmonitor that needs no account.

Drop-in replacement for SEOMonitorClient: identical method signatures, response
shapes copied from the real v3 docs. Set USE_MOCK_SEO=true in .env and the app
behaves as though live data is connected.

The data is deterministic — seeded per keyword — so the same question gives the
same answer every run. That makes it useful beyond just unblocking you: it's
how you write tests for the agent without burning API quota or depending on a
client's rankings staying still.

The scenario is built to exercise the playbooks rather than to look pretty:
a genuine visibility drop starting 12 days ago, concentrated in a handful of
commercial keywords, two of which lost position to an AI Overview. Ask "why did
visibility drop?" and the diagnostic sequence in playbooks.md will actually
find something.

Swap in a real provider later by writing one class with these same six methods.
Nothing in core/ changes.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any

CAMPAIGN_ID = 72416
DOMAIN = "example-retail.com"

_KEYWORDS: list[dict[str, Any]] = [
    # keyword, volume, rank, trend, intent, aio_present, difficulty
    {"kw": "running shoes", "vol": 90500, "rank": 14, "trend": 6, "intent": "commercial", "aio": True, "diff": "hard"},
    {"kw": "best running shoes for flat feet", "vol": 12100, "rank": 3, "trend": -1, "intent": "commercial", "aio": True, "diff": "medium"},
    {"kw": "trail running shoes", "vol": 27100, "rank": 11, "trend": 5, "intent": "commercial", "aio": True, "diff": "medium"},
    {"kw": "buy running shoes online", "vol": 8100, "rank": 4, "trend": 0, "intent": "transactional", "aio": False, "diff": "easy"},
    {"kw": "running shoes sale", "vol": 18100, "rank": 18, "trend": 9, "intent": "transactional", "aio": False, "diff": "medium"},
    {"kw": "how to choose running shoes", "vol": 6600, "rank": 7, "trend": -2, "intent": "informational", "aio": True, "diff": "easy"},
    {"kw": "marathon training shoes", "vol": 3600, "rank": 5, "trend": -1, "intent": "commercial", "aio": False, "diff": "medium"},
    {"kw": "waterproof running shoes", "vol": 4400, "rank": 22, "trend": 3, "intent": "commercial", "aio": False, "diff": "medium"},
    {"kw": "running shoes for beginners", "vol": 5400, "rank": 9, "trend": 0, "intent": "informational", "aio": True, "diff": "easy"},
    {"kw": "cheap running shoes", "vol": 14800, "rank": 100, "trend": 0, "intent": "transactional", "aio": False, "diff": "hard"},
    {"kw": "example retail", "vol": 33100, "rank": 1, "trend": 0, "intent": "navigational", "aio": False, "diff": "easy"},
    {"kw": "stability running shoes", "vol": 2900, "rank": 6, "trend": -3, "intent": "commercial", "aio": False, "diff": "medium"},
]


def _jitter(seed: str, lo: int, hi: int) -> int:
    """Stable pseudo-random int, so repeated calls agree with each other."""
    h = int(hashlib.sha1(seed.encode()).hexdigest()[:8], 16)
    return lo + (h % (hi - lo + 1))


def _opportunity(row: dict[str, Any]) -> dict[str, Any]:
    rank, vol = row["rank"], row["vol"]
    score = 1 if rank == 1 else min(10, max(1, round((vol / 10000) + (10 - min(rank, 20) / 2))))
    return {
        "score": int(score),
        "difficulty_top_10": row["diff"],
        "additional_monthly_sessions": int(vol * 0.28) if rank > 3 else 0,
        "avg_cpc": round(0.4 + _jitter(row["kw"], 0, 180) / 100, 2),
    }


class MockSEOMonitorClient:
    """Same surface as SEOMonitorClient. No network, no credentials."""

    def __init__(self, *_: Any, **__: Any) -> None:
        self.api_key = "mock"

    # ---------------------------------------------------------------- shapes

    def tracked_campaigns(self, campaign_ids: str | None = None, company_id: int | None = None) -> Any:
        return [{
            "campaign_info": {
                "id": str(CAMPAIGN_ID),
                "name": "Example Retail",
                "company": "Example Retail Ltd",
                "company_id": "51256",
                "domain": DOMAIN,
                "keyword_count": len(_KEYWORDS),
                "date_created": "2025-04-25",
                "location": "United Kingdom",
                "currency": "GBP",
            },
            "visibility": {
                "desktop": {"latest": 0.31, "trend_7days": -0.04, "trend_30days": -0.06},
                "mobile": {"latest": 0.27, "trend_7days": -0.07, "trend_30days": -0.09},
            },
            "health_status": "needs_attention",
            "objective_status": {
                "actual_sessions": 61200,
                "estimated_sessions": 74000,
                "performance": 0.83,
                "status": "off_track",
                "start_month": "Jan, 2026",
                "end_month": "Dec, 2026",
            },
            "reporting_status": "pending",
            "account_manager": "Sam Okafor",
            "_mock": True,
        }]

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
        rows = _KEYWORDS
        if search:
            rows = [r for r in rows if search.lower() in r["kw"].lower()]
        if order_by == "search_volume":
            rows = sorted(rows, key=lambda r: r["vol"], reverse=order_direction != "asc")
        elif order_by in ("rank", "trend"):
            rows = sorted(rows, key=lambda r: r[order_by if order_by == "rank" else "trend"],
                          reverse=order_direction == "desc")

        out = []
        for row in rows[offset : offset + limit]:
            out.append({
                "keyword_id": 7000000 + _jitter(row["kw"], 1000, 99999),
                "keyword": row["kw"],
                "groups": "40112",
                "search_intent": row["intent"],
                "search_data": {
                    "search_volume": row["vol"],
                    "year_over_year": round(0.85 + _jitter(row["kw"], 0, 60) / 100, 2),
                },
                "percentage_clicks": 44 if row["aio"] else 71,
                "ranking_data": {
                    "desktop": {
                        "rank": row["rank"],
                        "trend": row["trend"],
                        "trend_impact": int(row["vol"] * 0.01 * row["trend"]),
                        "best_rank": {"rank": max(1, row["rank"] - row["trend"]),
                                      "date": (date.today() - timedelta(days=21)).isoformat()},
                    },
                    "mobile": {
                        "rank": min(100, row["rank"] + (2 if row["aio"] else 0)),
                        "trend": row["trend"] + (2 if row["aio"] else 0),
                        "trend_impact": 0,
                        "best_rank": {"rank": max(1, row["rank"] - 2),
                                      "date": (date.today() - timedelta(days=25)).isoformat()},
                    },
                },
                "ai_overview": {
                    "desktop": {"my_brand_present": False, "any_brand_present": row["aio"],
                                "rank": 1 if row["aio"] else None, "trend": 0, "processing": False},
                    "mobile": {"my_brand_present": False, "any_brand_present": row["aio"],
                               "rank": 1 if row["aio"] else None, "trend": 0, "processing": False},
                },
                "traffic_data": {"sessions": int(row["vol"] * 0.02) if row["rank"] < 20 else 0,
                                 "ecommerce": {"transactions": 0, "revenue": 0},
                                 "goals": {"completions": 0, "revenue": 0}},
                "opportunity": _opportunity(row),
                "landing_pages": {
                    "desktop": {"current": f"https://{DOMAIN}/shop/{row['kw'].replace(' ', '-')}",
                                "desired": f"https://{DOMAIN}/shop/{row['kw'].replace(' ', '-')}"},
                    "mobile": {"current": f"https://{DOMAIN}/shop/{row['kw'].replace(' ', '-')}",
                               "desired": f"https://{DOMAIN}/shop/{row['kw'].replace(' ', '-')}"},
                },
                "serp_data": {
                    "desktop": ([{"feature": "aio", "position": "1", "listed": False}] if row["aio"] else [])
                    + [{"feature": "shp", "position": "2", "listed": True}],
                    "mobile": ([{"feature": "aio", "position": "1", "listed": False}] if row["aio"] else []),
                },
                "_mock": True,
            })
        return out

    def group_daily_visibility(
        self,
        campaign_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
        group_id: int | None = None,
        keyword_ids: str | None = None,
        domain: str | None = None,
    ) -> Any:
        """90 days, flat then a step change 12 days ago — a findable drop."""
        today = date.today()
        series = []
        for days_ago in range(89, -1, -1):
            day = today - timedelta(days=days_ago)
            base = 0.36 if days_ago > 12 else 0.27
            wobble = (_jitter(day.isoformat(), 0, 20) - 10) / 1000
            series.append({
                "date": day.isoformat(),
                "visibility": round(base + wobble, 3),
                "avg_rank": round((8.4 if days_ago > 12 else 12.9) + wobble * 10, 1),
            })
        return {"campaign_id": campaign_id, "group_id": group_id or 40112,
                "daily_visibility": series, "_mock": True}

    def topic_overview(self, campaign_id: int, keyword: str) -> Any:
        vol = next((r["vol"] for r in _KEYWORDS if r["kw"] == keyword), _jitter(keyword, 400, 40000))
        return {
            "related_keywords": _jitter(keyword, 60, 900),
            "search_data": {"search_volume": vol,
                            "year_over_year": round(0.9 + _jitter(keyword, 0, 50) / 100, 2)},
            "serp_data": {"percentage_clicks": 0.58,
                          "serp_features": [{"feature": "aio", "count": 8},
                                            {"feature": "shp", "count": 10}]},
            "visibility_data": {"visibility": 0.19, "trend": -0.2},
            "_mock": True,
        }

    def domain_overview(self, campaign_id: int, url: str, gap_analysis: str | None = None) -> Any:
        is_us = DOMAIN in url
        return {
            "domain": url,
            "visibility": {"latest": 0.27 if is_us else 0.44,
                           "trend_30days": -0.09 if is_us else 0.11},
            "traffic": {"estimated_monthly_sessions": 61200 if is_us else 128400},
            "rankings": {"top_3": 2 if is_us else 9, "top_10": 5 if is_us else 17,
                         "top_100": 11 if is_us else 24},
            "_mock": True,
        }

    def keyword_vault_overview(self, campaign_id: int, list_id: str) -> Any:
        return {"list": list_id, "keywords": len(_KEYWORDS),
                "total_search_volume": sum(r["vol"] for r in _KEYWORDS), "_mock": True}
