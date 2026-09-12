"""Day 9 - tests for the marketing maths and safety rails.

No AI, no internet, no API key.

    python -m pytest tests/test_marketing_service.py -v
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.database.sqlite_db import StockDatabase
from app.services.marketing_service import (
    Channel,
    MarketingService,
    OfferType,
    PromoSafety,
)


@pytest.fixture()
def service(tmp_path) -> MarketingService:
    db = StockDatabase(tmp_path / "marketing.db")
    db.initialise()
    # Plenty of stock, healthy margin - the ideal promotion candidate.
    db.add_product("White Bread", cost_price="15.00", selling_price="20.00",
                   category="Bakery", quantity=60, low_stock_threshold=6)
    # Good margin, lots of stock.
    db.add_product("Simba Chips 36g", cost_price="6.50", selling_price="10.00",
                   category="Snacks", quantity=80, low_stock_threshold=12)
    # Almost out - must never be advertised.
    db.add_product("Paraffin 1L", cost_price="26.00", selling_price="34.00",
                   category="Household", quantity=2, low_stock_threshold=3)
    # Wafer-thin margin.
    db.add_product("Airtime R12", cost_price="11.40", selling_price="12.00",
                   category="Airtime", quantity=100, low_stock_threshold=20)
    return MarketingService(db, shop_name="Mama T Spaza")


class TestChoosingWhatToPromote:
    def test_well_stocked_high_margin_products_come_first(self, service):
        names = [c.name for c in service.suggest_products_to_promote()]
        assert names[0] in {"Simba Chips 36g", "White Bread"}

    def test_low_stock_products_are_never_suggested(self, service):
        """Advertising something you are about to run out of loses customers."""
        assert "Paraffin 1L" not in [c.name for c in service.suggest_products_to_promote()]

    def test_limit_is_respected(self, service):
        assert len(service.suggest_products_to_promote(limit=2)) == 2

    def test_each_suggestion_explains_itself(self, service):
        candidate = service.suggest_products_to_promote()[0]
        assert "in stock" in candidate.reason and "margin" in candidate.reason

    def test_zero_profit_products_are_skipped(self, tmp_path):
        db = StockDatabase(tmp_path / "zero.db")
        db.initialise()
        db.add_product("At Cost", cost_price="10.00", selling_price="10.00",
                       quantity=100, low_stock_threshold=5)
        assert MarketingService(db).suggest_products_to_promote() == []

    def test_empty_shop(self, tmp_path):
        db = StockDatabase(tmp_path / "empty.db")
        db.initialise()
        assert MarketingService(db).suggest_products_to_promote() == []


class TestBuildingOffers:
    def test_straight_offer_uses_the_normal_price(self, service):
        offer = service.build_offer("White Bread")
        assert offer.promo_price_cents == 2000
        assert offer.is_discounted is False
        assert offer.offer_type is OfferType.STRAIGHT

    def test_percentage_discount(self, service):
        offer = service.build_offer("White Bread", discount_percent=10)
        assert offer.promo_price_cents == 1800        # R20 less 10%
        assert offer.saving_cents == 200
        assert offer.discount_percent == Decimal("10.00")

    def test_discount_price_is_rounded_to_cash(self, service):
        offer = service.build_offer("White Bread", discount_percent=13)
        assert offer.promo_price_cents % 50 == 0      # R17.40 -> R17.50

    def test_profit_survives_the_discount(self, service):
        offer = service.build_offer("White Bread", discount_percent=10)
        assert offer.profit_cents == 300              # R18.00 - R15.00
        assert offer.safety is PromoSafety.SAFE

    def test_fixed_price_offer(self, service):
        offer = service.build_offer("White Bread", promo_price="17.50")
        assert offer.promo_price_cents == 1750
        assert offer.offer_type is OfferType.FIXED_PRICE

    def test_unknown_product(self, service):
        assert service.build_offer("Caviar", discount_percent=10) is None

    def test_impossible_discounts_are_rejected(self, service):
        with pytest.raises(ValueError):
            service.build_offer("White Bread", discount_percent=100)
        with pytest.raises(ValueError):
            service.build_offer("White Bread", discount_percent=-5)


class TestSafetyRails:
    """The two mistakes the service exists to prevent."""

    def test_a_discount_below_cost_is_blocked(self, service):
        offer = service.build_offer("White Bread", promo_price="12.00")   # cost is R15
        assert offer.safety is PromoSafety.LOSS
        assert offer.safety.blocks_campaign is True
        assert offer.profit_cents < 0

    def test_low_stock_is_blocked(self, service):
        offer = service.build_offer("Paraffin 1L", discount_percent=10)
        assert offer.safety is PromoSafety.LOW_STOCK
        assert offer.safety.blocks_campaign is True

    def test_thin_profit_warns_but_does_not_block(self, service):
        offer = service.build_offer("Airtime R12")
        assert offer.safety is PromoSafety.THIN_PROFIT
        assert offer.safety.blocks_campaign is False
        assert offer.safety.warning

    def test_a_healthy_offer_is_safe(self, service):
        assert service.build_offer("White Bread", discount_percent=10).safety is PromoSafety.SAFE

    def test_safe_verdict_has_no_warning(self, service):
        assert service.build_offer("White Bread").safety.warning == ""


class TestDiscountHeadroom:
    def test_headroom_matches_the_margin(self, service):
        # Bread: R15 cost, R20 sell -> 25% of the price is profit
        assert service.max_safe_discount_percent("White Bread") == Decimal("25")

    def test_headroom_is_rounded_down_for_safety(self, service):
        # Chips: R6.50 cost, R10.00 sell -> 35% exactly
        assert service.max_safe_discount_percent("Simba Chips 36g") == Decimal("35")

    def test_thin_margin_has_almost_no_headroom(self, service):
        assert service.max_safe_discount_percent("Airtime R12") == Decimal("5")

    def test_unknown_product(self, service):
        assert service.max_safe_discount_percent("Caviar") is None


class TestAutomaticOfferSuggestion:
    def test_suggested_offer_gives_away_at_most_half_the_profit(self, service):
        offer = service.suggest_offer("White Bread")
        assert offer.discount_percent <= Decimal("13")     # half of 25%, rounded
        assert offer.profit_cents > 0

    def test_suggested_offer_is_always_safe(self, service):
        for name in ("White Bread", "Simba Chips 36g"):
            assert service.suggest_offer(name).safety is not PromoSafety.LOSS

    def test_suggested_offer_is_capped_at_25_percent(self, tmp_path):
        db = StockDatabase(tmp_path / "fat.db")
        db.initialise()
        db.add_product("Huge Margin", cost_price="1.00", selling_price="20.00",
                       quantity=100, low_stock_threshold=5)
        assert MarketingService(db).suggest_offer("Huge Margin").discount_percent <= Decimal("25")

    def test_unknown_product(self, service):
        assert service.suggest_offer("Caviar") is None


class TestBundles:
    def test_bundle_maths(self, service):
        offer = service.build_bundle("White Bread", units=2, bundle_price="35.00")
        assert offer.normal_price_cents == 4000       # 2 x R20
        assert offer.promo_price_cents == 3500
        assert offer.saving_cents == 500
        assert offer.cost_cents == 3000               # 2 x R15
        assert offer.profit_cents == 500

    def test_bundle_can_be_unprofitable(self, service):
        offer = service.build_bundle("White Bread", units=2, bundle_price="28.00")
        assert offer.safety is PromoSafety.LOSS

    def test_units_available_is_calculated(self, service):
        offer = service.build_bundle("White Bread", units=2, bundle_price="35.00")
        assert offer.max_units_available == 30        # 60 loaves / 2
        assert offer.profit_if_all_sold_cents == 30 * 500

    def test_a_bundle_needs_at_least_two(self, service):
        with pytest.raises(ValueError):
            service.build_bundle("White Bread", units=1, bundle_price="20.00")

    def test_unknown_product(self, service):
        assert service.build_bundle("Caviar", 2, "35.00") is None


class TestTheFactualBrief:
    def test_brief_carries_the_numbers(self, service):
        offer = service.build_offer("White Bread", discount_percent=10)
        brief = service.campaign_brief(offer, Channel.WHATSAPP)

        assert "White Bread" in brief
        assert "R18.00" in brief and "R20.00" in brief
        assert "Stock available: 60" in brief

    def test_brief_never_leaks_the_cost_price(self, service):
        """The copywriter must not be able to publish what the owner paid."""
        offer = service.build_offer("White Bread", discount_percent=10)
        assert "R15.00" not in service.campaign_brief(offer, Channel.WHATSAPP)

    def test_brief_includes_the_shop_name(self, service):
        offer = service.build_offer("White Bread")
        assert "Mama T Spaza" in service.campaign_brief(offer, Channel.WHATSAPP)

    def test_brief_includes_channel_guidance(self, service):
        offer = service.build_offer("White Bread")
        assert "cardboard" in service.campaign_brief(offer, Channel.POSTER)
        assert "hashtags" in service.campaign_brief(offer, Channel.SOCIAL)

    def test_occasion_is_passed_through(self, service):
        offer = service.build_offer("White Bread")
        assert "month end" in service.campaign_brief(offer, Channel.WHATSAPP, "month end")

    def test_thin_margin_adds_a_caution(self, service):
        offer = service.build_offer("Airtime R12")
        assert "do not promise unlimited" in service.campaign_brief(offer, Channel.WHATSAPP)

    def test_bundle_brief_reads_correctly(self, service):
        offer = service.build_bundle("White Bread", 2, "35.00")
        assert "2 for R35.00" in offer.as_facts()


class TestOwnerSummary:
    def test_summary_shows_the_profit_impact(self, service):
        summary = service.build_offer("White Bread", discount_percent=10).as_summary()
        assert "R20.00 -> R18.00" in summary
        assert "R3.00" in summary
        assert "SAFE" in summary

    def test_shop_name_falls_back_to_a_default(self, tmp_path):
        db = StockDatabase(tmp_path / "n.db")
        db.initialise()
        assert MarketingService(db, shop_name="   ").shop_name == "KasiBiz Spaza"
