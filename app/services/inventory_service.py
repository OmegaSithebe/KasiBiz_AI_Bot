"""Stock intelligence for KasiBiz: what is low, and what should be reordered.

This layer contains NO artificial intelligence. Every number here is calculated
by ordinary, testable Python so the answers are always exact and repeatable.
The Stock Agent asks this service for the facts, then puts them into words.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.database.sqlite_db import Product, StockDatabase, format_rand, get_db

# A flagged product is restocked back up to (alert level x this multiplier).
# Example: alert level 6 -> target shelf level 18.
DEFAULT_RESTOCK_MULTIPLIER = 3


class Urgency(str, Enum):
    """How badly a product needs attention. Ordered worst-first."""

    OUT_OF_STOCK = "OUT OF STOCK"
    CRITICAL = "CRITICAL"
    LOW = "LOW"
    OK = "OK"

    @property
    def rank(self) -> int:
        return {"OUT OF STOCK": 0, "CRITICAL": 1, "LOW": 2, "OK": 3}[self.value]

    @property
    def advice(self) -> str:
        return {
            "OUT OF STOCK": "You have none left. You are losing sales right now.",
            "CRITICAL": "Almost finished. Reorder today.",
            "LOW": "Running low. Add this to your next order.",
            "OK": "Stock level is fine.",
        }[self.value]


@dataclass(frozen=True)
class StockAlert:
    """One product's stock position, plus what to do about it."""

    product: Product
    urgency: Urgency
    suggested_reorder_qty: int
    reorder_cost_cents: int
    expected_profit_cents: int

    @property
    def name(self) -> str:
        return self.product.name

    @property
    def quantity(self) -> int:
        return self.product.quantity

    @property
    def alert_level(self) -> int:
        return self.product.low_stock_threshold

    @property
    def needs_reorder(self) -> bool:
        return self.urgency is not Urgency.OK

    def as_sentence(self) -> str:
        """One plain line a shop owner can read at a glance."""
        if not self.needs_reorder:
            return (
                f"{self.name}: {self.quantity} {self.product.unit} in stock - "
                f"above the alert level of {self.alert_level}. No need to reorder."
            )
        return (
            f"{self.name}: {self.quantity} left (alert level {self.alert_level}) "
            f"- {self.urgency.value}. Order {self.suggested_reorder_qty} more "
            f"for {format_rand(self.reorder_cost_cents)}, which should bring in "
            f"{format_rand(self.expected_profit_cents)} profit."
        )


@dataclass(frozen=True)
class ReorderPlan:
    """The full shopping list for the supplier."""

    alerts: list[StockAlert]
    total_cost_cents: int
    total_expected_profit_cents: int

    @property
    def is_empty(self) -> bool:
        return not self.alerts

    @property
    def item_count(self) -> int:
        return len(self.alerts)

    @property
    def out_of_stock(self) -> list[StockAlert]:
        return [a for a in self.alerts if a.urgency is Urgency.OUT_OF_STOCK]

    @property
    def critical(self) -> list[StockAlert]:
        return [a for a in self.alerts if a.urgency is Urgency.CRITICAL]

    def as_text(self) -> str:
        if self.is_empty:
            return "Nothing needs reordering. All your stock is above its alert level."

        lines = [f"You need to reorder {self.item_count} product(s):", ""]
        lines += [f"  {i}. {a.as_sentence()}" for i, a in enumerate(self.alerts, start=1)]
        lines += [
            "",
            f"Total cost of this order: {format_rand(self.total_cost_cents)}",
            f"Expected profit once sold: {format_rand(self.total_expected_profit_cents)}",
        ]
        return "\n".join(lines)


