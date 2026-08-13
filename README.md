# SEO Analyst chatbot

A retrieval-grounded chatbot that answers from your own SEO playbooks and from
live SEOmonitor campaign data, built on Hugging Face models and deployable both
as code and as a canvas flow.

## What requirements are met

**1. Knowledge-base specific.**

**2. SEOmonitor API.** 

**3. Dynamic.** 

**4. Hugging Face and canvas tools.** 

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env    
python -c "from core.kb import KnowledgeBase; print(KnowledgeBase().build(), 'chunks')"
python app.py           
```

The SEOmonitor token is in Account Settings → Edit Profile. It goes in the
`Authorization` header raw, with no `Bearer`

Without `SEOMONITOR_API_KEY` the app still runs in knowledge-base-only mode,
which is a useful way to develop retrieval before you have credentials.

## Deploying to a Hugging Face Space

1. Create a Space, SDK **Gradio**.
2. Push this directory. Gradio Spaces look for `app.py` and `requirements.txt`.
3. Settings → Variables and secrets: add `HF_TOKEN` and `SEOMONITOR_API_KEY`.
4. Set the Space to **private**. Client ranking data should not be on a public
   endpoint, and a public Space with your HF token in it is a billing incident
   waiting to happen.

If it is too slow, drop
`RERANK_MODEL` and raise `KB_MIN_RELEVANCE` to compensate, or upgrade the
hardware tier.

## Adapting it

**Your knowledge base.** Replace the two seed files. They contain placeholder
thresholds written to show the shape of a useful entry — a bot confidently
quoting someone else's escalation rules is worse than no bot. Chunk quality
dominates answer quality, so prefer many short documents with real headings
over one long one.


**A different model.** Change `HF_MODEL`. It must support tool calling, and
you should confirm it is currently served: `GET /v1/models` on the router lists
everything warm, with per-provider pricing and context length. Suffix the model
id with `:cheapest`, `:fastest` or a provider name like `:groq` to control
routing.

## Worth knowing before you ship

- **Cost is in tokens, not calls.** 
- **The daily quota is 10,000 requests.** 
- **SEOmonitor ships an official MCP server** 