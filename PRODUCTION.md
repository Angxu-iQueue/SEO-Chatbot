# Going to git, and going to production

These are two different bars. You can clear the first today. The second has two
blockers that no amount of code will fix.

---

# Part 1 — Git ready (30 minutes)

## 1. Confirm no secrets are staged

Do this before `git init`, not after. A committed token lives in history
forever, and a `git revert` does not remove it — you'd have to rewrite history
and rotate the token anyway.

```powershell
git init
git add -A
git status --short | Select-String "\.env$"
```

**That must return nothing.** If `.env` appears, stop and check `.gitignore`
contains a bare `.env` line. Then:

```powershell
git rm --cached .env
```

Sanity-check for pasted credentials anywhere else:

```powershell
git diff --cached | Select-String "hf_[A-Za-z0-9]{30,}|eyJ[A-Za-z0-9_-]{40,}"
```

Also nothing. The CI workflow runs this same scan on every push.

## 2. Commit

```powershell
git commit -m "SEO analyst chatbot: RAG over playbooks + SEOmonitor tools"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

## 3. What's already handled

- `.gitignore` covers `.env`, `.venv/`, `.kb_index/`, `__pycache__/`
- `.github/workflows/ci.yml` runs tests, the retrieval gate, and a secret scan
- `tests/` — 26 tests, no network or credentials needed, so forks can run CI
- `requirements.txt` pins gradio to `>=6.0,<7.0`

## 4. Before you invite collaborators

**Pin your dependencies.** The ranges in `requirements.txt` are fine for
development and dangerous for reproducibility — a Gradio 6 release already
broke this project once mid-build.

```powershell
pip freeze > requirements.lock
```

Commit both. Install from `requirements.txt` locally, from `requirements.lock`
in deployment.

**Add a LICENSE.** Without one, nobody can legally use your code — GitHub's
default is all-rights-reserved. MIT if you want it usable, none if it's internal
and private.

**Decide about the knowledge base.** `knowledge_base/*.md` will contain your
agency's methodology and client context. That is commercially sensitive and it
is not obvious to a future collaborator that it shouldn't be in a public repo.
Either keep the repo private, or gitignore `knowledge_base/` and distribute it
separately.

---

# Part 2 — Production ready

## Two blockers

**Blocker 1: the knowledge base is placeholder content.**

I wrote `seo-glossary.md` and `playbooks.md` to demonstrate the *shape* of
useful entries. Every threshold in them is invented — the 5-point escalation
rule, the opportunity-score cutoff, the rank targets by intent. None of it came
from your team.

Shipping this means a bot that confidently quotes fabricated policy in your
house voice. That is worse than no bot, because a confident answer that sounds
like it came from your own wiki does not get double-checked.

This is not a code change. It is a day or two of writing, and it is the actual
project.

**Blocker 2: you are running on fabricated data.**

`USE_MOCK_SEO=true` means every campaign figure is invented. Fine for
development and demos; catastrophic if it reaches someone who thinks the
numbers are real.

Two mitigations are already in place: the UI shows a Demo mode banner, and every
mock response carries `"_mock": true`. Neither survives a screenshot. Before any
non-technical person sees this, either connect a real data source or make the
banner impossible to miss.

Options if SEOmonitor stays unavailable: Google Search Console API is free and
official but needs a verified site you own; SerpApi has a small free tier;
DataForSEO is cheapest per query but requires a $50 minimum top-up. Any of them
means writing one class with the same six methods — nothing in `core/` changes.

## Once those are cleared

**Security**

- [ ] Set `APP_USER` and `APP_PASSWORD`. The app logs a warning when
      unauthenticated. The bot reads client data and spends your credits.
- [ ] Keep the Hugging Face Space **private**.
- [ ] Secrets go in the Space's *secrets*, never *variables* — variables are
      visible to anyone who can view the Space.
- [ ] Rotate both tokens once, now that they have been pasted into terminals
      and screenshots during setup.
- [ ] `HOST` defaults to `127.0.0.1`. Only set `0.0.0.0` where you intend
      network exposure (Spaces needs it).

**Cost control**

- [ ] Set a spend limit on your Hugging Face billing page. A retry loop against
      a 120B model is an expensive bug.
- [ ] Watch `usage.estimated_cost` for a week of real questions, then decide
      whether a smaller model handles most turns.
- [ ] `MAX_TOOL_ROUNDS=5` caps the worst case per question. Lower it if your
      logs show rounds 4 and 5 rarely adding anything.
- [ ] Raise `SEOMONITOR_CACHE_TTL` before you raise anything else — the daily
      quota is 10,000 requests and the cache is what keeps you inside it.

**Quality**

- [ ] Rewrite `EVAL_SET` in `eval_retrieval.py` with 25-30 real questions.
      Target recall@5 ≥ 0.85. CI enforces it.
- [ ] Run the abstention test after every knowledge-base change: ask something
      you deliberately did not document and confirm it says so.
- [ ] Add each wrong answer to `EVAL_SET` as a regression case.

**Observability**

- [ ] Log the tool trace, not just the answer. When someone reports a bad
      answer, the trace tells you whether retrieval or reasoning failed.
- [ ] Log `usage` per turn to track cost per question.
- [ ] Consider persisting conversations — but check your client agreements
      first, since prompts will contain their commercial data.

**Operations**

- [ ] Space storage is ephemeral; the index rebuilds on restart. Fine now, a
      problem past a few hundred documents — move to a hosted vector store then.
- [ ] Pick an owner for the knowledge base. Content rots faster than code, and
      a stale playbook is indistinguishable from a current one to the model.
- [ ] Add the n8n alerting flow from `flows/README.md`. Nobody opens a chatbot
      at 7am to ask whether anything broke overnight.

---

# Honest assessment

The engineering is in reasonable shape: tested, CI-gated, layered so components
swap cleanly, with the failure modes handled — abstention when retrieval is
weak, tool errors returned as data the model can recover from, a round cap
against runaway loops.

What is not ready is the content. Both remaining blockers are about the
knowledge base and the data source, and neither is a coding problem. That is
the normal shape of a RAG project: the code is the easy half, and the value
lives entirely in documents someone has to sit down and write.
