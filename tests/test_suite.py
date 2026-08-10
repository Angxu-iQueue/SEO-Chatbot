"""Test suite. No network, no credentials, no API quota.

    pytest -q

The mock connector is what makes this possible: the agent loop can be driven
end to end against deterministic data, so these run in CI on every push.

Deliberately not tested here: embedding quality and answer quality. Those are
not unit-testable. Retrieval is measured by eval_retrieval.py; answer quality
needs a human reading the Tool calls panel.
"""

from __future__ import annotations

import inspect
import json

import pytest

from connectors.mock_seomonitor import MockSEOMonitorClient
from connectors.seomonitor import (
    SEOMonitorClient,
    _TTLCache,
    _TokenBucket,
    compact_keywords,
    default_window,
    expand_serp_features,
)
from core.tools import TOOL_SCHEMAS, Dispatcher, ToolUnavailable

CAMPAIGN = 72416


class StubKB:
    """Stands in for KnowledgeBase so tests need no embedding models."""

    def __init__(self, hits=None):
        self._hits = hits if hits is not None else [
            {"text": "Rank 100 means not found.", "source": "seo-glossary.md#Rank", "score": 0.9}
        ]

    def search(self, query, k=5):
        return self._hits


@pytest.fixture
def dispatcher():
    return Dispatcher(StubKB(), MockSEOMonitorClient())


# --------------------------------------------------------------- contract

def test_mock_matches_real_client_surface():
    """The mock must stay a drop-in replacement, or demo mode diverges from
    production in ways nobody notices until deploy day."""
    def public(cls):
        return {n for n, _ in inspect.getmembers(cls, inspect.isfunction)
                if not n.startswith("_")}

    real, mock = public(SEOMonitorClient), public(MockSEOMonitorClient)
    assert not real - mock, f"mock is missing: {real - mock}"

    for name in real:
        assert (str(inspect.signature(getattr(SEOMonitorClient, name)))
                == str(inspect.signature(getattr(MockSEOMonitorClient, name)))), \
            f"signature drift on {name}"


def test_every_schema_has_a_handler(dispatcher):
    """A schema without a handler means the model can call something that
    always errors — invisible until a user hits it."""
    for schema in TOOL_SCHEMAS:
        name = schema["function"]["name"]
        assert name in dispatcher._handlers, f"no handler for {name}"


def test_schemas_are_wellformed():
    for schema in TOOL_SCHEMAS:
        fn = schema["function"]
        assert schema["type"] == "function"
        assert fn["description"].strip(), f"{fn['name']} has no description"
        # The description is what the model uses to choose. Terse ones misfire.
        assert len(fn["description"]) > 60, f"{fn['name']} description too thin"


# ------------------------------------------------------------ normalisation

def test_serp_codes_are_expanded():
    payload = {"serp_data": {"desktop": [{"feature": "aio"}, {"feature": "fsn"}]}}
    expand_serp_features(payload)
    features = [f["feature"] for f in payload["serp_data"]["desktop"]]
    assert features == ["AI Overview", "Featured Snippet"]


def test_unknown_serp_code_passes_through():
    payload = {"feature": "zzz"}
    assert expand_serp_features(payload)["feature"] == "zzz"


def test_compaction_preserves_both_ai_overview_signals():
    """`present` and `cites_us` answer different questions. Losing `present`
    breaks the 'rank flat, traffic down' diagnosis."""
    raw = MockSEOMonitorClient().keywords(CAMPAIGN)
    rows = compact_keywords(raw)
    assert {"ai_overview_present", "ai_overview_cites_us"} <= set(rows[0])
    assert any(r["ai_overview_present"] for r in rows)


def test_compaction_shrinks_the_payload():
    raw = MockSEOMonitorClient().keywords(CAMPAIGN)
    assert len(json.dumps(compact_keywords(raw))) < len(json.dumps(raw)) / 2


def test_default_window_is_iso_and_ordered():
    start, end = default_window(30)
    assert start < end and len(start) == len(end) == 10


# ----------------------------------------------------------- infrastructure

def test_cache_returns_a_live_entry():
    cache = _TTLCache(ttl_seconds=900)
    cache.set("k", {"a": 1})
    assert cache.get("k") == {"a": 1}


def test_cache_misses_unknown_key():
    assert _TTLCache(ttl_seconds=900).get("never-set") is None


def test_cache_expires_at_the_boundary():
    """Zero TTL must expire immediately. Asserting this via a real sleep would
    be flaky on Windows, whose clock is ~15ms coarse — so drive the clock
    directly instead."""
    cache = _TTLCache(ttl_seconds=0)
    cache.set("k", 1)
    assert cache.get("k") is None


def test_cache_expires_after_ttl(monkeypatch):
    import connectors.seomonitor as mod

    now = [1000.0]
    monkeypatch.setattr(mod.time, "time", lambda: now[0])

    cache = _TTLCache(ttl_seconds=60)
    cache.set("k", "v")
    assert cache.get("k") == "v"

    now[0] += 59
    assert cache.get("k") == "v", "should still be live one second before expiry"

    now[0] += 2
    assert cache.get("k") is None, "should be gone after expiry"


def test_cache_evicts_at_capacity():
    cache = _TTLCache(ttl_seconds=900, max_entries=2)
    for i in range(3):
        cache.set(f"k{i}", i)
    assert sum(cache.get(f"k{i}") is not None for i in range(3)) <= 2


def test_token_bucket_throttles():
    import time

    bucket = _TokenBucket(rate_per_sec=20, burst=2)
    start = time.monotonic()
    for _ in range(6):
        bucket.acquire()
    assert time.monotonic() - start >= 0.15


