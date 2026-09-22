"""Day 13 - tests for language detection and translation accuracy.

Entirely offline. Fake language models stand in for real translation, which is
what lets us test the accuracy checks without an API key.

    python -m pytest tests/test_multilingual.py -v
"""

from __future__ import annotations

import pytest

from app.agents.coordinator import KasiBizCoordinator, greeting_reply, unknown_reply
from app.agents.intent_classifier import IntentClassifier, Route
from app.utils.answer_check import (
    extract_money,
    extract_percentages,
    verify_figures,
)
from app.utils.language import (
    Language,
    detect_language,
    language_directive,
    phrase,
    supported_languages,
)


class TestDetectingLanguage:
    @pytest.mark.parametrize("text", [
        "What is low in stock?",
        "I buy bread for R15, what should I sell it for?",
        "How do I register with CIPC?",
    ])
    def test_english(self, text):
        assert detect_language(text).language is Language.ENGLISH

    @pytest.mark.parametrize("text", [
        "Sawubona, yini esiphelile?",
        "Ngingayithengisa ngamalini i-bread?",
        "Ngenzele isaziso se-WhatsApp",
    ])
    def test_zulu(self, text):
        assert detect_language(text).language is Language.ZULU

    @pytest.mark.parametrize("text", [
        "Molo, ndicela uncedo",
        "Yintoni ixabiso lesonka?",
        "Molweni, ndifuna intengiso",
    ])
    def test_xhosa(self, text):
        assert detect_language(text).language is Language.XHOSA

    @pytest.mark.parametrize("text", [
        "Goeie more, hoeveel voorraad het ek?",
        "Wat is die prys van brood?",
        "Ek wil 'n advertensie he asseblief",
    ])
    def test_afrikaans(self, text):
        assert detect_language(text).language is Language.AFRIKAANS

    @pytest.mark.parametrize("text", [
        "Ke reke eng hoseng hona?",
        "Theko ya bohobe ke bokae?",
    ])
    def test_sotho(self, text):
        assert detect_language(text).language is Language.SOTHO

    def test_empty_text_defaults_to_english(self):
        assert detect_language("").language is Language.ENGLISH
        assert detect_language("   ").language is Language.ENGLISH

    def test_unrecognised_text_defaults_to_english(self):
        """Guessing wrong is worse than staying in English."""
        assert detect_language("qwerty zxcvbn").language is Language.ENGLISH

    def test_a_single_shared_word_does_not_switch_language(self):
        """'malini' appears in both Nguni languages and must not decide alone."""
        assert detect_language("malini").language is Language.ENGLISH

    def test_detection_is_case_insensitive(self):
        assert detect_language("SAWUBONA, YINI ESIPHELILE?").language is Language.ZULU

    def test_punctuation_does_not_break_detection(self):
        assert detect_language("Sawubona!!! Yini esiphelile???").language is Language.ZULU

    def test_the_guess_explains_itself(self):
        assert "isiZulu" in detect_language("Sawubona, yini esiphelile?").explain()

    def test_confidence_is_reported(self):
        guess = detect_language("Goeie more, hoeveel voorraad het ek?")
        assert 0 < guess.confidence <= 1

    def test_scores_are_recorded(self):
        assert detect_language("Sawubona").scores


class TestLanguageDirective:
    def test_english_directive_is_simple(self):
        assert "English" in language_directive(Language.ENGLISH)

    @pytest.mark.parametrize("language", [
        Language.ZULU, Language.XHOSA, Language.AFRIKAANS,
        Language.SOTHO, Language.TSWANA,
    ])
    def test_other_languages_are_named_explicitly(self, language):
        directive = language_directive(language)
        assert language.english_name in directive
        assert "ENTIRE reply" in directive

    def test_directive_protects_the_numbers(self):
        assert "exactly as given" in language_directive(Language.ZULU)

    def test_directive_explains_the_english_facts(self):
        """The Day 8 bug: the model copied the language of the facts, not the question."""
        assert "not" in language_directive(Language.XHOSA).lower()


