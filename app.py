
from __future__ import annotations

import logging
import os

import gradio as gr
from dotenv import load_dotenv

load_dotenv()

from connectors.seomonitor import SEOMonitorClient  
from core.agent import SEOAgent  
from core.kb import KnowledgeBase  
from core.tools import Dispatcher  


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("app")

kb = KnowledgeBase()
kb.load()

USE_MOCK = os.getenv("USE_MOCK_SEO", "").lower() in ("1", "true", "yes")

if USE_MOCK:
    from connectors.mock_seomonitor import MockSEOMonitorClient

    seomonitor, MODE = MockSEOMonitorClient(), "mock"
    log.warning("USE_MOCK_SEO is on — SEO figures are fabricated sample data")
else:
    try:
        seomonitor, MODE = SEOMonitorClient(), "live"
    except ValueError:
        log.warning("SEOMONITOR_API_KEY not set — running knowledge-base only")
        seomonitor, MODE = None, "kb-only"

agent = SEOAgent(Dispatcher(kb, seomonitor))

STATUS = {
    "live": "Knowledge base and live SEOmonitor data connected.",
    "mock": "⚠️ **Demo mode.** Knowledge base is real; all campaign figures are "
            "fabricated sample data. Unset `USE_MOCK_SEO` to connect a real account.",
    "kb-only": "Knowledge base only. Set SEOMONITOR_API_KEY for live campaign data.",
}[MODE]


def respond(message: str, history: list[dict], campaign_id: str):
    """history arrives in messages format: [{'role': ..., 'content': ...}]."""
    if not message.strip():
        return "", history, ""

    cid = int(campaign_id) if campaign_id.strip().isdigit() else None
    prior = [m for m in history if m.get("role") in ("user", "assistant")][-8:]

    try:
        turn = agent.run(message, history=prior, campaign_id=cid)
        answer, trace = turn.answer, turn.tool_calls
    except Exception as exc: 
        log.exception("turn failed")
        answer = f"That request failed: {type(exc).__name__}: {exc}"
        trace = []

    if trace:
        lines = [
            f"**{i}. `{t['tool']}`** — `{t['arguments']}`\n\n```json\n{t['result']}\n```"
            for i, t in enumerate(trace, 1)
        ]
        trace_md = "\n\n".join(lines)
    else:
        trace_md = "_Answered without calling a tool._"

    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": answer},
    ]
    return "", history, trace_md


def reindex() -> str:
    try:
        count = kb.build()
        return f"Reindexed {count} chunks."
    except Exception as exc: 
        return f"Reindex failed: {exc}"


with gr.Blocks(title="SEO Analyst") as demo:
    gr.Markdown("## SEO Analyst\nGrounded in our playbooks and live SEOmonitor data.")
    gr.Markdown(STATUS)

    with gr.Row():
        with gr.Column(scale=3):
            chat = gr.Chatbot(height=520, show_label=False)
            box = gr.Textbox(
                placeholder="Which keywords lost the most traffic this month?",
                show_label=False,
                autofocus=True,
            )
            with gr.Row():
                send = gr.Button("Send", variant="primary")
                clear = gr.Button("Clear")

        with gr.Column(scale=1):
            campaign = gr.Textbox(
                label="Campaign ID",
                placeholder="e.g. 72416",
                info="Leave empty and the bot will look it up.",
            )
            gr.Markdown("**Tool calls**")
            trace_view = gr.Markdown(value="_No tools called yet._")
            gr.Markdown("---")
            reindex_btn = gr.Button("Reindex knowledge base")
            reindex_status = gr.Markdown()

    gr.Examples(
        examples=[
            "What does SEO Opportunity score mean in our reporting?",
            "Which tracked keywords dropped out of the top 10 in the last 30 days?",
            "Compare our visibility to competitor.com and tell me where the gaps are",
            "Visibility fell last week — walk me through what happened",
        ],
        inputs=box,
    )

    for trigger in (box.submit, send.click):
        trigger(respond, [box, chat, campaign], [box, chat, trace_view])
    clear.click(lambda: ([], "_No tools called yet._"), None, [chat, trace_view])
    reindex_btn.click(reindex, None, reindex_status)


if __name__ == "__main__":
    auth = None
    if os.getenv("APP_USER") and os.getenv("APP_PASSWORD"):
        auth = (os.environ["APP_USER"], os.environ["APP_PASSWORD"])
        log.info("password auth enabled")
    else:
        log.warning("no APP_USER/APP_PASSWORD set — the app is unauthenticated")

    demo.launch(
        server_name=os.getenv("HOST", "127.0.0.1"),
        server_port=int(os.getenv("PORT", "7860")),
        theme=gr.themes.Soft(),
        auth=auth,
    )
