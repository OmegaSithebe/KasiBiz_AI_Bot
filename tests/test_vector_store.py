"""Day 10 - tests for loading documents into the vector database.

Every test uses the offline LocalEmbedder and a throwaway Chroma folder, so the
suite stays free and needs no API key.

    python -m pytest tests/test_vector_store.py -v
"""

from __future__ import annotations

import pytest

from app.rag.vector_store import (
    KasiBizVectorStore,
    LocalEmbedder,
    build_chunks,
    chunk_text,
    load_documents,
    looks_like_questions_only,
)


@pytest.fixture()
def docs_root(tmp_path):
    """A miniature knowledge base, including the awkward cases."""
    root = tmp_path / "documents"

    (root / "taxation").mkdir(parents=True)
    (root / "taxation" / "sars_basics.md").write_text(
        "SARS Basics for Small Businesses\n\n"
        "SARS is the South African Revenue Service. Business owners may have tax "
        "responsibilities depending on turnover.\n\n"
        "Keep invoices, receipts, sales records and bank statements. "
        "Pay taxes on time to avoid penalties.",
        encoding="utf-8",
    )
    (root / "taxation" / "Questions_KasiBiz_Answer.txt").write_text(
        "Common Questions KasiBiz Should Handle\n"
        "What is SARS?\n"
        "Why must I keep receipts?\n"
        "How do I prepare for tax season?\n"
        "What is VAT?",
        encoding="utf-8",
    )

    (root / "registration").mkdir(parents=True)
    (root / "registration" / "cipc_registration.md").write_text(
        "How to Register a Business in South Africa\n\n"
        "Decide on a company name. Create a CIPC or BizPortal account. "
        "Reserve a business name. Register the company online and add director "
        "information. Open a business bank account.",
        encoding="utf-8",
    )

    (root / "business").mkdir(parents=True)
    (root / "business" / "pricing.md").write_text(
        "Simple Pricing Formula\n\n"
        "Selling Price minus Cost Price equals Profit. "
        "If cost is R15 and selling price is R20 then profit is R5.",
        encoding="utf-8",
    )
    (root / "business" / "photo.jpeg").write_bytes(b"\xff\xd8\xff\xe0 not text")
    (root / "business" / "empty.md").write_text("   \n\n  ", encoding="utf-8")

    return root


@pytest.fixture()
def store(tmp_path):
    return KasiBizVectorStore(
        path=tmp_path / "chroma",
        collection_name="test_knowledge",
        embedder=LocalEmbedder(),
    )


class TestLoadingDocuments:
    def test_markdown_files_are_loaded(self, docs_root):
        documents, _ = load_documents(docs_root)
        assert {d.source for d in documents} == {
            "sars_basics.md", "cipc_registration.md", "pricing.md"}

    def test_category_comes_from_the_folder(self, docs_root):
        documents, _ = load_documents(docs_root)
        by_name = {d.source: d for d in documents}
        assert by_name["sars_basics.md"].category == "taxation"
        assert by_name["cipc_registration.md"].category == "registration"

    def test_title_is_derived_from_the_filename(self, docs_root):
        documents, _ = load_documents(docs_root)
        titles = {d.title for d in documents}
        assert "Sars Basics" in titles

    def test_images_are_skipped(self, docs_root):
        _, skipped = load_documents(docs_root)
        assert any(name == "photo.jpeg" for name, _ in skipped)

    def test_empty_files_are_skipped(self, docs_root):
        _, skipped = load_documents(docs_root)
        assert any(name == "empty.md" and "empty" in reason for name, reason in skipped)

    def test_missing_folder_is_reported_clearly(self, tmp_path):
        from app.rag.vector_store import VectorStoreError

        with pytest.raises(VectorStoreError):
            load_documents(tmp_path / "nope")


class TestQuestionOnlyFiles:
    """Indexing a list of questions would make the assistant quote them as facts."""

    def test_question_files_are_detected(self):
        assert looks_like_questions_only(
            "Questions\nWhat is SARS?\nWhy keep receipts?\nWhat is VAT?"
        ) is True

    def test_real_content_is_not_flagged(self):
        assert looks_like_questions_only(
            "SARS is the South African Revenue Service.\n"
            "Keep your receipts.\nPay on time."
        ) is False

    def test_a_document_with_one_question_is_fine(self):
        assert looks_like_questions_only(
            "Pricing\nSelling price minus cost price is profit.\n"
            "Cost R15, sell R20, profit R5.\nAm I making profit?"
        ) is False

    def test_question_only_file_is_skipped_with_a_reason(self, docs_root):
        _, skipped = load_documents(docs_root)
        reasons = {name: reason for name, reason in skipped}
        assert "Questions_KasiBiz_Answer.txt" in reasons
        assert "questions but no answers" in reasons["Questions_KasiBiz_Answer.txt"]

    def test_question_file_never_reaches_the_index(self, store, docs_root):
        store.ingest(docs_root)
        assert "Questions_KasiBiz_Answer.txt" not in store.sources()


