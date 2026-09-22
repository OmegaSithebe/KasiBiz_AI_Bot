"""Day 11 - the retrieval half of RAG.

Day 10 put the documents into ChromaDB. This file takes a shop owner's question
and pulls back the passages that answer it, packaged so the language model can
be told: "answer using ONLY this, and say where it came from."

    question -> embed -> nearest chunks -> filter weak matches -> context + sources

The filtering step matters more than it looks. If nothing in the knowledge base
is close enough to the question, the honest answer is "I do not have that in my
guides" - not a confident invention.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.rag.vector_store import KasiBizVectorStore, SearchResult

# Below this similarity a passage is treated as unrelated to the question.
#
# THIS NUMBER IS TUNED TO THE EMBEDDER AND MUST BE RE-CHECKED IF IT CHANGES.
# Measured with LocalEmbedder against the KasiBiz guides:
#   "How do I register a company with CIPC?" -> 0.51  (relevant)
#   "What records must I keep for SARS?"     -> 0.33  (relevant)
#   "What is the capital city of Japan?"     -> 0.22  (NOT relevant, but scores
#                                                     above zero on shared words
#                                                     like "what is the")
#   "Who won the rugby world cup?"           -> 0.08  (not relevant)
# 0.25 sits in the gap. OpenAI embeddings separate these far more cleanly, so
# this floor is conservative rather than risky.
MIN_RELEVANCE = 0.25
TOP_K = 4
MAX_CONTEXT_CHARS = 4000


@dataclass
class RetrievedContext:
    """Everything the model is allowed to use, plus where it came from."""

    query: str
    results: list[SearchResult] = field(default_factory=list)

    @property
    def has_context(self) -> bool:
        return bool(self.results)

    @property
    def best_score(self) -> float:
        return self.results[0].score if self.results else 0.0

    @property
    def sources(self) -> list[str]:
        seen: list[str] = []
        for result in self.results:
            citation = result.as_citation()
            if citation not in seen:
                seen.append(citation)
        return seen

    def as_prompt_context(self, max_chars: int = MAX_CONTEXT_CHARS) -> str:
        """The passages, numbered and labelled so the model can cite them."""
        blocks: list[str] = []
        used = 0

        for index, result in enumerate(self.results, start=1):
            block = (
                f"[{index}] Source: {result.title} "
                f"(file: {result.source}, topic: {result.category})\n"
                f"{result.text.strip()}"
            )
            if used + len(block) > max_chars:
                break
            blocks.append(block)
            used += len(block)

        return "\n\n".join(blocks)

    def as_citation_line(self) -> str:
        if not self.sources:
            return ""
        return "Source: " + "; ".join(self.sources)


class KnowledgeRetriever:
    """Finds the passages that answer a question, and refuses to guess."""

    def __init__(
        self,
        store: KasiBizVectorStore | None = None,
        top_k: int = TOP_K,
        min_relevance: float = MIN_RELEVANCE,
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k must be at least 1.")
        self.store = store or KasiBizVectorStore()
        self.top_k = top_k
        self.min_relevance = min_relevance

    @property
    def is_ready(self) -> bool:
        """False when the knowledge base has never been built."""
        return self.store.count() > 0

    def retrieve(self, question: str, category: str | None = None) -> RetrievedContext:
        if not question.strip():
            raise ValueError("Question cannot be empty.")
        if not self.is_ready:
            return RetrievedContext(query=question, results=[])

        # Over-fetch, then keep only what is actually relevant.
        found = self.store.search(question, k=self.top_k * 2, category=category)
        relevant = [r for r in found if r.score >= self.min_relevance][:self.top_k]
        return RetrievedContext(query=question, results=relevant)

    def topics(self) -> list[str]:
        """The categories the knowledge base can speak to."""
        if not self.is_ready:
            return []
        stored = self.store._collection.get(include=["metadatas"])
        return sorted({str(m.get("category", "general")) for m in stored["metadatas"]})
