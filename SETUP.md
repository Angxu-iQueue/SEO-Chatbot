# Setup, start to finish

Eleven steps in four phases. Each ends with a check that either passes or tells
you exactly what's wrong. Don't skip the checks — this system has five
independent failure surfaces (Python env, HF auth, HF billing, SEOmonitor auth,
retrieval quality), and debugging them from a single stack trace in the middle
of an agent loop is miserable.

Realistic time: about 2 hours to a working local bot if you have both accounts
already, plus **a day or two of writing** for the knowledge base. Step 6 is the
one that determines whether this is useful or a toy. Everything else is plumbing.

---

# Phase 1 — Accounts and keys (~30 min)

## Step 1. Check your Python

```bash
python3 --version
```

Need **3.10 or newer**. Use 3.11 or 3.12 if you have a choice — `faiss-cpu` and
`torch` wheels lag on the newest release, and on 3.14 you may end up compiling
from source for an afternoon.

Windows: use WSL2. `faiss-cpu` on native Windows is a fight you don't need.

## Step 2. Hugging Face token

1. Sign up at [huggingface.co/join](https://huggingface.co/join).
2. Create a **fine-grained** token with the **Make calls to Inference
   Providers** permission. Direct link, pre-filled:
   [huggingface.co/settings/tokens/new?ownUserPermissions=inference.serverless.write&tokenType=fineGrained](https://huggingface.co/settings/tokens/new?ownUserPermissions=inference.serverless.write&tokenType=fineGrained)
3. Copy it now. You cannot view it again.

**Read this before you budget anything.** Inference Providers is a paid
product. Included monthly credits: **under $0.10 on Free, $2.00 on PRO**
($9/month), $2.00 per seat on Enterprise. Pay-as-you-go past that is available
to PRO and Enterprise only — on Free you're simply blocked when the credit runs
out.

A tool-calling agent makes three to six LLM round trips per question, each
carrying the system prompt plus accumulated tool output. **The free tier is
enough to confirm the pipeline works and not much more.** Plan on PRO plus PAYG
for anything a team touches. This is the number that surprises people at the
demo, not at the planning meeting.

```bash
export HF_TOKEN=hf_xxxxx

curl -s https://router.huggingface.co/v1/chat/completions \
  -H "Authorization: Bearer $HF_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"model":"openai/gpt-oss-120b:cheapest",
       "messages":[{"role":"user","content":"say ok"}],
       "max_tokens":5}'
```

✅ JSON with a `choices` array.
❌ `401` — token is wrong, or missing the Inference Providers permission.
❌ `402` — out of credits.
❌ `404` — that model isn't currently served. List what is:

```bash
curl -s https://router.huggingface.co/v1/models \
  -H "Authorization: Bearer $HF_TOKEN" | python3 -m json.tool | grep '"id"'
```

The warm model list changes. Suffix any model id with `:cheapest` (lowest price
per output token), `:fastest` (default), or a provider name like `:groq`. Given
how many round trips an agent makes, `:cheapest` is the right default here.

## Step 3. SEOmonitor token and campaign ID

You need an SEOmonitor account with at least one **Tracked Campaign** — API
access is scoped to those. No account? Skip to Step 4; everything runs in
knowledge-base-only mode and you can wire up live data later.

1. Log in at [app.seomonitor.com](https://app.seomonitor.com).
2. **Account Settings → Edit Profile → API Token.** Copy it.
   Careful with "Regenerate" — it instantly invalidates the old token, and if a
   colleague's script is using it, you've just broken their morning.
3. Get a campaign ID from the platform URL. Open a campaign; the URL reads
   `app.seomonitor.com/v2/72416/manage/strategy/...` → the ID is `72416`.

```bash
export SEO_TOKEN=eyJ0eXAi...

curl -s "https://apigw.seomonitor.com/v3/dashboard/v3.0/campaigns/tracked" \
  -H "Authorization: $SEO_TOKEN" -H "Accept: application/json"
```

✅ JSON with `campaign_info`, and the IDs you need are in it.
❌ `401` — almost always the `Bearer` prefix. **SEOmonitor takes the raw
token.** Note this differs from Hugging Face in the step above, which does want
`Bearer`. Getting these backwards is the single most common setup failure here.
❌ `403` — the token works but has no access to that data.

---

# Phase 2 — Local install (~20 min)

## Step 4. Environment and dependencies

```bash
cd seo-chatbot
python3 -m venv .venv

# macOS / Linux / WSL:
source .venv/bin/activate
# Git Bash on Windows — note Scripts, not bin:
# source .venv/Scripts/activate

pip install --upgrade pip
pip install -r requirements.txt
```

Your prompt should now start with `(.venv)`. If it doesn't, activation
silently failed and pip will install into your system Python instead. Verify
before installing anything:

```bash
which python     # must point inside .venv
```

This pulls torch as a transitive dependency of sentence-transformers: roughly
2 GB and several minutes. Expected, not stuck.

Apple Silicon: if `faiss-cpu` fails to build, `conda install -c pytorch faiss-cpu`
instead. It's the one dependency without reliable universal wheels.

## Step 5. Configuration

```bash
cp .env.example .env
```

Fill in `HF_TOKEN` and `SEOMONITOR_API_KEY`. Leave the rest at defaults for now.

`.env` is gitignored. Keep it that way — a leaked HF token is someone else's
inference bill, and a leaked SEOmonitor token is your clients' commercial data.

---

# Phase 3 — Make it yours (this is the real work)

## Step 6. Write the knowledge base

**Everything up to here is plumbing. This step decides whether the bot is
useful.** The seed files contain placeholder thresholds I invented to show the
shape of a good entry. Ship them unchanged and you have a bot confidently
quoting policy that is not yours.

Replace `knowledge_base/*.md` with what your team actually knows and can't get
from a Google search:

- How **you** define each metric, and which one you report to clients
- Your escalation thresholds, with the actual numbers
- Diagnostic sequences — the order a senior person checks things in
- Per-client context: their goals, their competitor set, their constraints
- The things you don't do, and why

What to leave out: anything the model already knows. "What is a meta
description" wastes a chunk and competes with your real content at retrieval
time. The value is entirely in the proprietary half.

Format rules that matter more than they look:

- **Descriptive headings.** Every heading is prepended to its chunk before
  embedding, so it carries a large share of the retrieval signal. `## Diagnosing
  a visibility drop` retrieves well; `## Process 4` does not.
- **Many short files beat one long file.** Split by topic.
- **One idea per section.** Sections split at ~1200 characters; an idea that
  straddles the boundary retrieves badly from either side.
- **Write answers, not references.** "Escalate above 5 points week-over-week" is
  retrievable. "See the escalation matrix in Confluence" is not.

Rough guide: 10-20 documents, 300-800 words each, is a solid v1.

## Step 7. Build the index

```bash
python -c "from core.kb import KnowledgeBase; print(KnowledgeBase().build(), 'chunks')"
```

First run downloads both models (~500 MB) and takes a few minutes. After that
it's seconds. ✅ A chunk count that roughly matches your document count × 2-4.

## Step 8. Preflight

```bash
python check_setup.py
```

Six checks: Python, packages, HF auth, **tool calling**, SEOmonitor auth,
retrieval. Fix anything marked FAIL before moving on.

The tool-calling check is the one people don't think to run. Plenty of models
accept a `tools` parameter and cheerfully ignore it — you get fluent answers
with invented numbers and no indication anything went wrong. If it fails,
change `HF_MODEL` and re-run.

## Step 9. Evaluate retrieval, before you touch a prompt

```bash
python eval_retrieval.py
```

Edit `EVAL_SET` first: 25-30 real questions your team asks, each paired with the
document that should answer it. Ten minutes of writing that buys you a
regression test for every future change.

**Target recall@5 ≥ 0.85.** Below that, stop and fix the documents. Nearly every
"the bot is wrong" report traces to retrieval, and no amount of prompt tuning
fixes a passage that was never retrieved. The script prints which lever to pull
for each failure mode.

---

# Phase 4 — Run and deploy

## Step 10. Run it

```bash
python app.py       # http://localhost:7860
```

Test in this order — each step isolates one more layer:

| # | Ask | Proves |
|---|-----|--------|
| 1 | "What does SEO Opportunity score mean in our reporting?" | Retrieval + citation. Answer should cite `file.md#heading` and match your document, not generic SEO advice. |
| 2 | "What's our policy on unicorn rankings?" | **Abstention.** It must say the knowledge base doesn't cover this. If it invents a policy, raise `KB_MIN_RELEVANCE` and re-test. |
| 3 | "List our tracked campaigns" | SEOmonitor auth from inside the app. |
| 4 | "Which keywords in campaign 72416 dropped out of the top 10?" | Tool call with real parameters. |
| 5 | "Visibility fell last week — walk me through what happened" | **Chaining.** The Tool calls panel should show 2+ calls: a trend, then keywords, then the playbook. One call means the model isn't chaining — check `MAX_TOOL_ROUNDS` and try a stronger model. |

Test 2 is the one to take seriously. A bot that abstains is useful; a bot that
invents plausible internal policy is worse than nothing, because nobody
double-checks a confident answer that sounds like it came from your own wiki.

Open the **Tool calls** panel on the right for every test. It shows exactly
which tools ran with which arguments — that's your debugger.

## Step 11. Deploy to a Hugging Face Space

1. [huggingface.co/new-space](https://huggingface.co/new-space) → SDK
   **Gradio** → **Private**. Private is not optional: client ranking data on a
   public endpoint is a client conversation you don't want, and a public Space
   is also a stranger spending your inference credits.

2. Prepend the Spaces frontmatter to `README.md`. Without it the Space won't
   boot, and the error message won't tell you why:

   ```yaml
   ---
   title: SEO Analyst
   emoji: 📈
   colorFrom: blue
   colorTo: indigo
   sdk: gradio
   sdk_version: 5.0.0
   app_file: app.py
   pinned: false
   ---
   ```

3. Push:

   ```bash
   git init && git add . && git commit -m "SEO analyst chatbot"
   git remote add origin https://huggingface.co/spaces/<you>/<space-name>
   git push origin main
   ```

   Confirm `.env` is not in `git status` before you push.

4. **Settings → Variables and secrets**: add `HF_TOKEN` and
   `SEOMONITOR_API_KEY` as *secrets*, not variables. Variables are visible to
   anyone who can see the Space.

5. Watch the build log. First boot takes ~5 minutes downloading models.

The free CPU tier works. Retrieval runs 1-2s per query, and the Space sleeps
after inactivity so the first request after a quiet period pays the model-load
cost again. If that's too slow: drop `RERANK_MODEL`, raise `KB_MIN_RELEVANCE`
to compensate, or upgrade the hardware tier.

Note the index rebuilds on every restart, since Space storage is ephemeral
without a paid persistent volume. Fine at this scale — it's a few seconds. If
your knowledge base grows past a few hundred documents, move to a hosted vector
store instead.

---

# Optional: the canvas build

Worth doing if non-engineers need to change prompts and routing without a pull
request. See `flows/README.md` for the full node graph.

```bash
pip install langflow
langflow run          # http://localhost:7860
```

Then: New Flow → New Custom Component → paste
`flows/langflow_seomonitor_component.py` → Save. SEOmonitor is now a node you
can drag onto any canvas. Wire it and a retriever into an Agent node's Tools
port, point the model node at `https://router.huggingface.co/v1`, and you have
the same behaviour built by dragging.

Run Langflow on a different port than the Gradio app — both default to 7860.

Separately, `flows/README.md` has an n8n workflow for scheduled alerts. That's
the piece chat can't do: nobody opens a chatbot at 7am to ask whether anything
broke overnight. Push and pull are different products; run both.

---

# When something breaks

| Symptom | Cause |
|---|---|
| `401` from SEOmonitor | You sent `Bearer <token>`. SEOmonitor wants it raw. |
| `401` from HF | You sent it raw. HF wants `Bearer <token>`. |
| `402` from HF | Out of Inference Provider credits. |
| `404` on the model | Not currently served. Check `GET /v1/models`. |
| Fluent answers, invented numbers | The model is ignoring `tools`. Run `check_setup.py` and change `HF_MODEL`. |
| "I don't have information on that" for things you documented | Retrieval miss. Run `eval_retrieval.py`; lower `KB_MIN_RELEVANCE` or improve headings. |
| Confident answers about undocumented policy | Threshold too low. Raise `KB_MIN_RELEVANCE` toward 0.4. |
| Bot ignores your edits | Index is stale. Click **Reindex knowledge base**. |
| `429` from SEOmonitor | Quota is 10k requests/day, 10/s. The cache is load-bearing; raise `SEOMONITOR_CACHE_TTL`. |
| Space won't start | Missing README frontmatter, or a secret set as a variable. |
| One tool call where you expect three | Model isn't chaining. Raise `MAX_TOOL_ROUNDS`, try a stronger model. |

---

# What to do once it works

**Get five people using it for two weeks and log every question.** Real usage
tells you which knowledge-base gaps and which endpoints actually matter. Both
lists will differ from what you'd predict.

Then, roughly in order of payoff:

1. Add the knowledge-base documents your logs show people needed.
2. Add SEOmonitor endpoints your logs show people asked for. Three edits each:
   a method on `SEOMonitorClient`, a schema in `TOOL_SCHEMAS`, a handler on
   `Dispatcher`. Verify the path against
   [api-docs.seomonitor.com](https://api-docs.seomonitor.com) — prefixes vary by
   module (`/rank-tracker/v3.0/`, `/research/v3.0/`, `/keyword-vault/v3.0/`).
3. Grow `EVAL_SET` with every question the bot got wrong. This is your
   regression suite.
4. Add the n8n alerting flow.
5. Watch the HF billing page for a week and decide whether a smaller model
   handles most turns.

One thing worth knowing before you invest heavily: SEOmonitor ships an official
**MCP server** (`seomonitor.com/mcp`, beta). If all you need is SEO data inside
Claude or ChatGPT, with no custom knowledge base and no house voice, that's a
far shorter path than this. Build this when the knowledge base, the tone, or
embedding it in your own product is the actual point.
