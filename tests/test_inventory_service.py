"""Day 7 - tests for the reorder rules.

These are pure logic tests: no AI, no internet, no API key.

    python -m pytest tests/test_inventory_service.py -v
"""

from __future__ import annotations

import pytest

from app.database.sqlite_db import StockDatabase
from app.services.inventory_service import InventoryService, Urgency


@pytest.fixture()
def service(tmp_path) -> InventoryService:
    db = StockDatabase(tmp_path / "test_stock.db")
    db.initialise()
    return InventoryService(db)


def add(service: InventoryService, name: str, quantity: int, alert_level: int = 6,
        cost: str = "10.00", sell: str = "15.00"):
    return service.db.add_product(
        name=name, cost_price=cost, selling_price=sell,
        quantity=quantity, low_stock_threshold=alert_level,
    )


class TestUrgencyRules:
    """The core rule: when does a product need attention?"""

    @pytest.mark.parametrize(
        "quantity, alert_level, expected",
        [
            (0, 6, Urgency.OUT_OF_STOCK),   # none left
            (1, 6, Urgency.CRITICAL),       # 1 of 6 -> half or less
            (3, 6, Urgency.CRITICAL),       # exactly half
            (4, 6, Urgency.LOW),            # above half, at or below alert
            (6, 6, Urgency.LOW),            # exactly on the alert level
            (7, 6, Urgency.OK),             # one above the alert level
            (50, 6, Urgency.OK),            # plenty
            (0, 0, Urgency.OUT_OF_STOCK),   # no alert level set, but empty
            (5, 0, Urgency.OK),             # no alert level set, has stock
        ],
    )
    def test_classification(self, service, quantity, alert_level, expected):
        product = add(service, "Test Item", quantity, alert_level)
        assert service.classify(product) is expected

    def test_alert_level_is_inclusive(self, service):
        """Sitting exactly on the alert level counts as low, not OK."""
        product = add(service, "Bread", quantity=6, alert_level=6)
        assert service.classify(product) is not Urgency.OK

    def test_urgency_ordering(self):
        assert Urgency.OUT_OF_STOCK.rank < Urgency.CRITICAL.rank
        assert Urgency.CRITICAL.rank < Urgency.LOW.rank
        assert Urgency.LOW.rank < Urgency.OK.rank


class TestReorderQuantity:
    def test_healthy_stock_suggests_nothing(self, service):
        product = add(service, "Bread", quantity=24, alert_level=6)
        assert service.suggest_reorder_quantity(product) == 0

    def test_tops_up_to_three_times_the_alert_level(self, service):
        # alert 6 -> target 18, currently 6, so order 12
        product = add(service, "Bread", quantity=6, alert_level=6)
        assert service.suggest_reorder_quantity(product) == 12

    def test_empty_shelf_orders_the_full_target(self, service):
        product = add(service, "Bread", quantity=0, alert_level=6)
        assert service.suggest_reorder_quantity(product) == 18

    def test_multiplier_is_configurable(self, tmp_path):
        db = StockDatabase(tmp_path / "x.db")
        db.initialise()
        svc = InventoryService(db, restock_multiplier=2)
        product = db.add_product("Bread", cost_price="10", selling_price="15",
                                 quantity=0, low_stock_threshold=5)
        assert svc.suggest_reorder_quantity(product) == 10

    def test_flagged_product_always_gets_at_least_one(self, service):
        product = add(service, "Odd Item", quantity=0, alert_level=0)
        assert service.suggest_reorder_quantity(product) >= 1

    def test_multiplier_must_be_sensible(self, service):
        with pytest.raises(ValueError):
            InventoryService(service.db, restock_multiplier=0)


class TestReorderCosts:
    def test_cost_and_profit_are_calculated(self, service):
        product = add(service, "Bread", quantity=0, alert_level=6,
                      cost="15.00", sell="20.00")
        alert = service.build_alert(product)
        assert alert.suggested_reorder_qty == 18
        assert alert.reorder_cost_cents == 18 * 1500       # R270.00
        assert alert.expected_profit_cents == 18 * 500     # R90.00

    def test_healthy_product_costs_nothing(self, service):
        product = add(service, "Bread", quantity=100, alert_level=6)
        alert = service.build_alert(product)
        assert alert.reorder_cost_cents == 0
        assert alert.needs_reorder is False


