"""The till: every way a sale can go right, and every way it can go wrong.

The tests that matter most here are the ones about failure. A sale that saves
correctly is the easy case. A sale that falls over halfway through must leave
the shelf exactly as it was.
"""

from __future__ import annotations

import pytest

from app.database.sqlite_db import DuplicateSaleError, StockDatabase
from app.services.calculation_service import InsufficientPaymentError
from app.services.sales_service import (
    AmbiguousProductError,
    Basket,
    EmptyBasketError,
    NotEnoughStockError,
    SalesError,
    SalesService,
    UnknownProductError,
)


@pytest.fixture
def db(tmp_path):
    database = StockDatabase(tmp_path / "till.db")
    database.initialise()
    database.add_product("White Bread", 15.00, 20.00, quantity=24, unit="loaf")
    database.add_product("Brown Bread", 14.00, 19.00, quantity=10, unit="loaf")
    database.add_product("Milk 1L", 17.50, 23.00, quantity=6)
    database.add_product("Simba Chips 36g", 6.50, 10.00, quantity=40)
    database.add_product("Paraffin 1L", 26.00, 34.00, quantity=0)
    database.add_product("Candles 6-pack", 18.00, 25.00, quantity=1)
    return database


@pytest.fixture
def till(db):
    return SalesService(db=db)


class TestMatchingAProduct:
    def test_exact_name(self, till):
        assert till.match_product("White Bread").name == "White Bread"

    def test_case_does_not_matter(self, till):
        assert till.match_product("white bread").name == "White Bread"

    def test_a_partial_name_that_is_unique_is_accepted(self, till):
        assert till.match_product("Simba").name == "Simba Chips 36g"

    def test_a_partial_name_that_is_not_unique_is_refused(self, till):
        """'Bread' means two things here. Guessing would sell the wrong loaf."""
        with pytest.raises(AmbiguousProductError) as caught:
            till.match_product("Bread")
        assert "White Bread" in caught.value.matches
        assert "Brown Bread" in caught.value.matches

    def test_an_unknown_product_says_so(self, till):
        with pytest.raises(UnknownProductError):
            till.match_product("Caviar")

    def test_a_near_miss_gets_a_suggestion(self, till):
        with pytest.raises(UnknownProductError) as caught:
            till.match_product("White Bred")
        assert "White Bread" in caught.value.suggestions

    def test_an_empty_name_is_refused(self, till):
        with pytest.raises(UnknownProductError):
            till.match_product("   ")


class TestBuildingTheBasket:
    def test_one_item(self, till):
        line = till.add_item("White Bread", 2)
        assert line.quantity == 2
        assert line.unit_price_cents == 2000
        assert line.line_total_cents == 4000

    def test_the_price_comes_from_the_database_not_the_caller(self, till):
        assert till.add_item("Milk 1L").unit_price_cents == 2300

    def test_a_confirmed_price_may_override_it(self, till):
        line = till.add_item("Milk 1L", 1, unit_price=25.00)
        assert line.unit_price_cents == 2500

    def test_several_products_in_one_basket(self, till):
        till.add_item("White Bread", 2)
        till.add_item("Milk 1L", 1)
        till.add_item("Simba Chips 36g", 3)
        basket = till.current_basket()
        assert len(basket.lines) == 3
        assert basket.item_count == 6
        assert basket.total_cents == 4000 + 2300 + 3000

    def test_adding_the_same_product_twice_merges_it(self, till):
        till.add_item("White Bread", 2)
        till.add_item("White Bread", 1)
        basket = till.current_basket()
        assert len(basket.lines) == 1
        assert basket.lines[0].quantity == 3

    def test_default_quantity_is_one(self, till):
        assert till.add_item("White Bread").quantity == 1

    @pytest.mark.parametrize("quantity", [0, -1, -50])
    def test_zero_or_negative_quantity_is_refused(self, till, quantity):
        with pytest.raises(SalesError):
            till.add_item("White Bread", quantity)

    def test_a_fractional_quantity_is_refused(self, till):
        with pytest.raises(SalesError):
            till.add_item("White Bread", 2.5)

    def test_cannot_add_more_than_the_shop_has(self, till):
        with pytest.raises(NotEnoughStockError) as caught:
            till.add_item("Milk 1L", 7)
        assert caught.value.available == 6

    def test_an_out_of_stock_product_cannot_be_sold(self, till):
        with pytest.raises(NotEnoughStockError):
            till.add_item("Paraffin 1L", 1)

    def test_topping_up_past_the_shelf_is_caught(self, till):
        """4 + 3 is 7, and there are only 6. The second add must fail."""
        till.add_item("Milk 1L", 4)
        with pytest.raises(NotEnoughStockError):
            till.add_item("Milk 1L", 3)

    def test_nothing_is_written_while_building(self, till, db):
        till.add_item("White Bread", 5)
        assert db.get_by_name("White Bread").quantity == 24
        assert db.count_sales() == 0

    def test_removing_an_item(self, till):
        till.add_item("White Bread", 2)
        till.add_item("Milk 1L", 1)
        assert till.remove_item("White Bread") is True
        assert till.current_basket().item_count == 1

    def test_removing_something_not_on_the_basket(self, till):
        till.add_item("White Bread", 2)
        assert till.remove_item("Simba Chips 36g") is False

    def test_setting_a_quantity_outright(self, till):
        till.add_item("White Bread", 2)
        till.set_quantity("White Bread", 5)
        assert till.current_basket().lines[0].quantity == 5


