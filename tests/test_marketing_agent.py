"""Day 9 - tests for the Marketing Agent.

Uses fake language models, so the suite stays free and offline.

    python -m pytest tests/test_marketing_agent.py -v
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.agents.marketing_agent import MarketingAgent, MarketingIntent
from app.database.sqlite_db import StockDatabase
from app.services.marketing_service import Channel, MarketingService, PromoSafety


@pytest.fixture()
def agent(tmp_path) -> MarketingAgent:
    db = StockDatabase(tmp_path / "marketing_agent.db")
    db.initialise()
    db.add_product("White Bread", cost_price="15.00", selling_price="20.00",
                   category="Bakery", quantity=60, low_stock_threshold=6)
    db.add_product("Coca-Cola 500ml", cost_price="12.00", selling_price="18.00",
                   category="Cold Drinks", quantity=72, low_stock_threshold=12)
    db.add_product("Paraffin 1L", cost_price="26.00", selling_price="34.00",
                   category="Household", quantity=2, low_stock_threshold=3)
    return MarketingAgent(MarketingService(db, shop_name="Mama T Spaza"), use_llm=False)


class TestUnderstandingTheRequest:
    @pytest.mark.parametrize("question", [
        "Write a WhatsApp advert for White Bread",
        "make a promo for White Bread",
        "advertise White Bread on status",
    ])
    def test_whatsapp(self, agent, question):
        assert agent.detect_intent(question)[0] is MarketingIntent.WHATSAPP

    @pytest.mark.parametrize("question", [
        "Facebook caption for White Bread",
        "instagram post for White Bread",
        "social media caption for White Bread",
    ])
    def test_social(self, agent, question):
        assert agent.detect_intent(question)[0] is MarketingIntent.SOCIAL

    @pytest.mark.parametrize("question", [
        "Make a poster for White Bread",
        "sign for the window for White Bread",
        "something to print for White Bread",
    ])
    def test_poster(self, agent, question):
        assert agent.detect_intent(question)[0] is MarketingIntent.POSTER

    def test_all_channels(self, agent):
        assert agent.detect_intent("full campaign for White Bread")[0] is MarketingIntent.ALL_CHANNELS

    @pytest.mark.parametrize("question", [
        "What should I promote?",
        "what should i advertise this week",
        "give me ideas",
    ])
    def test_what_to_promote(self, agent, question):
        assert agent.detect_intent(question)[0] is MarketingIntent.WHAT_TO_PROMOTE

    def test_product_is_captured(self, agent):
        assert agent.detect_intent("poster for coca-cola 500ml")[1] == "Coca-Cola 500ml"

    def test_bare_product_name_defaults_to_whatsapp(self, agent):
        intent, name = agent.detect_intent("White Bread")
        assert intent is MarketingIntent.WHATSAPP
        assert name == "White Bread"

    def test_empty_and_nonsense(self, agent):
        assert agent.detect_intent("")[0] is MarketingIntent.UNKNOWN
        assert agent.detect_intent("what is the time")[0] is MarketingIntent.UNKNOWN


class TestReadingOffersFromText:
    def test_percentage_is_found(self, agent):
        assert agent.extract_discount("10% off white bread") == Decimal("10")

    def test_no_percentage(self, agent):
        assert agent.extract_discount("advert for white bread") is None

    @pytest.mark.parametrize("text, units, price", [
        ("2 for R35", 2, Decimal("35")),
        ("3 for r50.50", 3, Decimal("50.50")),
        ("buy 2 for 35", 2, Decimal("35")),
    ])
    def test_bundle_is_found(self, agent, text, units, price):
        assert agent.extract_bundle(text) == (units, price)

    def test_no_bundle(self, agent):
        assert agent.extract_bundle("advert for bread") is None

    def test_discount_from_question_is_applied(self, agent):
        offer = agent.build_offer_from_question("10% off White Bread", "White Bread")
        assert offer.promo_price_cents == 1800

    def test_bundle_from_question_is_applied(self, agent):
        offer = agent.build_offer_from_question("2 White Bread for R35", "White Bread")
        assert offer.units_in_offer == 2
        assert offer.promo_price_cents == 3500

    def test_no_offer_details_gives_a_safe_suggestion(self, agent):
        offer = agent.build_offer_from_question("advert for White Bread", "White Bread")
        assert offer.safety is PromoSafety.SAFE
        assert offer.profit_cents > 0


class TestSafetyRefusals:
    """The agent must refuse to write adverts the shop cannot honour."""

    def test_it_refuses_to_advertise_low_stock(self, agent):
        response = agent.answer("Write an advert for Paraffin 1L")
        assert response.offer.safety is PromoSafety.LOW_STOCK
        assert "have not written the advert" in response.text
        assert response.pieces == []

    def test_it_refuses_a_loss_making_discount(self, agent):
        response = agent.answer("50% off White Bread")
        assert response.offer.safety is PromoSafety.LOSS
        assert "lose money" in response.text.lower()
        assert response.pieces == []

    def test_a_safe_request_is_written(self, agent):
        response = agent.answer("10% off White Bread")
        assert response.pieces
        assert response.offer.safety is PromoSafety.SAFE

    def test_unknown_product(self, agent):
        response = agent.answer("advert for Caviar")
        assert response.intent is MarketingIntent.UNKNOWN


class TestTemplateCopy:
    """Even with no AI, the owner must get usable advertising."""

    def test_whatsapp_template_has_the_price_and_shop(self, agent):
        response = agent.answer("WhatsApp advert for White Bread")
        assert "White Bread" in response.text
        assert "Mama T Spaza" in response.text
        assert response.used_llm is False

    def test_discount_template_shows_both_prices(self, agent):
        response = agent.answer("WhatsApp advert for White Bread with 10% off")
        assert "R18.00" in response.text and "R20.00" in response.text

    def test_poster_template_is_shouty_and_short(self, agent):
        response = agent.answer("Make a poster for White Bread")
        assert "WHITE BREAD" in response.text
        assert len(response.text.splitlines()) <= 10

    def test_social_template_has_hashtags(self, agent):
        response = agent.answer("Facebook caption for White Bread")
        assert "#" in response.text

    def test_bundle_template(self, agent):
        response = agent.answer("advert: 2 White Bread for R35")
        assert "2 White Bread for R35.00" in response.text

    def test_all_channels_produces_three_pieces(self, agent):
        response = agent.answer("full campaign for White Bread")
        assert len(response.pieces) == 3
        assert {p.channel for p in response.pieces} == {
            Channel.WHATSAPP, Channel.SOCIAL, Channel.POSTER}

    def test_copy_is_never_empty(self, agent):
        for question in ["poster for White Bread", "caption for Coca-Cola 500ml",
                         "White Bread", "what should I promote"]:
            assert agent.answer(question).text.strip()


class TestWhatToPromote:
    def test_it_lists_candidates_with_offers(self, agent):
        text = agent.what_to_promote()
        assert "Coca-Cola 500ml" in text or "White Bread" in text
        assert "Suggested offer" in text

    def test_it_never_suggests_low_stock(self, agent):
        assert "Paraffin 1L" not in agent.what_to_promote()

    def test_empty_shop_says_so(self, tmp_path):
        db = StockDatabase(tmp_path / "empty.db")
        db.initialise()
        quiet = MarketingAgent(MarketingService(db), use_llm=False)
        assert "Nothing is ready" in quiet.what_to_promote()


class TestWithALanguageModel:
    def test_llm_copy_is_used_when_it_works(self, tmp_path):
        class FakeLLM:
            def ask(self, prompt, **kwargs):
                return "Isinkwa esimhlophe manje ngo-R18.00 kuphela! Woza ku-Mama T Spaza."

        db = StockDatabase(tmp_path / "fake.db")
        db.initialise()
        db.add_product("White Bread", cost_price="15.00", selling_price="20.00",
                       quantity=60, low_stock_threshold=6)
        smart = MarketingAgent(MarketingService(db, shop_name="Mama T Spaza"), llm=FakeLLM())

        response = smart.answer("Ngenzele isaziso se-WhatsApp se-White Bread")
        assert response.used_llm is True
        assert "Isinkwa" in response.text

    def test_surrounding_quotes_are_stripped(self, tmp_path):
        class QuotingLLM:
            def ask(self, prompt, **kwargs):
                return '"Fresh bread at R18.00!"'

        db = StockDatabase(tmp_path / "q.db")
        db.initialise()
        db.add_product("White Bread", cost_price="15.00", selling_price="20.00",
                       quantity=60, low_stock_threshold=6)
        agent = MarketingAgent(MarketingService(db), llm=QuotingLLM())
        assert not agent.answer("advert for White Bread").text.startswith('"')

    def test_broken_llm_falls_back_to_the_template(self, tmp_path):
        from app.utils.llm_client import LLMError

        class BrokenLLM:
            def ask(self, *args, **kwargs):
                raise LLMError("OpenAI is down")

        db = StockDatabase(tmp_path / "broken.db")
        db.initialise()
        db.add_product("White Bread", cost_price="15.00", selling_price="20.00",
                       quantity=60, low_stock_threshold=6)
        agent = MarketingAgent(MarketingService(db, shop_name="Mama T Spaza"), llm=BrokenLLM())

        response = agent.answer("WhatsApp advert for White Bread")
        assert response.used_llm is False
        assert "White Bread" in response.text      # still usable advertising

    def test_the_llm_never_sees_the_cost_price(self, tmp_path):
        """A copywriter that knows the cost price could publish it by accident."""
        captured = {}

        class SpyLLM:
            def ask(self, prompt, **kwargs):
                captured["prompt"] = prompt
                return "advert"

        db = StockDatabase(tmp_path / "spy.db")
        db.initialise()
        db.add_product("White Bread", cost_price="15.00", selling_price="20.00",
                       quantity=60, low_stock_threshold=6)
        MarketingAgent(MarketingService(db), llm=SpyLLM()).answer("advert for White Bread")

        assert "R15.00" not in captured["prompt"]

    def test_a_blocked_offer_never_reaches_the_llm(self, tmp_path):
        class SpyLLM:
            called = False

            def ask(self, *args, **kwargs):
                SpyLLM.called = True
                return "advert"

        db = StockDatabase(tmp_path / "blocked.db")
        db.initialise()
        db.add_product("Paraffin 1L", cost_price="26.00", selling_price="34.00",
                       quantity=1, low_stock_threshold=3)
        agent = MarketingAgent(MarketingService(db), llm=SpyLLM())
        agent.answer("advert for Paraffin 1L")

        assert SpyLLM.called is False
