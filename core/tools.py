from __future__ import annotations

import json
import logging
from typing import Any, Callable

from connectors.seomonitor import (
    SEOMonitorClient,
    SEOMonitorError,
    compact_keywords,
    expand_serp_features,
)
from core.kb import KnowledgeBase

log = logging.getLogger(__name__)


class ToolUnavailable(RuntimeError):
    """A tool exists but isn't configured — expected, not an error to trace."""


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Search our internal SEO knowledge base: methodology, metric "
                "definitions, client playbooks, escalation rules and how we "
                "interpret SEOmonitor data. Use this for any 'what does X mean', "
                "'how do we', or 'what's our policy on' question. Always use it "
                "before answering from general SEO knowledge."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language search query"},
                    "k": {"type": "integer", "description": "Passages to return (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_campaigns",
            "description": (
                "List tracked SEOmonitor campaigns with current visibility, "
                "health status and objective progress. Call this first when the "
                "user names a client or domain but you don't have its campaign_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_ids": {
                        "type": "string",
                        "description": "Optional comma-separated IDs to filter by",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_keywords",
            "description": (
                "Live keyword data from the Rank Tracker: current rank, trend, "
                "search volume, SERP features, AI Overview presence and SEO "
                "Opportunity score. Use for 'how are we ranking', 'which keywords "
                "dropped', 'what should we prioritise'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "integer"},
                    "search": {"type": "string", "description": "Substring filter on the keyword"},
                    "group_id": {"type": "integer"},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "limit": {"type": "integer", "description": "Default 50, max 1000"},
                    "order_by": {
                        "type": "string",
                        "description": "e.g. rank, search_volume, opportunity",
                    },
                    "order_direction": {"type": "string", "enum": ["asc", "desc"]},
                },
                "required": ["campaign_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_visibility_trend",
            "description": (
                "Daily visibility series for a campaign or keyword group. Use "
                "for questions about direction over time: 'are we up or down', "
                "'when did the drop start', 'how did we recover'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "integer"},
                    "group_id": {"type": "integer"},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["campaign_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_topic_overview",
            "description": (
                "Research-database metrics for any keyword, tracked or not: "
                "search volume, year-over-year change, SERP features, click "
                "share. Use for keyword research and opportunity sizing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "integer"},
                    "keyword": {"type": "string"},
                },
                "required": ["campaign_id", "keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_domain_overview",
            "description": (
                "Aggregate visibility, traffic and ranking data for any domain. "
                "This is the competitor tool — use it when the user asks how a "
                "rival is performing or where the gaps are."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "integer"},
                    "url": {"type": "string", "description": "Domain or URL"},
                    "gap_analysis": {"type": "string"},
                },
                "required": ["campaign_id", "url"],
            },
        },
    },
]


class Dispatcher:
    """Executes tool calls and returns JSON-serialisable results.

    Every handler catches its own errors and returns them as data. A failed API
    call should give the model something to reason about ("campaign not found,
    try listing campaigns") rather than crashing the turn.
    """

    def __init__(self, kb: KnowledgeBase, seomonitor: SEOMonitorClient | None):
        self.kb = kb
        self.api = seomonitor
        self._handlers: dict[str, Callable[..., Any]] = {
            "search_knowledge_base": self._search_kb,
            "list_campaigns": self._list_campaigns,
            "get_keywords": self._get_keywords,
            "get_visibility_trend": self._get_visibility,
            "get_topic_overview": self._get_topic,
            "get_domain_overview": self._get_domain,
        }

    def run(self, name: str, arguments: dict[str, Any]) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            return json.dumps({"error": f"Unknown tool: {name}"})
        try:
            return json.dumps(handler(**arguments), default=str)[:12000]
        except ToolUnavailable as exc:
            log.info("%s unavailable: %s", name, exc)
            return json.dumps({"error": str(exc), "tool": name, "retryable": False})
        except SEOMonitorError as exc:
            log.warning("%s failed: %s", name, exc)
            return json.dumps(
                {"error": str(exc), "details": exc.details, "tool": name}
            )
        except TypeError as exc:
            return json.dumps({"error": f"Bad arguments for {name}: {exc}"})
        except Exception as exc:  
            log.exception("%s crashed", name)
            return json.dumps({"error": f"{type(exc).__name__}: {exc}", "tool": name})

   
    def _require_api(self) -> SEOMonitorClient:
        if self.api is None:
            raise ToolUnavailable(
                "SEOmonitor is not connected. Set SEOMONITOR_API_KEY to enable "
                "live data; knowledge-base answers still work without it."
            )
        return self.api

    def _search_kb(self, query: str, k: int = 5) -> dict[str, Any]:
        hits = self.kb.search(query, k=k)
        if not hits:
            return {
                "passages": [],
                "note": "Nothing in the knowledge base clears the relevance "
                "threshold. Say so rather than answering from memory.",
            }
        return {"passages": hits}

    def _list_campaigns(self, campaign_ids: str | None = None) -> Any:
        return self._require_api().tracked_campaigns(campaign_ids=campaign_ids)

    def _get_keywords(self, campaign_id: int, **kwargs: Any) -> Any:
        raw = self._require_api().keywords(campaign_id=campaign_id, **kwargs)
        return {
            "campaign_id": campaign_id,
            "keywords": compact_keywords(expand_serp_features(raw)),
            "note": "Ranks are 1-100; 100 means not found in the top 100.",
        }

    def _get_visibility(self, campaign_id: int, **kwargs: Any) -> Any:
        return self._require_api().group_daily_visibility(campaign_id=campaign_id, **kwargs)

    def _get_topic(self, campaign_id: int, keyword: str) -> Any:
        return expand_serp_features(
            self._require_api().topic_overview(campaign_id, keyword)
        )

    def _get_domain(self, campaign_id: int, url: str, gap_analysis: str | None = None) -> Any:
        return expand_serp_features(
            self._require_api().domain_overview(campaign_id, url, gap_analysis)
        )
