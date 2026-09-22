"""Day 11 - tests for the retriever and the Business Advisor.

Offline throughout: a local embedder and fake language models.

    python -m pytest tests/test_business_advisor.py -v
"""

from __future__ import annotations

import pytest

from app.agents.business_advisor_agent import (
    NO_CONTEXT_REPLY,
    NOT_BUILT_REPLY,
    AdviceTopic,
    BusinessAdvisorAgent,
)
from app.rag.retriever import KnowledgeRetriever
from app.rag.vector_store import KasiBizVectorStore, LocalEmbedder
from app.utils.llm_client import LLMError


@pytest.fixture()
def docs_root(tmp_path):
    root = tmp_path / "documents"

    (root / "registration").mkdir(parents=True)
    (root / "registration" / "cipc_registration.md").write_text(
        "How to Register a Business in South Africa\n\n"
        "Decide on a company name. Create a CIPC BizPortal account. "
        "Reserve a business name. Register the company online. "
        "Add director information. Receive company registration documents. "
        "Open a business bank account.",
        encoding="utf-8",
    )
    (root / "registration" / "annual_returns.md").write_text(
        "Annual Returns\n\n"
        "An annual return is a compliance submission that confirms company "
        "information with CIPC. Registered entities must submit annual returns "
        "even when dormant.",
        encoding="utf-8",
    )

    (root / "taxation").mkdir(parents=True)
    (root / "taxation" / "sars_basics.md").write_text(
        "SARS Basics\n\n"
        "SARS is the South African Revenue Service. Keep invoices, receipts, "
        "sales records, stock records and bank statements. Pay taxes on time "
        "to avoid penalties.",
        encoding="utf-8",
    )

    return root


@pytest.fixture()
def retriever(tmp_path, docs_root):
    store = KasiBizVectorStore(
        path=tmp_path / "chroma",
        collection_name="advisor_test",
        embedder=LocalEmbedder(),
    )
    store.ingest(docs_root)
    return KnowledgeRetriever(store)


@pytest.fixture()
def empty_retriever(tmp_path):
    store = KasiBizVectorStore(
        path=tmp_path / "empty_chroma",
        collection_name="empty_test",
        embedder=LocalEmbedder(),
    )
    return KnowledgeRetriever(store)


class FakeLLM:
    """Echoes back proof that it received the grounded context."""

    def __init__(self, reply="To register, create a CIPC BizPortal account."):
        self.reply = reply
        self.last_prompt = ""
        self.last_system = ""
        self.calls = 0

    def ask(self, prompt, system_prompt="", **kwargs):
        self.calls += 1
        self.last_prompt = prompt
        self.last_system = system_prompt
        return self.reply


class TestRetriever:
    def test_a_built_index_is_ready(self, retriever):
        assert retriever.is_ready is True

    def test_an_empty_index_is_not_ready(self, empty_retriever):
        assert empty_retriever.is_ready is False

    def test_it_finds_registration_guidance(self, retriever):
        context = retriever.retrieve("How do I register a company with CIPC?")
        assert context.has_context
        assert any("cipc" in r.source for r in context.results)

    def test_it_finds_tax_guidance(self, retriever):
        context = retriever.retrieve("What records must I keep for SARS?")
        assert context.results[0].source == "sars_basics.md"

    def test_unrelated_questions_return_nothing(self, retriever):
        context = retriever.retrieve("What is the capital city of Japan?")
        assert context.has_context is False

    def test_empty_question_is_rejected(self, retriever):
        with pytest.raises(ValueError):
            retriever.retrieve("   ")

    def test_empty_index_returns_no_context(self, empty_retriever):
        assert empty_retriever.retrieve("anything").has_context is False

    def test_top_k_is_respected(self, tmp_path, docs_root):
        store = KasiBizVectorStore(path=tmp_path / "c", collection_name="k_test",
                                   embedder=LocalEmbedder())
        store.ingest(docs_root)
        assert len(KnowledgeRetriever(store, top_k=1).retrieve("CIPC company").results) <= 1

    def test_invalid_top_k_is_rejected(self, retriever):
        with pytest.raises(ValueError):
            KnowledgeRetriever(retriever.store, top_k=0)

    def test_a_high_threshold_filters_everything(self, retriever):
        strict = KnowledgeRetriever(retriever.store, min_relevance=0.99)
        assert strict.retrieve("register a company").has_context is False

    def test_results_can_be_limited_to_one_topic(self, retriever):
        context = retriever.retrieve("company information", category="taxation")
        assert all(r.category == "taxation" for r in context.results)

    def test_topics_are_listed(self, retriever):
        assert set(retriever.topics()) == {"registration", "taxation"}


class TestContextFormatting:
    def test_context_is_numbered_and_labelled(self, retriever):
        block = retriever.retrieve("How do I register with CIPC?").as_prompt_context()
        assert "[1]" in block
        assert "Source:" in block and "file:" in block

    def test_context_respects_a_character_budget(self, retriever):
        block = retriever.retrieve("CIPC company").as_prompt_context(max_chars=120)
        assert len(block) <= 400        # one block may overshoot slightly, not many

    def test_sources_are_deduplicated(self, retriever):
        context = retriever.retrieve("CIPC company registration")
        assert len(context.sources) == len(set(context.sources))

    def test_citation_line_is_readable(self, retriever):
        line = retriever.retrieve("How do I register with CIPC?").as_citation_line()
        assert line.startswith("Source: ")

    def test_no_results_means_no_citation(self, retriever):
        assert retriever.retrieve("capital city of Japan").as_citation_line() == ""


