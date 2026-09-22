"""The Insights Agent: reporting the books, and refusing to go beyond them.

The most important tests in this file are the ones about silence. An empty shop
must produce "I cannot tell you that yet", not a confident-sounding sentence
built out of nothing.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.agents.insight_agent import InsightsAgent
from app.agents.intents import InsightIntent
from app.database.sqlite_db import StockDatabase
from app.services.analytics_service import AnalyticsService, Period
from app.services.sales_service import SalesService


@pytest.fixture
def db(tmp_path):
    database = StockDatabase(tmp_path / "books.db")
    database.initialise()
    database.add_product("White Bread", 15.00, 20.00, quantity=50, unit="loaf")
    database.add_product("Milk 1L", 17.50, 23.00, quantity=40)
    database.add_product("Simba Chips 36g", 6.50, 10.00, quantity=60)
    database.add_product("Tea Bags 26s", 22.00, 30.00, quantity=12)
    database.add_product("Candles 6-pack", 18.00, 25.00, quantity=1)
    return database


def sell(db, name, quantity, reference, days_ago=0):
    """Write a sale straight through the real path, dated in the past."""
    product = db.get_by_name(name)
    sale_id = db.record_sale(
        reference=reference,
        lines=[{
            "product_id": product.id, "product_name": product.name,
            "quantity": quantity,
            "unit_price_cents": product.selling_price_cents,
            "unit_cost_cents": product.cost_price_cents,
            "line_total_cents": product.selling_price_cents * quantity,
        }],
        paid_cents=product.selling_price_cents * quantity,
        change_cents=0,
    )
    if days_ago:
        when = datetime.now() - timedelta(days=days_ago)
        with db.connect() as conn:
            conn.execute("UPDATE sales SET sold_at = ? WHERE id = ?",
                         (when.strftime("%Y-%m-%d %H:%M:%S"), sale_id))
    return sale_id


@pytest.fixture
def traded(db):
    """A shop that has actually done business today."""
    sell(db, "White Bread", 10, "t1")
    sell(db, "White Bread", 4, "t2")
    sell(db, "Milk 1L", 6, "t3")
    sell(db, "Simba Chips 36g", 2, "t4")
    return db


@pytest.fixture
def agent(db):
    return InsightsAgent(service=AnalyticsService(db=db), use_llm=False)


class TestAnEmptyShopSaysNothing:
    """No sales means no insight. This is the whole point of the agent."""

    def test_best_sellers_with_no_sales(self, agent):
        response = agent.answer("What is selling well?")
        assert not response.has_data
        assert "no sales recorded" in response.text.lower()

    def test_sales_total_with_no_sales(self, agent):
        response = agent.answer("How much did I take this week?")
        assert not response.has_data

    def test_profit_with_no_sales(self, agent):
        response = agent.answer("What was my gross profit?")
        assert not response.has_data

    def test_no_product_is_called_popular_without_evidence(self, agent):
        text = agent.answer("What is selling well?").text.lower()
        for word in ("popular", "best seller", "top seller", "profitable"):
            assert word not in text

    def test_the_overview_still_helps_from_stock_levels(self, agent):
        """It has nothing to say about sales, but it can still read the shelf."""
        response = agent.answer("How is business?")
        assert not response.has_data
        assert "Candles 6-pack" in response.text

    def test_low_stock_works_without_any_sales(self, agent):
        response = agent.answer("What needs restocking?")
        assert "Candles 6-pack" in response.text


class TestBestSellers:
    def test_ranks_by_units_sold(self, traded, agent):
        response = agent.answer("What is selling well today?")
        assert response.has_data
        assert response.rows[0].startswith("White Bread")

    def test_names_the_period(self, traded, agent):
        assert "today" in agent.answer("What sold best today?").text

    def test_states_how_many_sales_it_is_based_on(self, traded, agent):
        assert "4 recorded sale" in agent.answer("What is selling well today?").text

    def test_gives_one_next_action(self, traded, agent):
        assert "Next:" in agent.answer("What is selling well today?").text

    def test_warns_when_the_ranking_rests_on_too_little(self, db, agent):
        sell(db, "White Bread", 1, "only-one")
        assert "early days" in agent.answer("What is selling well today?").text

    def test_no_warning_once_there_is_enough(self, traded, agent):
        assert "early days" not in agent.answer("What is selling well today?").text


class TestSlowMovers:
    def test_finds_what_is_not_moving(self, traded, agent):
        response = agent.answer("What is moving slowly?")
        assert "Tea Bags 26s" in response.text

    def test_a_product_that_sold_nothing_is_reported_as_none_sold(self, traded, agent):
        assert "none sold" in agent.answer("What is not selling?").text

    def test_says_how_much_cash_is_tied_up(self, traded, agent):
        assert "R" in agent.answer("What is sitting on the shelf?").text

    def test_only_counts_stock_the_shop_actually_holds(self, traded, db, agent):
        tea = db.get_by_name("Tea Bags 26s")
        db.set_stock(tea.id, 0)
        assert "Tea Bags 26s" not in agent.answer("What is moving slowly?").text


class TestSalesTotals:
    def test_totals_the_money_taken(self, traded, agent):
        response = agent.answer("How much did I take today?")
        expected = 14 * 2000 + 6 * 2300 + 2 * 1000
        assert f"R{expected / 100:,.2f}" in response.text

    def test_counts_the_sales_and_items(self, traded, agent):
        response = agent.answer("How much did I sell today?")
        assert "4 sale" in response.text
        assert "22 item" in response.text

    def test_reports_gross_profit(self, traded, agent):
        response = agent.answer("What was my profit today?")
        assert response.intent is InsightIntent.PROFIT
        assert "R" in response.text

    def test_profit_says_what_it_does_not_include(self, traded, agent):
        assert "not rent" in agent.answer("What was my profit today?").text


class TestPeriods:
    @pytest.mark.parametrize("question,expected", [
        ("How much did I take today?", Period.TODAY),
        ("What sold yesterday?", Period.YESTERDAY),
        ("How much this week?", Period.WEEK),
        ("What about last week?", Period.LAST_WEEK),
        ("Sales this month", Period.MONTH),
        ("What sells best all time?", Period.ALL),
    ])
    def test_reads_the_period(self, agent, question, expected):
        assert agent.detect_period(question) == expected

    def test_defaults_to_the_week(self, agent):
        assert agent.detect_period("What is selling well?") == Period.WEEK

    def test_yesterdays_sales_are_not_counted_as_today(self, db, agent):
        sell(db, "White Bread", 5, "old", days_ago=1)
        assert not agent.answer("How much did I take today?").has_data
        assert agent.answer("What did I sell yesterday?").has_data


class TestComparing:
    def test_says_so_when_there_is_nothing_to_compare_against(self, traded, agent):
        response = agent.answer("Is this week better than last week?")
        assert "cannot compare" in response.text.lower()

    def test_compares_when_both_periods_have_data(self, db, agent):
        sell(db, "White Bread", 10, "now-1")
        sell(db, "White Bread", 2, "then-1", days_ago=9)
        response = agent.answer("How does this week compare to last week?")
        assert response.intent is InsightIntent.COMPARE
        assert "up" in response.text or "down" in response.text

    def test_nothing_at_all_says_nothing(self, agent):
        assert not agent.answer("Is this week better than last week?").has_data


class TestEveryInsightIsTraceable:
    def test_the_facts_name_the_period(self, traded, agent):
        assert "Period:" in agent.answer("What is selling well today?").facts

    def test_the_facts_name_the_records_used(self, traded, agent):
        assert "recorded sale" in agent.answer("What is selling well today?").facts

    def test_no_figure_in_the_answer_is_invented(self, traded, agent):
        from app.utils.answer_check import verify_figures

        for question in ("What is selling well today?",
                         "How much did I take today?",
                         "What was my profit today?",
                         "What is moving slowly?"):
            response = agent.answer(question)
            check = verify_figures(response.facts, response.text)
            assert check.is_faithful, f"{question!r} invented {check.invented_money}"

    def test_it_all_works_with_no_ai(self, traded, agent):
        response = agent.answer("How is business today?")
        assert response.has_data
        assert not response.used_llm


class TestTheAnalyticsItself:
    def test_an_unknown_period_is_refused(self, db):
        with pytest.raises(ValueError):
            AnalyticsService(db=db).report("last_fortnight")

    def test_revenue_matches_what_was_sold(self, traded, db):
        report = AnalyticsService(db=db).report(Period.TODAY)
        assert report.revenue_cents == 14 * 2000 + 6 * 2300 + 2 * 1000

    def test_profit_is_revenue_minus_cost(self, traded, db):
        report = AnalyticsService(db=db).report(Period.TODAY)
        assert report.profit_cents == report.revenue_cents - report.cost_cents

    def test_the_average_sale(self, traded, db):
        report = AnalyticsService(db=db).report(Period.TODAY)
        assert report.average_sale_cents == report.revenue_cents // 4

    def test_an_empty_period_has_no_data(self, db):
        assert not AnalyticsService(db=db).report(Period.TODAY).has_data

    def test_units_are_grouped_per_product(self, traded, db):
        report = AnalyticsService(db=db).report(Period.TODAY)
        bread = next(p for p in report.products if p.product_name == "White Bread")
        assert bread.units == 14