class TestLowStockQuery:
    def test_only_flagged_products_are_returned(self, service):
        add(service, "Bread", quantity=24, alert_level=6)      # OK
        add(service, "Milk", quantity=2, alert_level=6)        # CRITICAL
        add(service, "Sugar", quantity=5, alert_level=6)       # LOW
        assert [a.name for a in service.get_low_stock()] == ["Milk", "Sugar"]

    def test_worst_comes_first(self, service):
        add(service, "Sugar", quantity=5, alert_level=6)       # LOW
        add(service, "Milk", quantity=1, alert_level=6)        # CRITICAL
        add(service, "Paraffin", quantity=0, alert_level=6)    # OUT OF STOCK
        assert [a.name for a in service.get_low_stock()] == ["Paraffin", "Milk", "Sugar"]

    def test_healthy_shop_returns_nothing(self, service):
        add(service, "Bread", quantity=100, alert_level=6)
        assert service.get_low_stock() == []


class TestReorderPlan:
    def test_totals_add_up(self, service):
        add(service, "Bread", quantity=0, alert_level=6, cost="15.00", sell="20.00")
        add(service, "Milk", quantity=0, alert_level=6, cost="17.50", sell="23.00")
        plan = service.get_reorder_plan()

        assert plan.item_count == 2
        assert plan.total_cost_cents == (18 * 1500) + (18 * 1750)
        assert plan.total_expected_profit_cents == (18 * 500) + (18 * 550)

    def test_empty_plan_when_everything_is_stocked(self, service):
        add(service, "Bread", quantity=100, alert_level=6)
        plan = service.get_reorder_plan()
        assert plan.is_empty
        assert "Nothing needs reordering" in plan.as_text()

    def test_plan_groups_by_urgency(self, service):
        add(service, "Paraffin", quantity=0, alert_level=6)
        add(service, "Milk", quantity=1, alert_level=6)
        add(service, "Sugar", quantity=5, alert_level=6)
        plan = service.get_reorder_plan()
        assert [a.name for a in plan.out_of_stock] == ["Paraffin"]
        assert [a.name for a in plan.critical] == ["Milk"]

    def test_plan_text_mentions_cost(self, service):
        add(service, "Bread", quantity=0, alert_level=6, cost="15.00", sell="20.00")
        assert "R270.00" in service.get_reorder_plan().as_text()


class TestCheckOneProduct:
    def test_known_product(self, service):
        add(service, "White Bread", quantity=2, alert_level=6)
        alert = service.check_product("white bread")
        assert alert is not None
        assert alert.urgency is Urgency.CRITICAL

    def test_unknown_product_returns_none(self, service):
        assert service.check_product("Caviar") is None

    def test_sentence_is_readable(self, service):
        add(service, "Milk", quantity=1, alert_level=6, cost="17.50", sell="23.00")
        sentence = service.check_product("Milk").as_sentence()
        assert "Milk" in sentence and "CRITICAL" in sentence

    def test_healthy_sentence_says_no_reorder(self, service):
        add(service, "Bread", quantity=50, alert_level=6)
        assert "No need to reorder" in service.check_product("Bread").as_sentence()


class TestSummary:
    def test_counts_every_category(self, service):
        add(service, "Bread", quantity=24, alert_level=6)      # OK
        add(service, "Milk", quantity=1, alert_level=6)        # CRITICAL
        add(service, "Sugar", quantity=5, alert_level=6)       # LOW
        add(service, "Paraffin", quantity=0, alert_level=6)    # OUT OF STOCK
        summary = service.get_summary()

        assert summary.total_products == 4
        assert summary.total_units == 30
        assert summary.out_of_stock_count == 1
        assert summary.critical_count == 1
        assert summary.low_count == 1
        assert summary.healthy_count == 1
        assert summary.needs_attention_count == 3

    def test_empty_shop(self, service):
        summary = service.get_summary()
        assert summary.total_products == 0
        assert summary.stock_value_cents == 0

    def test_stock_value_uses_cost_price(self, service):
        add(service, "Bread", quantity=10, alert_level=6, cost="15.00", sell="20.00")
        assert service.get_summary().stock_value_cents == 10 * 1500


class TestChangingTheAlertLevel:
    def test_raising_the_level_can_flag_a_product(self, service):
        product = add(service, "Bread", quantity=10, alert_level=6)
        assert service.classify(product) is Urgency.OK

        alert = service.set_alert_level(product.id, 20)
        assert alert.urgency is not Urgency.OK

    def test_negative_level_is_rejected(self, service):
        product = add(service, "Bread", quantity=10)
        with pytest.raises(ValueError):
            service.set_alert_level(product.id, -1)