# --------------------------------------------------------------- dispatcher

def test_unknown_tool_returns_error_not_raises(dispatcher):
    assert "error" in json.loads(dispatcher.run("nope", {}))


def test_bad_arguments_return_error(dispatcher):
    assert "error" in json.loads(dispatcher.run("get_topic_overview", {"wrong": 1}))


def test_missing_connector_is_not_retryable():
    result = json.loads(Dispatcher(StubKB(), None).run("get_keywords", {"campaign_id": 1}))
    assert result["retryable"] is False


def test_require_api_raises_tool_unavailable():
    with pytest.raises(ToolUnavailable):
        Dispatcher(StubKB(), None)._require_api()


def test_empty_kb_result_tells_the_model_to_abstain():
    """The abstention path. If this note disappears the bot starts inventing
    policy, which is the worst failure mode this system has."""
    result = json.loads(Dispatcher(StubKB(hits=[]), None).run(
        "search_knowledge_base", {"query": "unicorn rankings"}))
    assert result["passages"] == []
    assert "note" in result


def test_dispatcher_always_returns_a_json_string(dispatcher):
    for name in dispatcher._handlers:
        out = dispatcher.run(name, {"campaign_id": CAMPAIGN, "keyword": "x",
                                    "url": "y", "query": "z"})
        assert isinstance(out, str)
        json.loads(out)


# -------------------------------------------------------------- mock shape

def test_mock_is_deterministic():
    a = MockSEOMonitorClient().keywords(CAMPAIGN)
    b = MockSEOMonitorClient().keywords(CAMPAIGN)
    assert a == b


def test_mock_data_is_labelled():
    """Fabricated numbers must be identifiable downstream."""
    assert MockSEOMonitorClient().keywords(CAMPAIGN)[0]["_mock"] is True


def test_mock_visibility_contains_a_findable_drop():
    series = MockSEOMonitorClient().group_daily_visibility(CAMPAIGN)["daily_visibility"]
    early = sum(d["visibility"] for d in series[:60]) / 60
    late = sum(d["visibility"] for d in series[-7:]) / 7
    assert early - late > 0.05, "the demo scenario lost its drop"


def test_mock_search_filter_works():
    rows = MockSEOMonitorClient().keywords(CAMPAIGN, search="trail")
    assert rows and all("trail" in r["keyword"] for r in rows)


# ------------------------------------------------------------- agent loop

class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeToolCall:
    def __init__(self, name, args, call_id="c1"):
        self.id = call_id
        self.function = type("F", (), {"name": name, "arguments": json.dumps(args)})()


class FakeOpenAI:
    """Scripts a sequence of model replies so the loop runs without network."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0
        self.chat = type("C", (), {"completions": self})()

    def create(self, **kwargs):
        self.calls += 1
        message = self._script.pop(0) if self._script else FakeMessage("done")
        return type("R", (), {"choices": [type("C", (), {"message": message})()]})()


def _agent(script, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_stub")
    from core.agent import SEOAgent

    agent = SEOAgent(Dispatcher(StubKB(), MockSEOMonitorClient()))
    agent.client = FakeOpenAI(script)
    return agent


def test_agent_returns_directly_when_no_tools_needed(monkeypatch):
    turn = _agent([FakeMessage("Visibility is a weighted share of demand.")],
                  monkeypatch).run("what is visibility?")
    assert turn.rounds == 0 and turn.tool_calls == []


def test_agent_executes_and_traces_a_tool_call(monkeypatch):
    turn = _agent([
        FakeMessage(tool_calls=[FakeToolCall("list_campaigns", {})]),
        FakeMessage("You have one campaign: Example Retail."),
    ], monkeypatch).run("what campaigns do we have?")
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0]["tool"] == "list_campaigns"


def test_agent_chains_multiple_rounds(monkeypatch):
    """Chaining is the whole design. If this breaks, the bot silently becomes
    a single-lookup tool and nobody notices."""
    turn = _agent([
        FakeMessage(tool_calls=[FakeToolCall("get_visibility_trend", {"campaign_id": CAMPAIGN})]),
        FakeMessage(tool_calls=[FakeToolCall("get_keywords", {"campaign_id": CAMPAIGN})]),
        FakeMessage(tool_calls=[FakeToolCall("search_knowledge_base", {"query": "drop"})]),
        FakeMessage("Visibility fell 12 days ago across three commercial terms."),
    ], monkeypatch).run("why did visibility drop?")
    assert [t["tool"] for t in turn.tool_calls] == [
        "get_visibility_trend", "get_keywords", "search_knowledge_base"]


def test_agent_stops_at_max_rounds(monkeypatch):
    """A model that loops forever would otherwise burn credits until timeout."""
    from core.agent import MAX_TOOL_ROUNDS

    script = [FakeMessage(tool_calls=[FakeToolCall("list_campaigns", {}, f"c{i}")])
              for i in range(MAX_TOOL_ROUNDS + 5)]
    turn = _agent(script, monkeypatch).run("loop forever")
    assert turn.rounds == MAX_TOOL_ROUNDS
    assert len(turn.tool_calls) == MAX_TOOL_ROUNDS


def test_agent_survives_a_failing_tool(monkeypatch):
    turn = _agent([
        FakeMessage(tool_calls=[FakeToolCall("get_keywords", {"campaign_id": "not-an-int"})]),
        FakeMessage("I could not read that campaign ID."),
    ], monkeypatch).run("keywords please")
    assert turn.answer  # the turn completed rather than raising