class TestChunking:
    def test_short_text_stays_as_one_chunk(self):
        assert chunk_text("A short note about bread.") == ["A short note about bread."]

    def test_long_text_is_split(self):
        chunks = chunk_text("word " * 500, size=200, overlap=20)
        assert len(chunks) > 1

    def test_chunks_respect_the_size_limit(self):
        for chunk in chunk_text("word " * 500, size=200, overlap=20):
            assert len(chunk) <= 200

    def test_paragraphs_are_kept_together_when_they_fit(self):
        text = "First paragraph here.\n\nSecond paragraph here."
        assert chunk_text(text, size=500) == [text]

    def test_empty_text_produces_nothing(self):
        assert chunk_text("   ") == []

    def test_blank_line_runs_are_tidied(self):
        assert "\n\n\n" not in chunk_text("A\n\n\n\n\nB", size=500)[0]

    def test_invalid_settings_are_rejected(self):
        with pytest.raises(ValueError):
            chunk_text("text", size=0)
        with pytest.raises(ValueError):
            chunk_text("text", size=100, overlap=100)

    def test_chunks_carry_their_source(self, docs_root):
        documents, _ = load_documents(docs_root)
        chunks = build_chunks(documents)
        assert all(c.source and c.category and c.title for c in chunks)

    def test_chunk_ids_are_unique(self, docs_root):
        documents, _ = load_documents(docs_root)
        chunks = build_chunks(documents)
        assert len({c.id for c in chunks}) == len(chunks)


class TestEmbedding:
    def test_vectors_have_a_fixed_length(self):
        vectors = LocalEmbedder(dimensions=64).embed(["hello there", "a much longer piece"])
        assert all(len(v) == 64 for v in vectors)

    def test_the_same_text_always_gives_the_same_vector(self):
        embedder = LocalEmbedder()
        assert embedder.embed(["SARS tax"]) == embedder.embed(["SARS tax"])

    def test_similar_text_is_closer_than_unrelated_text(self):
        embedder = LocalEmbedder()
        base, similar, different = embedder.embed([
            "SARS tax records receipts",
            "tax receipts for SARS",
            "bread milk sugar shelf",
        ])
        dot = lambda a, b: sum(x * y for x, y in zip(a, b))  # noqa: E731
        assert dot(base, similar) > dot(base, different)

    def test_empty_text_does_not_crash(self):
        assert len(LocalEmbedder().embed([""])[0]) == 512


class TestStoringAndSearching:
    def test_a_new_store_is_empty(self, store):
        assert store.count() == 0

    def test_ingest_stores_chunks(self, store, docs_root):
        report = store.ingest(docs_root)
        assert report.chunks_stored > 0
        assert store.count() == report.chunks_stored

    def test_report_counts_loaded_and_skipped(self, store, docs_root):
        report = store.ingest(docs_root)
        assert report.files_loaded == 3
        assert report.files_skipped == 3      # jpeg, empty, questions-only
        assert "local" in report.embedder

    def test_report_text_lists_skip_reasons(self, store, docs_root):
        assert "Skipped:" in store.ingest(docs_root).as_text()

    def test_sources_lists_indexed_documents(self, store, docs_root):
        store.ingest(docs_root)
        assert store.sources() == ["cipc_registration.md", "pricing.md", "sars_basics.md"]

    def test_searching_an_empty_store_returns_nothing(self, store):
        assert store.search("anything") == []

    def test_empty_query_is_rejected(self, store):
        with pytest.raises(ValueError):
            store.search("   ")

    def test_search_finds_the_right_document(self, store, docs_root):
        store.ingest(docs_root)
        assert store.search("SARS receipts and tax records", k=1)[0].source == "sars_basics.md"

    def test_search_finds_registration_guidance(self, store, docs_root):
        store.ingest(docs_root)
        assert store.search("register a company with CIPC", k=1)[0].source == "cipc_registration.md"

    def test_results_are_ordered_best_first(self, store, docs_root):
        store.ingest(docs_root)
        scores = [r.score for r in store.search("cost price profit selling", k=3)]
        assert scores == sorted(scores, reverse=True)

    def test_k_limits_the_number_of_results(self, store, docs_root):
        store.ingest(docs_root)
        assert len(store.search("business", k=2)) <= 2

    def test_results_can_be_filtered_by_category(self, store, docs_root):
        store.ingest(docs_root)
        results = store.search("business", k=5, category="taxation")
        assert results and all(r.category == "taxation" for r in results)

    def test_every_result_can_be_cited(self, store, docs_root):
        store.ingest(docs_root)
        citation = store.search("profit", k=1)[0].as_citation()
        assert "(" in citation and ")" in citation

    def test_reset_empties_the_index(self, store, docs_root):
        store.ingest(docs_root)
        store.reset()
        assert store.count() == 0
        assert store.sources() == []

    def test_reindexing_does_not_duplicate(self, store, docs_root):
        first = store.ingest(docs_root).chunks_stored
        second = store.ingest(docs_root).chunks_stored
        assert first == second == store.count()

    def test_index_survives_a_restart(self, tmp_path, docs_root):
        path = tmp_path / "persist"
        KasiBizVectorStore(path=path, collection_name="kb",
                           embedder=LocalEmbedder()).ingest(docs_root)

        reopened = KasiBizVectorStore(path=path, collection_name="kb",
                                      embedder=LocalEmbedder())
        assert reopened.count() > 0
        assert "sars_basics.md" in reopened.sources()