class TestTheSums:
    def test_the_total(self, till):
        till.add_item("White Bread", 2)
        till.add_item("Milk 1L", 1)
        assert till.current_basket().total_cents == 6300

    def test_the_cost_and_the_profit(self, till):
        till.add_item("White Bread", 2)
        till.add_item("Milk 1L", 1)
        basket = till.current_basket()
        assert basket.cost_cents == 1500 * 2 + 1750
        assert basket.profit_cents == 6300 - 4750

    def test_the_change(self, till):
        till.add_item("White Bread", 2)
        assert till.set_payment(50) == 1000

    def test_exact_money(self, till):
        till.add_item("White Bread", 2)
        assert till.set_payment(40) == 0

    def test_not_enough_money_is_refused(self, till):
        till.add_item("White Bread", 2)
        with pytest.raises(InsufficientPaymentError):
            till.set_payment(30)

    def test_a_refused_payment_is_not_recorded(self, till):
        till.add_item("White Bread", 2)
        with pytest.raises(InsufficientPaymentError):
            till.set_payment(30)
        assert till.current_basket().paid_cents is None

    def test_paying_for_an_empty_basket_is_refused(self, till):
        with pytest.raises(EmptyBasketError):
            till.set_payment(50)

    def test_the_summary_shows_the_working(self, till):
        till.add_item("White Bread", 2)
        till.set_payment(50)
        summary = till.current_basket().as_summary()
        assert "2 x White Bread" in summary
        assert "R40.00" in summary
        assert "R50.00" in summary
        assert "R10.00" in summary


class TestConfirmation:
    def test_a_basket_is_not_ready_until_it_has_items(self, till):
        ready, reason = till.ready_to_confirm()
        assert not ready
        assert "nothing in the basket" in reason

    def test_a_basket_is_not_ready_until_it_is_paid(self, till):
        till.add_item("White Bread", 2)
        ready, reason = till.ready_to_confirm()
        assert not ready
        assert "R40.00" in reason

    def test_a_basket_is_ready_once_it_is_paid_for(self, till):
        till.add_item("White Bread", 2)
        till.set_payment(50)
        ready, _ = till.ready_to_confirm()
        assert ready

    def test_confirming_too_early_is_refused(self, till):
        till.add_item("White Bread", 2)
        with pytest.raises(SalesError):
            till.confirm_sale()

    def test_confirming_writes_the_sale(self, till, db):
        till.add_item("White Bread", 2)
        till.add_item("Milk 1L", 1)
        till.set_payment(100)
        sale = till.confirm_sale()

        assert sale.sale_id > 0
        assert sale.total_cents == 6300
        assert sale.change_cents == 3700
        assert db.count_sales() == 1

    def test_confirming_takes_the_stock_off_the_shelf(self, till, db):
        till.add_item("White Bread", 2)
        till.add_item("Milk 1L", 1)
        till.set_payment(100)
        till.confirm_sale()

        assert db.get_by_name("White Bread").quantity == 22
        assert db.get_by_name("Milk 1L").quantity == 5

    def test_the_stored_sale_keeps_every_line(self, till, db):
        till.add_item("White Bread", 2)
        till.add_item("Simba Chips 36g", 3)
        till.set_payment(100)
        sale = till.confirm_sale()

        stored = db.get_sale(sale.sale_id)
        assert len(stored["items"]) == 2
        assert stored["profit_cents"] == sale.profit_cents

    def test_the_price_is_frozen_into_the_record(self, till, db):
        """Repricing tomorrow must not rewrite what happened today."""
        till.add_item("White Bread", 2)
        till.set_payment(50)
        sale = till.confirm_sale()

        bread = db.get_by_name("White Bread")
        db.update_product(bread.id, selling_price=30.00)

        stored = db.get_sale(sale.sale_id)
        assert stored["items"][0]["unit_price_cents"] == 2000
        assert stored["total_cents"] == 4000

    def test_a_receipt_comes_back(self, till):
        till.add_item("White Bread", 2)
        till.set_payment(50)
        receipt = till.confirm_sale().as_receipt("Mama T Spaza")
        assert "Mama T Spaza" in receipt
        assert "White Bread" in receipt
        assert "R40.00" in receipt
        assert "R10.00" in receipt


