"""Day 6 - hands-on walkthrough of the KasiBiz stock database.

Runs every operation the shop owner needs, against the real kasibiz.db:

    python scripts/db_demo.py           # add, view, update, delete walkthrough
    python scripts/db_demo.py --seed    # load data/products.csv into the database
    python scripts/db_demo.py --list    # just show what is in stock
    python scripts/db_demo.py --reset   # empty the products table
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.sqlite_db import (  # noqa: E402
    DuplicateProductError,
    InsufficientStockError,
    Product,
    StockDatabase,
    format_rand,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_CSV = PROJECT_ROOT / "data" / "products.csv"


def heading(text: str) -> None:
    print(f"\n{text}")
    print("-" * len(text))


def show_table(products: list[Product]) -> None:
    if not products:
        print("  (no products)")
        return

    print(f"  {'ID':>3}  {'PRODUCT':<22}{'CATEGORY':<13}{'QTY':>5}  "
          f"{'COST':>9}{'SELL':>9}{'PROFIT':>9}{'MARGIN':>8}  LOW?")
    for p in products:
        flag = "LOW" if p.is_low_stock else ""
        print(f"  {p.id:>3}  {p.name[:21]:<22}{p.category[:12]:<13}{p.quantity:>5}  "
              f"{format_rand(p.cost_price_cents):>9}{format_rand(p.selling_price_cents):>9}"
              f"{format_rand(p.profit_per_unit_cents):>9}{p.margin_percent:>7}%  {flag}")


def seed_from_csv(db: StockDatabase) -> None:
    heading(f"Loading stock from {PRODUCTS_CSV.name}")
    if not PRODUCTS_CSV.exists():
        print(f"  Missing file: {PRODUCTS_CSV}")
        return

    added = skipped = 0
    with PRODUCTS_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                db.add_product(
                    name=row["name"],
                    category=row["category"],
                    unit=row["unit"],
                    cost_price=row["cost_price"],
                    selling_price=row["selling_price"],
                    quantity=int(row["quantity"]),
                    low_stock_threshold=int(row["low_stock_threshold"]),
                )
                added += 1
            except DuplicateProductError:
                skipped += 1

    print(f"  Added {added} products, skipped {skipped} already in the database.")


def walkthrough(db: StockDatabase) -> None:
    heading("1. ADD - a new product arrives from the supplier")
    try:
        product = db.add_product(
            name="Demo Amasi 500ml",
            category="Dairy",
            unit="bottle",
            cost_price="14.50",
            selling_price="20.00",
            quantity=12,
            low_stock_threshold=4,
        )
    except DuplicateProductError:
        product = db.get_by_name("Demo Amasi 500ml")
        print("  Already existed from a previous run - reusing it.")

    print(f"  Added #{product.id} {product.name}")
    print(f"  Cost {format_rand(product.cost_price_cents)}, "
          f"sell {format_rand(product.selling_price_cents)}, "
          f"profit {format_rand(product.profit_per_unit_cents)} per bottle "
          f"({product.margin_percent}% margin)")

    heading("2. READ - look it up by name, the way the owner would")
    found = db.get_by_name("demo amasi 500ml")
    print(f"  Found '{found.name}' with {found.quantity} in stock "
          f"(search was case-insensitive)")

    heading("3. UPDATE - the supplier raised the price, so we raise ours")
    updated = db.update_product(product.id, cost_price="16.00", selling_price="22.00")
    print(f"  New cost {format_rand(updated.cost_price_cents)}, "
          f"new price {format_rand(updated.selling_price_cents)}, "
          f"profit now {format_rand(updated.profit_per_unit_cents)} "
          f"({updated.margin_percent}% margin)")

    heading("4. STOCK OUT - a customer buys 3 bottles")
    after_sale = db.adjust_stock(product.id, -3)
    print(f"  Sold 3. Stock went from {updated.quantity} to {after_sale.quantity}")

    heading("5. STOCK IN - a delivery of 10 arrives")
    after_delivery = db.adjust_stock(product.id, +10)
    print(f"  Received 10. Stock is now {after_delivery.quantity}")

    heading("6. SAFETY - the database refuses to go into negative stock")
    try:
        db.adjust_stock(product.id, -500)
    except InsufficientStockError as exc:
        print(f"  Blocked, as intended: {exc}")
    print(f"  Stock is untouched at {db.get_product(product.id).quantity}")

    heading("7. LOW STOCK ALERT - what needs reordering")
    low = db.list_low_stock()
    if low:
        for p in low:
            print(f"  {p.name}: only {p.quantity} left (alert at {p.low_stock_threshold})")
    else:
        print("  Nothing is running low.")

    heading("8. DELETE - remove the demo product")
    db.delete_product(product.id)
    print(f"  Deleted #{product.id}. Products remaining: {db.count_products()}")


def summary(db: StockDatabase) -> None:
    heading("CURRENT STOCK")
    show_table(db.list_products())

    total = db.total_stock_value_cents()
    low = db.list_low_stock()
    print(f"\n  Products: {db.count_products()}")
    print(f"  Cash tied up in stock (at cost): {format_rand(total)}")
    print(f"  Products needing a reorder: {len(low)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="KasiBiz stock database demo")
    parser.add_argument("--seed", action="store_true", help="load data/products.csv")
    parser.add_argument("--list", action="store_true", help="only show current stock")
    parser.add_argument("--reset", action="store_true", help="delete every product")
    args = parser.parse_args()

    db = StockDatabase()
    db.initialise()
    print(f"KasiBiz stock database: {db.db_path}")

    if args.reset:
        removed = db.delete_all_products()
        print(f"\nRemoved {removed} products.")
        return 0

    if args.list:
        summary(db)
        return 0

    if args.seed or db.count_products() == 0:
        seed_from_csv(db)

    walkthrough(db)
    summary(db)
    print("\nDay 6 complete - the stock database works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
