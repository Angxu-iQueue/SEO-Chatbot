"""Preflight check. Run this before app.py, and again whenever something breaks.

    python check_setup.py

It tests each layer on its own — Python, packages, HF token, SEOmonitor token,
knowledge base — so a failure tells you which one to fix instead of leaving you
guessing at a stack trace from the middle of an agent loop.
"""

from __future__ import annotations

import os
import sys

PASS, FAIL, WARN = "  ok  ", " FAIL ", " warn "
results: list[tuple[str, str, str]] = []


def check(name: str, mark: str, detail: str = "") -> None:
    results.append((mark, name, detail))
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    # 1. Python -----------------------------------------------------------
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        check("Python version", FAIL, f"{major}.{minor} — need 3.10+")
        return 1
    elif (major, minor) >= (3, 14):
        check("Python version", WARN, f"{major}.{minor} — faiss/torch wheels may lag")
    else:
        check("Python version", PASS, f"{major}.{minor}")

    # 2. Packages ---------------------------------------------------------
    for module, label in [
        ("gradio", "gradio"),
        ("openai", "openai"),
        ("requests", "requests"),
        ("sentence_transformers", "sentence-transformers"),
        ("faiss", "faiss-cpu"),
    ]:
        try:
            __import__(module)
            check(f"package {label}", PASS)
        except ImportError as exc:
            check(f"package {label}", FAIL, str(exc))
            return 1

    # 3. Hugging Face -----------------------------------------------------
    import requests

    hf_token = os.getenv("HF_TOKEN", "")
    model = os.getenv("HF_MODEL", "openai/gpt-oss-120b:cheapest")
    if not hf_token:
        check("HF_TOKEN", FAIL, "not set")
    else:
        try:
            r = requests.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers={"Authorization": f"Bearer {hf_token}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "reply with the word ok"}],
                    "max_tokens": 5,
                },
                timeout=45,
            )
            if r.status_code == 200:
                check("HF inference", PASS, f"{model} responded")
            elif r.status_code == 401:
                check("HF inference", FAIL, "401 — token invalid or missing the "
                      "'Make calls to Inference Providers' permission")
            elif r.status_code == 402:
                check("HF inference", FAIL, "402 — out of Inference Provider credits")
            elif r.status_code == 404:
                check("HF inference", FAIL, f"404 — '{model}' is not served. "
                      "List warm models: GET https://router.huggingface.co/v1/models")
            else:
                check("HF inference", FAIL, f"{r.status_code}: {r.text[:120]}")
        except Exception as exc:  # noqa: BLE001
            check("HF inference", FAIL, f"{type(exc).__name__}: {exc}")

    # 4. Tool calling -----------------------------------------------------
    if hf_token:
        try:
            r = requests.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers={"Authorization": f"Bearer {hf_token}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "What is the weather in Oslo?"}],
                    "tools": [{
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "description": "Current weather for a city",
                            "parameters": {
                                "type": "object",
                                "properties": {"city": {"type": "string"}},
                                "required": ["city"],
                            },
                        },
                    }],
                    "tool_choice": "auto",
                    "max_tokens": 100,
                },
                timeout=45,
            )
            called = bool(
                r.status_code == 200
                and r.json()["choices"][0]["message"].get("tool_calls")
            )
            check("tool calling", PASS if called else FAIL,
                  "model emitted a tool call" if called
                  else "model did not call the tool — pick a different HF_MODEL")
        except Exception as exc:  # noqa: BLE001
            check("tool calling", FAIL, f"{type(exc).__name__}: {exc}")

    # 5. SEOmonitor -------------------------------------------------------
    seo_token = os.getenv("SEOMONITOR_API_KEY", "")
    if not seo_token:
        check("SEOMONITOR_API_KEY", WARN, "not set — knowledge-base-only mode")
    else:
        try:
            r = requests.get(
                "https://apigw.seomonitor.com/v3/dashboard/v3.0/campaigns/tracked",
                headers={"Authorization": seo_token, "Accept": "application/json"},
                timeout=30,
            )
            if r.status_code == 200:
                data = r.json()
                rows = data if isinstance(data, list) else [data]
                ids = [
                    (c.get("campaign_info") or {}).get("id")
                    for c in rows
                    if isinstance(c, dict)
                ]
                check("SEOmonitor", PASS, f"{len(rows)} campaign(s): {ids[:5]}")
            elif r.status_code == 401:
                check("SEOmonitor", FAIL, "401 — token wrong. Send it raw, no 'Bearer'")
            elif r.status_code == 403:
                check("SEOmonitor", FAIL, "403 — token has no access to this data")
            else:
                check("SEOmonitor", FAIL, f"{r.status_code}: {r.text[:120]}")
        except Exception as exc:  # noqa: BLE001
            check("SEOmonitor", FAIL, f"{type(exc).__name__}: {exc}")

    # 6. Knowledge base ---------------------------------------------------
    try:
        from core.kb import KnowledgeBase

        kb = KnowledgeBase()
        kb.load()
        hits = kb.search("what does a rank of 100 mean", k=3)
        if hits:
            check("knowledge base", PASS,
                  f"top hit {hits[0]['source']} @ {hits[0]['score']}")
        else:
            check("knowledge base", WARN,
                  "index built but nothing matched the smoke-test query — "
                  "expected if you replaced the seed documents")
    except Exception as exc:  # noqa: BLE001
        check("knowledge base", FAIL, f"{type(exc).__name__}: {exc}")

    failures = sum(1 for mark, _, _ in results if mark == FAIL)
    print("\n" + ("All checks passed. Run: python app.py"
                  if not failures else f"{failures} check(s) failed — fix these first."))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