@dataclass(frozen=True)
class StockSummary:
    total_products: int
    total_units: int
    stock_value_cents: int
    out_of_stock_count: int
    critical_count: int
    low_count: int
    healthy_count: int

    @property
    def needs_attention_count(self) -> int:
        return self.out_of_stock_count + self.critical_count + self.low_count

    def as_text(self) -> str:
        return (
            f"You have {self.total_products} products on the shelves "
            f"({self.total_units} items in total), worth "
            f"{format_rand(self.stock_value_cents)} at cost price.\n"
            f"Out of stock: {self.out_of_stock_count}. "
            f"Critical: {self.critical_count}. "
            f"Low: {self.low_count}. "
            f"Healthy: {self.healthy_count}."
        )


class InventoryService:
    """Turns raw stock rows into alerts, reorder plans and summaries."""

    def __init__(
        self,
        db: StockDatabase | None = None,
        restock_multiplier: int = DEFAULT_RESTOCK_MULTIPLIER,
    ) -> None:
        if restock_multiplier < 1:
            raise ValueError("restock_multiplier must be at least 1.")
        self.db = db or get_db()
        self.restock_multiplier = restock_multiplier

    # ------------------------------------------------------------- rules
    def classify(self, product: Product) -> Urgency:
        """The reorder rule, in one place so it can never disagree with itself."""
        if product.quantity == 0:
            return Urgency.OUT_OF_STOCK
        if product.quantity > product.low_stock_threshold:
            return Urgency.OK
        # At or below the alert level. Half-way or less is treated as critical.
        if product.quantity * 2 <= product.low_stock_threshold:
            return Urgency.CRITICAL
        return Urgency.LOW

    def suggest_reorder_quantity(self, product: Product) -> int:
        """How many to buy: top the shelf back up to the target level."""
        if self.classify(product) is Urgency.OK:
            return 0
        target = max(product.low_stock_threshold * self.restock_multiplier, 1)
        return max(target - product.quantity, 1)

    def build_alert(self, product: Product) -> StockAlert:
        quantity = self.suggest_reorder_quantity(product)
        return StockAlert(
            product=product,
            urgency=self.classify(product),
            suggested_reorder_qty=quantity,
            reorder_cost_cents=quantity * product.cost_price_cents,
            expected_profit_cents=quantity * product.profit_per_unit_cents,
        )

    # ----------------------------------------------------------- queries
    def get_low_stock(self) -> list[StockAlert]:
        """Everything at or below its alert level, worst first."""
        alerts = [self.build_alert(p) for p in self.db.list_products()]
        flagged = [a for a in alerts if a.needs_reorder]
        return sorted(flagged, key=lambda a: (a.urgency.rank, a.quantity, a.name))

    def get_reorder_plan(self) -> ReorderPlan:
        alerts = self.get_low_stock()
        return ReorderPlan(
            alerts=alerts,
            total_cost_cents=sum(a.reorder_cost_cents for a in alerts),
            total_expected_profit_cents=sum(a.expected_profit_cents for a in alerts),
        )

    def check_product(self, name: str) -> StockAlert | None:
        """Stock position for one named product. None if the shop does not stock it."""
        product = self.db.find_by_name(name)
        return self.build_alert(product) if product else None

    def get_summary(self) -> StockSummary:
        products = self.db.list_products()
        counts = {urgency: 0 for urgency in Urgency}
        for product in products:
            counts[self.classify(product)] += 1

        return StockSummary(
            total_products=len(products),
            total_units=sum(p.quantity for p in products),
            stock_value_cents=sum(p.stock_value_cents for p in products),
            out_of_stock_count=counts[Urgency.OUT_OF_STOCK],
            critical_count=counts[Urgency.CRITICAL],
            low_count=counts[Urgency.LOW],
            healthy_count=counts[Urgency.OK],
        )

    def set_alert_level(self, product_id: int, alert_level: int) -> StockAlert:
        """Change when a product starts warning the owner."""
        if alert_level < 0:
            raise ValueError("Alert level cannot be negative.")
        product = self.db.update_product(product_id, low_stock_threshold=alert_level)
        return self.build_alert(product)
