"""Day 12 - tests for intent classification and the Task Coordinator.

All offline: fake specialists, fake language model.

    python -m pytest tests/test_coordinator.py -v
"""

from __future__ import annotations

import pytest

from app.agents.coordinator import (
    GREETING_REPLY,
    HELP_REPLY,
    UNKNOWN_REPLY,
    CoordinatorResponse,
    KasiBizCoordinator,
)
from app.agents.intent_classifier import (
    IntentClassifier,
    LLMIntentClassifier,
    Route,
)


class FakeAgentResponse:
    def __init__(self, text, sources=None, used_llm=False):
        self.text = text
        self.sources = sources or []
        self.used_llm = used_llm


class FakeAgent:
    """Stands in for any specialist. Records what it was asked."""

    def __init__(self, name, sources=None):
        self.name = name
        self.asked = []
        self.sources = sources or []

    def answer(self, question):
        self.asked.append(question)
        return FakeAgentResponse(f"{self.name} says: {question}", self.sources)

    def ask(self, question):
        self.asked.append(question)
        response = FakeAgentResponse(f"{self.name} says: {question}", self.sources)
        response.answer = response.text
        return response


@pytest.fixture()
def agents():
    return {
        "stock": FakeAgent("STOCK"),
        "pricing": FakeAgent("PRICING"),
        "marketing": FakeAgent("MARKETING"),
        "advisor": FakeAgent("ADVISOR", sources=["Cipc Overview (registration/cipc_overview.md)"]),
    }


@pytest.fixture()
def coordinator(agents):
    return KasiBizCoordinator(
        stock_agent=agents["stock"],
        pricing_agent=agents["pricing"],
        marketing_agent=agents["marketing"],
        advisor_agent=agents["advisor"],
        use_llm=False,
        use_llm_routing=False,
    )


class TestClassifyingStockQuestions:
    @pytest.mark.parametrize("question", [
        "What is low in stock?",
        "What should I reorder?",
        "Do I have enough White Bread?",
        "Anything running out?",
        "How is my stock doing?",
        "Yini esiphelile?",
    ])
    def test_routes_to_stock(self, question):
        assert IntentClassifier().classify(question).route is Route.STOCK


class TestClassifyingPricingQuestions:
    @pytest.mark.parametrize("question", [
        "I buy bread for R15, what should I charge?",
        "Am I making profit on milk?",
        "Check my prices",
        "What is the difference between markup and margin?",
        "Are my prices too cheap?",
    ])
    def test_routes_to_pricing(self, question):
        assert IntentClassifier().classify(question).route is Route.PRICING


class TestClassifyingMarketingQuestions:
    @pytest.mark.parametrize("question", [
        "Write a WhatsApp advert for White Bread",
        "Make a poster for Coca-Cola",
        "Facebook caption for Simba Chips",
        "What should I promote this week?",
    ])
    def test_routes_to_marketing(self, question):
        assert IntentClassifier().classify(question).route is Route.MARKETING


class TestClassifyingAdviceQuestions:
    @pytest.mark.parametrize("question", [
        "How do I register with CIPC?",
        "What is an annual return?",
        "What records must I keep for SARS?",
        "Do I need to pay VAT?",
        "What is beneficial ownership?",
    ])
    def test_routes_to_advice(self, question):
        assert IntentClassifier().classify(question).route is Route.ADVICE


class TestGreetingsAndHelp:
    @pytest.mark.parametrize("question", ["Sawubona", "Good morning", "Dumela", "Hello"])
    def test_greetings(self, question):
        assert IntentClassifier().classify(question).route is Route.GREETING

    @pytest.mark.parametrize("question", ["What can you do?", "Who are you?"])
    def test_help(self, question):
        assert IntentClassifier().classify(question).route is Route.HELP

    def test_unknown(self):
        assert IntentClassifier().classify("who won the rugby").route is Route.UNKNOWN

    def test_empty_message(self):
        assert IntentClassifier().classify("   ").route is Route.UNKNOWN


