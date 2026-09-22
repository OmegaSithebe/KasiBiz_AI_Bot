"""One source of truth for what words mean.

The two-layer intent duplication cost this project three bugs. These tests are
the guard on the fix: the vocabulary is one table, both layers are derived from
it, and any phrase that claims to route must actually route.
"""

from __future__ import annotations

import pytest

from app.agents.intent_classifier import IntentClassifier
from app.agents.intents import (
    NEVER_ROUTES,
    VOCABULARY,
    InsightIntent,
    Route,
    SalesIntent,
    StockIntent,
    agent_keywords,
    is_cancellation,
    is_confirmation,
    keywords_for,
    router_patterns,
)


@pytest.fixture
def classifier():
    return IntentClassifier()


class TestTheTableIsTheOnlySource:
    def test_the_router_is_derived_from_it(self):
        patterns = router_patterns()
        for route, entries in patterns.items():
            for text, weight in entries:
                assert weight > NEVER_ROUTES
                assert any(p.text == text and p.route is route for p in VOCABULARY)

    def test_the_specialists_are_derived_from_it(self):
        for route in (Route.STOCK, Route.SALES, Route.PRICING,
                      Route.MARKETING, Route.INSIGHTS):
            for intent, words in agent_keywords(route).items():
                for word in words:
                    assert any(p.text == word and p.route is route
                               and p.intent == intent for p in VOCABULARY)

    def test_every_specialist_route_has_router_patterns(self):
        patterns = router_patterns()
        for route in Route:
            if route.is_specialist:
                assert route in patterns, f"{route.value} cannot be reached"

    def test_no_phrase_is_written_twice_for_the_same_route(self):
        seen = set()
        for phrase in VOCABULARY:
            key = (phrase.route, phrase.text)
            assert key not in seen, f"{phrase.text!r} appears twice for {phrase.route.value}"
            seen.add(key)

    def test_keywords_for_covers_every_member_of_the_enum(self):
        """A missing sub-intent must never become a KeyError at runtime."""
        for enum_cls, route in ((StockIntent, Route.STOCK),
                                (SalesIntent, Route.SALES),
                                (InsightIntent, Route.INSIGHTS)):
            derived = keywords_for(route, enum_cls)
            assert set(derived) == set(enum_cls)


class TestEveryRoutingPhraseActuallyRoutes:
    """A phrase given a weight but outscored by another route is a silent bug."""

    @pytest.mark.parametrize("phrase", [p for p in VOCABULARY if p.weight > NEVER_ROUTES],
                             ids=lambda p: f"{p.route.value}:{p.text}")
    def test_the_phrase_reaches_its_own_route(self, classifier, phrase):
        if "*" in phrase.text or "[" in phrase.text:
            pytest.skip("regex pattern, not a literal phrase")

        decision = classifier.classify(phrase.text)
        assert decision.route is phrase.route, (
            f"{phrase.text!r} was written for {phrase.route.value} "
            f"but routes to {decision.route.value}"
        )


class TestTheNewRoutes:
    @pytest.mark.parametrize("question", [
        "Start a new sale",
        "The customer wants 2 White Bread",
        "they paid R50",
        "how much change do I give",
        "what is the total",
        "ring up a sale",
    ])
    def test_sales_questions_reach_the_till(self, classifier, question):
        assert classifier.classify(question).route is Route.SALES

    @pytest.mark.parametrize("question", [
        "What is selling well?",
        "What is my best seller?",
        "Which products are moving slowly?",
        "How much did I take this week?",
        "What was my gross profit?",
        "How is business?",
        "Show me my sales report",
    ])
    def test_insight_questions_reach_the_insights_agent(self, classifier, question):
        assert classifier.classify(question).route is Route.INSIGHTS


class TestTheOldRoutesStillWork:
    """Consolidation must not have moved anything that was already correct."""

    @pytest.mark.parametrize("question,expected", [
        ("What is low in stock?", Route.STOCK),
        ("What should I reorder?", Route.STOCK),
        ("What should I charge for White Bread?", Route.PRICING),
        ("Am I making enough profit?", Route.PRICING),
        ("Write a WhatsApp advert", Route.MARKETING),
        ("What should I promote?", Route.MARKETING),
        ("How do I register with CIPC?", Route.ADVICE),
        ("What records does SARS want?", Route.ADVICE),
        ("Sawubona", Route.GREETING),
        ("What can you do?", Route.HELP),
    ])
    def test_routes_as_before(self, classifier, question, expected):
        assert classifier.classify(question).route is expected


class TestTheBoundariesBetweenRoutes:
    """The places where two routes genuinely compete for the same words."""

    def test_selling_a_thing_is_not_the_same_as_pricing_a_thing(self, classifier):
        assert classifier.classify("what should I sell it for").route is Route.PRICING
        assert classifier.classify("the customer wants 2 bread").route is Route.SALES

    def test_an_isizulu_verb_stem_does_not_hijack_a_pricing_question(self, classifier):
        """'-thengis-' means both 'sell' and 'sell for how much'. It must not route."""
        assert classifier.classify("Ngingayithengisa ngamalini?").route is Route.PRICING

    def test_how_much_did_i_sell_is_a_report_not_a_sale(self, classifier):
        assert classifier.classify("how much did I sell this week").route is Route.INSIGHTS

    def test_what_is_low_in_stock_is_not_an_insight(self, classifier):
        assert classifier.classify("What is low in stock?").route is Route.STOCK

    def test_total_stock_is_stock_not_a_basket_total(self, classifier):
        assert classifier.classify("how much total stock do I have").route is Route.STOCK


class TestConfirmAndCancel:
    @pytest.mark.parametrize("text", ["yes", "yebo", "ja", "ewe", "confirm",
                                      "that's right", "save it", "go ahead", "ok"])
    def test_recognises_a_yes(self, text):
        assert is_confirmation(text)

    @pytest.mark.parametrize("text", ["cancel", "cancel it", "no", "cha", "nee",
                                      "hayi", "forget it", "start over", "undo"])
    def test_recognises_a_no(self, text):
        assert is_cancellation(text)

    @pytest.mark.parametrize("text", [
        "What is low in stock?",
        "2 White Bread",
        "How do I register with CIPC?",
    ])
    def test_an_ordinary_question_is_neither(self, text):
        assert not is_confirmation(text)
        assert not is_cancellation(text)

    def test_a_yes_inside_a_longer_sentence_is_not_a_bare_yes(self):
        assert not is_confirmation("yesterday I sold ten loaves")

    def test_no_wins_over_yes_when_both_appear(self):
        assert not is_confirmation("ok no cancel that")
        assert is_cancellation("ok no cancel that")
