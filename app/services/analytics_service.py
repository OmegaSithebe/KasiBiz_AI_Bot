"""Reading the shop's own books. Nothing here is estimated or assumed.

Every figure this service returns is counted from rows that exist in the sales
tables. When there are no rows, it says so - it never fills a gap with a guess.
That is the whole point: an insight a shop owner cannot trust is worse than no
insight at all, because they will act on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from app.database.sqlite_db import StockDatabase, format_rand, get_db, to_rand
from app.services.calculation_service import margin_percent_of


class Period:
    """Named windows of time, so 'this week' means the same thing everywhere."""

    TODAY = "today"
    YESTERDAY = "yesterday"
    WEEK = "this_week"
    LAST_WEEK = "last_week"
    MONTH = "this_month"
    ALL = "all_time"

    ALL_NAMES = (TODAY, YESTERDAY, WEEK, LAST_WEEK, MONTH, ALL)

    LABELS = {
        TODAY: "today",
        YESTERDAY: "yesterday",
        WEEK: "the last 7 days",
        LAST_WEEK: "the 7 days before that",
        MONTH: "the last 30 days",
        ALL: "all time",
    }

    @staticmethod
    def label(name: str) -> str:
        return Period.LABELS.get(name, name)

    @staticmethod
    def bounds(name: str, now: datetime | None = None) -> tuple[str | None, str | None]:
        """(since, until) as SQL datetime strings. None means unbounded."""
        now = now or datetime.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        fmt = "%Y-%m-%d %H:%M:%S"

        if name == Period.TODAY:
            return midnight.strftime(fmt), None
        if name == Period.YESTERDAY:
            return ((midnight - timedelta(days=1)).strftime(fmt), midnight.strftime(fmt))
        if name == Period.WEEK:
            return (midnight - timedelta(days=6)).strftime(fmt), None
        if name == Period.LAST_WEEK:
            return ((midnight - timedelta(days=13)).strftime(fmt),
                    (midnight - timedelta(days=6)).strftime(fmt))
        if name == Period.MONTH:
            return (midnight - timedelta(days=29)).strftime(fmt), None
        return None, None


@dataclass(frozen=True)
class ProductSales:
    """What one product did over a period. Counted, not estimated."""

    product_id: int | None
    product_name: str
    units: int
    revenue_cents: int
    cost_cents: int

    @property
    def profit_cents(self) -> int:
        return self.revenue_cents - self.cost_cents

    @property
    def revenue(self) -> Decimal:
        return to_rand(self.revenue_cents)

    def as_row(self) -> str:
        return (f"{self.product_name}: {self.units} sold, "
                f"{format_rand(self.revenue_cents)} in sales, "
                f"{format_rand(self.profit_cents)} profit")


@dataclass
class PeriodReport:
    """Everything recorded in one window of time."""

    period: str
    since: str | None
    until: str | None
    sale_count: int = 0
    units: int = 0
    revenue_cents: int = 0
    cost_cents: int = 0
    products: list[ProductSales] = field(default_factory=list)

    @property
    def label(self) -> str:
        return Period.label(self.period)

    @property
    def profit_cents(self) -> int:
        return self.revenue_cents - self.cost_cents

    @property
    def has_data(self) -> bool:
        return self.sale_count > 0

    @property
    def margin_percent(self) -> Decimal:
        return margin_percent_of(self.profit_cents, self.revenue_cents)

    @property
    def average_sale_cents(self) -> int:
        return self.revenue_cents // self.sale_count if self.sale_count else 0

    def best_sellers(self, limit: int = 5) -> list[ProductSales]:
        return sorted(self.products, key=lambda p: (-p.units, p.product_name))[:limit]

    def most_profitable(self, limit: int = 5) -> list[ProductSales]:
        return sorted(self.products, key=lambda p: (-p.profit_cents, p.product_name))[:limit]

    def as_facts(self) -> str:
        """The counted truth. An agent may reword this but may not add to it."""
        if not self.has_data:
            return f"No sales were recorded {self.label}."
        return "\n".join([
            f"Period: {self.label}",
            f"Sales recorded: {self.sale_count}",
            f"Items sold: {self.units}",
            f"Money taken: {format_rand(self.revenue_cents)}",
            f"Cost of those goods: {format_rand(self.cost_cents)}",
            f"Gross profit: {format_rand(self.profit_cents)} ({self.margin_percent}%)",
            f"Average sale: {format_rand(self.average_sale_cents)}",
        ])


@dataclass(frozen=True)
class SlowMover:
    """A product with stock on the shelf and little or no movement."""

    product_name: str
    quantity: int
    units_sold: int
    stock_value_cents: int

    @property
    def never_sold(self) -> bool:
        return self.units_sold == 0

    def as_row(self) -> str:
        sold = "none sold" if self.never_sold else f"only {self.units_sold} sold"
        return (f"{self.product_name}: {self.quantity} on the shelf, {sold}, "
                f"{format_rand(self.stock_value_cents)} tied up")


class AnalyticsService:
    """Counts what happened. Refuses to describe what did not."""

    # Below this, "best seller" would be a story told about two or three sales.
    MIN_SALES_FOR_RANKING = 3

    def __init__(self, db: StockDatabase | None = None) -> None:
        self.db = db or get_db()

    # ------------------------------------------------------------- reading
    def report(self, period: str = Period.WEEK, now: datetime | None = None) -> PeriodReport:
        if period not in Period.ALL_NAMES:
            raise ValueError(
                f"Unknown period {period!r}. Use one of: {', '.join(Period.ALL_NAMES)}"
            )

        since, until = Period.bounds(period, now)
        sales = self.db.list_sales(since=since, until=until)
        items = self.db.list_sale_items(since=since, until=until)

        grouped: dict[str, dict] = {}
        for item in items:
            key = item["product_name"]
            bucket = grouped.setdefault(key, {
                "product_id": item["product_id"], "units": 0,
                "revenue_cents": 0, "cost_cents": 0,
            })
            bucket["units"] += item["quantity"]
            bucket["revenue_cents"] += item["line_total_cents"]
            bucket["cost_cents"] += item["unit_cost_cents"] * item["quantity"]

        products = [
            ProductSales(data["product_id"], name, data["units"],
                         data["revenue_cents"], data["cost_cents"])
            for name, data in grouped.items()
        ]

        return PeriodReport(
            period=period,
            since=since,
            until=until,
            sale_count=len(sales),
            units=sum(p.units for p in products),
            revenue_cents=sum(int(s["total_cents"]) for s in sales),
            cost_cents=sum(int(s["cost_cents"]) for s in sales),
            products=products,
        )

    def best_sellers(self, period: str = Period.WEEK, limit: int = 5,
                     now: datetime | None = None) -> tuple[list[ProductSales], PeriodReport]:
        report = self.report(period, now)
        return report.best_sellers(limit), report

    def slow_movers(self, period: str = Period.WEEK, limit: int = 5,
                    now: datetime | None = None) -> tuple[list[SlowMover], PeriodReport]:
        """Products the shop is holding that barely moved. Stocked items only."""
        report = self.report(period, now)
        sold_units = {p.product_name: p.units for p in report.products}

        movers = [
            SlowMover(product.name, product.quantity,
                      sold_units.get(product.name, 0), product.stock_value_cents)
            for product in self.db.list_products()
            if product.quantity > 0
        ]
        movers.sort(key=lambda m: (m.units_sold, -m.stock_value_cents))
        return movers[:limit], report

    def restock_list(self, limit: int = 10) -> list:
        """What is low now. Comes from stock levels, not from sales guesswork."""
        return self.db.list_low_stock()[:limit]

    def compare(self, period: str = Period.WEEK, against: str = Period.LAST_WEEK,
                now: datetime | None = None) -> tuple[PeriodReport, PeriodReport]:
        return self.report(period, now), self.report(against, now)

    def enough_data_to_rank(self, report: PeriodReport) -> bool:
        """Whether a ranking would mean anything, or just describe a handful of sales."""
        return report.sale_count >= self.MIN_SALES_FOR_RANKING

    def has_any_sales(self) -> bool:
        return self.db.count_sales() > 0
