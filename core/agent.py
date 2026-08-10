"""The agent loop.

Model access goes through Hugging Face Inference Providers, which exposes an
OpenAI-compatible endpoint at https://router.huggingface.co/v1. That means the
`openai` SDK works unchanged and you can swap models — or move to a model you
host yourself on Inference Endpoints — by editing one env var.

Pick a model with real tool-calling support, and confirm it is currently
served before relying on it — the warm model list changes:

    curl -s https://router.huggingface.co/v1/models \
      -H "Authorization: Bearer $HF_TOKEN" | jq -r '.data[].id'

Append a routing policy to the model id: `:fastest` (the default),
`:cheapest` (lowest price per output token), or a named provider like
`:groq`. `:cheapest` is the right default here — a tool-calling agent makes
several LLM round trips per question.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterator

from openai import OpenAI

from core.tools import TOOL_SCHEMAS, Dispatcher

log = logging.getLogger(__name__)

HF_BASE_URL = os.getenv("HF_BASE_URL", "https://router.huggingface.co/v1")
HF_MODEL = os.getenv("HF_MODEL", "openai/gpt-oss-120b:cheapest")
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "5"))

SYSTEM_PROMPT = """You are an SEO analyst assistant for an agency that runs its \
campaigns in SEOmonitor. Today is {today}.

You have two sources of truth and they are not interchangeable:

1. `search_knowledge_base` — our own methodology, definitions, playbooks and \
policies. This is authoritative for how *we* work.
2. The SEOmonitor tools — live campaign data. This is authoritative for what is \
*currently true* about a client's rankings.

Rules:
- Never answer a question about our process, thresholds or definitions from \
general SEO knowledge. Search the knowledge base. If it returns nothing \
relevant, say the knowledge base doesn't cover it and offer what you know as \
clearly-labelled general context.
- Never state a number about a client's performance unless a tool returned it. \
No estimating, no remembering across sessions.
- If you don't have a campaign_id, call `list_campaigns` before anything else. \
Don't guess IDs.
- Chain tools when the question needs it. "Why did visibility drop?" usually \
means a visibility trend, then the keywords that moved, then whatever the \
knowledge base says about diagnosing drops.
- Cite knowledge-base passages by their source, like [seo-glossary.md#Visibility].
- Rank 100 means "not in the top 100", not "ranked 100th". Say so when it matters.
- Be direct. Lead with the answer, then the evidence. An agency lead reading \
this on their phone should get the point in the first sentence.
{campaign_hint}"""


@dataclass
class Turn:
    """One completed exchange, including what the agent did to get there."""

    answer: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    rounds: int = 0


class SEOAgent:
    def __init__(self, dispatcher: Dispatcher, model: str = HF_MODEL):
        token = os.environ.get("HF_TOKEN")
        if not token:
            raise ValueError("HF_TOKEN is not set — get one at huggingface.co/settings/tokens")
        self.client = OpenAI(base_url=HF_BASE_URL, api_key=token)
        self.dispatcher = dispatcher
        self.model = model

    def _system_message(self, campaign_id: int | None) -> dict[str, str]:
        hint = (
            f"\nThe user is currently looking at campaign_id={campaign_id}. "
            "Use it unless they name a different client."
            if campaign_id
            else ""
        )
        return {
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                today=date.today().isoformat(), campaign_hint=hint
            ),
        }

    def run(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        campaign_id: int | None = None,
    ) -> Turn:
        messages: list[dict[str, Any]] = [self._system_message(campaign_id)]
        messages.extend(history or [])
        messages.append({"role": "user", "content": question})

        trace: list[dict[str, Any]] = []

        for round_no in range(1, MAX_TOOL_ROUNDS + 1):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=1200,
            )
            message = response.choices[0].message

            if not message.tool_calls:
                return Turn(
                    answer=message.content or "", tool_calls=trace, rounds=round_no - 1
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                }
            )

            for call in message.tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                log.info("round %d: %s(%s)", round_no, call.function.name, args)
                result = self.dispatcher.run(call.function.name, args)
                trace.append(
                    {"tool": call.function.name, "arguments": args, "result": result[:800]}
                )
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": result}
                )

        # Out of rounds. Ask for a best-effort answer from what we gathered
        # rather than returning nothing.
        messages.append(
            {
                "role": "user",
                "content": "Answer now with what you have. Note explicitly if "
                "anything is still missing.",
            }
        )
        final = self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=0.2, max_tokens=1200
        )
        return Turn(
            answer=final.choices[0].message.content or "",
            tool_calls=trace,
            rounds=MAX_TOOL_ROUNDS,
        )
