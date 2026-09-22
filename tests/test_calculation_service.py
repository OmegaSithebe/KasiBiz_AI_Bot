"""The arithmetic. If anything in KasiBiz is allowed to be boring, it is this.

These are the sums a shop owner would otherwise do on the back of a till slip,
and they have to be right every single time. The language model is not involved
in any of them.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.calculation_service import (
    BasketMaths,
    CalculationError,
    InsufficientPaymentError,
    basket_cost_cents,
    basket_profit_cents,
    basket_total_cents,
    change_cents,
    gross_profit_per_item_cents,
    line_gross_profit_cents,
    line_total_cents,
    margin_percent_of,
)


class TestLineTotal:
    """line_total = unit_price x quantity"""

    @pytest.mark.parametrize("price,quantity,expected", [
        (1550, 1, 1550),
        (1550, 2, 3100),
        (1550, 3, 4650),
        (999, 7, 6993),
        (0, 5, 0),
        (2000, 100, 200_000),
    ])
    def test_multiplies(self, price, quantity, expected):
        assert line_total_cents(price, quantity) == expected

    def test_a_cent_never_goes_missing(self):
        """The classic float bug: 0.1 x 3 is not 0.3. In cents it always is."""
        assert line_total_cents(10, 3) == 30

    def test_three_lots_of_r19_99(self):
        assert line_total_cents(1999, 3) == 5997

    @pytest.mark.parametrize("quantity", [0, -1, -100])
    def test_refuses_a_quantity_below_one(self, quantity):
        with pytest.raises(CalculationError):
            line_total_cents(1000, quantity)

    @pytest.mark.parametrize("quantity", [1.5, "2", None, True])
    def test_refuses_a_quantity_that_is_not_a_whole_number(self, quantity):
        with pytest.raises(CalculationError):
            line_total_cents(1000, quantity)

    def test_refuses_a_negative_price(self):
        with pytest.raises(CalculationError):
            line_total_cents(-100, 1)


class TestBasketTotal:
    """basket_total = sum of line totals"""

    def test_adds_the_lines_up(self):
        assert basket_total_cents([1550, 2300, 850]) == 4700

    def test_an_empty_basket_is_zero_not_an_error(self):
        assert basket_total_cents([]) == 0

    def test_a_hundred_small_amounts_still_land_exactly(self):
        assert basket_total_cents([1] * 100) == 100

    def test_ten_lots_of_ten_cents_is_exactly_one_rand(self):
        """In floats this is 0.9999999999999999. In cents it is 100."""
        assert basket_total_cents([10] * 10) == 100

    def test_accepts_a_generator(self):
        assert basket_total_cents(n * 100 for n in range(1, 5)) == 1000

    def test_refuses_a_negative_line(self):
        with pytest.raises(CalculationError):
            basket_total_cents([1000, -500])


class TestChange:
    """change = amount_paid - basket_total"""

    @pytest.mark.parametrize("total,paid,expected", [
        (4700, 5000, 300),
        (4700, 4700, 0),
        (1, 10000, 9999),
        (0, 0, 0),
        (2350, 5000, 2650),
    ])
    def test_works_out_the_change(self, total, paid, expected):
        assert change_cents(total, paid) == expected

    def test_exact_money_gives_no_change(self):
        assert change_cents(3500, 3500) == 0

    def test_refuses_to_invent_money(self):
        with pytest.raises(InsufficientPaymentError):
            change_cents(5000, 4500)

    def test_the_shortfall_is_spelled_out(self):
        with pytest.raises(InsufficientPaymentError) as caught:
            change_cents(5000, 4500)
        assert caught.value.short_cents == 500
        assert "R5.00" in str(caught.value)
        assert "R45.00" in str(caught.value)

    def test_one_cent_short_is_still_short(self):
        with pytest.raises(InsufficientPaymentError):
            change_cents(5000, 4999)


class TestProfit:
    """gross_profit_per_item = selling_price - cost_price"""

    def test_profit_per_item(self):
        assert gross_profit_per_item_cents(2000, 1500) == 500

    def test_a_loss_is_reported_honestly_not_clamped_to_zero(self):
        assert gross_profit_per_item_cents(1200, 1500) == -300

    def test_line_profit_multiplies_by_quantity(self):
        assert line_gross_profit_cents(2000, 1500, 4) == 2000

    def test_a_loss_multiplies_too(self):
        assert line_gross_profit_cents(1200, 1500, 3) == -900

    def test_basket_cost(self):
        assert basket_cost_cents([(1500, 2), (1750, 1)]) == 4750

    def test_basket_profit(self):
        assert basket_profit_cents(4700, 3100) == 1600

    @pytest.mark.parametrize("profit,total,expected", [
        (500, 2000, Decimal("25.00")),
        (0, 2000, Decimal("0.00")),
        (1000, 3000, Decimal("33.33")),
        (500, 0, Decimal("0.00")),
    ])
    def test_margin_percent(self, profit, total, expected):
        assert margin_percent_of(profit, total) == expected


class TestBasketMaths:
    """One object holding every figure, so two parts of the app cannot disagree."""

    @pytest.fixture
    def maths(self):
        return BasketMaths(total_cents=4700, cost_cents=3100, profit_cents=1600,
                           item_count=3, paid_cents=5000, change_cents=300)

    def test_rand_views(self, maths):
        assert maths.total == Decimal("47.00")
        assert maths.profit == Decimal("16.00")

    def test_margin(self, maths):
        assert maths.margin_percent == Decimal("34.04")

    def test_knows_whether_it_is_paid(self, maths):
        assert maths.is_paid
        assert not BasketMaths(100, 50, 50, 1).is_paid

    def test_facts_name_every_figure(self, maths):
        facts = maths.as_facts()
        for expected in ("R47.00", "R31.00", "R16.00", "R50.00", "R3.00"):
            assert expected in facts

    def test_facts_leave_out_payment_until_there_is_one(self):
        facts = BasketMaths(4700, 3100, 1600, 3).as_facts()
        assert "Paid" not in facts
        assert "Change" not in facts


class TestTheWorkedExample:
    """A real basket, checked end to end the way a shop owner would."""

    def test_two_bread_and_one_milk(self):
        bread_price, bread_cost = 2000, 1500
        milk_price, milk_cost = 2300, 1750

        bread_line = line_total_cents(bread_price, 2)
        milk_line = line_total_cents(milk_price, 1)
        assert bread_line == 4000
        assert milk_line == 2300

        total = basket_total_cents([bread_line, milk_line])
        assert total == 6300

        cost = basket_cost_cents([(bread_cost, 2), (milk_cost, 1)])
        assert cost == 4750

        assert basket_profit_cents(total, cost) == 1550
        assert change_cents(total, 10000) == 3700
