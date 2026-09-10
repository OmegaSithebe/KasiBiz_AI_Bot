"""Pricing maths for KasiBiz: what to charge, and what you actually make.

No artificial intelligence in this file. Every figure is calculated exactly,
in whole cents, so a price suggestion is never a guess.

The one distinction that matters most here is MARKUP versus MARGIN. They are
not the same number, and confusing them is the most common way a small shop
quietly under-prices itself:

    Cost R15, sell R20, profit R5
        markup = 5 / 15 = 33.33%   (profit measured against what you PAID)
        margin = 5 / 20 = 25.00%   (profit measured against what you CHARGE)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from app.database.sqlite_db import (
    Money,
    Product,
    StockDatabase,
    format_rand,
    get_db,
    to_cents,
    to_rand,
)

DEFAULT_MARKUP_PERCENT = Decimal("35")

# Spaza shops trade in cash, and coins below 10c no longer circulate.
# A price of R19.87 is useless at the counter, so suggestions round to 50c.
PRICE_ROUNDING_CENTS = 50

DEFAULT_MIN_MARGIN = Decimal("15")

# Some categories are genuinely low-margin. Airtime is sold at a few percent by
# every shop in the country, so flagging it as "too cheap" would be wrong.
CATEGORY_MIN_MARGIN: dict[str, Decimal] = {
    "airtime": Decimal("3"),
    "staples": Decimal("10"),
    "dairy": Decimal("12"),
    "bakery": Decimal("12"),
    "cold drinks": Decimal("18"),
    "snacks": Decimal("20"),
    "household": Decimal("18"),
    "groceries": Decimal("15"),
}

HIGH_MARGIN_PERCENT = Decimal("60")


class PriceHealth(str, Enum):
    LOSS = "LOSING MONEY"
    TOO_LOW = "TOO CHEAP"
    HEALTHY = "HEALTHY"
    HIGH = "VERY HIGH"

    @property
    def advice(self) -> str:
        return {
            "LOSING MONEY": "You lose money on every one you sell. Raise this price today.",
            "TOO CHEAP": "You are making very little on this. A small increase adds up fast.",
            "HEALTHY": "This price is working for you.",
            "VERY HIGH": "Good profit, but check nearby shops so customers do not go elsewhere.",
        }[self.value]


def _pct(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def markup_percent(cost_cents: int, selling_cents: int) -> Decimal:
    """Profit as a percentage of what you PAID."""
    if cost_cents == 0:
        return Decimal("0.00")
    return _pct(Decimal(selling_cents - cost_cents) / Decimal(cost_cents) * 100)


def margin_percent(cost_cents: int, selling_cents: int) -> Decimal:
    """Profit as a percentage of what you CHARGE."""
    if selling_cents == 0:
        return Decimal("0.00")
    return _pct(Decimal(selling_cents - cost_cents) / Decimal(selling_cents) * 100)


def round_to_practical(cents: int, step_cents: int = PRICE_ROUNDING_CENTS) -> int:
    """Round to a price the owner can actually take in coins."""
    if step_cents <= 0:
        raise ValueError("Rounding step must be a positive number of cents.")
    return int((Decimal(cents) / step_cents).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * step_cents


@dataclass(frozen=True)
class PriceSuggestion:
    """A recommended selling price, and everything behind it."""

    cost_price_cents: int
    suggested_price_cents: int
    exact_price_cents: int
    requested_markup_percent: Decimal

    @property
    def profit_cents(self) -> int:
        return self.suggested_price_cents - self.cost_price_cents

    @property
    def actual_markup_percent(self) -> Decimal:
        return markup_percent(self.cost_price_cents, self.suggested_price_cents)

    @property
    def actual_margin_percent(self) -> Decimal:
        return margin_percent(self.cost_price_cents, self.suggested_price_cents)

    @property
    def rounding_adjustment_cents(self) -> int:
        return self.suggested_price_cents - self.exact_price_cents

    def as_sentence(self) -> str:
        line = (
            f"Buy at {format_rand(self.cost_price_cents)}, "
            f"sell at {format_rand(self.suggested_price_cents)}. "
            f"You make {format_rand(self.profit_cents)} on each one "
            f"({self.actual_markup_percent}% markup, "
            f"{self.actual_margin_percent}% margin)."
        )
        if self.rounding_adjustment_cents:
            line += (
                f" Rounded from {format_rand(self.exact_price_cents)} "
                "to keep it easy to pay in cash."
            )
        return line


@dataclass(frozen=True)
class PriceAnalysis:
    """What an existing price is really earning."""

    cost_price_cents: int
    selling_price_cents: int
    health: PriceHealth
    minimum_margin_percent: Decimal
    product_name: str | None = None

    @property
    def profit_cents(self) -> int:
        return self.selling_price_cents - self.cost_price_cents

    @property
    def markup_percent(self) -> Decimal:
        return markup_percent(self.cost_price_cents, self.selling_price_cents)

    @property
    def margin_percent(self) -> Decimal:
        return margin_percent(self.cost_price_cents, self.selling_price_cents)

    @property
    def needs_attention(self) -> bool:
        return self.health in (PriceHealth.LOSS, PriceHealth.TOO_LOW)

    def as_sentence(self) -> str:
        label = self.product_name or "This product"
        return (
            f"{label}: costs {format_rand(self.cost_price_cents)}, "
            f"sells for {format_rand(self.selling_price_cents)}, "
            f"profit {format_rand(self.profit_cents)} each "
            f"({self.markup_percent}% markup, {self.margin_percent}% margin) "
            f"- {self.health.value}. {self.health.advice}"
        )


@dataclass(frozen=True)
class PriceChangeImpact:
    """What happens if the owner changes a price."""

    product_name: str
    cost_price_cents: int
    old_price_cents: int
    new_price_cents: int
    quantity: int

    @property
    def old_profit_each_cents(self) -> int:
        return self.old_price_cents - self.cost_price_cents

    @property
    def new_profit_each_cents(self) -> int:
        return self.new_price_cents - self.cost_price_cents

    @property
    def extra_profit_each_cents(self) -> int:
        return self.new_profit_each_cents - self.old_profit_each_cents

    @property
    def extra_profit_on_shelf_cents(self) -> int:
        return self.extra_profit_each_cents * self.quantity

    def as_sentence(self) -> str:
        direction = "more" if self.extra_profit_each_cents >= 0 else "less"
        return (
            f"{self.product_name}: moving from "
            f"{format_rand(self.old_price_cents)} to {format_rand(self.new_price_cents)} "
            f"changes your profit from {format_rand(self.old_profit_each_cents)} to "
            f"{format_rand(self.new_profit_each_cents)} each - "
            f"{format_rand(abs(self.extra_profit_each_cents))} {direction} per sale. "
            f"On the {self.quantity} you have in stock that is "
            f"{format_rand(abs(self.extra_profit_on_shelf_cents))} {direction}."
        )


@dataclass(frozen=True)
class PricingReview:
    """A pricing health check across the whole shop."""

    analyses: list[PriceAnalysis]

    @property
    def losing_money(self) -> list[PriceAnalysis]:
        return [a for a in self.analyses if a.health is PriceHealth.LOSS]

    @property
    def too_cheap(self) -> list[PriceAnalysis]:
        return [a for a in self.analyses if a.health is PriceHealth.TOO_LOW]

    @property
    def needs_attention(self) -> list[PriceAnalysis]:
        return [a for a in self.analyses if a.needs_attention]

    @property
    def average_margin_percent(self) -> Decimal:
        if not self.analyses:
            return Decimal("0.00")
        return _pct(sum((a.margin_percent for a in self.analyses), Decimal("0"))
                    / len(self.analyses))

    def as_text(self) -> str:
        if not self.analyses:
            return "There are no products to review yet."

        lines = [
            f"Checked {len(self.analyses)} products. "
            f"Average margin is {self.average_margin_percent}%.",
        ]
        if not self.needs_attention:
            lines.append("Every product is priced sensibly for its category.")
            return "\n".join(lines)

        lines.append(f"{len(self.needs_attention)} product(s) need attention:")
        lines.append("")
        lines += [f"  - {a.as_sentence()}" for a in self.needs_attention]
        return "\n".join(lines)


class PricingService:
    """Suggests prices, checks prices, and works out what they earn."""

    def __init__(
        self,
        db: StockDatabase | None = None,
        default_markup_percent: Money = DEFAULT_MARKUP_PERCENT,
        rounding_cents: int = PRICE_ROUNDING_CENTS,
    ) -> None:
        markup = Decimal(str(default_markup_percent))
        if markup < 0:
            raise ValueError("Markup cannot be negative.")
        if rounding_cents <= 0:
            raise ValueError("Rounding step must be a positive number of cents.")

        self.db = db or get_db()
        self.default_markup_percent = markup
        self.rounding_cents = rounding_cents

    # ------------------------------------------------------- suggesting
    def suggest_price(
        self,
        cost_price: Money,
        markup_percent_value: Money | None = None,
        round_price: bool = True,
    ) -> PriceSuggestion:
        """cost + markup = selling price. The core Day 8 calculation."""
        cost_cents = to_cents(cost_price)
        markup = Decimal(str(
            self.default_markup_percent if markup_percent_value is None else markup_percent_value
        ))
        if markup < 0:
            raise ValueError("Markup cannot be negative.")

        exact = int((Decimal(cost_cents) * (1 + markup / 100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
        suggested = round_to_practical(exact, self.rounding_cents) if round_price else exact

        return PriceSuggestion(
            cost_price_cents=cost_cents,
            suggested_price_cents=suggested,
            exact_price_cents=exact,
            requested_markup_percent=_pct(markup),
        )

    def price_for_target_margin(self, cost_price: Money, target_margin: Money) -> PriceSuggestion:
        """Work backwards from a wanted margin: price = cost / (1 - margin)."""
        margin = Decimal(str(target_margin))
        if not 0 <= margin < 100:
            raise ValueError("Target margin must be between 0 and 100 percent (100 is impossible).")

        cost_cents = to_cents(cost_price)
        exact = int((Decimal(cost_cents) / (1 - margin / 100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))

        return PriceSuggestion(
            cost_price_cents=cost_cents,
            suggested_price_cents=round_to_practical(exact, self.rounding_cents),
            exact_price_cents=exact,
            requested_markup_percent=markup_percent(cost_cents, exact),
        )

    def suggest_price_options(self, cost_price: Money) -> dict[str, PriceSuggestion]:
        """Three prices to choose between, rather than one take-it-or-leave-it number."""
        return {
            "Competitive": self.suggest_price(cost_price, Decimal("20")),
            "Recommended": self.suggest_price(cost_price, self.default_markup_percent),
            "Premium": self.suggest_price(cost_price, Decimal("50")),
        }

    # -------------------------------------------------------- reviewing
    def minimum_margin_for(self, category: str) -> Decimal:
        return CATEGORY_MIN_MARGIN.get(category.strip().lower(), DEFAULT_MIN_MARGIN)

    def classify(self, cost_cents: int, selling_cents: int, category: str = "") -> PriceHealth:
        if selling_cents < cost_cents:
            return PriceHealth.LOSS
        margin = margin_percent(cost_cents, selling_cents)
        if margin < self.minimum_margin_for(category):
            return PriceHealth.TOO_LOW
        if margin > HIGH_MARGIN_PERCENT:
            return PriceHealth.HIGH
        return PriceHealth.HEALTHY

    def analyse(self, cost_price: Money, selling_price: Money,
                category: str = "", product_name: str | None = None) -> PriceAnalysis:
        cost_cents = to_cents(cost_price)
        selling_cents = to_cents(selling_price)
        return PriceAnalysis(
            cost_price_cents=cost_cents,
            selling_price_cents=selling_cents,
            health=self.classify(cost_cents, selling_cents, category),
            minimum_margin_percent=self.minimum_margin_for(category),
            product_name=product_name,
        )

    def analyse_product(self, product: Product) -> PriceAnalysis:
        return self.analyse(
            cost_price=to_rand(product.cost_price_cents),
            selling_price=to_rand(product.selling_price_cents),
            category=product.category,
            product_name=product.name,
        )

    def check_product(self, name: str) -> PriceAnalysis | None:
        product = self.db.find_by_name(name)
        return self.analyse_product(product) if product else None

    def review_all(self) -> PricingReview:
        analyses = [self.analyse_product(p) for p in self.db.list_products()]
        analyses.sort(key=lambda a: (not a.needs_attention, a.margin_percent))
        return PricingReview(analyses=analyses)

    # ------------------------------------------------------- what-if
    def price_change_impact(self, name: str, new_price: Money) -> PriceChangeImpact | None:
        product = self.db.find_by_name(name)
        if product is None:
            return None
        return PriceChangeImpact(
            product_name=product.name,
            cost_price_cents=product.cost_price_cents,
            old_price_cents=product.selling_price_cents,
            new_price_cents=to_cents(new_price),
            quantity=product.quantity,
        )

    def apply_suggested_price(self, name: str, new_price: Money) -> Product | None:
        """Actually change the price in the database, once the owner agrees."""
        product = self.db.find_by_name(name)
        if product is None:
            return None
        return self.db.update_product(product.id, selling_price=new_price)
