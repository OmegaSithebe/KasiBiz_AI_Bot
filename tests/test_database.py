"""Day 6 - tests for the SQLite stock database.

These tests never touch the real kasibiz.db. Each test gets a throwaway
database in a temporary folder, so they are safe to run any time:

    python -m pytest tests/test_database.py -v
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.database.sqlite_db import (
    DuplicateProductError,
    InsufficientStockError,
    ProductNotFoundError,
    StockDatabase,
    format_rand,
    resolve_db_path,
    to_cents,
    to_rand,
)


@pytest.fixture()
def db(tmp_path) -> StockDatabase:
    database = StockDatabase(tmp_path / "test_kasibiz.db")
    database.initialise()
    return database


@pytest.fixture()
def bread(db: StockDatabase):
    return db.add_product(
        name="White Bread",
        cost_price="15.00",
        selling_price="20.00",
        quantity=24,
        category="Bakery",
        unit="loaf",
        low_stock_threshold=6,
    )


# ------------------------------------------------------------------- money
class TestMoney:
    @pytest.mark.parametrize(
        "rand, cents",
        [("0", 0), ("1", 100), ("15.00", 1500), ("12.50", 1250), ("0.05", 5), (19.99, 1999)],
    )
    def test_to_cents(self, rand, cents):
        assert to_cents(rand) == cents

    def test_to_rand_round_trip(self):
        assert to_rand(to_cents("123.45")) == Decimal("123.45")

    def test_cents_never_lose_money_when_summed(self):
        """The reason we store cents: 0.1 + 0.2 != 0.3 in floating point."""
        total_cents = sum(to_cents("0.10") for _ in range(10))
        assert to_rand(total_cents) == Decimal("1.00")

    def test_format_rand(self):
        assert format_rand(1250) == "R12.50"
        assert format_rand(123456) == "R1,234.56"

    def test_negative_money_rejected(self):
        with pytest.raises(ValueError):
            to_cents("-5.00")

    def test_nonsense_money_rejected(self):
        with pytest.raises(ValueError):
            to_cents("twenty rand")


# ------------------------------------------------------------- db plumbing
class TestSetup:
    def test_initialise_creates_the_file(self, tmp_path):
        path = tmp_path / "nested" / "kasibiz.db"
        StockDatabase(path).initialise()
        assert path.exists()

    def test_initialise_is_safe_to_run_twice(self, db):
        db.initialise()
        assert db.count_products() == 0

    def test_resolve_relative_url(self):
        assert resolve_db_path("sqlite:///kasibiz.db").name == "kasibiz.db"

    def test_resolve_rejects_non_sqlite_url(self):
        with pytest.raises(ValueError):
            resolve_db_path("postgresql://user:pass@host/db")


# ----------------------------------------------------------------- CREATE
class TestAddProduct:
    def test_add_returns_the_saved_product(self, bread):
        assert bread.id > 0
        assert bread.name == "White Bread"
        assert bread.quantity == 24
        assert bread.cost_price == Decimal("15.00")
        assert bread.selling_price == Decimal("20.00")

    def test_prices_are_stored_as_cents(self, bread):
        assert bread.cost_price_cents == 1500
        assert bread.selling_price_cents == 2000

    def test_defaults_are_applied(self, db):
        product = db.add_product("Matches", cost_price="3.00", selling_price="5.00")
        assert product.quantity == 0
        assert product.category == "General"
        assert product.unit == "each"
        assert product.low_stock_threshold == 5

    def test_duplicate_name_is_rejected_case_insensitively(self, db, bread):
        with pytest.raises(DuplicateProductError):
            db.add_product("white bread", cost_price="15.00", selling_price="20.00")

    def test_empty_name_is_rejected(self, db):
        with pytest.raises(ValueError):
            db.add_product("   ", cost_price="1.00", selling_price="2.00")

    def test_negative_quantity_is_rejected(self, db):
        with pytest.raises(ValueError):
            db.add_product("Milk", cost_price="17.50", selling_price="23.00", quantity=-1)

    def test_name_is_trimmed(self, db):
        product = db.add_product("  Sugar 1kg  ", cost_price="24.00", selling_price="31.00")
        assert product.name == "Sugar 1kg"


# ------------------------------------------------------------------- READ
class TestReadProduct:
    def test_get_by_id(self, db, bread):
        assert db.get_product(bread.id).name == "White Bread"

    def test_get_missing_id_raises(self, db):
        with pytest.raises(ProductNotFoundError):
            db.get_product(999)

    def test_find_by_name_is_case_insensitive(self, db, bread):
        assert db.find_by_name("WHITE BREAD").id == bread.id

    def test_find_by_name_returns_none_when_absent(self, db):
        assert db.find_by_name("Caviar") is None

    def test_get_by_name_raises_when_absent(self, db):
        with pytest.raises(ProductNotFoundError):
            db.get_by_name("Caviar")

    def test_list_is_sorted_by_name(self, db):
        db.add_product("Sugar", cost_price="24.00", selling_price="31.00")
        db.add_product("Bread", cost_price="15.00", selling_price="20.00")
        db.add_product("Milk", cost_price="17.50", selling_price="23.00")
        assert [p.name for p in db.list_products()] == ["Bread", "Milk", "Sugar"]

    def test_list_filtered_by_category(self, db):
        db.add_product("Bread", cost_price="15.00", selling_price="20.00", category="Bakery")
        db.add_product("Milk", cost_price="17.50", selling_price="23.00", category="Dairy")
        assert [p.name for p in db.list_products(category="dairy")] == ["Milk"]

    def test_list_with_search(self, db):
        db.add_product("Coca-Cola 500ml", cost_price="12.00", selling_price="18.00")
        db.add_product("Bread", cost_price="15.00", selling_price="20.00")
        assert [p.name for p in db.list_products(search="cola")] == ["Coca-Cola 500ml"]

    def test_invalid_sort_column_is_rejected(self, db):
        with pytest.raises(ValueError):
            db.list_products(order_by="id; DROP TABLE products")

    def test_count_and_total_stock_value(self, db):
        db.add_product("Bread", cost_price="15.00", selling_price="20.00", quantity=10)
        db.add_product("Milk", cost_price="17.50", selling_price="23.00", quantity=4)
        assert db.count_products() == 2
        assert db.total_stock_value_cents() == (1500 * 10) + (1750 * 4)


# ---------------------------------------------------------------- ANALYSIS
class TestProfitAndLowStock:
    def test_profit_and_margin(self, bread):
        assert bread.profit_per_unit == Decimal("5.00")
        assert bread.margin_percent == Decimal("25.00")

    def test_stock_value(self, bread):
        assert bread.stock_value_cents == 1500 * 24

    def test_zero_price_does_not_crash_margin(self, db):
        freebie = db.add_product("Free Sample", cost_price="0", selling_price="0")
        assert freebie.margin_percent == Decimal("0.00")

    def test_low_stock_flag(self, db):
        product = db.add_product(
            "Candles", cost_price="18.00", selling_price="25.00",
            quantity=3, low_stock_threshold=3,
        )
        assert product.is_low_stock is True

    def test_low_stock_list_only_returns_products_at_or_below_threshold(self, db):
        db.add_product("Bread", cost_price="15.00", selling_price="20.00",
                       quantity=24, low_stock_threshold=6)
        db.add_product("Candles", cost_price="18.00", selling_price="25.00",
                       quantity=2, low_stock_threshold=3)
        db.add_product("Paraffin", cost_price="26.00", selling_price="34.00",
                       quantity=0, low_stock_threshold=3)
        low = db.list_low_stock()
        assert [p.name for p in low] == ["Paraffin", "Candles"]


# ----------------------------------------------------------------- UPDATE
class TestUpdateProduct:
    def test_update_selling_price(self, db, bread):
        updated = db.update_product(bread.id, selling_price="22.50")
        assert updated.selling_price == Decimal("22.50")
        assert updated.selling_price_cents == 2250

    def test_update_several_fields_at_once(self, db, bread):
        updated = db.update_product(bread.id, name="White Bread 700g", quantity=30,
                                    low_stock_threshold=10)
        assert updated.name == "White Bread 700g"
        assert updated.quantity == 30
        assert updated.low_stock_threshold == 10

    def test_update_missing_product_raises(self, db):
        with pytest.raises(ProductNotFoundError):
            db.update_product(999, quantity=1)

    def test_update_to_a_taken_name_is_rejected(self, db, bread):
        milk = db.add_product("Milk 1L", cost_price="17.50", selling_price="23.00")
        with pytest.raises(DuplicateProductError):
            db.update_product(milk.id, name="White Bread")

    def test_unknown_field_is_rejected(self, db, bread):
        with pytest.raises(ValueError):
            db.update_product(bread.id, colour="blue")

    def test_negative_quantity_is_rejected(self, db, bread):
        with pytest.raises(ValueError):
            db.update_product(bread.id, quantity=-5)


class TestStockLevels:
    def test_receiving_stock_increases_quantity(self, db, bread):
        assert db.adjust_stock(bread.id, +12).quantity == 36

    def test_selling_stock_decreases_quantity(self, db, bread):
        assert db.adjust_stock(bread.id, -4).quantity == 20

    def test_cannot_sell_more_than_you_have(self, db, bread):
        with pytest.raises(InsufficientStockError):
            db.adjust_stock(bread.id, -25)

    def test_failed_adjustment_leaves_stock_untouched(self, db, bread):
        with pytest.raises(InsufficientStockError):
            db.adjust_stock(bread.id, -100)
        assert db.get_product(bread.id).quantity == 24

    def test_stock_can_reach_exactly_zero(self, db, bread):
        assert db.adjust_stock(bread.id, -24).quantity == 0

    def test_set_stock_after_a_physical_count(self, db, bread):
        assert db.set_stock(bread.id, 19).quantity == 19


# ----------------------------------------------------------------- DELETE
class TestDeleteProduct:
    def test_delete_removes_the_product(self, db, bread):
        db.delete_product(bread.id)
        assert db.count_products() == 0
        with pytest.raises(ProductNotFoundError):
            db.get_product(bread.id)

    def test_delete_missing_product_raises(self, db):
        with pytest.raises(ProductNotFoundError):
            db.delete_product(999)

    def test_delete_all(self, db):
        db.add_product("Bread", cost_price="15.00", selling_price="20.00")
        db.add_product("Milk", cost_price="17.50", selling_price="23.00")
        assert db.delete_all_products() == 2
        assert db.count_products() == 0


# ------------------------------------------------------- persistence check
def test_data_survives_a_restart(tmp_path):
    """Prove the data is really on disk, not just in memory."""
    path = tmp_path / "kasibiz.db"

    first = StockDatabase(path)
    first.initialise()
    first.add_product("Bread", cost_price="15.00", selling_price="20.00", quantity=24)

    second = StockDatabase(path)
    reloaded = second.get_by_name("Bread")
    assert reloaded.quantity == 24
    assert reloaded.selling_price == Decimal("20.00")