class TestScoringBehaviour:
    """The router must be explainable, not a black box."""

    def test_scores_are_returned(self):
        decision = IntentClassifier().classify("What is low in stock?")
        assert decision.scores[Route.STOCK] > 0

    def test_matched_patterns_are_recorded(self):
        assert IntentClassifier().classify("What should I reorder?").matched

    def test_longer_phrases_beat_single_words(self):
        """'what should i charge' must outweigh a stray mention of 'stock'."""
        decision = IntentClassifier().classify(
            "I have stock of bread - what should I charge for it?")
        assert decision.route is Route.PRICING

    def test_confidence_is_between_zero_and_one(self):
        decision = IntentClassifier().classify("How do I register with CIPC?")
        assert 0 < decision.confidence <= 1

    def test_a_single_weak_word_is_not_enough(self):
        """One weak signal should not confidently route anywhere."""
        decision = IntentClassifier().classify("charge")
        assert decision.route is Route.UNKNOWN or decision.confidence < 1

    def test_the_decision_explains_itself(self):
        assert "Stock Agent" in IntentClassifier().classify("What is low in stock?").explain()

    def test_routing_is_case_insensitive(self):
        assert IntentClassifier().classify("WHAT IS LOW IN STOCK?").route is Route.STOCK

    def test_extra_whitespace_is_handled(self):
        assert IntentClassifier().classify("  what   is   low   in stock ").route is Route.STOCK


class TestDispatch:
    def test_stock_question_reaches_the_stock_agent(self, coordinator, agents):
        response = coordinator.ask("What is low in stock?")
        assert response.route is Route.STOCK
        assert agents["stock"].asked == ["What is low in stock?"]
        assert "STOCK says" in response.answer

    def test_pricing_question_reaches_the_pricing_agent(self, coordinator, agents):
        coordinator.ask("I buy bread for R15, what should I charge?")
        assert agents["pricing"].asked

    def test_marketing_question_reaches_the_marketing_agent(self, coordinator, agents):
        coordinator.ask("Write a WhatsApp advert for bread")
        assert agents["marketing"].asked

    def test_advice_question_reaches_the_advisor(self, coordinator, agents):
        coordinator.ask("How do I register with CIPC?")
        assert agents["advisor"].asked

    def test_only_one_specialist_is_called(self, coordinator, agents):
        coordinator.ask("What is low in stock?")
        called = [name for name, agent in agents.items() if agent.asked]
        assert called == ["stock"]

    def test_the_advisor_uses_its_own_entry_point(self, coordinator, agents):
        """BusinessAdvisorAgent exposes ask(), the others expose answer()."""
        response = coordinator.ask("What records must I keep for SARS?")
        assert "ADVISOR says" in response.answer

    def test_sources_are_passed_through(self, coordinator):
        response = coordinator.ask("How do I register with CIPC?")
        assert response.sources == ["Cipc Overview (registration/cipc_overview.md)"]

    def test_specialist_name_is_reported(self, coordinator):
        assert coordinator.ask("What is low in stock?").specialist == "Stock Agent"

    def test_empty_question_is_rejected(self, coordinator):
        with pytest.raises(ValueError):
            coordinator.ask("   ")


class TestBuiltInReplies:
    def test_greeting(self, coordinator, agents):
        """Since Day 13 the greeting comes back in the owner's own language."""
        response = coordinator.ask("Sawubona")
        assert "Sawubona" in response.answer
        assert not any(agent.asked for agent in agents.values())

    def test_english_greeting(self, coordinator):
        assert coordinator.ask("Good morning").answer == GREETING_REPLY

    def test_help_lists_all_four_areas(self, coordinator):
        answer = coordinator.ask("What can you do?").answer
        assert answer == HELP_REPLY
        for area in ("STOCK", "PRICING", "MARKETING", "ADVICE"):
            assert area in answer

    def test_unknown_offers_examples(self, coordinator):
        assert coordinator.ask("who won the rugby").answer == UNKNOWN_REPLY

    def test_no_specialist_is_called_for_unknown(self, coordinator, agents):
        coordinator.ask("who won the rugby")
        assert not any(agent.asked for agent in agents.values())


