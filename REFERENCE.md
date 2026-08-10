# API reference

Every class, method and function in the project, grouped by the layer it
belongs to. Private members (leading underscore) are documented too, since you
need them to modify anything.

**Reading order if you're new to the codebase:** `Dispatcher.run` →
`SEOAgent.run` → `KnowledgeBase.search` → `SEOMonitorClient._get`. Those four
are the load-bearing ones; the rest is support.

---

## Layer map

```
app.py              UI. Owns nothing, wires everything.
  └─ core/agent.py       Decides what to do. The LLM loop.
       └─ core/tools.py       Executes decisions. Tool schemas + dispatch.
            ├─ core/kb.py            Retrieval over your documents.
            └─ connectors/*.py       HTTP to SEOmonitor (or the mock).
```

Dependencies point downward only. `core/kb.py` knows nothing about SEOmonitor;
`connectors/` knows nothing about the LLM. That's what makes the mock a
drop-in and what would let you swap FAISS for a hosted vector store without
touching the agent.

---

# connectors/seomonitor.py

HTTP against SEOmonitor API v3. No LLM concepts appear in this file.

## Module constants

| Name | Purpose |
|---|---|
| `BASE_URL` | `https://apigw.seomonitor.com/v3`, overridable via `SEOMONITOR_BASE_URL`. |
| `SERP_FEATURES` | Maps the API's 3-letter codes (`aio`, `fsn`, `geo`…) to full names. 27 entries. |

## `SEOMonitorError(RuntimeError)`

**`__init__(status, message, details=None)`**

