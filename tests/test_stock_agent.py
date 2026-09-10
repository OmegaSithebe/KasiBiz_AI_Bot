"""Day 7 - tests for the Stock Agent.

Every test runs with use_llm=False, so the suite is free, offline and instant.
What is tested is the agent's own thinking: did it understand the question, and
did it fetch the right facts?

    python -m pytest tests/test_stock_agent.py -v
"""

from __future__ import annotations

import pytest

from app.agents.inventory_agent import Intent, StockAgent
from app.database.sqlite_db import StockDatabase
from app.services.inventory_service import InventoryService


@pytest.fixture()
def agent(tmp_path) -> StockAgent:
    db = StockDatabase(tmp_path / "agent_test.db")
    db.initialise()
    db.add_product("White Bread", cost_price="15.00", selling_price="20.00",
                   quantity=24, low_stock_threshold=6)
    db.add_product("Milk 1L", cost_price="17.50", selling_price="23.00",
                   quantity=1, low_stock_threshold=6)
    db.add_product("Paraffin 1L", cost_price="26.00", selling_price="34.00",
                   quantity=0, low_stock_threshold=3)
    db.add_product("Sugar 1kg", cost_price="24.00", selling_price="31.00",
                   quantity=5, low_stock_threshold=6)
    return StockAgent(InventoryService(db), use_llm=False)


class TestUnderstandingTheQuestion:
    @pytest.mark.parametrize("question", [
        "What's low in stock?",
        "what is running low",
        "Which items are almost out?",
        "anything finished?",
        "What's running out?",
    ])
    def test_low_stock_questions(self, agent, question):
        assert agent.detect_intent(question)[0] is Intent.LOW_STOCK

    @pytest.mark.parametrize("question", [
        "What should I reorder?",
        "what must i restock",
        "give me a shopping list",
        "what do I buy more of",
    ])
    def test_reorder_questions(self, agent, question):
        assert agent.detect_intent(question)[0] is Intent.REORDER

    @pytest.mark.parametrize("question", [
        "How is my stock doing?",
        "give me a stock report",
        "stock summary please",
    ])
    def test_summary_questions(self, agent, question):
        assert agent.detect_intent(question)[0] is Intent.SUMMARY

    def test_a_named_product_is_recognised(self, agent):
        intent, name = agent.detect_intent("do I have enough white bread?")
        assert intent is Intent.CHECK_PRODUCT
        assert name == "White Bread"

    def test_named_product_beats_a_general_keyword(self, agent):
        """'should I reorder milk' is about milk, not the whole shop."""
        intent, name = agent.detect_intent("should I reorder Milk 1L?")
        assert intent is Intent.CHECK_PRODUCT
        assert name == "Milk 1L"

    def test_product_matching_ignores_capitals(self, agent):
        assert agent.detect_intent("how much PARAFFIN 1L is left")[1] == "Paraffin 1L"

    def test_empty_question(self, agent):
        assert agent.detect_intent("   ")[0] is Intent.UNKNOWN

    def test_nonsense_question(self, agent):
        assert agent.detect_intent("what is the weather tomorrow")[0] is Intent.UNKNOWN


class TestMultilingualKeywords:
    """The MVP promise is English, isiZulu and Sesotho. Still needs native review."""

    @pytest.mark.parametrize("question", ["yini esiphelile?", "ikuphi okuphelile"])
    def test_isizulu_low_stock(self, agent, question):
        assert agent.detect_intent(question)[0] is Intent.LOW_STOCK

    @pytest.mark.parametrize("question", ["ke reke eng?", "ke lokela ho reka eng"])
    def test_sesotho_reorder(self, agent, question):
        assert agent.detect_intent(question)[0] is Intent.REORDER


