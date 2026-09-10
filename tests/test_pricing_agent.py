"""Day 8 - tests for the Pricing Agent.

All tests run with use_llm=False or a fake model, so the suite is free,
offline and instant.

    python -m pytest tests/test_pricing_agent.py -v
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.agents.pricing_agent import PricingAgent, PricingIntent
from app.database.sqlite_db import StockDatabase
from app.services.pricing_service import PricingService


@pytest.fixture()
def agent(tmp_path) -> PricingAgent:
    db = StockDatabase(tmp_path / "pricing_agent.db")
    db.initialise()
    db.add_product("White Bread", cost_price="15.00", selling_price="20.00",
                   category="Bakery", quantity=24)
    db.add_product("Milk 1L", cost_price="17.50", selling_price="23.00",
                   category="Dairy", quantity=20)
    db.add_product("Airtime R12", cost_price="11.40", selling_price="12.00",
                   category="Airtime", quantity=50)
    db.add_product("Bad Deal", cost_price="20.00", selling_price="18.00",
                   category="Snacks", quantity=5)
    return PricingAgent(PricingService(db), use_llm=False)


class TestReadingAmountsFromText:
    @pytest.mark.parametrize("text, expected", [
        ("i buy bread for r15", [Decimal("15")]),
        ("i pay R15.50 for it", [Decimal("15.50")]),
        ("cost 15 sell 20", [Decimal("15"), Decimal("20")]),
        ("i buy for r15,50", [Decimal("15.50")]),
        ("no money here", []),
    ])
    def test_amounts_are_found(self, agent, text, expected):
        assert agent.extract_amounts(text) == expected

    def test_percentages_are_not_mistaken_for_money(self, agent):
        assert agent.extract_amounts("add 40% to r15") == [Decimal("15")]

    def test_percent_is_read_separately(self, agent):
        assert agent.extract_percent("use a 40% markup") == Decimal("40")

    def test_no_percent_returns_none(self, agent):
        assert agent.extract_percent("what should i charge") is None


class TestUnderstandingTheQuestion:
    @pytest.mark.parametrize("question", [
        "What should I charge for bread?",
        "I buy bread for R15, what should I sell it for?",
        "how much should i sell this for",
        "suggest a price",
    ])
    def test_suggest_price(self, agent, question):
        assert agent.detect_intent(question)[0] is PricingIntent.SUGGEST_PRICE

    @pytest.mark.parametrize("question", [
        "Am I making profit on White Bread?",
        "how much profit do i make",
        "is my price right",
    ])
    def test_check_price(self, agent, question):
        assert agent.detect_intent(question)[0] is PricingIntent.CHECK_PRICE

    @pytest.mark.parametrize("question", [
        "Check all my prices",
        "are my prices right",
        "which products are underpriced",
    ])
    def test_review_all(self, agent, question):
        assert agent.detect_intent(question)[0] is PricingIntent.REVIEW_ALL

    @pytest.mark.parametrize("question", [
        "What if I sell White Bread for R22?",
        "should i raise the price of Milk 1L",
    ])
    def test_what_if(self, agent, question):
        assert agent.detect_intent(question)[0] is PricingIntent.WHAT_IF

    @pytest.mark.parametrize("question", [
        "What is markup?",
        "what is the difference between markup and margin",
        "explain margin",
    ])
    def test_explain_concept(self, agent, question):
        assert agent.detect_intent(question)[0] is PricingIntent.EXPLAIN_CONCEPT

    def test_a_bare_product_name_is_a_price_check(self, agent):
        intent, name = agent.detect_intent("White Bread")
        assert intent is PricingIntent.CHECK_PRICE
        assert name == "White Bread"

    def test_product_is_captured_alongside_the_intent(self, agent):
        assert agent.detect_intent("what if I sell Milk 1L for R25")[1] == "Milk 1L"

    def test_empty_and_nonsense(self, agent):
        assert agent.detect_intent("   ")[0] is PricingIntent.UNKNOWN
        assert agent.detect_intent("who won the game")[0] is PricingIntent.UNKNOWN


class TestTheFactsItCalculates:
    def test_price_suggestion_from_a_stated_cost(self, agent):
        facts = agent.gather_facts(PricingIntent.SUGGEST_PRICE,
                                   "i buy bread for r15 what should i charge")
        assert "R15.00" in facts
        assert "RECOMMENDED" in facts
        assert "Competitive" in facts and "Premium" in facts

    def test_price_suggestion_uses_a_known_product_cost(self, agent):
        facts = agent.gather_facts(PricingIntent.SUGGEST_PRICE,
                                   "what should i charge for white bread", "White Bread")
        assert "R15.00" in facts

    def test_a_stated_markup_is_honoured(self, agent):
        facts = agent.gather_facts(PricingIntent.SUGGEST_PRICE,
                                   "i buy for r10 and want 50% markup")
        assert "R15.00" in facts

    def test_suggestion_without_a_cost_asks_for_one(self, agent):
        facts = agent.gather_facts(PricingIntent.SUGGEST_PRICE, "what should i charge")
        assert "what you paid" in facts.lower()

    def test_check_a_known_product(self, agent):
        facts = agent.gather_facts(PricingIntent.CHECK_PRICE,
                                   "am i making profit on white bread", "White Bread")
        assert "White Bread" in facts and "HEALTHY" in facts

    def test_check_catches_a_loss_maker(self, agent):
        facts = agent.gather_facts(PricingIntent.CHECK_PRICE,
                                   "am i making profit on bad deal", "Bad Deal")
        assert "LOSING MONEY" in facts

    def test_check_from_two_loose_numbers(self, agent):
        facts = agent.gather_facts(PricingIntent.CHECK_PRICE,
                                   "i buy for r15 and sell for r20, am i making profit")
        assert "R5.00" in facts

    def test_review_lists_the_problem_product(self, agent):
        facts = agent.gather_facts(PricingIntent.REVIEW_ALL, "check my prices")
        assert "Bad Deal" in facts
        assert "Checked 4 products" in facts

    def test_review_does_not_flag_airtime(self, agent):
        """Airtime at 5% margin is normal, not a pricing mistake."""
        facts = agent.gather_facts(PricingIntent.REVIEW_ALL, "check my prices")
        problem_section = facts.split("need attention:")[-1]
        assert "Airtime R12" not in problem_section

    def test_what_if_shows_the_difference(self, agent):
        facts = agent.gather_facts(PricingIntent.WHAT_IF,
                                   "what if i sell white bread for r22", "White Bread")
        assert "R20.00" in facts and "R22.00" in facts

    def test_what_if_without_a_product(self, agent):
        facts = agent.gather_facts(PricingIntent.WHAT_IF, "what if i charge r22")
        assert "which product" in facts.lower()

    def test_concept_explanation_shows_both_numbers(self, agent):
        facts = agent.gather_facts(PricingIntent.EXPLAIN_CONCEPT, "what is markup")
        assert "33.33%" in facts and "25.00%" in facts
        assert "PAID" in facts and "CHARGE" in facts

    def test_unknown_offers_examples(self, agent):
        facts = agent.gather_facts(PricingIntent.UNKNOWN, "who won the game")
        assert "I can help you with prices" in facts


class TestFullAnswers:
    def test_suggest_a_price(self, agent):
        response = agent.answer("I buy bread for R15, what should I sell it for?")
        assert response.intent is PricingIntent.SUGGEST_PRICE
        assert response.used_llm is False
        assert "R20" in response.text

    def test_check_a_price(self, agent):
        response = agent.answer("Am I making profit on White Bread?")
        assert response.product_name == "White Bread"
        assert "White Bread" in response.text

    def test_review_all_prices(self, agent):
        response = agent.answer("Check all my prices")
        assert response.intent is PricingIntent.REVIEW_ALL

    def test_amounts_are_recorded_on_the_response(self, agent):
        assert agent.answer("I buy bread for R15").amounts == [Decimal("15")]

    def test_answer_is_never_empty(self, agent):
        for question in ["what is markup", "check my prices", "", "asdfgh", "R15"]:
            assert agent.answer(question).text.strip()

    def test_facts_are_kept_for_audit(self, agent):
        assert agent.answer("Check all my prices").facts.strip()


class TestGracefulDegradation:
    def test_works_with_no_llm(self, agent):
        response = agent.answer("I buy bread for R15, what should I charge?")
        assert response.used_llm is False
        assert "R20" in response.text

    def test_broken_llm_falls_back_to_facts(self, tmp_path):
        from app.utils.llm_client import LLMError

        class BrokenLLM:
            def ask(self, *args, **kwargs):
                raise LLMError("OpenAI is down")

        db = StockDatabase(tmp_path / "broken.db")
        db.initialise()
        broken = PricingAgent(PricingService(db), llm=BrokenLLM())
        response = broken.answer("I buy bread for R15, what should I charge?")

        assert response.used_llm is False
        assert "R20" in response.text

    def test_llm_is_used_when_it_works(self, tmp_path):
        class FakeLLM:
            def ask(self, prompt, **kwargs):
                return "Thenga nge-R15, uthengise nge-R20. Uzozuza u-R5."

        db = StockDatabase(tmp_path / "fake.db")
        db.initialise()
        smart = PricingAgent(PricingService(db), llm=FakeLLM())
        response = smart.answer("Ngingayithengisa ngamalini i-bread engiyithenge nge-R15?")

        assert response.used_llm is True
        assert response.text.startswith("Thenga")
        assert "R15.00" in response.facts       # the real maths is still recorded

    def test_llm_cannot_corrupt_the_facts(self, tmp_path):
        class LyingLLM:
            def ask(self, prompt, **kwargs):
                return "Sell it for R500, you will make R485 profit."

        db = StockDatabase(tmp_path / "lying.db")
        db.initialise()
        agent = PricingAgent(PricingService(db), llm=LyingLLM())
        response = agent.answer("I buy bread for R15, what should I charge?")

        assert "R500" not in response.facts
        assert "R20.50" in response.facts or "R20.00" in response.facts
