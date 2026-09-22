"""Day 14 - tests for conversation memory.

Entirely offline: fake specialists, no language model.

    python -m pytest tests/test_conversation.py -v
"""

from __future__ import annotations

import pytest

from app.agents.coordinator import KasiBizCoordinator
from app.agents.intent_classifier import Route
from app.utils.conversation import ConversationMemory, Turn
from app.utils.language import Language

PRODUCTS = ["White Bread", "Milk 1L", "Coca-Cola 500ml", "Simba Chips 36g"]


class FakeAgentResponse:
    def __init__(self, text, product_name=None):
        self.text = text
        self.facts = ""
        self.sources = []
        self.used_llm = False
        self.product_name = product_name


class FakeAgent:
    """Records the question it actually received, after memory resolved it."""

    def __init__(self, name, products=PRODUCTS):
        self.name = name
        self.asked = []
        self.products = products

    def _product_in(self, question):
        matches = [p for p in self.products if p.lower() in question.lower()]
        return max(matches, key=len) if matches else None

    def answer(self, question):
        self.asked.append(question)
        return FakeAgentResponse(f"{self.name}: {question}", self._product_in(question))

    def ask(self, question):
        return self.answer(question)


@pytest.fixture()
def memory():
    return ConversationMemory()


@pytest.fixture()
def agents():
    return {
        "stock": FakeAgent("STOCK"),
        "pricing": FakeAgent("PRICING"),
        "marketing": FakeAgent("MARKETING"),
        "advisor": FakeAgent("ADVISOR"),
    }


@pytest.fixture()
def chat(agents, monkeypatch):
    coordinator = KasiBizCoordinator(
        stock_agent=agents["stock"],
        pricing_agent=agents["pricing"],
        marketing_agent=agents["marketing"],
        advisor_agent=agents["advisor"],
        use_llm=False,
        use_llm_routing=False,
    )
    monkeypatch.setattr(coordinator, "known_products", lambda: PRODUCTS)
    return coordinator


class TestRecordingTurns:
    def test_a_new_memory_is_empty(self, memory):
        assert memory.is_empty
        assert memory.last_product is None
        assert memory.last_route is None

    def test_turns_are_kept(self, memory):
        memory.remember(Turn("q", "q", "a", route="pricing", product="White Bread"))
        assert memory.last_product == "White Bread"
        assert memory.last_route == "pricing"

    def test_old_turns_fall_off_the_end(self):
        memory = ConversationMemory(max_turns=3)
        for i in range(5):
            memory.remember(Turn(f"q{i}", f"q{i}", "a"))
        assert len(memory.turns) == 3
        assert memory.turns[0].question == "q2"

    def test_the_most_recent_product_wins(self, memory):
        memory.remember(Turn("a", "a", "x", product="White Bread"))
        memory.remember(Turn("b", "b", "x", product="Milk 1L"))
        assert memory.last_product == "Milk 1L"

    def test_a_turn_without_a_product_does_not_erase_the_old_one(self, memory):
        memory.remember(Turn("a", "a", "x", product="White Bread"))
        memory.remember(Turn("b", "b", "x", product=None))
        assert memory.last_product == "White Bread"

    def test_clearing_forgets_everything(self, memory):
        memory.remember(Turn("a", "a", "x", product="White Bread"))
        memory.clear()
        assert memory.is_empty

    def test_max_turns_must_be_sensible(self):
        with pytest.raises(ValueError):
            ConversationMemory(max_turns=0)


class TestSpottingReferences:
    @pytest.mark.parametrize("text", [
        "how much is it?", "what about that?", "sell it for R22",
        "dit is te duur", "ngiyithengise ngamalini yona",
    ])
    def test_pronouns_are_found(self, text):
        assert ConversationMemory.has_pronoun(text) is True

    @pytest.mark.parametrize("text", [
        "What is low in stock?", "How do I register with CIPC?",
    ])
    def test_plain_questions_have_no_pronoun(self, text):
        assert ConversationMemory.has_pronoun(text) is False

    @pytest.mark.parametrize("text", [
        "What should I promote this week?",
        "what should I do about that price",
        "check these products",
    ])
    def test_determiners_are_not_references(self, text):
        """'this week' is not a way of saying 'that product'."""
        assert ConversationMemory.has_pronoun(text) is False

    @pytest.mark.parametrize("text", ["what about that?", "how about this", "I like those"])
    def test_a_demonstrative_standing_alone_is_a_reference(self, text):
        assert ConversationMemory.has_pronoun(text) is True

    def test_a_time_phrase_is_never_mangled(self, memory):
        memory.remember(Turn("q", "q", "a", route="marketing", product="Simba Chips 36g"))
        resolved = memory.resolve("What should I promote this week?", PRODUCTS).resolved
        assert resolved == "What should I promote this week?"

    @pytest.mark.parametrize("text", [
        "and what about Milk 1L?", "what about milk", "how about bread",
        "also Coca-Cola 500ml", "en wat van melk",
    ])
    def test_followups_are_found(self, text):
        assert ConversationMemory.is_followup(text) is True

    def test_a_standalone_question_is_not_a_followup(self):
        assert ConversationMemory.is_followup("What is low in stock?") is False

    def test_the_longest_product_name_wins(self):
        assert ConversationMemory.find_product(
            "how much is milk 1l", PRODUCTS) == "Milk 1L"

    def test_no_product_mentioned(self):
        assert ConversationMemory.find_product("how much is it", PRODUCTS) is None