class TestWhenThingsGoWrong:
    def test_cancelling_leaves_the_shelf_alone(self, till, db):
        till.add_item("White Bread", 5)
        till.add_item("Milk 1L", 2)
        message = till.cancel_sale()

        assert "not recorded" in message
        assert db.get_by_name("White Bread").quantity == 24
        assert db.get_by_name("Milk 1L").quantity == 6
        assert db.count_sales() == 0

    def test_cancelling_nothing_is_not_an_error(self, till):
        assert "nothing to cancel" in till.cancel_sale().lower()

    def test_cancelling_starts_a_clean_basket(self, till):
        till.add_item("White Bread", 2)
        till.cancel_sale()
        assert till.current_basket().is_empty

    def test_confirming_twice_does_not_record_two_sales(self, till, db):
        till.add_item("White Bread", 2)
        till.set_payment(50)
        basket = till.current_basket()
        till.confirm_sale(basket)

        with pytest.raises(SalesError):
            till.confirm_sale(basket)
        assert db.count_sales() == 1

    def test_a_retry_with_the_same_reference_is_rejected_by_the_database(self, till, db):
        """The UNIQUE index, not the app, is what makes a double-tap safe."""
        till.add_item("White Bread", 2)
        till.set_payment(50)
        basket = till.current_basket()
        till.confirm_sale(basket)

        with pytest.raises(DuplicateSaleError):
            db.record_sale(
                reference=basket.reference,
                lines=[line.as_record() for line in basket.lines],
                paid_cents=5000, change_cents=1000,
            )
        assert db.count_sales() == 1
        assert db.get_by_name("White Bread").quantity == 22

    def test_a_sale_that_fails_halfway_changes_nothing(self, till, db):
        """The second line has no stock. The first line must not be taken either."""
        bread = db.get_by_name("White Bread")
        candles = db.get_by_name("Candles 6-pack")

        with pytest.raises(Exception):
            db.record_sale(
                reference="half-way",
                lines=[
                    {"product_id": bread.id, "product_name": bread.name, "quantity": 2,
                     "unit_price_cents": 2000, "unit_cost_cents": 1500,
                     "line_total_cents": 4000},
                    {"product_id": candles.id, "product_name": candles.name, "quantity": 9,
                     "unit_price_cents": 2500, "unit_cost_cents": 1800,
                     "line_total_cents": 22500},
                ],
                paid_cents=30000, change_cents=3500,
            )

        assert db.get_by_name("White Bread").quantity == 24
        assert db.get_by_name("Candles 6-pack").quantity == 1
        assert db.count_sales() == 0

    def test_stock_can_never_go_negative(self, till, db):
        candles = db.get_by_name("Candles 6-pack")
        with pytest.raises(Exception):
            db.record_sale(
                reference="too-many",
                lines=[{"product_id": candles.id, "product_name": candles.name,
                        "quantity": 5, "unit_price_cents": 2500,
                        "unit_cost_cents": 1800, "line_total_cents": 12500}],
                paid_cents=12500, change_cents=0,
            )
        assert db.get_by_name("Candles 6-pack").quantity == 1

    def test_a_sale_with_no_lines_is_refused(self, db):
        with pytest.raises(ValueError):
            db.record_sale(reference="empty", lines=[], paid_cents=0, change_cents=0)


class TestBasketHousekeeping:
    def test_a_new_sale_throws_the_old_basket_away(self, till):
        till.add_item("White Bread", 2)
        till.start_sale()
        assert till.current_basket().is_empty

    def test_every_basket_gets_its_own_reference(self):
        assert Basket().reference != Basket().reference

    def test_an_open_basket_is_visible_to_the_coordinator(self, till):
        assert till.has_open_basket is False
        till.add_item("White Bread", 1)
        assert till.has_open_basket is True

    def test_a_saved_basket_is_no_longer_open(self, till):
        till.add_item("White Bread", 1)
        till.set_payment(20)
        till.confirm_sale()
        assert till.has_open_basket is False
