"""The Sales Agent: turning what an owner says into a basket, safely.

The agent's job is understanding, not arithmetic. So these tests ask two kinds
of question: did it understand, and did it refuse to do anything permanent
before being told to.
"""

from __future__ import annotations

import pytest

from app.agents.intents import SalesIntent
from app.agents.sales_agent import SalesAgent
from app.database.sqlite_db import StockDatabase
from app.services.sales_service import SalesService


@pytest.fixture
def db(tmp_path):
    database = StockDatabase(tmp_path / "agent.db")
    database.initialise()
    database.add_product("White Bread", 15.00, 20.00, quantity=24, unit="loaf")
    database.add_product("Brown Bread", 14.00, 19.00, quantity=10, unit="loaf")
    database.add_product("Milk 1L", 17.50, 23.00, quantity=6)
    database.add_product("Simba Chips 36g", 6.50, 10.00, quantity=40)
    database.add_product("Coca-Cola 500ml", 12.00, 18.00, quantity=30)
    database.add_product("Paraffin 1L", 26.00, 34.00, quantity=0)
    return database


@pytest.fixture
def agent(db):
    return SalesAgent(service=SalesService(db=db), use_llm=False)


class TestUnderstanding:
    @pytest.mark.parametrize("question,expected", [
        ("Start a new sale", SalesIntent.START_SALE),
        ("2 White Bread", SalesIntent.ADD_ITEM),
        ("the customer wants Milk 1L", SalesIntent.ADD_ITEM),
        ("show me the basket", SalesIntent.SHOW_BASKET),
        ("what is the total", SalesIntent.SHOW_BASKET),
        ("take off the Milk 1L", SalesIntent.REMOVE_ITEM),
        ("they paid R50", SalesIntent.PAYMENT),
        ("how much change", SalesIntent.PAYMENT),
        ("cancel it", SalesIntent.CANCEL),
        ("forget it", SalesIntent.CANCEL),
    ])
    def test_reads_the_intent(self, agent, question, expected):
        assert agent.detect_intent(question)[0] is expected

    def test_a_bare_product_name_means_add_it(self, agent):
        intent, product = agent.detect_intent("Simba Chips 36g")
        assert intent is SalesIntent.ADD_ITEM
        assert product == "Simba Chips 36g"

    def test_yes_only_means_confirm_when_a_sale_is_open(self, agent):
        assert agent.detect_intent("yes")[0] is not SalesIntent.CONFIRM
        agent.answer("2 White Bread")
        assert agent.detect_intent("yes")[0] is SalesIntent.CONFIRM

    def test_the_longest_product_name_wins(self, agent):
        assert agent.detect_intent("2 Coca-Cola 500ml")[1] == "Coca-Cola 500ml"


class TestReadingQuantities:
    @pytest.mark.parametrize("text,expected", [
        ("2 White Bread", 2),
        ("3 x White Bread", 3),
        ("White Bread x 2", None),
        ("two White Bread", 2),
        ("a White Bread", 1),
        ("White Bread", None),
        ("12 White Bread", 12),
    ])
    def test_finds_the_quantity(self, agent, text, expected):
        assert agent.extract_quantity(text, "White Bread") == expected

    def test_a_size_in_the_name_is_not_a_quantity(self, agent):
        """'Coca-Cola 500ml' must never be read as 500 bottles."""
        assert agent.extract_quantity("Coca-Cola 500ml", "Coca-Cola 500ml") is None

    def test_a_quantity_beside_a_sized_product_still_works(self, agent):
        assert agent.extract_quantity("2 Coca-Cola 500ml", "Coca-Cola 500ml") == 2

    def test_missing_quantity_defaults_to_one(self, agent):
        response = agent.answer("White Bread")
        assert response.basket.lines[0].quantity == 1


class TestReadingPayment:
    @pytest.mark.parametrize("text,expected", [
        ("they paid R50", 50),
        ("customer paid R100", 100),
        ("he gave me R20.50", "20.50"),
        ("paid with 50", 50),
    ])
    def test_finds_the_amount(self, agent, text, expected):
        assert str(agent.extract_payment(text)) == str(expected)

    def test_no_amount_mentioned(self, agent):
        assert agent.extract_payment("they paid") is None


class TestBuildingABasket:
    def test_adds_one_item(self, agent):
        response = agent.answer("2 White Bread")
        assert response.intent is SalesIntent.ADD_ITEM
        assert "R40.00" in response.text

    def test_adds_several_items_over_several_messages(self, agent):
        agent.answer("2 White Bread")
        agent.answer("1 Milk 1L")
        response = agent.answer("3 Simba Chips 36g")
        assert response.basket.item_count == 6
        assert response.basket.total_cents == 4000 + 2300 + 3000

    def test_the_running_total_is_shown_each_time(self, agent):
        agent.answer("2 White Bread")
        response = agent.answer("1 Milk 1L")
        assert "R63.00" in response.text

    def test_add_another_keeps_building(self, agent):
        agent.answer("1 White Bread")
        response = agent.answer("add another 1 White Bread")
        assert response.basket.lines[0].quantity == 2

    def test_nothing_is_written_while_building(self, agent, db):
        agent.answer("2 White Bread")
        agent.answer("1 Milk 1L")
        assert db.get_by_name("White Bread").quantity == 24
        assert db.count_sales() == 0


