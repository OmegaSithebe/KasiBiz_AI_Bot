"""SQLite stock database for KasiBiz: add, view, update and delete products.

Money rule: prices are stored in the database as whole CENTS (INTEGER) and are
exposed to the rest of the app as Decimal Rand. Never use float for money.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator

from app.utils.config import PROJECT_ROOT, get_database_url

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

Money = Decimal | int | float | str


class DatabaseError(RuntimeError):
    """Base class for stock database problems."""


class ProductNotFoundError(DatabaseError):
    """Raised when a product id or name does not exist."""


class DuplicateProductError(DatabaseError):
    """Raised when a product name is already in use."""


class InsufficientStockError(DatabaseError):
    """Raised when a stock reduction would take quantity below zero."""


class DuplicateSaleError(DatabaseError):
    """Raised when the same basket is confirmed twice."""


class SaleNotFoundError(DatabaseError):
    """Raised when a sale id does not exist."""


# --------------------------------------------------------------------- money
def to_cents(amount: Money) -> int:
    """Convert Rand (R12.50) to whole cents (1250), rounding half up."""
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{amount!r} is not a valid amount of money.") from exc

    if value < 0:
        raise ValueError("Money amounts cannot be negative.")
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_rand(cents: int) -> Decimal:
    """Convert whole cents (1250) back to Rand (Decimal('12.50'))."""
    return (Decimal(cents) / 100).quantize(Decimal("0.01"))


def format_rand(cents: int) -> str:
    """Format cents for display, e.g. 1250 -> 'R12.50'."""
    return f"R{to_rand(cents):,.2f}"


# ------------------------------------------------------------------- product
@dataclass(frozen=True)
class Product:
    id: int
    name: str
    category: str
    unit: str
    cost_price_cents: int
    selling_price_cents: int
    quantity: int
    low_stock_threshold: int
    barcode: str | None
    created_at: str
    updated_at: str

    @property
    def cost_price(self) -> Decimal:
        return to_rand(self.cost_price_cents)

    @property
    def selling_price(self) -> Decimal:
        return to_rand(self.selling_price_cents)

    @property
    def profit_per_unit_cents(self) -> int:
        return self.selling_price_cents - self.cost_price_cents

    @property
    def profit_per_unit(self) -> Decimal:
        return to_rand(self.profit_per_unit_cents)

    @property
    def margin_percent(self) -> Decimal:
        """Profit as a percentage of the selling price."""
        if self.selling_price_cents == 0:
            return Decimal("0.00")
        ratio = Decimal(self.profit_per_unit_cents) / Decimal(self.selling_price_cents)
        return (ratio * 100).quantize(Decimal("0.01"))

    @property
    def stock_value_cents(self) -> int:
        """What this shelf is worth at cost price."""
        return self.cost_price_cents * self.quantity

    @property
    def is_low_stock(self) -> bool:
        return self.quantity <= self.low_stock_threshold

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Product":
        return cls(**{key: row[key] for key in row.keys()})


# ------------------------------------------------------------------ database
def resolve_db_path(database_url: str | None = None) -> Path:
    """Turn a DATABASE_URL such as 'sqlite:///kasibiz.db' into a real file path."""
    url = (database_url or get_database_url()).strip()

    if url.startswith("sqlite:////"):
        return Path("/" + url[len("sqlite:////"):])
    if url.startswith("sqlite:///"):
        remainder = url[len("sqlite:///"):]
        path = Path(remainder)
        return path if path.is_absolute() else PROJECT_ROOT / path
    if url.startswith("sqlite://"):
        raise ValueError(
            f"Unsupported DATABASE_URL {url!r}. "
            "Use 'sqlite:///kasibiz.db' (relative) or 'sqlite:////abs/path.db' (absolute)."
        )
    if not url.startswith("sqlite"):
        raise ValueError(
            f"DATABASE_URL {url!r} is not a SQLite URL. "
            "KasiBiz only supports SQLite for now."
        )
    return Path(url)


class StockDatabase:
    """All stock reads and writes go through this class."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            self.db_path: str | Path = resolve_db_path()
        elif str(db_path) == ":memory:":
            self.db_path = ":memory:"
        else:
            self.db_path = Path(db_path)

        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- connection
    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection that commits on success and rolls back on error."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialise(self) -> None:
        """Create the tables, indexes, trigger and view if they do not exist."""
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        with self.connect() as conn:
            conn.executescript(schema)

    # ---------------------------------------------------------------- create
    def add_product(
        self,
        name: str,
        cost_price: Money,
        selling_price: Money,
        quantity: int = 0,
        category: str = "General",
        unit: str = "each",
        low_stock_threshold: int = 5,
        barcode: str | None = None,
    ) -> Product:
        """Add a new product and return it. Raises DuplicateProductError if the name exists."""
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Product name cannot be empty.")
        if quantity < 0:
            raise ValueError("Quantity cannot be negative.")
        if low_stock_threshold < 0:
            raise ValueError("Low stock threshold cannot be negative.")

        try:
            with self.connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO products (
                        name, category, unit, cost_price_cents, selling_price_cents,
                        quantity, low_stock_threshold, barcode
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_name,
                        category.strip() or "General",
                        unit.strip() or "each",
                        to_cents(cost_price),
                        to_cents(selling_price),
                        quantity,
                        low_stock_threshold,
                        barcode.strip() if barcode else None,
                    ),
                )
                new_id = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            if "idx_products_name_unique" in str(exc) or "UNIQUE" in str(exc).upper():
                raise DuplicateProductError(
                    f"A product called '{clean_name}' already exists. "
                    "Use update_product() to change it, or pick a different name."
                ) from exc
            raise DatabaseError(f"Could not add '{clean_name}': {exc}") from exc

        return self.get_product(int(new_id))

    # ------------------------------------------------------------------ read
    def get_product(self, product_id: int) -> Product:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM products WHERE id = ?", (product_id,)
            ).fetchone()
        if row is None:
            raise ProductNotFoundError(f"No product with id {product_id}.")
        return Product.from_row(row)

    def find_by_name(self, name: str) -> Product | None:
        """Case-insensitive lookup. Returns None instead of raising, for 'do we stock this?'."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM products WHERE lower(trim(name)) = lower(trim(?))",
                (name,),
            ).fetchone()
        return Product.from_row(row) if row else None

    def get_by_name(self, name: str) -> Product:
        product = self.find_by_name(name)
        if product is None:
            raise ProductNotFoundError(f"No product called '{name}'.")
        return product

    def list_products(
        self,
        category: str | None = None,
        search: str | None = None,
        order_by: str = "name",
    ) -> list[Product]:
        allowed = {"name", "quantity", "category", "created_at", "selling_price_cents"}
        if order_by not in allowed:
            raise ValueError(f"Cannot sort by {order_by!r}. Allowed: {sorted(allowed)}")

        sql = "SELECT * FROM products"
        clauses: list[str] = []
        params: list[object] = []

        if category:
            clauses.append("lower(category) = lower(?)")
            params.append(category.strip())
        if search:
            clauses.append("lower(name) LIKE lower(?)")
            params.append(f"%{search.strip()}%")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += f" ORDER BY {order_by} ASC"

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [Product.from_row(row) for row in rows]

    def list_low_stock(self) -> list[Product]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM low_stock_products").fetchall()
        return [Product.from_row(row) for row in rows]

    def count_products(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM products").fetchone()[0])

    def total_stock_value_cents(self) -> int:
        """Total cash tied up in stock, at cost price."""
        with self.connect() as conn:
            result = conn.execute(
                "SELECT COALESCE(SUM(cost_price_cents * quantity), 0) FROM products"
            ).fetchone()[0]
        return int(result)

    # ---------------------------------------------------------------- update
    def update_product(self, product_id: int, **changes: object) -> Product:
        """Update any subset of a product's fields, e.g. update_product(1, selling_price=22)."""
        self.get_product(product_id)  # raises ProductNotFoundError if missing

        column_map = {
            "name": "name",
            "category": "category",
            "unit": "unit",
            "quantity": "quantity",
            "low_stock_threshold": "low_stock_threshold",
            "barcode": "barcode",
            "cost_price": "cost_price_cents",
            "selling_price": "selling_price_cents",
            "cost_price_cents": "cost_price_cents",
            "selling_price_cents": "selling_price_cents",
        }

        assignments: list[str] = []
        params: list[object] = []

        for field, value in changes.items():
            if field not in column_map:
                raise ValueError(
                    f"Cannot update {field!r}. Allowed fields: {sorted(column_map)}"
                )
            if field in ("cost_price", "selling_price"):
                value = to_cents(value)  # type: ignore[arg-type]
            elif field == "name":
                value = str(value).strip()
                if not value:
                    raise ValueError("Product name cannot be empty.")
            elif field in ("quantity", "low_stock_threshold"):
                value = int(value)  # type: ignore[arg-type]
                if value < 0:
                    raise ValueError(f"{field} cannot be negative.")

            assignments.append(f"{column_map[field]} = ?")
            params.append(value)

        if not assignments:
            raise ValueError("No changes supplied.")

        params.append(product_id)
        try:
            with self.connect() as conn:
                conn.execute(
                    f"UPDATE products SET {', '.join(assignments)} WHERE id = ?", params
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateProductError(
                f"Could not update product {product_id}: that name is already taken."
            ) from exc

        return self.get_product(product_id)

    def adjust_stock(self, product_id: int, change: int) -> Product:
        """Add to (+) or take from (-) stock. Refuses to go below zero."""
        product = self.get_product(product_id)
        new_quantity = product.quantity + change

        if new_quantity < 0:
            raise InsufficientStockError(
                f"Cannot remove {abs(change)} x {product.name}: only {product.quantity} in stock."
            )

        with self.connect() as conn:
            conn.execute(
                "UPDATE products SET quantity = ? WHERE id = ?", (new_quantity, product_id)
            )
        return self.get_product(product_id)

    def set_stock(self, product_id: int, quantity: int) -> Product:
        """Set stock to an exact number, e.g. after a physical stock count."""
        if quantity < 0:
            raise ValueError("Quantity cannot be negative.")
        return self.update_product(product_id, quantity=quantity)

    # ---------------------------------------------------------------- delete
    def delete_product(self, product_id: int) -> None:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
            if cursor.rowcount == 0:
                raise ProductNotFoundError(f"No product with id {product_id}.")

    def delete_all_products(self) -> int:
        """Wipe the products table. Development and test use only."""
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM products")
            return cursor.rowcount

    # ----------------------------------------------------------------- sales
    def record_sale(
        self,
        reference: str,
        lines: list[dict],
        paid_cents: int,
        change_cents: int,
        note: str | None = None,
    ) -> int:
        """Save a sale and take the stock off the shelf, together or not at all.

        Every line must carry product_id, product_name, quantity,
        unit_price_cents, unit_cost_cents and line_total_cents.

        Returns the new sale id. Raises DuplicateSaleError if this basket has
        already been saved, which is what makes a double-tap on Confirm safe.
        """
        if not lines:
            raise ValueError("A sale must have at least one item.")

        total_cents = sum(int(line["line_total_cents"]) for line in lines)
        cost_cents = sum(int(line["unit_cost_cents"]) * int(line["quantity"]) for line in lines)
        item_count = sum(int(line["quantity"]) for line in lines)

        conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("BEGIN IMMEDIATE")

            cursor = conn.execute(
                """
                INSERT INTO sales (reference, total_cents, paid_cents, change_cents,
                                   cost_cents, profit_cents, item_count, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (reference, total_cents, int(paid_cents), int(change_cents),
                 cost_cents, total_cents - cost_cents, item_count, note),
            )
            sale_id = int(cursor.lastrowid)

            for line in lines:
                quantity = int(line["quantity"])
                product_id = line.get("product_id")

                conn.execute(
                    """
                    INSERT INTO sale_items (sale_id, product_id, product_name, quantity,
                                            unit_price_cents, unit_cost_cents, line_total_cents)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (sale_id, product_id, line["product_name"], quantity,
                     int(line["unit_price_cents"]), int(line["unit_cost_cents"]),
                     int(line["line_total_cents"])),
                )

                if product_id is None:
                    continue

                # The WHERE clause is the guard, not a prior read. Two tills
                # selling the last loaf at once cannot both succeed.
                updated = conn.execute(
                    "UPDATE products SET quantity = quantity - ? "
                    "WHERE id = ? AND quantity >= ?",
                    (quantity, product_id, quantity),
                ).rowcount

                if updated != 1:
                    raise InsufficientStockError(
                        f"Not enough {line['product_name']} left to sell {quantity}. "
                        "Nothing was saved."
                    )

            conn.execute("COMMIT")
            return sale_id

        except sqlite3.IntegrityError as exc:
            conn.execute("ROLLBACK")
            if "reference" in str(exc).lower() or "UNIQUE" in str(exc).upper():
                raise DuplicateSaleError(
                    "That sale has already been saved. Nothing was recorded twice."
                ) from exc
            raise DatabaseError(f"Could not save the sale: {exc}") from exc
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def get_sale(self, sale_id: int) -> dict:
        with self.connect() as conn:
            sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
            if sale is None:
                raise SaleNotFoundError(f"No sale with id {sale_id}.")
            items = conn.execute(
                "SELECT * FROM sale_items WHERE sale_id = ? ORDER BY id", (sale_id,)
            ).fetchall()
        return {**dict(sale), "items": [dict(item) for item in items]}

    def find_sale_by_reference(self, reference: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM sales WHERE reference = ?", (reference,)
            ).fetchone()
        return self.get_sale(int(row["id"])) if row else None

    def list_sales(self, since: str | None = None, until: str | None = None) -> list[dict]:
        sql = "SELECT * FROM sales"
        clauses: list[str] = []
        params: list[object] = []
        if since:
            clauses.append("sold_at >= ?")
            params.append(since)
        if until:
            clauses.append("sold_at <= ?")
            params.append(until)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY sold_at DESC, id DESC"

        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def list_sale_items(self, since: str | None = None, until: str | None = None) -> list[dict]:
        """Every line sold in a period, with the sale's timestamp attached."""
        sql = (
            "SELECT i.*, s.sold_at FROM sale_items i "
            "JOIN sales s ON s.id = i.sale_id"
        )
        clauses: list[str] = []
        params: list[object] = []
        if since:
            clauses.append("s.sold_at >= ?")
            params.append(since)
        if until:
            clauses.append("s.sold_at <= ?")
            params.append(until)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY s.sold_at DESC, i.id DESC"

        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def count_sales(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0])

    def delete_all_sales(self) -> int:
        """Wipe the sales history. Development and demo-reset use only."""
        with self.connect() as conn:
            conn.execute("DELETE FROM sale_items")
            return conn.execute("DELETE FROM sales").rowcount


_default_db: StockDatabase | None = None


def get_db() -> StockDatabase:
    """Shared database instance for the running app, created and initialised once."""
    global _default_db
    if _default_db is None:
        _default_db = StockDatabase()
        _default_db.initialise()
    return _default_db
