"""Day 10 - loading KasiBiz's business knowledge into a vector database.

This file does the INDEXING half of RAG (Retrieval-Augmented Generation). It is
run occasionally, offline, whenever the knowledge base changes:

    1. LOAD    read every document in rag/documents/
    2. CHUNK   split each one into ~800 character pieces, with overlap
    3. EMBED   turn each chunk into a list of numbers that captures its meaning
    4. STORE   save those numbers into ChromaDB on disk

The RETRIEVAL half - taking a shop owner's question and finding the right
chunks - is Day 11.

ChromaDB in local mode needs no API key, no account and no server. It is just a
folder on disk, named by CHROMA_DB_PATH in .env.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

from app.utils.config import PROJECT_ROOT, get_chroma_db_path

DOCUMENTS_ROOT = PROJECT_ROOT / "rag" / "documents"
COLLECTION_NAME = "kasibiz_knowledge"

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120

TEXT_SUFFIXES = {".md", ".txt", ".markdown"}
PDF_SUFFIXES = {".pdf"}
IGNORED_SUFFIXES = {".jpeg", ".jpg", ".png", ".gif", ".webp", ".docx", ".xlsx", ".zip"}


class VectorStoreError(RuntimeError):
    """Raised when the knowledge base cannot be built or queried."""


# ------------------------------------------------------------------ embedding
class Embedder(Protocol):
    """Anything that can turn text into vectors. Swappable so tests run offline."""

    name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    """Production embedder. Costs about 2 US cents per million tokens."""

    name = "openai:text-embedding-3-small"

    def __init__(self, model: str = "text-embedding-3-small", batch_size: int = 64) -> None:
        from app.utils.config import load_settings

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise VectorStoreError("The openai package is not installed.") from exc

        self.model = model
        self.batch_size = batch_size
        self.name = f"openai:{model}"
        self._client = OpenAI(api_key=load_settings().openai_api_key)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start:start + self.batch_size])
            response = self._client.embeddings.create(model=self.model, input=batch)
            vectors.extend(item.embedding for item in response.data)
        return vectors


# Words carrying no topic meaning. Without removing these, a short question like
# "How do I register with CIPC?" is dominated by "how do i with" and matches the
# wrong document entirely.
STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does for from get got had has
have he her him his how i if in into is it its me must my no not of on or our out
should so than that the their them then there these they this those to us was we
were what when where which who why will with would you your am are shall may might
about after all also any because before being between both during each few more
most other over same some such through under until up very
""".split())


class LocalEmbedder:
    """Offline word-based embedder used by the tests.

    It hashes each meaningful word into a fixed number of buckets. That gives
    real (if crude) similarity between texts sharing vocabulary, with no API
    key, no downloads and no cost - so the whole RAG layer stays testable.

    It is NOT a substitute for real embeddings: it matches words, not meaning,
    so it cannot tell that "company registration" and "starting a business" are
    the same idea. Production uses OpenAIEmbedder.
    """

    name = "local:bag-of-words"

    def __init__(self, dimensions: int = 512) -> None:
        self.dimensions = dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            if len(word) < 3 or word in STOPWORDS:
                continue
            digest = hashlib.md5(word.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimensions] += 1.0

        magnitude = sum(value * value for value in vector) ** 0.5
        return [value / magnitude for value in vector] if magnitude else vector


# ------------------------------------------------------------------ documents
@dataclass(frozen=True)
class Document:
    path: Path
    text: str
    category: str
    title: str

    @property
    def source(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    source: str
    category: str
    title: str
    chunk_index: int

    @property
    def metadata(self) -> dict[str, str | int]:
        return {
            "source": self.source,
            "category": self.category,
            "title": self.title,
            "chunk_index": self.chunk_index,
        }


@dataclass
class IngestReport:
    files_found: int = 0
    files_loaded: int = 0
    chunks_stored: int = 0
    embedder: str = ""
    loaded: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def files_skipped(self) -> int:
        return len(self.skipped)

    def as_text(self) -> str:
        lines = [
            f"Documents found:  {self.files_found}",
            f"Documents loaded: {self.files_loaded}",
            f"Documents skipped: {self.files_skipped}",
            f"Chunks stored:    {self.chunks_stored}",
            f"Embedder:         {self.embedder}",
        ]
        if self.skipped:
            lines += ["", "Skipped:"]
            lines += [f"  - {name}: {reason}" for name, reason in self.skipped]
        return "\n".join(lines)


def looks_like_questions_only(text: str) -> bool:
    """Detect files that list questions with no answers.

    Indexing these is worse than useless: RAG would retrieve a question and the
    model would present it to the shop owner as if it were a fact.

    A proper FAQ (Q: ... / A: ...) is the opposite - it is ideal RAG material -
    so an explicit answer marker always means the file is kept.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False

    questions = [line for line in lines if line.endswith("?")]
    if not questions:
        return False

    answers = [line for line in lines if re.match(r"^(a|ans|answer)\s*[:.\-]", line, re.I)]
    if len(answers) >= len(questions) / 2:
        return False

    return len(questions) / len(lines) > 0.6


def read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise VectorStoreError(
            "PDF found but pypdf is not installed. Run: pip install pypdf"
        ) from exc

    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)


def load_documents(root: Path = DOCUMENTS_ROOT) -> tuple[list[Document], list[tuple[str, str]]]:
    """Read every usable document under root. Returns (documents, skipped)."""
    if not root.exists():
        raise VectorStoreError(f"Knowledge base folder not found: {root}")

    documents: list[Document] = []
    skipped: list[tuple[str, str]] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        suffix = path.suffix.lower()
        category = path.parent.name if path.parent != root else "general"

        if suffix in IGNORED_SUFFIXES:
            skipped.append((path.name, f"not a text document ({suffix})"))
            continue

        if suffix in PDF_SUFFIXES:
            try:
                text = read_pdf(path)
            except VectorStoreError as exc:
                skipped.append((path.name, str(exc)))
                continue
        elif suffix in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="replace")
        else:
            skipped.append((path.name, f"unsupported file type ({suffix or 'no extension'})"))
            continue

        if not text.strip():
            skipped.append((path.name, "file is empty"))
            continue

        if looks_like_questions_only(text):
            skipped.append((
                path.name,
                "contains questions but no answers - indexing it would make the "
                "assistant quote questions back as facts",
            ))
            continue

        documents.append(Document(
            path=path,
            text=text,
            category=category,
            title=path.stem.replace("_", " ").title(),
        ))

    return documents, skipped


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping pieces, preferring paragraph boundaries.

    The overlap stops an idea being cut in half at a boundary and lost.
    """
    if size <= 0:
        raise ValueError("Chunk size must be positive.")
    if overlap < 0 or overlap >= size:
        raise ValueError("Overlap must be zero or more, and smaller than the chunk size.")

    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not cleaned:
        return []
    if len(cleaned) <= size:
        return [cleaned]

    paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > size:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(paragraph), size - overlap):
                piece = paragraph[start:start + size].strip()
                if piece:
                    chunks.append(piece)
            continue

        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= size:
            current = candidate
        else:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph

    if current:
        chunks.append(current)
    return chunks


