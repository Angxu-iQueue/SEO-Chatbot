# SEO Analyst chatbot

A retrieval-grounded chatbot that answers from your own SEO playbooks and from
live SEOmonitor campaign data, built on Hugging Face models and deployable both
as code and as a canvas flow.

```
                   ┌─────────────────────────────────────┐
   Gradio UI ─────▶│  Agent loop (tool calling)          │
   (HF Space)      │  HF Inference Providers router      │
                   │  Qwen2.5-72B-Instruct               │
                   └──────────┬──────────────┬───────────┘
                              │              │
              ┌───────────────▼──┐        ┌──▼────────────────────┐
              │ Knowledge base   │        │ SEOmonitor API v3     │
              │ bge-small ─▶FAISS│        │ rate limit + TTL cache│
              │ bge-reranker     │        │ 6 endpoints as tools  │
              │ abstains if weak │        │ payload normalisation │
              └──────────────────┘        └───────────────────────┘
```

## How each requirement is met

**1. Knowledge-base specific.** Markdown under `knowledge_base/` is chunked on
heading boundaries, embedded with `BAAI/bge-small-en-v1.5`, indexed in FAISS,
then reranked with the `bge-reranker-base` cross-encoder. Passages scoring below
`KB_MIN_RELEVANCE` are dropped, and the retriever returns an explicit "nothing
relevant" signal — so the bot says it doesn't know instead of falling back to
generic SEO advice. Answers cite `file.md#heading`.

**2. SEOmonitor API.** `connectors/seomonitor.py` covers six confirmed v3
endpoints with a token-bucket limiter (8 rps against the documented 10 rps
ceiling), a 15-minute TTL cache, and exponential backoff on 429. Two
normalisation steps matter more than they look: SERP feature codes get expanded
to full names before the model sees them (it will otherwise invent a meaning for
`vdi`), and keyword payloads get flattened from ~40 fields to 13, which is the
difference between a good answer and a context-window full of nulls.

**3. Dynamic.** Three separate things:
- *Runtime tool selection* — no dialogue tree. The model reads the question,
  picks tools, reads results, decides whether to call again (up to
  `MAX_TOOL_ROUNDS`). "Why did visibility drop?" naturally becomes a trend call,
  then a keyword call, then a knowledge-base lookup for the diagnostic playbook.
- *Live data* — every campaign number comes from an API call in that turn. The
  system prompt forbids stating performance figures a tool didn't return.
- *Editable knowledge* — the Reindex button rebuilds FAISS in place. Edit a
  playbook, click, done. No redeploy.

**4. Hugging Face and canvas tools.** LLM via the HF Inference Providers router
(OpenAI-compatible, so the `openai` SDK works unchanged), embeddings and
reranking via `sentence-transformers` from the Hub, UI in Gradio, hosted as a
Space. For the canvas path, `flows/langflow_seomonitor_component.py` is a
drop-in Langflow custom component and `flows/README.md` gives the full node
graph for Langflow, Flowise and n8n.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # add HF_TOKEN and SEOMONITOR_API_KEY
python -c "from core.kb import KnowledgeBase; print(KnowledgeBase().build(), 'chunks')"
python app.py               # http://localhost:7860
```

The SEOmonitor token is in Account Settings → Edit Profile. It goes in the
`Authorization` header raw, with no `Bearer` prefix — a detail that costs
people an afternoon. Campaign IDs are in the platform URL:
`app.seomonitor.com/v2/72416/manage/...` → `72416`.

Without `SEOMONITOR_API_KEY` the app still runs in knowledge-base-only mode,
which is a useful way to develop retrieval before you have credentials.

## Deploying to a Hugging Face Space

1. Create a Space, SDK **Gradio**.
2. Push this directory. Gradio Spaces look for `app.py` and `requirements.txt`.
3. Settings → Variables and secrets: add `HF_TOKEN` and `SEOMONITOR_API_KEY`.
4. Set the Space to **private**. Client ranking data should not be on a public
   endpoint, and a public Space with your HF token in it is a billing incident
   waiting to happen.

The reranker adds ~15s to a cold start while it downloads. On the free CPU tier
retrieval runs about 1-2s per query; if that's too slow, drop
`RERANK_MODEL` and raise `KB_MIN_RELEVANCE` to compensate, or upgrade the
hardware tier.

## Adapting it

**Your knowledge base.** Replace the two seed files. They contain placeholder
thresholds written to show the shape of a useful entry — a bot confidently
quoting someone else's escalation rules is worse than no bot. Chunk quality
dominates answer quality, so prefer many short documents with real headings
over one long one.

**More endpoints.** Add a method to `SEOMonitorClient`, a schema to
`TOOL_SCHEMAS`, a handler to `Dispatcher`. Nothing else changes. Only endpoints
whose paths are confirmed against the docs are included; check
`api-docs.seomonitor.com` before adding, since the path prefixes vary by module
(`/rank-tracker/v3.0/`, `/research/v3.0/`, `/keyword-vault/v3.0/`).

**A different model.** Change `HF_MODEL`. It must support tool calling, and
you should confirm it is currently served: `GET /v1/models` on the router lists
everything warm, with per-provider pricing and context length. Suffix the model
id with `:cheapest`, `:fastest` or a provider name like `:groq` to control
routing.

## Worth knowing before you ship

- **Cost is in tokens, not calls.** SEOmonitor's API is unmetered on tracked
  campaigns; your inference bill is what scales. The payload compaction in
  `compact_keywords` is the main lever.
- **The daily quota is 10,000 requests.** An agent that chains four tools per
  turn burns it faster than you'd expect across a team. The cache is load-bearing.
- **Evaluate retrieval separately from generation.** Build 30 question/passage
  pairs from your playbooks and measure recall@5 before tuning any prompt.
  Almost every "the bot is wrong" report traces back to retrieval.
- **SEOmonitor ships an official MCP server** (`seomonitor.com/mcp`, beta). If
  you only need SEO data in Claude or ChatGPT with no custom knowledge base,
  that's a far shorter path than this. Build this when the knowledge base, the
  house voice, or the embedding in your own product is the point.