class TestWhenTheOwnerIsVague:
    def test_an_unknown_product_gets_a_helpful_answer(self, agent):
        response = agent.answer("sell 2 Caviar")
        assert response.error
        assert "does not stock" in response.text

    def test_a_near_miss_gets_a_suggestion(self, agent):
        response = agent.answer("2 White Bred")
        assert "White Bread" in response.text

    def test_an_ambiguous_name_asks_which_one(self, agent):
        response = agent.answer("2 Bread")
        assert "White Bread" in response.text and "Brown Bread" in response.text
        assert response.options

    def test_an_ambiguous_name_adds_nothing(self, agent):
        agent.answer("2 Bread")
        assert agent.service.basket is None or agent.service.basket.is_empty

    def test_no_product_at_all_asks_for_one(self, agent):
        response = agent.answer("start a new sale")
        assert "buying" in response.text.lower()

    def test_not_enough_stock_says_how_many_there_are(self, agent):
        response = agent.answer("7 Milk 1L")
        assert "only 6" in response.text

    def test_an_out_of_stock_product_is_refused(self, agent):
        response = agent.answer("1 Paraffin 1L")
        assert "out of stock" in response.text.lower()


class TestPaymentAndChange:
    def test_asks_for_payment_when_none_is_given(self, agent):
        agent.answer("2 White Bread")
        response = agent.answer("how much change")
        assert "R40.00" in response.text
        assert "how much" in response.text.lower()

    def test_works_out_the_change(self, agent):
        agent.answer("2 White Bread")
        response = agent.answer("they paid R50")
        assert "R10.00" in response.text
        assert response.needs_confirmation

    def test_not_enough_money_is_refused(self, agent):
        agent.answer("2 White Bread")
        response = agent.answer("they paid R30")
        assert response.error
        assert "not enough" in response.text.lower()

    def test_a_refused_payment_does_not_arm_the_confirmation(self, agent):
        agent.answer("2 White Bread")
        response = agent.answer("they paid R30")
        assert not response.needs_confirmation

    def test_payment_in_the_same_breath_as_the_item(self, agent):
        response = agent.answer("2 White Bread, they paid R50")
        assert "R10.00" in response.text

    def test_paying_with_nothing_in_the_basket(self, agent):
        response = agent.answer("they paid R50")
        assert response.error or "nothing in the basket" in response.text.lower()


class TestConfirming:
    def test_a_sale_is_not_saved_without_a_yes(self, agent, db):
        agent.answer("2 White Bread")
        agent.answer("they paid R50")
        assert db.count_sales() == 0
        assert db.get_by_name("White Bread").quantity == 24

    def test_yes_saves_it(self, agent, db):
        agent.answer("2 White Bread")
        agent.answer("they paid R50")
        response = agent.answer("yes")

        assert response.committed
        assert db.count_sales() == 1
        assert db.get_by_name("White Bread").quantity == 22

    def test_a_receipt_comes_back(self, agent):
        agent.answer("2 White Bread")
        agent.answer("they paid R50")
        response = agent.answer("yes")
        assert "R40.00" in response.text
        assert "R10.00" in response.text
        assert "White Bread" in response.text

    def test_saying_yes_twice_does_not_save_twice(self, agent, db):
        agent.answer("2 White Bread")
        agent.answer("they paid R50")
        agent.answer("yes")
        agent.answer("yes")
        assert db.count_sales() == 1
        assert db.get_by_name("White Bread").quantity == 22

    def test_yes_with_nothing_pending_does_nothing(self, agent, db):
        response = agent.answer("yes")
        assert db.count_sales() == 0
        assert not response.committed


class TestCancelling:
    def test_cancel_before_confirming_writes_nothing(self, agent, db):
        agent.answer("2 White Bread")
        agent.answer("they paid R50")
        response = agent.answer("cancel")

        assert db.count_sales() == 0
        assert db.get_by_name("White Bread").quantity == 24
        assert "not recorded" in response.text

    def test_cancel_clears_the_basket(self, agent):
        agent.answer("2 White Bread")
        agent.answer("cancel it")
        assert not agent.awaiting_confirmation

    def test_a_new_sale_can_start_straight_after_a_cancel(self, agent):
        agent.answer("2 White Bread")
        agent.answer("cancel")
        response = agent.answer("1 Milk 1L")
        assert response.basket.item_count == 1

    def test_removing_an_item_instead_of_cancelling(self, agent):
        agent.answer("2 White Bread")
        agent.answer("1 Milk 1L")
        response = agent.answer("take off the Milk 1L")
        assert response.basket.item_count == 2


class TestFiguresAreNeverInvented:
    def test_every_figure_in_the_answer_is_in_the_facts(self, agent):
        from app.utils.answer_check import verify_figures

        agent.answer("2 White Bread")
        response = agent.answer("they paid R50")
        assert verify_figures(response.facts, response.text).is_faithful

    def test_the_facts_carry_the_real_numbers(self, agent):
        agent.answer("2 White Bread")
        response = agent.answer("they paid R50")
        assert "R40.00" in response.facts
        assert "R50.00" in response.facts
        assert "R10.00" in response.facts

    def test_the_till_works_with_no_ai(self, agent, db):
        """Nothing in this journey needed the language model."""
        agent.answer("2 White Bread")
        agent.answer("1 Milk 1L")
        agent.answer("they paid R100")
        response = agent.answer("yes")
        assert response.committed
        assert not response.used_llm
