"""Set up the demonstration shop: products on the shelf and a week of sales.

This writes DEMONSTRATION DATA. It is not a real shop's books. Every product and
every sale created here is invented for the purpose of showing how KasiBiz
works, and the script says so on screen every time it runs.

    python scripts/seed_demo.py            # add products, keep anything already there
    python scripts/seed_demo.py --reset    # wipe first, then rebuild from scratch
    python scripts/seed_demo.py --no-sales # products only, so Insights has nothing
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.database.sqlite_db import (  # noqa: E402
    DuplicateProductError,
    StockDatabase,
    format_rand,
    get_db,
    to_cents,
)

PRODUCTS_CSV = Path(__file__).resolve().parents[1] / "data" / "products.csv"

BANNER = """
==============================================================================
  KASIBIZ DEMONSTRATION DATA
  The products and sales below are invented for demonstration purposes.
  They are not a real shop's records.
==============================================================================
"""

# How briskly each product moves, so the demo has believable best sellers and
# slow movers instead of everything selling the same amount.
POPULARITY: dict[str, int] = {
    "White Bread": 9, "Brown Bread": 7, "Milk 1L": 8, "Eggs 6-pack": 5,
    "Simba Chips 36g": 9, "Coca-Cola 500ml": 8, "Airtime R10": 7,
    "Maize Meal 2.5kg": 4, "Sugar 1kg": 4, "Rice 2kg": 3, "Tea Bags 26s": 2,
    "Cooking Oil 750ml": 3, "Baked Beans 410g": 2, "Washing Powder 1kg": 1,
    "Candles 6-pack": 1, "Paraffin 1L": 1, "Soap Bar": 2, "Toilet Paper 4s": 2,
}


def load_products(db: StockDatabase) -> int:
    if not PRODUCTS_CSV.exists():
        print(f"  ! {PRODUCTS_CSV} not found - no products loaded.")
        return 0

    added = 0
    with PRODUCTS_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                db.add_product(
                    name=row["name"],
                    cost_price=row["cost_price"],
                    selling_price=row["selling_price"],
                    quantity=int(row["quantity"]),
                    category=row.get("category", "General"),
                    unit=row.get("unit", "each"),
                    low_stock_threshold=int(row.get("low_stock_threshold", 5)),
                )
                added += 1
            except DuplicateProductError:
                continue
    return added


def make_sales(db: StockDatabase, days: int = 7, seed: int = 20260921) -> int:
    """Invent a week of believable trading, written through the real sale path."""
    rng = random.Random(seed)
    products = [p for p in db.list_products() if p.quantity > 0]
    if not products:
        return 0

    weighted = [p for p in products for _ in range(POPULARITY.get(p.name, 2))]
    if not weighted:
        return 0

    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    created = 0

    for day_offset in range(days - 1, -1, -1):
        day = midnight - timedelta(days=day_offset)
        # Quieter early in the week, busier towards the weekend.
        for _ in range(rng.randint(3, 8)):
            basket: dict[int, dict] = {}

            for _ in range(rng.randint(1, 3)):
                product = rng.choice(weighted)
                live = db.find_by_name(product.name)
                if live is None or live.quantity <= 0:
                    continue

                quantity = min(rng.randint(1, 3), live.quantity)
                line = basket.setdefault(live.id, {
                    "product_id": live.id,
                    "product_name": live.name,
                    "quantity": 0,
                    "unit_price_cents": live.selling_price_cents,
                    "unit_cost_cents": live.cost_price_cents,
                    "line_total_cents": 0,
                })
                if line["quantity"] + quantity > live.quantity:
                    continue
                line["quantity"] += quantity
                line["line_total_cents"] = line["unit_price_cents"] * line["quantity"]

            lines = [line for line in basket.values() if line["quantity"] > 0]
            if not lines:
                continue

            total = sum(line["line_total_cents"] for line in lines)
            paid = ((total + rng.choice([0, 500, 1000, 2000])) // 500) * 500
            paid = max(paid, total)

            sale_id = db.record_sale(
                reference=f"demo-{day.strftime('%Y%m%d')}-{created:04d}",
                lines=lines,
                paid_cents=paid,
                change_cents=paid - total,
                note="demonstration data",
            )

            # Spread the sale across trading hours instead of all at midnight.
            when = day + timedelta(hours=rng.randint(7, 18), minutes=rng.randint(0, 59))
            with db.connect() as conn:
                conn.execute("UPDATE sales SET sold_at = ? WHERE id = ?",
                             (when.strftime("%Y-%m-%d %H:%M:%S"), sale_id))
            created += 1

    return created


def restore_shelf(db: StockDatabase) -> int:
    """Put the stock back to the levels in products.csv.

    The invented sales above really do take stock off the shelf - that is the
    point of writing them through the real code path. But it leaves the shop
    stripped bare, and a demonstration has to start from the same place every
    time. So the shelf is restocked afterwards.
    """
    if not PRODUCTS_CSV.exists():
        return 0

    restored = 0
    with PRODUCTS_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            product = db.find_by_name(row["name"])
            if product is not None and product.quantity != int(row["quantity"]):
                db.set_stock(product.id, int(row["quantity"]))
                restored += 1
    return restored


def force_low_stock(db: StockDatabase) -> list[str]:
    """Make sure the demo always has something to warn about."""
    wanted = {"Paraffin 1L": 0, "Candles 6-pack": 1, "Milk 1L": 4}
    changed = []
    for name, quantity in wanted.items():
        product = db.find_by_name(name)
        if product is not None and product.quantity != quantity:
            db.set_stock(product.id, quantity)
            changed.append(f"{name} -> {quantity}")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the KasiBiz demonstration shop")
    parser.add_argument("--reset", action="store_true",
                        help="delete all products and sales first")
    parser.add_argument("--no-sales", action="store_true",
                        help="load products only, leaving no sales history")
    parser.add_argument("--days", type=int, default=7,
                        help="how many days of sales to invent (default 7)")
    args = parser.parse_args()

    print(BANNER)

    db = get_db()

    if args.reset:
        sales = db.delete_all_sales()
        products = db.delete_all_products()
        print(f"  Reset: removed {products} product(s) and {sales} sale(s).\n")

    added = load_products(db)
    print(f"  Products loaded: {added} new, {db.count_products()} on the shelf.")

    if args.no_sales:
        print("  Sales history: skipped (--no-sales).")
    else:
        created = make_sales(db, days=args.days)
        print(f"  Sales invented: {created} over the last {args.days} day(s).")
        restored = restore_shelf(db)
        print(f"  Shelf restocked after those sales: {restored} product(s).")

    lowered = force_low_stock(db)
    if lowered:
        print(f"  Forced low stock for the demo: {', '.join(lowered)}")

    print(f"  Stock value at cost: {format_rand(db.total_stock_value_cents())}")
    print(f"  Sales on record: {db.count_sales()}")

    print("\n  Ready. Start the app with:")
    print("      streamlit run streamlit_app/app.py")
    print("  Or the terminal version:")
    print("      python scripts/kasibiz.py --chat\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