class TestTopicDetection:
    @pytest.mark.parametrize("question", [
        "How do I register with CIPC?",
        "What is an annual return?",
        "What is beneficial ownership?",
    ])
    def test_registration(self, question):
        assert BusinessAdvisorAgent.detect_topic(question) is AdviceTopic.REGISTRATION

    @pytest.mark.parametrize("question", [
        "What records must I keep for SARS?",
        "Do I need to charge VAT?",
        "Why must I keep receipts?",
    ])
    def test_taxation(self, question):
        assert BusinessAdvisorAgent.detect_topic(question) is AdviceTopic.TAXATION

    def test_inventory(self):
        assert BusinessAdvisorAgent.detect_topic(
            "what do I do with slow moving stock") is AdviceTopic.INVENTORY

    def test_general(self):
        assert BusinessAdvisorAgent.detect_topic("how are you") is AdviceTopic.GENERAL


class TestGroundedAnswers:
    def test_it_answers_the_day_11_question(self, retriever):
        llm = FakeLLM()
        response = BusinessAdvisorAgent(retriever, llm=llm).ask("How do I register with CIPC?")

        assert response.grounded is True
        assert response.used_llm is True
        assert response.sources

    def test_the_answer_carries_a_citation(self, retriever):
        response = BusinessAdvisorAgent(retriever, llm=FakeLLM()).ask(
            "How do I register with CIPC?")
        assert "Source:" in response.answer_with_citation
        assert "cipc_registration.md" in response.answer_with_citation

    def test_the_prompt_contains_the_real_passages(self, retriever):
        llm = FakeLLM()
        BusinessAdvisorAgent(retriever, llm=llm).ask("How do I register with CIPC?")
        assert "BizPortal" in llm.last_prompt
        assert "SOURCE PASSAGES" in llm.last_prompt

    def test_the_model_is_told_not_to_invent(self, retriever):
        llm = FakeLLM()
        BusinessAdvisorAgent(retriever, llm=llm).ask("How do I register with CIPC?")
        assert "ONLY from the SOURCE PASSAGES" in llm.last_system
        assert "Never invent" in llm.last_system

    def test_confidence_is_recorded(self, retriever):
        response = BusinessAdvisorAgent(retriever, llm=FakeLLM()).ask(
            "How do I register a company with CIPC?")
        assert response.confidence > 0

    def test_topic_is_recorded(self, retriever):
        response = BusinessAdvisorAgent(retriever, llm=FakeLLM()).ask(
            "How do I register with CIPC?")
        assert response.topic is AdviceTopic.REGISTRATION

    def test_str_includes_the_citation(self, retriever):
        assert "Source:" in str(
            BusinessAdvisorAgent(retriever, llm=FakeLLM()).ask("How do I register with CIPC?"))


class TestRefusingToGuess:
    """The behaviour that makes this safe to put in front of a real shop owner."""

    def test_unknown_questions_are_not_answered(self, retriever):
        llm = FakeLLM()
        response = BusinessAdvisorAgent(retriever, llm=llm).ask(
            "What is the capital city of Japan?")

        assert response.grounded is False
        assert response.sources == []
        assert "do not cover that" in response.answer

    def test_the_llm_is_never_called_without_context(self, retriever):
        llm = FakeLLM()
        BusinessAdvisorAgent(retriever, llm=llm).ask("What is the capital city of Japan?")
        assert llm.calls == 0

    def test_it_points_to_the_official_sources(self, retriever):
        response = BusinessAdvisorAgent(retriever, llm=FakeLLM()).ask(
            "What is the capital city of Japan?")
        assert "bizportal.gov.za" in response.answer
        assert "sars.gov.za" in response.answer

    def test_an_unbuilt_index_says_how_to_fix_it(self, empty_retriever):
        response = BusinessAdvisorAgent(empty_retriever, llm=FakeLLM()).ask(
            "How do I register with CIPC?")
        assert response.answer == NOT_BUILT_REPLY
        assert "rag_ingest" in response.answer

    def test_empty_question_is_rejected(self, retriever):
        with pytest.raises(ValueError):
            BusinessAdvisorAgent(retriever, llm=FakeLLM()).ask("  ")

    def test_no_context_reply_mentions_both_authorities(self):
        assert "CIPC" in NO_CONTEXT_REPLY and "SARS" in NO_CONTEXT_REPLY


class TestWorkingWithoutAI:
    def test_it_answers_from_the_documents_with_no_llm(self, retriever):
        response = BusinessAdvisorAgent(retriever, use_llm=False).ask(
            "How do I register with CIPC?")

        assert response.used_llm is False
        assert response.grounded is True
        assert "BizPortal" in response.answer
        assert response.sources

    def test_a_broken_llm_falls_back_to_the_documents(self, retriever):
        class BrokenLLM:
            def ask(self, *args, **kwargs):
                raise LLMError("OpenAI is down")

        response = BusinessAdvisorAgent(retriever, llm=BrokenLLM()).ask(
            "How do I register with CIPC?")

        assert response.used_llm is False
        assert response.grounded is True
        assert "BizPortal" in response.answer

    def test_citations_survive_the_fallback(self, retriever):
        response = BusinessAdvisorAgent(retriever, use_llm=False).ask(
            "How do I register with CIPC?")
        assert "Source:" in response.answer_with_citation


class TestHelp:
    def test_it_lists_what_it_knows(self, retriever):
        text = BusinessAdvisorAgent(retriever, use_llm=False).what_can_i_ask()
        assert "registration" in text and "taxation" in text

    def test_help_explains_how_to_build_the_index(self, empty_retriever):
        assert "rag_ingest" in BusinessAdvisorAgent(
            empty_retriever, use_llm=False).what_can_i_ask()