class TestTheFactsItFetches:
    def test_low_stock_lists_worst_first(self, agent):
        facts, alerts = agent.gather_facts(Intent.LOW_STOCK)
        assert [a.name for a in alerts] == ["Paraffin 1L", "Milk 1L", "Sugar 1kg"]
        assert "Paraffin 1L" in facts

    def test_healthy_products_are_not_listed(self, agent):
        facts, _ = agent.gather_facts(Intent.LOW_STOCK)
        assert "White Bread" not in facts

    def test_reorder_plan_includes_a_total(self, agent):
        facts, _ = agent.gather_facts(Intent.REORDER)
        assert "Total cost of this order" in facts
        assert "Expected profit" in facts

    def test_check_known_product(self, agent):
        facts, alerts = agent.gather_facts(Intent.CHECK_PRODUCT, "Milk 1L")
        assert "Milk 1L" in facts
        assert len(alerts) == 1

    def test_check_unknown_product_says_so(self, agent):
        facts, alerts = agent.gather_facts(Intent.CHECK_PRODUCT, "Caviar")
        assert "does not stock" in facts
        assert alerts == []

    def test_summary_counts_the_shop(self, agent):
        facts, _ = agent.gather_facts(Intent.SUMMARY)
        assert "4 products" in facts
        assert "Most urgent: Paraffin 1L" in facts

    def test_unknown_intent_offers_help(self, agent):
        facts, _ = agent.gather_facts(Intent.UNKNOWN)
        assert "What is low in stock?" in facts


class TestFullAnswers:
    def test_low_stock_answer(self, agent):
        response = agent.answer("What's low in stock?")
        assert response.intent is Intent.LOW_STOCK
        assert response.used_llm is False          # LLM switched off for tests
        assert "Paraffin 1L" in response.text
        assert len(response.alerts) == 3

    def test_reorder_answer(self, agent):
        response = agent.answer("What should I reorder?")
        assert response.intent is Intent.REORDER
        assert "Total cost of this order" in response.text

    def test_single_product_answer(self, agent):
        response = agent.answer("do I have enough Sugar 1kg?")
        assert response.product_name == "Sugar 1kg"
        assert "Sugar 1kg" in response.text

    def test_answer_text_is_never_empty(self, agent):
        for question in ["what's low", "reorder?", "hello", "", "asdfgh"]:
            assert agent.answer(question).text.strip()

    def test_facts_are_always_kept_alongside_the_words(self, agent):
        """Auditability: we can always show where a number came from."""
        response = agent.answer("What should I reorder?")
        assert response.facts.strip()

    def test_str_returns_the_text(self, agent):
        assert str(agent.answer("what's low")) == agent.answer("what's low").text


class TestGracefulDegradation:
    """If OpenAI is down or unpaid, the owner must still get their answer."""

    def test_agent_works_with_no_llm_at_all(self, agent):
        response = agent.answer("What's low in stock?")
        assert response.used_llm is False
        assert "Paraffin 1L" in response.text

    def test_broken_llm_falls_back_to_facts(self, tmp_path):
        from app.utils.llm_client import LLMError

        class BrokenLLM:
            def ask(self, *args, **kwargs):
                raise LLMError("OpenAI is down")

        db = StockDatabase(tmp_path / "fallback.db")
        db.initialise()
        db.add_product("Bread", cost_price="15.00", selling_price="20.00",
                       quantity=0, low_stock_threshold=6)

        broken = StockAgent(InventoryService(db), llm=BrokenLLM())
        response = broken.answer("What's low in stock?")

        assert response.used_llm is False
        assert "Bread" in response.text

    def test_llm_is_used_when_it_works(self, tmp_path):
        class FakeLLM:
            def ask(self, prompt, **kwargs):
                return "Sawubona! Ubhedu lwakho luphelile."

        db = StockDatabase(tmp_path / "fake.db")
        db.initialise()
        db.add_product("Bread", cost_price="15.00", selling_price="20.00",
                       quantity=0, low_stock_threshold=6)

        smart = StockAgent(InventoryService(db), llm=FakeLLM())
        response = smart.answer("Yini esiphelile?")

        assert response.used_llm is True
        assert response.text == "Sawubona! Ubhedu lwakho luphelile."
        assert "Bread" in response.facts       # the real numbers are still kept

    def test_llm_never_changes_the_underlying_facts(self, tmp_path):
        class LyingLLM:
            def ask(self, prompt, **kwargs):
                return "You have 500 loaves, everything is fine."

        db = StockDatabase(tmp_path / "lying.db")
        db.initialise()
        db.add_product("Bread", cost_price="15.00", selling_price="20.00",
                       quantity=0, low_stock_threshold=6)

        agent = StockAgent(InventoryService(db), llm=LyingLLM())
        response = agent.answer("What's low?")

        # The words may be wrong, but the audited facts are still correct.
        assert "0 left" in response.facts
        assert response.alerts[0].quantity == 0
