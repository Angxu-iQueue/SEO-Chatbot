# Building this on a canvas

The Python app and the canvas build are two front doors to the same
architecture. Use the canvas when non-engineers need to change prompts and
routing; use the repo when you need version control, tests and CI.

A note on exported flow JSON: Langflow and Flowise both embed version-specific
node schemas, so a file written by hand against one version silently fails to
import on another. The node graph below is stable; build it once in your own
version and export from there.

## Langflow

Node graph:

```
Chat Input ─────────────┐
                        ▼
File ──▶ Split Text ──▶ Astra/Chroma ◀── HuggingFace Embeddings
                        │                 (BAAI/bge-small-en-v1.5)
                        ▼
                    Retriever ──┐
                                ├──▶ Agent ──▶ Chat Output
        SEOmonitor (custom) ────┘     │
                                      └── Model: HuggingFace / OpenAI-compatible
                                          base_url https://router.huggingface.co/v1
```

Steps:

1. **Embeddings** — add a *Hugging Face Embeddings* node, set the model to
   `BAAI/bge-small-en-v1.5`. It runs locally, no inference credits burned on
   indexing.
2. **Vector store** — *Chroma* is the least friction for local work; swap for
   Astra DB or Qdrant in production. Wire *File* → *Split Text* (chunk 1200,
   overlap 180) → vector store.
3. **SEOmonitor node** — paste `langflow_seomonitor_component.py` into a new
   Custom Component. Toggle Tool Mode on `campaign_id` and `query`.
4. **Agent** — add an *Agent* node, connect both the retriever and the
   SEOmonitor component to its Tools port. Paste the system prompt from
   `core/agent.py` into its instructions field.
5. **Model** — point the model node at `https://router.huggingface.co/v1` with
   your `HF_TOKEN`. Any tool-calling model works;
   `Qwen/Qwen2.5-72B-Instruct` is a good default.

Langflow exposes every flow as a REST endpoint, so the Gradio app in this repo
can call a Langflow flow instead of `SEOAgent` if you want the canvas to own
the orchestration. That is a one-function change in `app.py`.

## Flowise

Same shape, different node names: *Conversational Retrieval QA Chain* won't do
what you need here because it can't call APIs. Use *Tool Agent* instead, with:

- *HuggingFace Inference Embeddings* → *In-Memory Vector Store* → *Retriever Tool*
- *Custom Tool* wrapping the SEOmonitor calls (Flowise custom tools are
  JavaScript; port the `fetch` method above)
- *ChatOpenAI Custom* pointed at the Hugging Face router base URL

## n8n

n8n suits scheduled monitoring better than chat. The high-value flow:

```
Schedule (daily 07:00)
  → HTTP Request: GET /rank-tracker/v3.0/keywords
  → Code: filter keywords whose trend breaches the escalation thresholds
  → IF any breached
      → Basic LLM Chain (HF router): write the alert in the house voice
      → Slack: post to #seo-alerts
```

This is the piece a chat interface can't do — nobody is going to ask the bot
"did anything break overnight" every morning. Run both: n8n pushes, the chatbot
pulls.

## Which to reach for

| Need | Use |
| --- | --- |
| Non-engineers editing prompts and routing | Langflow / Flowise |
| Scheduled alerts, no human in the loop | n8n |
| Tests, code review, CI, custom retrieval | this repo |
| Fastest possible demo to a client | Langflow, then export |