class TestFixedPhrases:
    def test_every_language_has_a_greeting(self):
        for language in supported_languages():
            assert phrase("greeting", language).strip()

    def test_greetings_actually_differ(self):
        greetings = {phrase("greeting", lang) for lang in supported_languages()}
        assert len(greetings) >= 5

    def test_zulu_greeting_is_zulu(self):
        assert "Sawubona" in phrase("greeting", Language.ZULU)

    def test_xhosa_greeting_is_xhosa(self):
        assert "Molo" in phrase("greeting", Language.XHOSA)

    def test_afrikaans_greeting_is_afrikaans(self):
        assert "Hallo" in phrase("greeting", Language.AFRIKAANS)

    def test_unknown_phrase_key_is_rejected(self):
        with pytest.raises(KeyError):
            phrase("nonsense", Language.ZULU)

    def test_all_phrase_keys_have_english(self):
        for key in ("greeting", "ask_me_about", "not_sure", "no_guides", "source"):
            assert phrase(key, Language.ENGLISH).strip()


class TestExtractingFigures:
    @pytest.mark.parametrize("text, expected", [
        ("Sell at R20.00", {"20.00"}),
        ("R15 cost, R20 selling", {"15.00", "20.00"}),
        ("Total R1,234.56", {"1234.56"}),
        ("Total R1 234,56", {"123456.00"}),
        ("no money here", set()),
    ])
    def test_money(self, text, expected):
        assert extract_money(text) == expected

    def test_money_is_normalised_for_comparison(self):
        assert extract_money("R20") == extract_money("R20.00")

    @pytest.mark.parametrize("text, expected", [
        ("10% off", {"10"}),
        ("33.33% markup and 25% margin", {"33.33", "25"}),
        ("no percentages", set()),
    ])
    def test_percentages(self, text, expected):
        assert extract_percentages(text) == expected


class TestTranslationAccuracy:
    """The Day 13 requirement: answers must stay accurate when translated."""

    FACTS = ("White Bread: 24 left. Promotion price: R18.00. Normal price: R20.00. "
             "Customer saves: R2.00 (10.00% off).")

    def test_a_faithful_english_answer_passes(self):
        answer = "White Bread is now R18.00, was R20.00. You save R2.00, that is 10% off."
        assert verify_figures(self.FACTS, answer).is_faithful

    def test_a_faithful_zulu_answer_passes(self):
        """We cannot read the isiZulu, but we can check the numbers."""
        answer = "Isinkwa esimhlophe manje singu-R18.00, besingu-R20.00. Wonga u-R2.00, okungu-10%."
        assert verify_figures(self.FACTS, answer).is_faithful

    def test_a_faithful_afrikaans_answer_passes(self):
        answer = "Witbrood is nou R18.00, was R20.00. Jy spaar R2.00, dit is 10% afslag."
        assert verify_figures(self.FACTS, answer).is_faithful

    def test_an_invented_price_is_caught(self):
        answer = "Isinkwa manje singu-R80.00."      # R18.00 became R80.00
        check = verify_figures(self.FACTS, answer)
        assert check.is_faithful is False
        assert "R80.00" in check.invented

    def test_an_invented_percentage_is_caught(self):
        answer = "Save R2.00, that is 100% off!"    # 10% became 100%
        check = verify_figures(self.FACTS, answer)
        assert check.is_faithful is False
        assert "100%" in check.invented

    def test_a_completely_made_up_figure_is_caught(self):
        answer = "Buy now and save R500.00 today!"
        assert verify_figures(self.FACTS, answer).is_faithful is False

    def test_leaving_a_figure_out_is_allowed(self):
        """A shorter answer is fine. Inventing is not."""
        answer = "White Bread is now R18.00."
        check = verify_figures(self.FACTS, answer)
        assert check.is_faithful is True
        assert "20.00" in check.missing_money

    def test_an_answer_with_no_figures_is_faithful(self):
        assert verify_figures(self.FACTS, "Come to the shop today!").is_faithful

    def test_different_number_formats_still_match(self):
        """R1 234,56 and R1,234.56 are the same amount written two ways."""
        assert verify_figures("Total R1,234.56", "Totaal R1,234.56").is_faithful

    def test_the_check_explains_itself(self):
        good = verify_figures(self.FACTS, "Now R18.00")
        bad = verify_figures(self.FACTS, "Now R80.00")
        assert "verified" in good.as_text()
        assert "DO NOT MATCH" in bad.as_text()


