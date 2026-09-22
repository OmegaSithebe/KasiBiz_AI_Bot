"""The till: building a basket, checking it, and committing it to the books.

The shape of this file follows one idea. A sale has two halves and they are
deliberately kept apart:

    BEFORE confirmation   nothing is written, nothing leaves the shelf
    AFTER confirmation    the sale and the stock move together, or not at all

Everything in between - matching a product name, checking there is enough on
the shelf, adding up the basket, working out change - happens in plain Python
where it can be tested, and where it costs nothing and cannot hallucinate.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from app.database.sqlite_db import (
    DuplicateSaleError,
    InsufficientStockError,
    Product,
    StockDatabase,
    format_rand,
    get_db,
    to_cents,
    to_rand,
)
from app.services.calculation_service import (
    BasketMaths,
    CalculationError,
    InsufficientPaymentError,
    basket_cost_cents,
    basket_total_cents,
    change_cents,
    line_gross_profit_cents,
    line_total_cents,
)
from app.utils.logging_setup import get_logger

log = get_logger("kasibiz.till")


class SalesError(RuntimeError):
    """Something about this sale cannot be done."""


class UnknownProductError(SalesError):
    """The shop does not stock anything by that name."""

    def __init__(self, name: str, suggestions: list[str] | None = None) -> None:
        self.name = name
        self.suggestions = suggestions or []
        message = f"The shop does not stock anything called '{name}'."
        if self.suggestions:
            message += " Did you mean: " + ", ".join(self.suggestions) + "?"
        super().__init__(message)


class AmbiguousProductError(SalesError):
    """More than one product matches, and guessing would sell the wrong thing."""

    def __init__(self, name: str, matches: list[str]) -> None:
        self.name = name
        self.matches = matches
        super().__init__(
            f"'{name}' could mean {len(matches)} different products: "
            + ", ".join(matches) + ". Which one?"
        )


class NotEnoughStockError(SalesError):
    """Asked to sell more than the shop has."""

    def __init__(self, name: str, wanted: int, available: int) -> None:
        self.name = name
        self.wanted = wanted
        self.available = available
        super().__init__(
            f"Cannot sell {wanted} x {name}: only {available} in stock."
            if available else f"Cannot sell {name}: it is out of stock."
        )


class EmptyBasketError(SalesError):
    """Asked to total or confirm a basket with nothing in it."""


@dataclass
class BasketLine:
    """One product on the basket. Prices are captured now, not looked up later."""

    product_id: int | None
    product_name: str
    quantity: int
    unit_price_cents: int
    unit_cost_cents: int
    unit: str = "each"

    @property
    def line_total_cents(self) -> int:
        return line_total_cents(self.unit_price_cents, self.quantity)

    @property
    def line_profit_cents(self) -> int:
        return line_gross_profit_cents(
            self.unit_price_cents, self.unit_cost_cents, self.quantity
        )

    @property
    def unit_price(self) -> Decimal:
        return to_rand(self.unit_price_cents)

    @property
    def line_total(self) -> Decimal:
        return to_rand(self.line_total_cents)

    def as_row(self) -> str:
        return (f"{self.quantity} x {self.product_name} @ "
                f"{format_rand(self.unit_price_cents)} = "
                f"{format_rand(self.line_total_cents)}")

    def as_record(self) -> dict:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "unit_price_cents": self.unit_price_cents,
            "unit_cost_cents": self.unit_cost_cents,
            "line_total_cents": self.line_total_cents,
        }


@dataclass
class Basket:
    """A sale in progress. Nothing here has touched the database yet."""

    reference: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    lines: list[BasketLine] = field(default_factory=list)
    paid_cents: int | None = None
    note: str | None = None
    saved_sale_id: int | None = None

    @property
    def is_empty(self) -> bool:
        return not self.lines

    @property
    def is_saved(self) -> bool:
        return self.saved_sale_id is not None

    @property
    def total_cents(self) -> int:
        return basket_total_cents(line.line_total_cents for line in self.lines)

    @property
    def cost_cents(self) -> int:
        return basket_cost_cents((line.unit_cost_cents, line.quantity) for line in self.lines)

    @property
    def profit_cents(self) -> int:
        return self.total_cents - self.cost_cents

    @property
    def item_count(self) -> int:
        return sum(line.quantity for line in self.lines)

    @property
    def total(self) -> Decimal:
        return to_rand(self.total_cents)

    def find(self, product_name: str) -> BasketLine | None:
        target = product_name.strip().lower()
        for line in self.lines:
            if line.product_name.lower() == target:
                return line
        return None

    def maths(self) -> BasketMaths:
        """Every figure for this basket, worked out in one place."""
        change = None
        if self.paid_cents is not None and self.paid_cents >= self.total_cents:
            change = self.paid_cents - self.total_cents
        return BasketMaths(
            total_cents=self.total_cents,
            cost_cents=self.cost_cents,
            profit_cents=self.profit_cents,
            item_count=self.item_count,
            paid_cents=self.paid_cents,
            change_cents=change,
        )

    def as_summary(self, shop_name: str = "") -> str:
        if self.is_empty:
            return "The basket is empty."

        rows = [f"  {line.as_row()}" for line in self.lines]
        out = ["Basket:", *rows, f"TOTAL: {format_rand(self.total_cents)}"]

        if self.paid_cents is not None:
            out.append(f"Paid:  {format_rand(self.paid_cents)}")
            if self.paid_cents >= self.total_cents:
                out.append(f"CHANGE: {format_rand(self.paid_cents - self.total_cents)}")
            else:
                short = self.total_cents - self.paid_cents
                out.append(f"SHORT BY {format_rand(short)} - not enough to complete the sale.")
        return "\n".join(out)

    def as_facts(self) -> str:
        """Every figure behind this basket, including each line's unit price.

        The summary quotes unit prices, so they have to be here too or the
        figure checker reports an honest answer as an invented number.
        """
        if self.is_empty:
            return ""
        rows = [f"  {line.as_row()}" for line in self.lines]
        return "\n".join(["Basket lines:", *rows, self.maths().as_facts()])


@dataclass
class CompletedSale:
    """A sale that is now on the books. Read-only."""

    sale_id: int
    reference: str
    lines: list[BasketLine]
    total_cents: int
    paid_cents: int
    change_cents: int
    cost_cents: int
    profit_cents: int
    item_count: int
    sold_at: str = ""

    @property
    def total(self) -> Decimal:
        return to_rand(self.total_cents)

    @property
    def change(self) -> Decimal:
        return to_rand(self.change_cents)

    def as_facts(self) -> str:
        """The calculated truth behind this sale. An agent may only reword this."""
        rows = [f"  {line.as_row()}" for line in self.lines]
        return "\n".join([
            f"Sale #{self.sale_id} recorded.",
            *rows,
            f"Total: {format_rand(self.total_cents)}",
            f"Paid: {format_rand(self.paid_cents)}",
            f"Change: {format_rand(self.change_cents)}",
            f"Profit on this sale: {format_rand(self.profit_cents)}",
        ])

    def as_receipt(self, shop_name: str = "KasiBiz") -> str:
        width = 34
        rows = []
        for line in self.lines:
            left = f"{line.quantity} x {line.product_name}"
            right = format_rand(line.line_total_cents)
            rows.append(f"{left[:width - len(right) - 1]:<{width - len(right)}}{right}")

        return "\n".join([
            shop_name.center(width),
            "-" * width,
            *rows,
            "-" * width,
            f"{'TOTAL':<{width - len(format_rand(self.total_cents))}}"
            f"{format_rand(self.total_cents)}",
            f"{'PAID':<{width - len(format_rand(self.paid_cents))}}"
            f"{format_rand(self.paid_cents)}",
            f"{'CHANGE':<{width - len(format_rand(self.change_cents))}}"
            f"{format_rand(self.change_cents)}",
            "-" * width,
            f"Sale #{self.sale_id}  {self.sold_at}".center(width),
            "Thank you!".center(width),
        ])


class SalesService:
    """Runs one till. Holds at most one basket at a time."""

    def __init__(self, db: StockDatabase | None = None) -> None:
        self.db = db or get_db()
        self.basket: Basket | None = None

    # -------------------------------------------------------- starting up
    def start_sale(self) -> Basket:
        """Open a fresh basket, throwing away any unconfirmed one."""
        self.basket = Basket()
        return self.basket

    def current_basket(self) -> Basket:
        if self.basket is None or self.basket.is_saved:
            return self.start_sale()
        return self.basket

    @property
    def has_open_basket(self) -> bool:
        return self.basket is not None and not self.basket.is_saved and not self.basket.is_empty

    # ------------------------------------------------- matching a product
    def match_product(self, name: str) -> Product:
        """Find exactly one product, or explain clearly why we cannot."""
        query = name.strip()
        if not query:
            raise UnknownProductError(name)

        exact = self.db.find_by_name(query)
        if exact is not None:
            return exact

        partial = [p for p in self.db.list_products() if query.lower() in p.name.lower()]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            raise AmbiguousProductError(query, sorted(p.name for p in partial))

        raise UnknownProductError(query, self.suggest_names(query))

    def suggest_names(self, name: str, limit: int = 3) -> list[str]:
        """Nearby product names, so an unknown item is a helpful message not a dead end."""
        from difflib import get_close_matches

        names = [p.name for p in self.db.list_products()]
        close = get_close_matches(name, names, n=limit, cutoff=0.5)
        if close:
            return close

        words = [w for w in name.lower().split() if len(w) > 2]
        return [n for n in names if any(w in n.lower() for w in words)][:limit]

    # ------------------------------------------------ building the basket
    def add_item(
        self,
        product_name: str,
        quantity: int = 1,
        unit_price: object = None,
        basket: Basket | None = None,
    ) -> BasketLine:
        """Put a product on the basket. Nothing is written and no stock moves."""
        if not isinstance(quantity, int) or isinstance(quantity, bool):
            raise SalesError(f"Quantity must be a whole number, not {quantity!r}.")
        if quantity <= 0:
            raise SalesError("Quantity must be at least 1. To take an item off, remove it.")

        basket = basket or self.current_basket()
        product = self.match_product(product_name)

        already = basket.find(product.name)
        wanted = quantity + (already.quantity if already else 0)
        if wanted > product.quantity:
            raise NotEnoughStockError(product.name, wanted, product.quantity)

        # A price may be confirmed by the owner, but it is never invented.
        price_cents = to_cents(unit_price) if unit_price is not None else product.selling_price_cents

        if already is not None and already.unit_price_cents == price_cents:
            already.quantity = wanted
            return already

        line = BasketLine(
            product_id=product.id,
            product_name=product.name,
            quantity=quantity,
            unit_price_cents=price_cents,
            unit_cost_cents=product.cost_price_cents,
            unit=product.unit,
        )
        basket.lines.append(line)
        return line

    def remove_item(self, product_name: str, basket: Basket | None = None) -> bool:
        basket = basket or self.current_basket()
        line = basket.find(product_name)
        if line is None:
            match = self.match_product(product_name)
            line = basket.find(match.name)
        if line is None:
            return False
        basket.lines.remove(line)
        return True

    def set_quantity(self, product_name: str, quantity: int,
                     basket: Basket | None = None) -> BasketLine:
        basket = basket or self.current_basket()
        if quantity <= 0:
            raise SalesError("Quantity must be at least 1. To take an item off, remove it.")

        product = self.match_product(product_name)
        if quantity > product.quantity:
            raise NotEnoughStockError(product.name, quantity, product.quantity)

        line = basket.find(product.name)
        if line is None:
            return self.add_item(product.name, quantity, basket=basket)
        line.quantity = quantity
        return line

    # ------------------------------------------------------------ payment
    def set_payment(self, amount: object, basket: Basket | None = None) -> int:
        """Record what the customer handed over and return the change."""
        basket = basket or self.current_basket()
        if basket.is_empty:
            raise EmptyBasketError("There is nothing in the basket to pay for yet.")

        paid = to_cents(amount)
        change = change_cents(basket.total_cents, paid)  # raises if short
        basket.paid_cents = paid
        return change

    def change_for(self, basket: Basket | None = None) -> int:
        basket = basket or self.current_basket()
        if basket.paid_cents is None:
            raise SalesError("No payment has been entered yet.")
        return change_cents(basket.total_cents, basket.paid_cents)

    # --------------------------------------------------- the confirmation
    def ready_to_confirm(self, basket: Basket | None = None) -> tuple[bool, str]:
        """Everything that must be true before money is committed to the books."""
        basket = basket or self.current_basket()

        if basket.is_saved:
            return False, "This sale has already been saved."
        if basket.is_empty:
            return False, "There is nothing in the basket yet."
        if basket.paid_cents is None:
            return False, (f"The total is {format_rand(basket.total_cents)}. "
                           "How much did the customer pay?")
        if basket.paid_cents < basket.total_cents:
            short = basket.total_cents - basket.paid_cents
            return False, (f"{format_rand(basket.paid_cents)} is not enough. "
                           f"Still short {format_rand(short)}.")
        return True, "Ready to save."

    def confirm_sale(self, basket: Basket | None = None) -> CompletedSale:
        """Write the sale and take the stock off the shelf, in one transaction."""
        basket = basket or self.current_basket()

        ready, reason = self.ready_to_confirm(basket)
        if not ready:
            raise SalesError(reason)

        # A retry after a database failure reuses the same reference, so the
        # UNIQUE index turns a duplicate save into a clean error instead of a
        # second sale.
        try:
            sale_id = self.db.record_sale(
                reference=basket.reference,
                lines=[line.as_record() for line in basket.lines],
                paid_cents=basket.paid_cents or 0,
                change_cents=self.change_for(basket),
                note=basket.note,
            )
        except InsufficientStockError as exc:
            log.warning("sale %s refused: %s", basket.reference, exc)
            raise NotEnoughStockError(str(exc), 0, 0) from exc
        except DuplicateSaleError:
            log.warning("sale %s was already saved - not recorded twice",
                        basket.reference)
            raise

        basket.saved_sale_id = sale_id
        stored = self.db.get_sale(sale_id)

        log.info("sale #%s saved: %s item(s), %s, %s change",
                 sale_id, basket.item_count, format_rand(basket.total_cents),
                 format_rand(stored["change_cents"]))

        return CompletedSale(
            sale_id=sale_id,
            reference=basket.reference,
            lines=list(basket.lines),
            total_cents=basket.total_cents,
            paid_cents=basket.paid_cents or 0,
            change_cents=stored["change_cents"],
            cost_cents=basket.cost_cents,
            profit_cents=basket.profit_cents,
            item_count=basket.item_count,
            sold_at=stored["sold_at"],
        )

    def cancel_sale(self, basket: Basket | None = None) -> str:
        """Throw the basket away. Nothing was written, so nothing needs undoing."""
        basket = basket or self.basket
        if basket is None or basket.is_empty:
            self.basket = None
            return "There was nothing to cancel."

        count = basket.item_count
        total = basket.total_cents
        self.basket = None
        log.info("sale %s cancelled: %s item(s), %s, nothing written",
                 basket.reference, count, format_rand(total))
        return (f"Sale cancelled. {count} item(s) worth {format_rand(total)} "
                "were not recorded and no stock was changed.")


__all__ = [
    "SalesService", "Basket", "BasketLine", "CompletedSale",
    "SalesError", "UnknownProductError", "AmbiguousProductError",
    "NotEnoughStockError", "EmptyBasketError",
    "InsufficientPaymentError", "CalculationError", "DuplicateSaleError",
]
