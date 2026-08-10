"""Knowledge base: chunk -> embed (Hugging Face) -> FAISS -> rerank.

Two models, both from the Hub, both running locally in the Space:

  BAAI/bge-small-en-v1.5      384-dim bi-encoder, fast, indexes everything
  BAAI/bge-reranker-base      cross-encoder, slow, only rescores the top 20

The bi-encoder alone gets you roughly the right neighbourhood; the reranker is
what makes the difference between "a document about rankings" and "the document
that answers this question". Swap either for a bigger sibling (bge-base,
bge-large) by changing the env var — nothing else needs to move.

Rebuilding is cheap and idempotent, so `build()` is safe to call from a button
in the UI. That's what keeps the bot's knowledge editable without a redeploy.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

KB_DIR = Path(os.getenv("KB_DIR", "knowledge_base"))
INDEX_DIR = Path(os.getenv("KB_INDEX_DIR", ".kb_index"))
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-base")
CHUNK_CHARS = int(os.getenv("KB_CHUNK_CHARS", "1200"))
CHUNK_OVERLAP = int(os.getenv("KB_CHUNK_OVERLAP", "180"))
# Below this reranker score the bot says it doesn't know rather than guessing.
MIN_RELEVANCE = float(os.getenv("KB_MIN_RELEVANCE", "0.25"))


@dataclass
class Chunk:
    text: str
    source: str
    heading: str
    chunk_id: str

    def cite(self) -> str:
        return f"{self.source}#{self.heading}" if self.heading else self.source


def _split_markdown(text: str, source: str) -> list[Chunk]:
    """Split on headings first, then on size. Heading-aware splitting keeps a
    definition with its term instead of orphaning it across a boundary."""
    sections: list[tuple[str, str]] = []
    current_heading, buffer = "", []
    for line in text.splitlines():
        if re.match(r"^#{1,4}\s+", line):
            if buffer:
                sections.append((current_heading, "\n".join(buffer).strip()))
            current_heading = line.lstrip("#").strip()
            buffer = []
        else:
            buffer.append(line)
    if buffer:
        sections.append((current_heading, "\n".join(buffer).strip()))

    chunks: list[Chunk] = []
    for heading, body in sections:
        if not body:
            continue
        start = 0
        while start < len(body):
            piece = body[start : start + CHUNK_CHARS]
            payload = f"{heading}\n\n{piece}" if heading else piece
            chunks.append(
                Chunk(
                    text=payload,
                    source=source,
                    heading=heading,
                    chunk_id=hashlib.sha1(
                        f"{source}:{heading}:{start}".encode()
                    ).hexdigest()[:12],
                )
            )
            if start + CHUNK_CHARS >= len(body):
                break
            start += CHUNK_CHARS - CHUNK_OVERLAP
    return chunks


def _read_documents(kb_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(kb_dir.rglob("*")):
        if path.suffix.lower() not in {".md", ".txt", ".mdx"}:
            continue
        chunks.extend(_split_markdown(path.read_text(encoding="utf-8"), path.name))
    if not chunks:
        raise RuntimeError(f"No .md/.txt documents found under {kb_dir}")
    return chunks


class KnowledgeBase:
    def __init__(self, kb_dir: Path = KB_DIR, index_dir: Path = INDEX_DIR):
        self.kb_dir = Path(kb_dir)
        self.index_dir = Path(index_dir)
        self._encoder = None
        self._reranker = None
        self._index = None
        self._chunks: list[Chunk] = []

    # ------------------------------------------------------------ lazy models

    @property
    def encoder(self):
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer

            log.info("loading encoder %s", EMBED_MODEL)
            self._encoder = SentenceTransformer(EMBED_MODEL)
        return self._encoder

    @property
    def reranker(self):
        if self._reranker is None:
            from sentence_transformers import CrossEncoder

            log.info("loading reranker %s", RERANK_MODEL)
            self._reranker = CrossEncoder(RERANK_MODEL)
        return self._reranker

    # ----------------------------------------------------------------- build

    def build(self) -> int:
        """(Re)index everything under kb_dir. Returns the chunk count."""
        import faiss

        chunks = _read_documents(self.kb_dir)
        vectors = self.encoder.encode(
            [c.text for c in chunks],
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=False,
        ).astype("float32")

        # Normalised vectors + inner product == cosine similarity.
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)

        self.index_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(self.index_dir / "kb.faiss"))
        (self.index_dir / "chunks.json").write_text(
            json.dumps([c.__dict__ for c in chunks]), encoding="utf-8"
        )

        self._index, self._chunks = index, chunks
        log.info("indexed %d chunks from %s", len(chunks), self.kb_dir)
        return len(chunks)

    def load(self) -> None:
        import faiss

        index_path = self.index_dir / "kb.faiss"
        if not index_path.exists():
            self.build()
            return
        self._index = faiss.read_index(str(index_path))
        self._chunks = [
            Chunk(**d)
            for d in json.loads((self.index_dir / "chunks.json").read_text("utf-8"))
        ]

    # ---------------------------------------------------------------- search

    def search(self, query: str, k: int = 5, pool: int = 20) -> list[dict]:
        """Retrieve `pool` candidates by embedding, rerank, return the top `k`
        that clear MIN_RELEVANCE. An empty list is a valid, useful answer — it
        tells the agent to say it doesn't know."""
        if self._index is None:
            self.load()

        # bge models want this prefix on queries but not on documents.
        query_vec = self.encoder.encode(
            [f"Represent this sentence for searching relevant passages: {query}"],
            normalize_embeddings=True,
        ).astype("float32")

        _, ids = self._index.search(query_vec, min(pool, len(self._chunks)))
        candidates = [self._chunks[i] for i in ids[0] if i >= 0]
        if not candidates:
            return []

        scores = self.reranker.predict([(query, c.text) for c in candidates])
        ranked = sorted(zip(candidates, scores), key=lambda p: p[1], reverse=True)

        return [
            {"text": c.text, "source": c.cite(), "score": round(float(s), 3)}
            for c, s in ranked[:k]
            if float(s) >= MIN_RELEVANCE
        ]