class TestResolvingFollowUps:
    def test_nothing_happens_on_an_empty_memory(self, memory):
        resolution = memory.resolve("how much is it?", PRODUCTS)
        assert resolution.resolved == "how much is it?"
        assert resolution.used_memory is False

    def test_a_pronoun_is_replaced_with_the_product(self, memory):
        memory.remember(Turn("q", "q", "a", route="pricing", product="White Bread"))
        resolution = memory.resolve("how much is it?", PRODUCTS)

        assert resolution.resolved == "how much is White Bread?"
        assert resolution.inherited_product == "White Bread"

    def test_a_bare_followup_gets_the_product_appended(self, memory):
        memory.remember(Turn("q", "q", "a", route="pricing", product="White Bread"))
        resolution = memory.resolve("and what about the margin", PRODUCTS)
        assert "White Bread" in resolution.resolved

    def test_a_named_product_is_never_overridden(self, memory):
        memory.remember(Turn("q", "q", "a", route="pricing", product="White Bread"))
        resolution = memory.resolve("and what about Milk 1L?", PRODUCTS)

        assert resolution.inherited_product is None
        assert resolution.resolved == "and what about Milk 1L?"

    def test_a_followup_suggests_the_previous_route(self, memory):
        memory.remember(Turn("q", "q", "a", route="pricing", product="White Bread"))
        assert memory.resolve("and what about Milk 1L?", PRODUCTS).suggested_route == "pricing"

    def test_a_standalone_question_is_left_alone(self, memory):
        memory.remember(Turn("q", "q", "a", route="pricing", product="White Bread"))
        resolution = memory.resolve("What is low in stock?", PRODUCTS)

        assert resolution.used_memory is False
        assert resolution.resolved == "What is low in stock?"

    def test_the_resolution_explains_itself(self, memory):
        memory.remember(Turn("q", "q", "a", route="pricing", product="White Bread"))
        assert "White Bread" in memory.resolve("how much is it?", PRODUCTS).explain()

    def test_language_is_remembered(self, memory):
        memory.remember(Turn("q", "q", "a", language=Language.ZULU))
        assert memory.resolve("R20", PRODUCTS).language is Language.ZULU

    def test_english_is_not_treated_as_sticky(self, memory):
        memory.remember(Turn("q", "q", "a", language=Language.ENGLISH))
        assert memory.resolve("R20", PRODUCTS).language is None


class TestConversationsThatWork:
    """The whole point of Day 14, end to end."""

    def test_the_product_carries_across_turns(self, chat, agents):
        chat.ask("What should I charge for White Bread?")
        chat.ask("how much is it?")

        assert "White Bread" in agents["pricing"].asked[-1]

    def test_a_new_product_in_a_followup_keeps_the_specialist(self, chat, agents):
        chat.ask("What should I charge for White Bread?")
        response = chat.ask("and what about Milk 1L?")

        assert response.route is Route.PRICING
        assert "Milk 1L" in agents["pricing"].asked[-1]

    def test_the_remembered_route_is_recorded_as_the_method(self, chat):
        chat.ask("What should I charge for White Bread?")
        response = chat.ask("and what about Milk 1L?")
        assert response.decision.method == "memory"

    def test_changing_subject_overrides_memory(self, chat, agents):
        chat.ask("What should I charge for White Bread?")
        response = chat.ask("What is low in stock?")

        assert response.route is Route.STOCK
        assert agents["stock"].asked

    def test_the_response_reports_that_memory_was_used(self, chat):
        chat.ask("What should I charge for White Bread?")
        assert chat.ask("how much is it?").used_memory is True

    def test_a_standalone_question_reports_no_memory_use(self, chat):
        assert chat.ask("What is low in stock?").used_memory is False

    def test_the_resolved_question_is_available(self, chat):
        chat.ask("What should I charge for White Bread?")
        assert chat.ask("how much is it?").asked == "how much is White Bread?"

    def test_the_original_question_is_preserved(self, chat):
        chat.ask("What should I charge for White Bread?")
        assert chat.ask("how much is it?").question == "how much is it?"

    def test_a_three_step_conversation(self, chat, agents):
        chat.ask("What should I charge for White Bread?")
        chat.ask("and what about Milk 1L?")
        chat.ask("write an advert for it")

        assert "Milk 1L" in agents["marketing"].asked[-1]

    def test_starting_over_forgets_the_product(self, chat):
        chat.ask("What should I charge for White Bread?")
        chat.new_conversation()

        assert chat.memory.is_empty
        assert chat.ask("how much is it?").used_memory is False

    def test_memory_can_be_switched_off(self, agents, monkeypatch):
        coordinator = KasiBizCoordinator(
            pricing_agent=agents["pricing"], use_llm=False,
            use_llm_routing=False, remember=False,
        )
        monkeypatch.setattr(coordinator, "known_products", lambda: PRODUCTS)

        coordinator.ask("What should I charge for White Bread?")
        assert coordinator.memory.is_empty


class TestReviewingAConversation:
    def test_summary_of_an_empty_memory(self, memory):
        assert "Nothing discussed" in memory.summary()

    def test_summary_names_the_current_product(self, memory):
        memory.remember(Turn("q", "q", "a", route="pricing", product="White Bread"))
        summary = memory.summary()
        assert "White Bread" in summary and "pricing" in summary

    def test_summary_mentions_a_non_english_language(self, memory):
        memory.remember(Turn("q", "q", "a", language=Language.ZULU))
        assert "isiZulu" in memory.summary()

    def test_transcript_shows_the_exchange(self, memory):
        memory.remember(Turn("What is low?", "What is low?", "Paraffin is out"))
        transcript = memory.transcript()
        assert "Owner: What is low?" in transcript
        assert "KasiBiz: Paraffin is out" in transcript

    def test_a_turn_knows_whether_memory_changed_it(self):
        assert Turn("how much is it?", "how much is White Bread?", "a").used_memory is True
        assert Turn("same", "same", "a").used_memory is False
