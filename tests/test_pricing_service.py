"""Day 8 - tests for the pricing maths.

Pure logic: no AI, no internet, no API key.

    python -m pytest tests/test_pricing_service.py -v
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.database.sqlite_db import StockDatabase
from app.services.pricing_service import (
    PriceHealth,
    PricingService,
    margin_percent,
    markup_percent,
    round_to_practical,
)


@pytest.fixture()
def service(tmp_path) -> PricingService:
    db = StockDatabase(tmp_path / "pricing_test.db")
    db.initialise()
    return PricingService(db)


class TestMarkupVersusMargin:
    """The distinction that stops a shop under-pricing itself."""

    def test_the_classic_example(self):
        # Buy R15, sell R20, profit R5
        assert markup_percent(1500, 2000) == Decimal("33.33")   # against what you PAID
        assert margin_percent(1500, 2000) == Decimal("25.00")   # against what you CHARGE

    def test_they_are_never_the_same_when_there_is_profit(self):
        assert markup_percent(1000, 1500) != margin_percent(1000, 1500)

    def test_markup_is_always_the_bigger_number(self):
        assert markup_percent(1000, 1500) > margin_percent(1000, 1500)

    def test_doubling_the_price_is_100_markup_but_50_margin(self):
        assert markup_percent(1000, 2000) == Decimal("100.00")
        assert margin_percent(1000, 2000) == Decimal("50.00")

    def test_no_profit_means_zero_both_ways(self):
        assert markup_percent(1500, 1500) == Decimal("0.00")
        assert margin_percent(1500, 1500) == Decimal("0.00")

    def test_selling_below_cost_goes_negative(self):
        assert markup_percent(2000, 1500) < 0
        assert margin_percent(2000, 1500) < 0

    def test_zero_cost_does_not_crash(self):
        assert markup_percent(0, 1500) == Decimal("0.00")

    def test_zero_price_does_not_crash(self):
        assert margin_percent(1500, 0) == Decimal("0.00")


class TestPracticalRounding:
    """Spaza shops trade in cash, so prices must be payable in coins."""

    @pytest.mark.parametrize("raw, expected", [
        (2025, 2050),   # R20.25 -> R20.50
        (2024, 2000),   # R20.24 -> R20.00
        (1987, 2000),   # R19.87 -> R20.00
        (2000, 2000),   # already round
        (2050, 2050),   # already on a 50c step
        (7, 0),         # 7c rounds away entirely
    ])
    def test_rounds_to_nearest_fifty_cents(self, raw, expected):
        assert round_to_practical(raw) == expected

    def test_rounding_step_can_change(self):
        assert round_to_practical(1987, step_cents=100) == 2000
        assert round_to_practical(1940, step_cents=100) == 1900

    def test_invalid_step_is_rejected(self):
        with pytest.raises(ValueError):
            round_to_practical(1000, step_cents=0)


class TestSuggestingAPrice:
    """Day 8's core requirement: cost price + markup = selling price."""

    def test_basic_markup(self, service):
        s = service.suggest_price("15.00", 40)
        assert s.cost_price_cents == 1500
        assert s.exact_price_cents == 2100          # R15 + 40%
        assert s.suggested_price_cents == 2100
        assert s.profit_cents == 600

    def test_result_is_rounded_to_a_payable_price(self, service):
        s = service.suggest_price("14.50", 37)
        assert s.exact_price_cents == 1987          # R19.87 - awkward in cash
        assert s.suggested_price_cents == 2000      # R20.00 - easy
        assert s.rounding_adjustment_cents == 13

    def test_rounding_can_be_switched_off(self, service):
        s = service.suggest_price("14.50", 37, round_price=False)
        assert s.suggested_price_cents == 1987

    def test_default_markup_is_used_when_none_given(self, service):
        assert service.suggest_price("10.00").requested_markup_percent == Decimal("35.00")

    def test_default_markup_is_configurable(self, tmp_path):
        db = StockDatabase(tmp_path / "x.db")
        db.initialise()
        svc = PricingService(db, default_markup_percent=50)
        assert svc.suggest_price("10.00").suggested_price_cents == 1500

    def test_zero_markup_sells_at_cost(self, service):
        s = service.suggest_price("15.00", 0)
        assert s.suggested_price_cents == 1500
        assert s.profit_cents == 0

    def test_negative_markup_is_rejected(self, service):
        with pytest.raises(ValueError):
            service.suggest_price("15.00", -10)

    def test_negative_cost_is_rejected(self, service):
        with pytest.raises(ValueError):
            service.suggest_price("-15.00", 30)

    def test_suggestion_reports_its_real_percentages(self, service):
        s = service.suggest_price("15.00", 33.33)
        assert s.suggested_price_cents == 2000
        assert s.actual_markup_percent == Decimal("33.33")
        assert s.actual_margin_percent == Decimal("25.00")

    def test_sentence_is_readable(self, service):
        sentence = service.suggest_price("15.00", 33.33).as_sentence()
        assert "R15.00" in sentence and "R20.00" in sentence and "R5.00" in sentence


class TestWorkingBackwardsFromMargin:
    def test_target_margin_is_achieved(self, service):
        s = service.price_for_target_margin("15.00", 25)
        assert s.suggested_price_cents == 2000
        assert s.actual_margin_percent == Decimal("25.00")

    def test_fifty_percent_margin_means_double_the_cost(self, service):
        assert service.price_for_target_margin("20.00", 50).suggested_price_cents == 4000

    def test_zero_margin_sells_at_cost(self, service):
        assert service.price_for_target_margin("15.00", 0).suggested_price_cents == 1500

    def test_one_hundred_percent_margin_is_impossible(self, service):
        with pytest.raises(ValueError):
            service.price_for_target_margin("15.00", 100)

    def test_negative_margin_is_rejected(self, service):
        with pytest.raises(ValueError):
            service.price_for_target_margin("15.00", -5)