Raised for any non-2xx response. Carries `.status` (int), `.details` (list of
strings from the API's own error body), and formats as `[404] Campaign not
found`. `Dispatcher.run` catches this and hands it to the model as data, so a
bad campaign ID becomes something the model can recover from rather than a
crashed turn.

## `_TokenBucket`

Classic token-bucket rate limiter, thread-safe.

**`__init__(rate_per_sec, burst)`** — Configured at `rate_per_sec=8, burst=8`
against SEOmonitor's documented 10/s ceiling. The headroom matters because the
limit is enforced server-side and a 429 costs more than the delay avoids.

**`acquire()`** — **Blocks** until a token is available. Called before every
request inside `_get`. Refills continuously based on elapsed wall-clock time
rather than on a timer thread.

## `_TTLCache`

**`__init__(ttl_seconds=900, max_entries=512)`** — TTL from
`SEOMONITOR_CACHE_TTL`.

**`get(key)`** — Returns the value or `None`. Deletes expired entries on read,
so there's no background sweeper.

**`set(key, value)`** — At capacity, evicts the entry with the earliest
expiry. That's not LRU — it's closer to "expiring soonest first," which is
cheaper and adequate here.

This cache is load-bearing, not an optimisation. SEOmonitor allows 10,000
requests/day; an agent chaining four tools per turn across a team burns that
faster than you'd expect. Rank data updates daily, so a 15-minute TTL costs
you no freshness.

## `default_window(days=30)`

Returns `(start_date, end_date)` as `YYYY-MM-DD` strings, ending today. Used by
`keywords()` and `group_daily_visibility()` when the model omits dates — which
it often does, since it has no reason to invent a range.

## `SEOMonitorClient`

A dataclass. Fields: `api_key` (defaults to `SEOMONITOR_API_KEY`), `base_url`,
`timeout=30`, `max_retries=3`.

**`__post_init__()`** — Raises `ValueError` if no API key. Builds a persistent
`requests.Session` with the auth header, plus the bucket and cache. **The
`Authorization` header is the raw token with no `Bearer` prefix** — this
differs from Hugging Face and is the most common setup failure.

**`_get(path, params)`** — The single chokepoint every request passes through.
In order: drop `None` params, check cache, acquire a rate token, GET, and on
200 cache and return. On 429 retry with exponential backoff (1s, 2s, 4s). On
any other error raise `SEOMonitorError` carrying the API's own message. Adding
an endpoint means writing a one-line method here, and it inherits all of this
for free.

The six public endpoint methods, all confirmed against the published docs:

| Method | Endpoint | Use for |
|---|---|---|
| `tracked_campaigns(campaign_ids=None, company_id=None)` | `/dashboard/v3.0/campaigns/tracked` | Resolving a client name to a `campaign_id`. Everything else needs one. |
| `keywords(campaign_id, start_date, end_date, group_id, keyword_ids, search, limit=50, offset=0, order_by, order_direction)` | `/rank-tracker/v3.0/keywords` | Ranks, volume, SERP features, AI Overview, opportunity scores. `limit` is clamped to the API's 1000 max. |
| `group_daily_visibility(campaign_id, start_date, end_date, group_id, keyword_ids, domain)` | `/rank-tracker/v3.0/groups/daily-visibility` | Time series. Defaults to a 90-day window, since trend questions need more than 30. |
| `topic_overview(campaign_id, keyword)` | `/research/v3.0/topic-overview` | Keyword research. Works on keywords you don't track. |
| `domain_overview(campaign_id, url, gap_analysis=None)` | `/research/v3.0/domain-overview` | Competitor analysis. |
| `keyword_vault_overview(campaign_id, list_id)` | `/keyword-vault/v3.0/get-overview-data` | Saved list metrics. **Implemented but not exposed as a tool** — add a schema in `tools.py` if you want the model to reach it. |

## `expand_serp_features(payload)`

Walks a response at any depth and rewrites every `"feature"` value from code to
full name, **mutating in place** and also returning it.

Not cosmetic. Given `"feature": "vdi"` the model will confidently invent a
meaning. Given `"Visual Digest"` it won't need to.

## `compact_keywords(payload, keep=25)`

Flattens the keywords response from ~40 nested fields per keyword to 13 flat
ones: keyword, id, intent, volume, YoY, desktop/mobile rank and trend,
opportunity score, difficulty, extra sessions, `ai_overview_present`,
`ai_overview_cites_us`, landing page.

The most consequential function in the file. Fifty raw keyword objects cost
more context than the entire rest of the prompt, and burying the signal in
nulls measurably degrades answers. Note the two separate AI Overview fields:
*present* (an AI Overview appeared, which suppresses clicks even at rank 1) and
*cites us* (we're in it). Diagnosing "rank flat, traffic down" needs the first.

---

# connectors/mock_seomonitor.py

Identical public surface to `SEOMonitorClient`, no network, no credentials.
Activated by `USE_MOCK_SEO=true`. Signature-compatible — verified by
introspection, so it's a genuine drop-in.

## `_jitter(seed, lo, hi)`

Deterministic pseudo-random int from a SHA1 of the seed string. **Determinism
is the point:** the same question gives the same answer every run, which is
what makes the mock usable for regression tests rather than just demos.

## `_opportunity(row)`

Derives a plausible 1-10 opportunity score from volume and rank, plus
difficulty and estimated additional sessions.

## `MockSEOMonitorClient`

Six methods mirroring the real client exactly. The fabricated data encodes a
deliberate scenario rather than noise: visibility flat at ~0.36 for 78 days,
stepping down to ~0.27 twelve days ago, with the losses concentrated in three
commercial keywords, two of which have an AI Overview that doesn't cite the
site. Run the six-step drop playbook against it and each step finds real
evidence.

Every response includes `"_mock": True`, so fabricated data is identifiable
downstream and in logs.

---

# core/kb.py

Retrieval. Knows nothing about SEO or the LLM.

## Module constants

`KB_DIR`, `INDEX_DIR`, `EMBED_MODEL`, `RERANK_MODEL`, `CHUNK_CHARS` (1200),
`CHUNK_OVERLAP` (180), `MIN_RELEVANCE` (0.25) — all env-overridable.

`MIN_RELEVANCE` is the abstention threshold and the most important knob in the
project. Too low and the bot invents policy; too high and it claims ignorance
about documents you wrote.

## `Chunk`

Dataclass: `text`, `source`, `heading`, `chunk_id`.

**`cite()`** — Returns `file.md#Heading`, or just `file.md` if the chunk had no
heading. This string is what appears in the model's citations.

## `_split_markdown(text, source)`

Splits on markdown headings (`#` through `####`) first, then on `CHUNK_CHARS`
with overlap.

Heading-first ordering is deliberate: splitting purely by size orphans a
definition from its term, and the resulting chunk retrieves for neither. **The
heading is prepended to every chunk before embedding**, so it carries a large
share of the retrieval signal — which is why `## Diagnosing a visibility drop`
works and `## Process 4` doesn't.

## `_read_documents(kb_dir)`

Recursively reads `.md`, `.txt`, `.mdx`. Raises if it finds nothing, rather
than silently building an empty index that fails mysteriously at query time.

## `KnowledgeBase`

**`__init__(kb_dir, index_dir)`** — Cheap. Loads no models.

**`encoder`** (property) — Lazy-loads the bi-encoder on first use.
**`reranker`** (property) — Lazy-loads the cross-encoder on first use.

Laziness matters: together these are ~1.5 GB, and `check_setup.py` shouldn't
pay for them before it's confirmed your token works.

**`build()`** — Read → chunk → embed → FAISS `IndexFlatIP` → write index and
chunk metadata to disk. Returns the chunk count. Idempotent and safe to call
from the UI button; that's what makes the knowledge base editable without a
redeploy. Vectors are normalised, so inner product equals cosine similarity.

**`load()`** — Reads the index from disk, calling `build()` if absent. So a
fresh clone self-initialises.

**`search(query, k=5, pool=20)`** — Two-stage. Embed the query (with the
`bge`-specific prefix that these models expect on queries but not documents),
retrieve `pool` candidates by vector similarity, rerank all of them with the
cross-encoder, return the top `k` scoring above `MIN_RELEVANCE`.

The two stages do different jobs: the bi-encoder gets you the right
neighbourhood fast, the cross-encoder distinguishes "a document about rankings"
from "the document that answers this question."

**An empty list is a meaningful return value, not a failure.** It's how the
agent learns to say "not in the knowledge base" instead of falling back on
generic SEO knowledge.

---

# core/tools.py

The bridge between the model's decisions and actual execution.

## `TOOL_SCHEMAS`

Six OpenAI-format function schemas: `search_knowledge_base`, `list_campaigns`,
`get_keywords`, `get_visibility_trend`, `get_topic_overview`,
`get_domain_overview`.

**The `description` fields are prompt engineering, not documentation.** They're
the only thing the model reads when choosing a tool. `list_campaigns` says
"call this first when the user names a client but you don't have its
campaign_id" — that sentence is what prevents the model from inventing IDs.
Treat edits here as prompt changes and re-test.

## `ToolUnavailable(RuntimeError)`

A tool exists but isn't configured. Separated from real errors so a missing API
key logs at info level without a stack trace — an expected state, not a fault.

## `Dispatcher`

**`__init__(kb, seomonitor)`** — Takes the KB and a client (real, mock, or
`None`). Builds the name → handler map.

**`run(name, arguments)`** — Returns a JSON **string**, always, truncated to
12,000 chars. Catches everything: unknown tool, `ToolUnavailable`,
`SEOMonitorError`, `TypeError` from bad arguments, and any unexpected
exception.

This total-catch design is deliberate. A failed tool call should give the model
something to reason about — "campaign not found, try listing campaigns" — and
let it recover mid-turn. An exception would kill the turn and show the user a
stack trace.

**`_require_api()`** — Returns the client or raises `ToolUnavailable`. Every
SEOmonitor handler calls it first.

**Handlers** — `_search_kb` (adds an explicit note when nothing clears the
threshold, so the model knows silence is meaningful), `_list_campaigns`,
`_get_keywords` (applies `expand_serp_features` then `compact_keywords`, and
appends a note that rank 100 means "not in the top 100"), `_get_visibility`,
`_get_topic`, `_get_domain`.

**Adding a tool is three edits:** a method on the client, a schema in
`TOOL_SCHEMAS`, a handler here. No routing logic to update — that's the whole
point of the design.

---

# core/agent.py

## Module constants

`HF_BASE_URL` (`https://router.huggingface.co/v1`), `HF_MODEL`
(`openai/gpt-oss-120b:cheapest`), `MAX_TOOL_ROUNDS` (5).

## `SYSTEM_PROMPT`

Establishes two non-interchangeable sources of truth — the knowledge base is
authoritative for *how we work*, SEOmonitor for *what is currently true* — and
forbids answering process questions from general knowledge or stating client
numbers no tool returned. Formatted at call time with today's date and, if set,
the campaign ID.

## `Turn`

Dataclass: `answer`, `tool_calls` (the trace), `rounds`. Returning the trace
alongside the answer is what powers the UI's Tool calls panel.

## `SEOAgent`

**`__init__(dispatcher, model)`** — Raises `ValueError` without `HF_TOKEN`.
Constructs an `OpenAI` client pointed at the HF router; the endpoint is
OpenAI-compatible, so the SDK works unchanged.

**`_system_message(campaign_id)`** — Builds the system message, injecting the
current date (the model can't know it) and the sidebar campaign ID.

**`run(question, history=None, campaign_id=None)`** — The core loop:

1. Assemble system + history + question.
2. Call the model with `TOOL_SCHEMAS` and `tool_choice="auto"`.
3. **No tool calls → done.** Return the answer.
4. Otherwise append the assistant message, execute every requested call via the
   dispatcher, append each result as a `tool` message, loop.
5. On exhausting `MAX_TOOL_ROUNDS`, make one final call asking for a best-effort
   answer that flags what's missing — better than returning nothing after five
   rounds of work.

`temperature=0.2` throughout. This is analysis, not creative writing.

Note that tool results go back to the model as messages, which is why context
grows each round and why `compact_keywords` matters so much.

---

# app.py

## Startup (module scope)

`load_dotenv()` runs **before** the local imports, because `core` and
`connectors` read env vars at module scope. The `# noqa: E402` comments mark
the deliberate import-order violation. Then: build the KB, pick a connector
(mock / live / none) into `MODE`, construct the agent, set `STATUS`.

## `respond(message, history, campaign_id)`

Gradio event handler. Returns `("", history, trace_md)` — the empty string
clears the input box.

Passes only the **last 8 messages** as history. Unbounded history plus tool
results would blow the context window within a few turns.

Catches every exception and returns it as a chat message, since an unhandled
error in a Gradio handler surfaces as a silent failure in the browser.

Formats the trace into markdown for the sidebar panel, truncating each result
to 800 chars.

## `reindex()`

Calls `KnowledgeBase.build()` and returns a status string. Wired to the sidebar
button — the mechanism that makes the knowledge base editable at runtime.

## UI layout

`gr.Blocks` → chatbot + textbox + Send/Clear on the left, campaign ID + trace
panel + reindex on the right, examples underneath.

**Gradio 6 notes.** `Chatbot` no longer accepts `type` — the messages format
(`{"role", "content"}` dicts) is now the only one. `theme` moved from
`Blocks()` to `launch()`. `requirements.txt` pins `gradio>=6.0,<7.0`.

---

# check_setup.py

## `check(name, mark, detail)`

Records and prints one result. Marks are `  ok  `, ` FAIL `, ` warn `.

## `main()`

Six independent checks, in dependency order: Python version, packages, HF auth,
**tool calling**, SEOmonitor auth, retrieval. Returns 1 if any failed.

Testing each layer separately is the design. A single failure tells you which
layer to fix rather than leaving you reading a stack trace from inside an agent
loop.

The tool-calling check is the one nobody thinks to write. It sends a dummy
`get_weather` tool and asserts `tool_calls` comes back populated. Plenty of
models accept a `tools` parameter and ignore it — you get fluent answers full
of invented numbers with nothing signalling failure.

HTTP status codes are mapped to specific causes: 401 → token or permission,
402 → out of credits, 404 → model not served.

---

# eval_retrieval.py

## `EVAL_SET`

List of `(question, expected_source_substring)`. **Replace this when you
replace the documents** — the seed entries only test my sample content.

## `main()`

Runs every question through `KnowledgeBase.search`, computes recall@1 and
recall@5, prints misses with what was retrieved instead, and exits non-zero
below 85% recall@5 — so it works as a CI gate.

No LLM involved, so it's free and fast. Retrieval is where almost every wrong
answer originates, and no prompt tuning recovers a passage that was never
retrieved. The closing hint maps each failure mode to the specific lever:
nothing returned → lower `MIN_RELEVANCE`; wrong document → vague headings;
right document wrong chunk → smaller `CHUNK_CHARS`.

---

# flows/langflow_seomonitor_component.py

## `SEOMonitorComponent(Component)`

A Langflow custom component — paste it into Langflow and SEOmonitor becomes a
draggable canvas node.

`inputs`: api_key (secret), endpoint (dropdown over 5 paths), campaign_id,
query, limit, start_date, end_date. `campaign_id` and `query` have
`tool_mode=True`, which lets a Langflow Agent node call this component as a
tool — the same behaviour as `core/agent.py`, built by dragging.

**`fetch()`** — Looks up the path and its accepted parameters, filters the
inputs to only those the endpoint takes, GETs, and returns a `Data` object.
Sets `self.status` for the node's on-canvas readout. Returns errors as data
rather than raising, so the canvas shows a failed node instead of a broken
flow.

Deliberately self-contained rather than importing `connectors/seomonitor.py`,
so it can be pasted into a Langflow instance that has no access to this repo.
If you do put the repo on Langflow's `PYTHONPATH`, import the client instead
and keep one implementation.

---

# Where to change things

| Goal | Edit |
|---|---|
| Change what the bot knows | `knowledge_base/*.md`, then click Reindex |
| Bot invents policy | Raise `KB_MIN_RELEVANCE` |
| Bot claims ignorance too readily | Lower `KB_MIN_RELEVANCE`, run `eval_retrieval.py` |
| Add an SEO endpoint | Client method + `TOOL_SCHEMAS` entry + `Dispatcher` handler |
| Change tone or rules | `SYSTEM_PROMPT` in `core/agent.py` |
| Change which tool gets picked | The `description` fields in `TOOL_SCHEMAS` |
| Swap SEO provider | New class with the six client methods; nothing in `core/` changes |
| Swap the LLM | `HF_MODEL` in `.env` (must support tool calling) |
| Reduce token cost | `keep` in `compact_keywords`, history window in `respond` |
