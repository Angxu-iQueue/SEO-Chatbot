
from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

from core.kb import KnowledgeBase 

EVAL_SET: list[tuple[str, str]] = [
    ("what does a rank of 100 mean", "seo-glossary"),
    ("how is visibility calculated", "seo-glossary"),
    ("is a negative rank trend good or bad", "seo-glossary"),
    ("what SEO opportunity score do we prioritise", "seo-glossary"),
    ("what does fsn stand for", "seo-glossary"),
    ("difference between brand and non-brand traffic", "seo-glossary"),
    ("rank target for informational keywords", "seo-glossary"),
    ("what does my_brand_present mean", "seo-glossary"),
    ("visibility dropped, what do I check first", "playbooks"),
    ("when do I escalate to the account lead", "playbooks"),
    ("how should a monthly client report be structured", "playbooks"),
    ("can I blame an algorithm update", "playbooks"),
    ("how do we choose keywords for a sprint", "playbooks"),
    ("should I lead a report with visibility", "playbooks"),
    ("what counts as a sustained drop", "playbooks"),
]


def main() -> int:
    kb = KnowledgeBase()
    kb.load()

    hits_at_1 = hits_at_5 = 0
    misses: list[tuple[str, str, list[str]]] = []

    for question, expected in EVAL_SET:
        results = kb.search(question, k=5)
        sources = [r["source"] for r in results]

        if sources and expected in sources[0]:
            hits_at_1 += 1
        if any(expected in s for s in sources):
            hits_at_5 += 1
        else:
            misses.append((question, expected, sources))

    total = len(EVAL_SET)
    print(f"\nrecall@1  {hits_at_1}/{total}  {hits_at_1 / total:.0%}")
    print(f"recall@5  {hits_at_5}/{total}  {hits_at_5 / total:.0%}")

    if misses:
        print(f"\n{len(misses)} miss(es):")
        for question, expected, got in misses:
            print(f"  ✗ {question}")
            print(f"    wanted {expected}, got {got or '[nothing above threshold]'}")

    print(
        "\nrecall@5 below 85%? The fix is in the documents, not the prompt:\n"
        "  - nothing returned at all      -> lower KB_MIN_RELEVANCE\n"
        "  - wrong document returned      -> headings are too vague; the heading\n"
        "                                    is prepended to every chunk, so it\n"
        "                                    carries a lot of the signal\n"
        "  - right document, wrong chunk  -> lower KB_CHUNK_CHARS, then rebuild"
    )
    return 0 if hits_at_5 / total >= 0.85 else 1


if __name__ == "__main__":
    sys.exit(main())