class TestPriceOptions:
    def test_three_options_are_offered(self, service):
        options = service.suggest_price_options("15.00")
        assert set(options) == {"Competitive", "Recommended", "Premium"}

    def test_options_increase_in_price(self, service):
        o = service.suggest_price_options("15.00")
        assert (o["Competitive"].suggested_price_cents
                < o["Recommended"].suggested_price_cents
                < o["Premium"].suggested_price_cents)


class TestPriceHealth:
    def test_selling_below_cost_is_a_loss(self, service):
        assert service.analyse("20.00", "15.00").health is PriceHealth.LOSS

    def test_selling_at_cost_is_a_loss_of_opportunity(self, service):
        assert service.analyse("20.00", "20.00").health is PriceHealth.TOO_LOW

    def test_a_normal_markup_is_healthy(self, service):
        assert service.analyse("15.00", "20.00").health is PriceHealth.HEALTHY

    def test_a_very_large_margin_is_flagged(self, service):
        assert service.analyse("10.00", "50.00").health is PriceHealth.HIGH

    def test_airtime_low_margin_is_not_wrongly_flagged(self, service):
        """Airtime is 5% everywhere. Calling it 'too cheap' would be wrong."""
        assert service.analyse("11.40", "12.00", category="Airtime").health is PriceHealth.HEALTHY

    def test_the_same_margin_is_too_low_for_snacks(self, service):
        assert service.analyse("11.40", "12.00", category="Snacks").health is PriceHealth.TOO_LOW

    def test_unknown_category_uses_the_default_minimum(self, service):
        assert service.minimum_margin_for("Something New") == Decimal("15")

    def test_analysis_sentence_names_the_product(self, service):
        sentence = service.analyse("15.00", "20.00", product_name="Bread").as_sentence()
        assert "Bread" in sentence and "HEALTHY" in sentence


class TestReviewingRealProducts:
    def test_a_healthy_product_passes(self, service):
        service.db.add_product("Bread", cost_price="15.00", selling_price="20.00",
                               category="Bakery")
        assert service.check_product("Bread").needs_attention is False

    def test_a_loss_making_product_is_caught(self, service):
        service.db.add_product("Mistake", cost_price="20.00", selling_price="18.00")
        analysis = service.check_product("Mistake")
        assert analysis.health is PriceHealth.LOSS
        assert analysis.profit_cents == -200

    def test_unknown_product_returns_none(self, service):
        assert service.check_product("Caviar") is None

    def test_shop_wide_review_puts_problems_first(self, service):
        service.db.add_product("Good", cost_price="15.00", selling_price="20.00",
                               category="Bakery")
        service.db.add_product("Bad", cost_price="20.00", selling_price="18.00",
                               category="Bakery")
        review = service.review_all()
        assert review.analyses[0].product_name == "Bad"
        assert len(review.losing_money) == 1

    def test_average_margin_is_calculated(self, service):
        service.db.add_product("A", cost_price="15.00", selling_price="20.00")  # 25%
        service.db.add_product("B", cost_price="10.00", selling_price="20.00")  # 50%
        assert service.review_all().average_margin_percent == Decimal("37.50")

    def test_empty_shop_review(self, service):
        assert "no products" in service.review_all().as_text().lower()

    def test_healthy_shop_says_so(self, service):
        service.db.add_product("Bread", cost_price="15.00", selling_price="20.00",
                               category="Bakery")
        assert "priced sensibly" in service.review_all().as_text()


class TestWhatIfAPriceChanges:
    def test_raising_a_price_shows_the_extra_profit(self, service):
        service.db.add_product("Bread", cost_price="15.00", selling_price="20.00", quantity=10)
        impact = service.price_change_impact("Bread", "22.00")

        assert impact.old_profit_each_cents == 500
        assert impact.new_profit_each_cents == 700
        assert impact.extra_profit_each_cents == 200
        assert impact.extra_profit_on_shelf_cents == 2000   # R20 across 10 loaves

    def test_dropping_a_price_shows_the_loss(self, service):
        service.db.add_product("Bread", cost_price="15.00", selling_price="20.00", quantity=10)
        impact = service.price_change_impact("Bread", "18.00")
        assert impact.extra_profit_each_cents == -200

    def test_unknown_product_returns_none(self, service):
        assert service.price_change_impact("Caviar", "20.00") is None

    def test_sentence_mentions_both_prices(self, service):
        service.db.add_product("Bread", cost_price="15.00", selling_price="20.00", quantity=10)
        sentence = service.price_change_impact("Bread", "22.00").as_sentence()
        assert "R20.00" in sentence and "R22.00" in sentence


class TestApplyingAPrice:
    def test_price_is_actually_saved(self, service):
        service.db.add_product("Bread", cost_price="15.00", selling_price="20.00")
        updated = service.apply_suggested_price("Bread", "22.00")
        assert updated.selling_price_cents == 2200
        assert service.db.get_by_name("Bread").selling_price_cents == 2200

    def test_unknown_product_returns_none(self, service):
        assert service.apply_suggested_price("Caviar", "20.00") is None


class TestServiceSetup:
    def test_negative_default_markup_is_rejected(self, service):
        with pytest.raises(ValueError):
            PricingService(service.db, default_markup_percent=-5)

    def test_invalid_rounding_is_rejected(self, service):
        with pytest.raises(ValueError):
            PricingService(service.db, rounding_cents=0)
