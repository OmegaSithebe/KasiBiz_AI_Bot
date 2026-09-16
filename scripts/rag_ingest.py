"""Day 10 - load the KasiBiz knowledge base into ChromaDB.

    python scripts/rag_ingest.py              # build the index (OpenAI embeddings)
    python scripts/rag_ingest.py --local      # build it offline, no API key, free
    python scripts/rag_ingest.py --status     # what is currently indexed
    python scripts/rag_ingest.py --search "do I need to register my spaza shop"
    python scripts/rag_ingest.py --reset      # empty the index

Building the index costs a fraction of a cent and only needs to be re-run when
the documents in rag/documents/ change.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.rag.vector_store import (  # noqa: E402
    DOCUMENTS_ROOT,
    KasiBizVectorStore,
    LocalEmbedder,
    OpenAIEmbedder,
    VectorStoreError,
    build_chunks,
    load_documents,
)
from app.utils.config import ConfigError  # noqa: E402

SAMPLE_QUESTIONS = [
    "Do I need to register my spaza shop?",
    "What records must I keep for SARS?",
    "How do I work out if I am making a profit?",
    "What should I do about slow moving stock?",
]


def heading(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")


def make_store(use_local: bool) -> KasiBizVectorStore:
    if use_local:
        return KasiBizVectorStore(embedder=LocalEmbedder())
    try:
        return KasiBizVectorStore(embedder=OpenAIEmbedder())
    except (ConfigError, VectorStoreError) as exc:
        print(f"[falling back to the offline embedder] {exc}\n")
        return KasiBizVectorStore(embedder=LocalEmbedder())


def show_preview() -> None:
    heading("STEP 1 and 2 - LOAD and CHUNK (no AI yet, nothing stored)")
    documents, skipped = load_documents()
    chunks = build_chunks(documents)

    print(f"  {'DOCUMENT':<42}{'CATEGORY':<14}{'CHARS':>7}{'CHUNKS':>8}")
    for document in documents:
        count = len([c for c in chunks if c.source == document.source])
        print(f"  {document.source[:41]:<42}{document.category[:13]:<14}"
              f"{len(document.text):>7}{count:>8}")

    if skipped:
        print("\n  SKIPPED - and why that matters:")
        for name, reason in skipped:
            print(f"    {name}")
            print(f"      -> {reason}")

    print(f"\n  {len(documents)} documents became {len(chunks)} chunks.")


def show_status(store: KasiBizVectorStore) -> None:
    heading("KNOWLEDGE BASE STATUS")
    print(f"  Location: {store.path}")
    print(f"  Collection: {store.collection_name}")
    print(f"  Embedder: {store.embedder.name}")
    print(f"  Chunks stored: {store.count()}")

    sources = store.sources()
    if sources:
        print(f"\n  Documents indexed ({len(sources)}):")
        for source in sources:
            print(f"    - {source}")
    else:
        print("\n  Nothing indexed yet. Run: python scripts/rag_ingest.py --local")


def show_search(store: KasiBizVectorStore, query: str) -> None:
    heading(f"SEARCH: {query}")
    results = store.search(query, k=3)
    if not results:
        print("  Nothing found. Has the index been built?")
        return

    for i, result in enumerate(results, start=1):
        preview = " ".join(result.text.split())[:150]
        print(f"\n  {i}. {result.as_citation()}   [similarity {result.score}]")
        print(f"     {preview}{'...' if len(preview) == 150 else ''}")


def main() -> int:
    parser = argparse.ArgumentParser(description="KasiBiz knowledge base loader")
    parser.add_argument("--local", action="store_true",
                        help="use the offline embedder (no API key, no cost)")
    parser.add_argument("--status", action="store_true", help="show what is indexed")
    parser.add_argument("--search", metavar="QUERY", help="search the knowledge base")
    parser.add_argument("--reset", action="store_true", help="empty the index")
    parser.add_argument("--preview", action="store_true",
                        help="show loading and chunking without storing anything")
    args = parser.parse_args()

    if args.preview:
        show_preview()
        return 0

    try:
        store = make_store(args.local)
    except VectorStoreError as exc:
        print(f"[error] {exc}")
        return 1

    if args.reset:
        store.reset()
        print(f"Index emptied. {store.count()} chunks remain.")
        return 0

    if args.status:
        show_status(store)
        return 0

    if args.search:
        show_search(store, args.search)
        return 0

    show_preview()

    heading("STEP 3 and 4 - EMBED and STORE")
    print(f"  Embedder: {store.embedder.name}")
    print(f"  Destination: {store.path}\n")
    report = store.ingest(DOCUMENTS_ROOT)
    print(report.as_text())

    show_status(store)

    heading("PROOF IT WORKS - searching by meaning, not by keyword")
    for question in SAMPLE_QUESTIONS:
        results = store.search(question, k=1)
        if results:
            best = results[0]
            preview = " ".join(best.text.split())[:110]
            print(f"\n  Q: {question}")
            print(f"  -> {best.as_citation()}  [similarity {best.score}]")
            print(f"     {preview}...")

    print("\n\nDay 10 complete - the knowledge base is loaded into ChromaDB.")
    print("Day 11 will use it to answer business questions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