class TestFailingSpecialists:
    """One broken specialist must not take the whole assistant down."""

    def test_a_crashing_agent_is_reported_politely(self, agents):
        class BrokenAgent:
            def answer(self, question):
                raise RuntimeError("database is locked")

        coordinator = KasiBizCoordinator(
            stock_agent=BrokenAgent(),
            pricing_agent=agents["pricing"],
            use_llm=False, use_llm_routing=False,
        )
        response = coordinator.ask("What is low in stock?")

        assert "could not answer" in response.answer
        assert "database is locked" in response.error

    def test_the_owner_never_sees_the_technical_reason(self, agents):
        """The detail belongs in the log and in .error, not on the screen."""
        class BrokenAgent:
            def answer(self, question):
                raise RuntimeError("sqlite3.OperationalError: database is locked")

        coordinator = KasiBizCoordinator(
            stock_agent=BrokenAgent(), use_llm=False, use_llm_routing=False,
        )
        response = coordinator.ask("What is low in stock?")

        assert "sqlite3" not in response.answer
        assert "OperationalError" not in response.answer
        assert "Traceback" not in response.answer
        assert "sqlite3" in response.error

    def test_other_specialists_still_work(self, agents):
        class BrokenAgent:
            def answer(self, question):
                raise RuntimeError("boom")

        coordinator = KasiBizCoordinator(
            stock_agent=BrokenAgent(),
            pricing_agent=agents["pricing"],
            use_llm=False, use_llm_routing=False,
        )
        coordinator.ask("What is low in stock?")
        response = coordinator.ask("Am I making profit?")

        assert "PRICING says" in response.answer
        assert response.error == ""


class TestLLMFallbackRouting:
    """Tier 2 is only used when tier 1 is genuinely unsure."""

    class SpyLLMClassifier(LLMIntentClassifier):
        def __init__(self, route):
            super().__init__(llm=object())
            self.route = route
            self.calls = 0

        def classify(self, message):
            self.calls += 1
            return self.route

    def test_the_model_is_not_called_for_a_clear_question(self, agents):
        spy = self.SpyLLMClassifier(Route.STOCK)
        coordinator = KasiBizCoordinator(
            stock_agent=agents["stock"], llm_classifier=spy,
            use_llm=False, use_llm_routing=True,
        )
        coordinator.ask("What is low in stock?")
        assert spy.calls == 0

    def test_the_model_is_called_when_nothing_matches(self, agents):
        spy = self.SpyLLMClassifier(Route.ADVICE)
        coordinator = KasiBizCoordinator(
            advisor_agent=agents["advisor"], llm_classifier=spy,
            use_llm=False, use_llm_routing=True,
        )
        response = coordinator.ask("is my shop allowed to sell cigarettes")

        assert spy.calls == 1
        assert response.route is Route.ADVICE
        assert response.decision.method == "llm"

    def test_routing_falls_back_to_rules_when_the_model_fails(self, agents):
        class DeadClassifier(LLMIntentClassifier):
            def __init__(self):
                super().__init__(llm=object())

            def classify(self, message):
                return None

        coordinator = KasiBizCoordinator(
            llm_classifier=DeadClassifier(), use_llm=False, use_llm_routing=True,
        )
        assert coordinator.ask("something unclear entirely").answer == UNKNOWN_REPLY

    def test_llm_routing_can_be_switched_off(self, agents):
        spy = self.SpyLLMClassifier(Route.ADVICE)
        coordinator = KasiBizCoordinator(
            advisor_agent=agents["advisor"], llm_classifier=spy,
            use_llm=False, use_llm_routing=False,
        )
        coordinator.ask("is my shop allowed to sell cigarettes")
        assert spy.calls == 0


class TestExplainability:
    def test_explain_routing_shows_every_score(self, coordinator):
        text = coordinator.explain_routing("What should I charge for bread?")
        assert "pricing" in text and "score" in text and "chosen" in text

    def test_explain_routing_handles_no_match(self, coordinator):
        assert "no keywords matched" in coordinator.explain_routing("qwerty zxcvb")

    def test_all_routes_have_a_specialist(self):
        for value, specialist in KasiBizCoordinator.routes():
            assert value and specialist

    def test_route_names_map_to_specialists(self):
        assert Route.STOCK.specialist == "Stock Agent"
        assert Route.ADVICE.specialist == "Business Advisor"