def build_chunks(documents: Sequence[Document], size: int = CHUNK_SIZE,
                 overlap: int = CHUNK_OVERLAP) -> list[Chunk]:
    chunks: list[Chunk] = []
    for document in documents:
        for index, piece in enumerate(chunk_text(document.text, size, overlap)):
            chunks.append(Chunk(
                id=f"{document.category}/{document.source}#{index}",
                text=piece,
                source=document.source,
                category=document.category,
                title=document.title,
                chunk_index=index,
            ))
    return chunks


# --------------------------------------------------------------------- store
@dataclass(frozen=True)
class SearchResult:
    text: str
    source: str
    category: str
    title: str
    score: float

    def as_citation(self) -> str:
        return f"{self.title} ({self.category}/{self.source})"


class KasiBizVectorStore:
    """Thin wrapper around a local ChromaDB collection."""

    def __init__(
        self,
        path: str | Path | None = None,
        collection_name: str = COLLECTION_NAME,
        embedder: Embedder | None = None,
    ) -> None:
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise VectorStoreError(
                "chromadb is not installed. Run: pip install chromadb"
            ) from exc

        resolved = Path(path) if path is not None else PROJECT_ROOT / get_chroma_db_path()
        resolved.mkdir(parents=True, exist_ok=True)

        self.path = resolved
        self.collection_name = collection_name
        self.embedder = embedder or LocalEmbedder()
        self._client = chromadb.PersistentClient(
            path=str(resolved),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        self._collection = self._client.get_or_create_collection(
            name=collection_name, metadata={"hnsw:space": "cosine"},
        )

    def count(self) -> int:
        return self._collection.count()

    def reset(self) -> None:
        """Delete every stored chunk. The source documents are untouched."""
        self._client.delete_collection(self.collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name, metadata={"hnsw:space": "cosine"},
        )

    def add_chunks(self, chunks: Sequence[Chunk], batch_size: int = 100) -> int:
        if not chunks:
            return 0

        for start in range(0, len(chunks), batch_size):
            batch = list(chunks[start:start + batch_size])
            self._collection.upsert(
                ids=[c.id for c in batch],
                documents=[c.text for c in batch],
                metadatas=[c.metadata for c in batch],
                embeddings=self.embedder.embed([c.text for c in batch]),
            )
        return len(chunks)

    def ingest(self, root: Path = DOCUMENTS_ROOT, reset: bool = True,
               size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> IngestReport:
        """The whole Day 10 pipeline: load, chunk, embed, store."""
        documents, skipped = load_documents(root)
        all_files = [p for p in root.rglob("*") if p.is_file()]

        if reset:
            self.reset()

        chunks = build_chunks(documents, size, overlap)
        stored = self.add_chunks(chunks)

        return IngestReport(
            files_found=len(all_files),
            files_loaded=len(documents),
            chunks_stored=stored,
            embedder=self.embedder.name,
            loaded=[d.source for d in documents],
            skipped=skipped,
        )

    def search(self, query: str, k: int = 4, category: str | None = None) -> list[SearchResult]:
        """Find the chunks whose meaning is closest to the query."""
        if not query.strip():
            raise ValueError("Search query cannot be empty.")
        if self.count() == 0:
            return []

        response = self._collection.query(
            query_embeddings=self.embedder.embed([query]),
            n_results=min(k, self.count()),
            where={"category": category} if category else None,
        )

        documents = response.get("documents") or [[]]
        metadatas = response.get("metadatas") or [[]]
        distances = response.get("distances") or [[]]

        results: list[SearchResult] = []
        for text, meta, distance in zip(documents[0], metadatas[0], distances[0]):
            results.append(SearchResult(
                text=text,
                source=str(meta.get("source", "unknown")),
                category=str(meta.get("category", "general")),
                title=str(meta.get("title", "Untitled")),
                score=round(1 - float(distance), 4),
            ))
        return results

    def sources(self) -> list[str]:
        """Every document currently represented in the knowledge base."""
        if self.count() == 0:
            return []
        stored = self._collection.get(include=["metadatas"])
        return sorted({str(m.get("source")) for m in stored["metadatas"]})