class TestMultilingualRouting:
    @pytest.mark.parametrize("question, route", [
        ("Yini esiphelile?", Route.STOCK),
        ("Hoeveel voorraad het ek?", Route.STOCK),
        ("Ngingayithengisa ngamalini?", Route.PRICING),
        ("Wat is die prys van brood?", Route.PRICING),
        ("Yintoni ixabiso lesonka?", Route.PRICING),
        ("Ek wil 'n advertensie he", Route.MARKETING),
        ("Hoe registreer ek by CIPC?", Route.ADVICE),
        ("Molo", Route.GREETING),
        ("Goeie more", Route.GREETING),
        ("Dumela", Route.GREETING),
    ])
    def test_routes_in_other_languages(self, question, route):
        assert IntentClassifier().classify(question).route is route


class FakeAgentResponse:
    def __init__(self, text, facts="", sources=None):
        self.text = text
        self.facts = facts
        self.sources = sources or []
        self.used_llm = True


class FakeAgent:
    def __init__(self, text, facts=""):
        self.text = text
        self.facts = facts

    def answer(self, question):
        return FakeAgentResponse(self.text, self.facts)


class TestCoordinatorIsLanguageAware:
    def test_a_zulu_greeting_gets_a_zulu_reply(self):
        coordinator = KasiBizCoordinator(use_llm=False, use_llm_routing=False)
        response = coordinator.ask("Sawubona")
        assert "Sawubona" in response.answer
        assert response.language.language is Language.ZULU

    def test_an_afrikaans_greeting_gets_an_afrikaans_reply(self):
        coordinator = KasiBizCoordinator(use_llm=False, use_llm_routing=False)
        response = coordinator.ask("Goeie more")
        assert "Hallo" in response.answer
        assert response.language.language is Language.AFRIKAANS

    def test_an_english_greeting_stays_english(self):
        coordinator = KasiBizCoordinator(use_llm=False, use_llm_routing=False)
        assert "Hello" in coordinator.ask("Good morning").answer

    def test_the_refusal_is_translated_too(self):
        assert "Andiqinisekanga" in unknown_reply(Language.XHOSA)
        assert "Angiqiniseki" in unknown_reply(Language.ZULU)

    def test_greeting_reply_falls_back_to_english(self):
        assert "Hello" in greeting_reply(Language.ENGLISH)

    def test_the_detected_language_is_reported(self):
        coordinator = KasiBizCoordinator(use_llm=False, use_llm_routing=False)
        assert coordinator.ask("Molo").language.language is Language.XHOSA


class TestCoordinatorChecksFigures:
    FACTS = "White Bread: R18.00 now, was R20.00. Save R2.00."

    def test_a_faithful_answer_is_verified(self):
        coordinator = KasiBizCoordinator(
            marketing_agent=FakeAgent("Bread now R18.00, was R20.00", self.FACTS),
            use_llm=False, use_llm_routing=False,
        )
        response = coordinator.ask("Write an advert")
        assert response.figures_verified is True

    def test_an_invented_figure_is_flagged(self):
        coordinator = KasiBizCoordinator(
            marketing_agent=FakeAgent("Bread now R80.00!", self.FACTS),
            use_llm=False, use_llm_routing=False,
        )
        response = coordinator.ask("Write an advert")
        assert response.figures_verified is False
        assert "R80.00" in response.figures.invented

    def test_answers_without_facts_are_not_checked(self):
        coordinator = KasiBizCoordinator(use_llm=False, use_llm_routing=False)
        response = coordinator.ask("Sawubona")
        assert response.figures is None
        assert response.figures_verified is True
