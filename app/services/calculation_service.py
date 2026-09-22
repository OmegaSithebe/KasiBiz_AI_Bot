"""Every sum in KasiBiz that involves money.

One rule governs this file: the language model never touches a number. Totals,
change and profit are worked out here, in ordinary Python, and the AI is only
ever handed the finished figures to put into a sentence.

Money is whole CENTS as `int`. Not float, and not Decimal either - a shop
owner's total is a count of coins, and counting is exactly what integers do.
Decimal Rand is produced only at the edge, for display, by `to_rand`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.database.sqlite_db import format_rand, to_cents, to_rand

__all__ = [
    "CalculationError",
    "InsufficientPaymentError",
    "line_total_cents",
    "basket_total_cents",
    "change_cents",
    "gross_profit_per_item_cents",
    "line_gross_profit_cents",
    "basket_cost_cents",
    "basket_profit_cents",
    "margin_percent_of",
    "BasketMaths",
    "to_cents",
    "to_rand",
    "format_rand",
]


class CalculationError(ValueError):
    """A sum was asked for that cannot be answered honestly."""


class InsufficientPaymentError(CalculationError):
    """The customer has not handed over enough money."""

    def __init__(self, total_cents: int, paid_cents: int) -> None:
        self.total_cents = total_cents
        self.paid_cents = paid_cents
        self.short_cents = total_cents - paid_cents
        super().__init__(
            f"{format_rand(paid_cents)} is not enough for a "
            f"{format_rand(total_cents)} sale. "
            f"Still short {format_rand(self.short_cents)}."
        )


def _check_quantity(quantity: int) -> int:
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise CalculationError(f"Quantity must be a whole number, not {quantity!r}.")
    if quantity <= 0:
        raise CalculationError("Quantity must be at least 1.")
    return quantity


def _check_cents(value: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise CalculationError(f"{label} must be whole cents, not {value!r}.")
    if value < 0:
        raise CalculationError(f"{label} cannot be negative.")
    return value


# ------------------------------------------------------------------ one line
def line_total_cents(unit_price_cents: int, quantity: int) -> int:
    """line_total = unit_price x quantity"""
    _check_cents(unit_price_cents, "Unit price")
    return unit_price_cents * _check_quantity(quantity)


def gross_profit_per_item_cents(selling_price_cents: int, cost_price_cents: int) -> int:
    """gross_profit_per_item = selling_price - cost_price. May be negative."""
    _check_cents(selling_price_cents, "Selling price")
    _check_cents(cost_price_cents, "Cost price")
    return selling_price_cents - cost_price_cents


def line_gross_profit_cents(
    selling_price_cents: int, cost_price_cents: int, quantity: int
) -> int:
    """line_gross_profit = gross_profit_per_item x quantity"""
    per_item = gross_profit_per_item_cents(selling_price_cents, cost_price_cents)
    return per_item * _check_quantity(quantity)


# --------------------------------------------------------------- the basket
def basket_total_cents(line_totals) -> int:
    """basket_total = sum of line totals. An empty basket is R0.00, not an error."""
    total = 0
    for value in line_totals:
        total += _check_cents(value, "Line total")
    return total


def basket_cost_cents(pairs) -> int:
    """What the basket cost the shop, from (unit_cost_cents, quantity) pairs."""
    return sum(_check_cents(cost, "Unit cost") * _check_quantity(qty) for cost, qty in pairs)


def basket_profit_cents(total_cents: int, cost_cents: int) -> int:
    return _check_cents(total_cents, "Total") - _check_cents(cost_cents, "Cost")


def change_cents(total_cents: int, paid_cents: int) -> int:
    """change = amount_paid - basket_total. Refuses to invent money."""
    _check_cents(total_cents, "Total")
    _check_cents(paid_cents, "Amount paid")
    if paid_cents < total_cents:
        raise InsufficientPaymentError(total_cents, paid_cents)
    return paid_cents - total_cents


def margin_percent_of(profit_cents: int, total_cents: int) -> Decimal:
    """Profit as a percentage of what was charged. R0.00 of sales is 0%, not an error."""
    if total_cents <= 0:
        return Decimal("0.00")
    return (Decimal(profit_cents) / Decimal(total_cents) * 100).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class BasketMaths:
    """Every figure for one basket, worked out once so nothing can disagree."""

    total_cents: int
    cost_cents: int
    profit_cents: int
    item_count: int
    paid_cents: int | None = None
    change_cents: int | None = None

    @property
    def total(self) -> Decimal:
        return to_rand(self.total_cents)

    @property
    def profit(self) -> Decimal:
        return to_rand(self.profit_cents)

    @property
    def margin_percent(self) -> Decimal:
        return margin_percent_of(self.profit_cents, self.total_cents)

    @property
    def is_paid(self) -> bool:
        return self.paid_cents is not None

    def as_facts(self) -> str:
        """The calculated truth, for an agent to put into words. Never guessed."""
        lines = [
            f"Items: {self.item_count}",
            f"Total: {format_rand(self.total_cents)}",
            f"Cost to the shop: {format_rand(self.cost_cents)}",
            f"Profit on this sale: {format_rand(self.profit_cents)} "
            f"({self.margin_percent}% of the sale)",
        ]
        if self.paid_cents is not None:
            lines.append(f"Paid: {format_rand(self.paid_cents)}")
        if self.change_cents is not None:
            lines.append(f"Change: {format_rand(self.change_cents)}")
        return "\n".join(lines)
