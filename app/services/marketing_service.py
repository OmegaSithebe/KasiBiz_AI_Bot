"""Marketing maths for KasiBiz: what to promote, and what a promotion really costs.

No artificial intelligence in this file. Its job is to stop the shop owner
advertising themselves into trouble, in two specific ways:

    1. Never promote something that is about to run out.
    2. Never promote a discount that sells below cost.

The Marketing Agent writes the words. This decides what the words are allowed
to say.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from enum import Enum

from app.database.sqlite_db import (
    Money,
    Product,
    StockDatabase,
    format_rand,
    get_db,
    to_cents,
)
from app.services.pricing_service import margin_percent, round_to_practical

DEFAULT_SHOP_NAME = "KasiBiz Spaza"

# A promotion should not be run on stock that is barely covering normal trade.
MIN_STOCK_MULTIPLE_TO_PROMOTE = 2

# Below this margin a promotion is not worth running: there is no room to
# discount, so the owner is warned even though the offer is not a loss.
# This is stricter than the pricing minimums, which judge everyday prices.
DEFAULT_MIN_SAFE_MARGIN = 10


class Channel(str, Enum):
    WHATSAPP = "WhatsApp advert"
    SOCIAL = "Social media caption"
    POSTER = "Shop poster"

    @property
    def guidance(self) -> str:
        return {
            "WhatsApp advert": (
                "Very short, 2 to 4 lines. Written to be forwarded to a WhatsApp "
                "status or a community group. A few emoji are welcome. End with the "
                "shop name."
            ),
            "Social media caption": (
                "3 to 5 lines for Facebook or Instagram. Friendly and a bit playful. "
                "Finish with 3 to 5 short hashtags."
            ),
            "Shop poster": (
                "Very few words in capitals, laid out in short lines, so it can be "
                "written on cardboard and stuck in the window. No hashtags, no emoji. "
                "The price must be the biggest thing on it."
            ),
        }[self.value]


class OfferType(str, Enum):
    STRAIGHT = "straight"
    PERCENT_OFF = "percent_off"
    FIXED_PRICE = "fixed_price"
    BUNDLE = "bundle"


class PromoSafety(str, Enum):
    SAFE = "SAFE"
    THIN_PROFIT = "THIN PROFIT"
    LOW_STOCK = "NOT ENOUGH STOCK"
    LOSS = "SELLS AT A LOSS"

    @property
    def blocks_campaign(self) -> bool:
        return self in (PromoSafety.LOSS, PromoSafety.LOW_STOCK)

    @property
    def warning(self) -> str:
        return {
            "SAFE": "",
            "THIN PROFIT": "You will still make money, but only just. Check it is worth it.",
            "NOT ENOUGH STOCK": "Do not advertise this yet. You will run out and disappoint customers.",
            "SELLS AT A LOSS": "Do not run this. You would lose money on every one you sell.",
        }[self.value]


@dataclass(frozen=True)
class PromoOffer:
    """One promotion, with every figure worked out before a word is written."""

    product: Product
    offer_type: OfferType
    promo_price_cents: int
    units_in_offer: int = 1
    safety: PromoSafety = PromoSafety.SAFE

    @property
    def name(self) -> str:
        return self.product.name

    @property
    def normal_price_cents(self) -> int:
        return self.product.selling_price_cents * self.units_in_offer

    @property
    def cost_cents(self) -> int:
        return self.product.cost_price_cents * self.units_in_offer

    @property
    def saving_cents(self) -> int:
        return max(self.normal_price_cents - self.promo_price_cents, 0)

    @property
    def discount_percent(self) -> Decimal:
        if self.normal_price_cents == 0:
            return Decimal("0.00")
        return (Decimal(self.saving_cents) / Decimal(self.normal_price_cents) * 100
                ).quantize(Decimal("0.01"))

    @property
    def profit_cents(self) -> int:
        return self.promo_price_cents - self.cost_cents

    @property
    def margin_percent(self) -> Decimal:
        return margin_percent(self.cost_cents, self.promo_price_cents)

    @property
    def is_discounted(self) -> bool:
        return self.saving_cents > 0

    @property
    def max_units_available(self) -> int:
        return self.product.quantity // self.units_in_offer

    @property
    def profit_if_all_sold_cents(self) -> int:
        return self.profit_cents * self.max_units_available

    def as_facts(self) -> str:
        """The factual brief handed to the copywriter. Numbers only, no adjectives."""
        lines = [f"Product: {self.name} ({self.product.unit})"]

        if self.offer_type is OfferType.BUNDLE:
            lines.append(f"Offer: {self.units_in_offer} for "
                         f"{format_rand(self.promo_price_cents)}")
            lines.append(f"Normally: {format_rand(self.normal_price_cents)} "
                         f"for {self.units_in_offer}")
        elif self.is_discounted:
            lines.append(f"Promotion price: {format_rand(self.promo_price_cents)}")
            lines.append(f"Normal price: {format_rand(self.normal_price_cents)}")
        else:
            lines.append(f"Price: {format_rand(self.promo_price_cents)}")

        if self.is_discounted:
            lines.append(f"Customer saves: {format_rand(self.saving_cents)} "
                         f"({self.discount_percent}% off)")

        lines.append(f"Stock available: {self.product.quantity} {self.product.unit}")
        return "\n".join(lines)

    def as_summary(self) -> str:
        """One line for the owner, showing what the promotion does to their profit."""
        if self.is_discounted:
            return (
                f"{self.name}: {format_rand(self.normal_price_cents)} -> "
                f"{format_rand(self.promo_price_cents)} "
                f"({self.discount_percent}% off). You still make "
                f"{format_rand(self.profit_cents)} each. "
                f"{self.product.quantity} in stock. [{self.safety.value}]"
            )
        return (
            f"{self.name} at {format_rand(self.promo_price_cents)}, "
            f"profit {format_rand(self.profit_cents)} each, "
            f"{self.product.quantity} in stock. [{self.safety.value}]"
        )


@dataclass(frozen=True)
class PromoCandidate:
    """A product worth promoting, and why."""

    product: Product
    score: Decimal
    reason: str

    @property
    def name(self) -> str:
        return self.product.name


class MarketingService:
    """Chooses what to promote and works out what each promotion costs."""

    def __init__(
        self,
        db: StockDatabase | None = None,
        shop_name: str = DEFAULT_SHOP_NAME,
        min_safe_margin_percent: Money = DEFAULT_MIN_SAFE_MARGIN,
    ) -> None:
        self.db = db or get_db()
        self.shop_name = shop_name.strip() or DEFAULT_SHOP_NAME
        self.min_safe_margin_percent = Decimal(str(min_safe_margin_percent))

    # ------------------------------------------------- choosing what to push
    def suggest_products_to_promote(self, limit: int = 5) -> list[PromoCandidate]:
        """Plenty of stock plus a healthy margin makes the best promotion."""
        candidates: list[PromoCandidate] = []

        for product in self.db.list_products():
            floor = max(product.low_stock_threshold, 1) * MIN_STOCK_MULTIPLE_TO_PROMOTE
            if product.quantity < floor:
                continue
            if product.profit_per_unit_cents <= 0:
                continue

            stock_cover = Decimal(product.quantity) / Decimal(max(product.low_stock_threshold, 1))
            score = (stock_cover * product.margin_percent).quantize(Decimal("0.01"))
            candidates.append(PromoCandidate(
                product=product,
                score=score,
                reason=(
                    f"{product.quantity} in stock ({stock_cover.quantize(Decimal('0.1'))}x "
                    f"the alert level) and a {product.margin_percent}% margin"
                ),
            ))

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:limit]

    # ------------------------------------------------------ building offers
    def assess_safety(self, product: Product, promo_price_cents: int,
                      units: int = 1) -> PromoSafety:
        cost = product.cost_price_cents * units
        if promo_price_cents < cost:
            return PromoSafety.LOSS
        if product.quantity < max(product.low_stock_threshold, 1) * MIN_STOCK_MULTIPLE_TO_PROMOTE:
            return PromoSafety.LOW_STOCK
        if margin_percent(cost, promo_price_cents) < self.min_safe_margin_percent:
            return PromoSafety.THIN_PROFIT
        return PromoSafety.SAFE

    def build_offer(self, name: str, discount_percent: Money | None = None,
                    promo_price: Money | None = None) -> PromoOffer | None:
        """A single-item offer: full price, a percentage off, or a fixed price."""
        product = self.db.find_by_name(name)
        if product is None:
            return None

        if promo_price is not None:
            price_cents = to_cents(promo_price)
            offer_type = OfferType.FIXED_PRICE
        elif discount_percent is not None:
            discount = Decimal(str(discount_percent))
            if not 0 <= discount < 100:
                raise ValueError("Discount must be between 0 and 100 percent.")
            raw = Decimal(product.selling_price_cents) * (1 - discount / 100)
            price_cents = round_to_practical(int(raw))
            offer_type = OfferType.PERCENT_OFF if discount else OfferType.STRAIGHT
        else:
            price_cents = product.selling_price_cents
            offer_type = OfferType.STRAIGHT

        return PromoOffer(
            product=product,
            offer_type=offer_type,
            promo_price_cents=price_cents,
            safety=self.assess_safety(product, price_cents),
        )

    def build_bundle(self, name: str, units: int, bundle_price: Money) -> PromoOffer | None:
        """A multi-buy: '2 loaves for R35'."""
        if units < 2:
            raise ValueError("A bundle needs at least 2 units.")

        product = self.db.find_by_name(name)
        if product is None:
            return None

        price_cents = to_cents(bundle_price)
        return PromoOffer(
            product=product,
            offer_type=OfferType.BUNDLE,
            promo_price_cents=price_cents,
            units_in_offer=units,
            safety=self.assess_safety(product, price_cents, units),
        )

    def max_safe_discount_percent(self, name: str) -> Decimal | None:
        """The biggest discount that still breaks even, rounded down to be safe."""
        product = self.db.find_by_name(name)
        if product is None or product.selling_price_cents == 0:
            return None
        room = Decimal(product.profit_per_unit_cents) / Decimal(product.selling_price_cents) * 100
        return max(room.quantize(Decimal("1"), rounding=ROUND_DOWN), Decimal("0"))

    def suggest_offer(self, name: str) -> PromoOffer | None:
        """A sensible promotion the owner can afford, chosen automatically."""
        headroom = self.max_safe_discount_percent(name)
        if headroom is None:
            return None
        # Give away at most half the profit, and never more than 25% off.
        discount = min(headroom / 2, Decimal("25")).quantize(Decimal("1"), rounding=ROUND_DOWN)
        return self.build_offer(name, discount_percent=discount)

    # ----------------------------------------------------------- the brief
    def campaign_brief(self, offer: PromoOffer, channel: Channel,
                       occasion: str | None = None) -> str:
        """Everything the copywriter is allowed to know, and nothing more."""
        lines = [
            f"Shop name: {self.shop_name}",
            f"Channel: {channel.value}",
            f"Format guidance: {channel.guidance}",
            "",
            offer.as_facts(),
        ]
        if occasion:
            lines.append(f"Occasion: {occasion}")
        if offer.safety is PromoSafety.THIN_PROFIT:
            lines.append("Note: margin is thin, so do not promise unlimited quantities.")
        return "\n".join(lines)
