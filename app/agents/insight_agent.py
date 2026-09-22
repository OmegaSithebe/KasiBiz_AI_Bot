"""The Insights Agent: telling the owner what the books actually say.

The temptation with an agent like this is to let the model look at some numbers
and offer an opinion. That is exactly what it must not do. A shop owner acting
on an invented "your best seller is bread" will order the wrong stock with real
money.

So every insight this agent gives states four things:

    THE PERIOD   which days were counted
    THE DATA     how many sales and items that covers
    THE RESULT   the figure itself, counted in Python
    ONE ACTION   something the owner can do today

And when there is not enough recorded data, it says so plainly instead of
finding something to say.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.agents.intents import InsightIntent, Route, keywords_for
from app.database.sqlite_db import format_rand
from app.services.analytics_service import AnalyticsService, Period, PeriodReport
from app.utils.config import ConfigError
from app.utils.language import detect_language, language_directive
from app.utils.llm_client import KasiBizLLM, LLMError

INSIGHTS_SYSTEM_PROMPT = (
    "You explain a South African spaza shop's own sales figures to its owner.\n"
    "- You will be given counted figures. Reword them. Never add a number.\n"
    "- Never say a product is popular, slow or profitable unless the figures say so.\n"
    "- If the figures say there is not enough data, say that plainly. Do not guess.\n"
    "- Always name the period the figures cover.\n"
    "- Plain everyday words, no business jargon. Under 90 words.\n"
    "- Money is South African Rand, already written as R00.00. Do not convert it.\n"
    "- End with one clear thing the owner can do today."
)

INTENT_KEYWORDS: dict[InsightIntent, tuple[str, ...]] = keywords_for(
    Route.INSIGHTS, InsightIntent
)

PERIOD_PHRASES: tuple[tuple[str, str], ...] = (
    ("today", Period.TODAY),
    ("so far today", Period.TODAY),
    ("yesterday", Period.YESTERDAY),
    ("last week", Period.LAST_WEEK),
    ("this week", Period.WEEK),
    ("past week", Period.WEEK),
    ("last 7 days", Period.WEEK),
    ("this month", Period.MONTH),
    ("past month", Period.MONTH),
    ("last 30 days", Period.MONTH),
    ("all time", Period.ALL),
    ("ever", Period.ALL),
    ("altogether", Period.ALL),
    ("namuhla", Period.TODAY),
    ("vandag", Period.TODAY),
    ("kajeno", Period.TODAY),
)

NOT_ENOUGH_DATA = (
    "I cannot answer that yet - there are no sales recorded {when}.\n"
    "Record a few sales first and then ask me again."
)


@dataclass
class InsightResponse:
    text: str
    intent: InsightIntent
    facts: str
    period: str
    used_llm: bool = False
    has_data: bool = True
    report: PeriodReport | None = None
    rows: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return self.text


class InsightsAgent:
    """Answers questions about the shop's performance, from recorded sales only."""

    def __init__(
        self,
        service: AnalyticsService | None = None,
        llm: KasiBizLLM | None = None,
        use_llm: bool = True,
    ) -> None:
        self.service = service or AnalyticsService()
        self.use_llm = use_llm
        self._llm = llm
        self._llm_ready = llm is not None

    # ------------------------------------------------------- 1. UNDERSTAND
    @staticmethod
    def detect_period(question: str) -> str:
        text = question.lower()
        for phrase, period in PERIOD_PHRASES:
            if phrase in text:
                return period
        return Period.WEEK

    def detect_intent(self, question: str) -> InsightIntent:
        text = question.lower().strip()
        if not text:
            return InsightIntent.UNKNOWN

        for intent in (
            InsightIntent.COMPARE,
            InsightIntent.BEST_SELLERS,
            InsightIntent.SLOW_MOVERS,
            InsightIntent.LOW_STOCK,
            InsightIntent.PROFIT,
            InsightIntent.SALES_TOTAL,
            InsightIntent.OVERVIEW,
        ):
            if any(word in text for word in INTENT_KEYWORDS[intent]):
                return intent
        return InsightIntent.OVERVIEW

    # -------------------------------------------------------- 2. THE BOOKS
    def answer(self, question: str) -> InsightResponse:
        intent = self.detect_intent(question)
        period = self.detect_period(question)

        builders = {
            InsightIntent.BEST_SELLERS: self._best_sellers,
            InsightIntent.SLOW_MOVERS: self._slow_movers,
            InsightIntent.LOW_STOCK: self._low_stock,
            InsightIntent.SALES_TOTAL: self._sales_total,
            InsightIntent.PROFIT: self._profit,
            InsightIntent.COMPARE: self._compare,
            InsightIntent.OVERVIEW: self._overview,
        }
        return builders.get(intent, self._overview)(period)

    # ---------------------------------------------------------- the reports
    def _no_data(self, intent: InsightIntent, period: str,
                 report: PeriodReport | None = None) -> InsightResponse:
        when = Period.label(period)
        return InsightResponse(
            NOT_ENOUGH_DATA.format(when=when),
            intent, facts=f"No sales recorded {when}.", period=period,
            has_data=False, report=report,
        )

    def _best_sellers(self, period: str) -> InsightResponse:
        rows, report = self.service.best_sellers(period)
        if not report.has_data or not rows:
            return self._no_data(InsightIntent.BEST_SELLERS, period, report)

        listed = [f"  {i}. {row.as_row()}" for i, row in enumerate(rows, 1)]
        facts = "\n".join([
            f"Period: {report.label}",
            f"Based on {report.sale_count} recorded sale(s), {report.units} item(s).",
            "Best sellers by units:",
            *listed,
        ])

        caveat = ("" if self.service.enough_data_to_rank(report) else
                  f"\nThis is only {report.sale_count} sale(s), so treat the order "
                  "as early days rather than a trend.")
        text = (f"Best sellers for {report.label} "
                f"(from {report.sale_count} recorded sale(s)):\n"
                + "\n".join(listed)
                + caveat
                + f"\n\nNext: check you have enough {rows[0].product_name} for the week.")

        return InsightResponse(self._reword(text, facts), InsightIntent.BEST_SELLERS,
                               facts=facts, period=period, report=report,
                               rows=[r.as_row() for r in rows],
                               used_llm=self._used_llm_last)

    def _slow_movers(self, period: str) -> InsightResponse:
        movers, report = self.service.slow_movers(period)
        if not movers:
            return InsightResponse(
                "There is nothing on the shelf to report on yet.",
                InsightIntent.SLOW_MOVERS, facts="No stock on hand.",
                period=period, has_data=False, report=report,
            )
        if not report.has_data:
            return self._no_data(InsightIntent.SLOW_MOVERS, period, report)

        listed = [f"  {i}. {m.as_row()}" for i, m in enumerate(movers, 1)]
        tied_up = sum(m.stock_value_cents for m in movers)
        facts = "\n".join([
            f"Period: {report.label}",
            f"Compared against {report.sale_count} recorded sale(s).",
            "Slowest movers that are in stock:",
            *listed,
            f"Cash tied up in these: {format_rand(tied_up)}",
        ])

        text = (f"Moving slowest over {report.label} "
                f"(measured against {report.sale_count} recorded sale(s)):\n"
                + "\n".join(listed)
                + f"\n\nThat is {format_rand(tied_up)} sitting on the shelf. "
                f"Next: try a small promotion on {movers[0].product_name}.")

        return InsightResponse(self._reword(text, facts), InsightIntent.SLOW_MOVERS,
                               facts=facts, period=period, report=report,
                               rows=[m.as_row() for m in movers],
                               used_llm=self._used_llm_last)

    def _low_stock(self, period: str) -> InsightResponse:
        products = self.service.restock_list()
        if not products:
            facts = "No product is at or below its alert level."
            return InsightResponse(
                "Nothing needs restocking right now. Every product is above its alert level.",
                InsightIntent.LOW_STOCK, facts=facts, period=period,
            )

        listed = [f"  {i}. {p.name}: {p.quantity} left (alert level {p.low_stock_threshold})"
                  for i, p in enumerate(products, 1)]
        facts = "\n".join(["Source: current stock levels, not sales history.",
                           f"{len(products)} product(s) at or below the alert level:",
                           *listed])
        text = (f"{len(products)} product(s) need restocking:\n" + "\n".join(listed)
                + f"\n\nNext: put {products[0].name} at the top of the supplier list.")

        return InsightResponse(self._reword(text, facts), InsightIntent.LOW_STOCK,
                               facts=facts, period=period,
                               rows=[line.strip() for line in listed],
                               used_llm=self._used_llm_last)

    def _sales_total(self, period: str) -> InsightResponse:
        report = self.service.report(period)
        if not report.has_data:
            return self._no_data(InsightIntent.SALES_TOTAL, period, report)

        facts = report.as_facts()
        text = (f"For {report.label} you recorded {report.sale_count} sale(s) "
                f"covering {report.units} item(s).\n"
                f"Money taken: {format_rand(report.revenue_cents)}\n"
                f"Gross profit: {format_rand(report.profit_cents)} "
                f"({report.margin_percent}% of sales)\n"
                f"Average sale: {format_rand(report.average_sale_cents)}\n\n"
                "Next: compare this with last week to see which way you are going.")

        return InsightResponse(self._reword(text, facts), InsightIntent.SALES_TOTAL,
                               facts=facts, period=period, report=report,
                               used_llm=self._used_llm_last)

    def _profit(self, period: str) -> InsightResponse:
        report = self.service.report(period)
        if not report.has_data:
            return self._no_data(InsightIntent.PROFIT, period, report)

        top = report.most_profitable(3)
        listed = [f"  {i}. {p.product_name}: {format_rand(p.profit_cents)} profit "
                  f"from {p.units} sold" for i, p in enumerate(top, 1)]
        facts = "\n".join([report.as_facts(), "Most profitable products:", *listed])

        text = (f"Gross profit for {report.label}: "
                f"{format_rand(report.profit_cents)} on "
                f"{format_rand(report.revenue_cents)} of sales "
                f"({report.margin_percent}%).\n"
                f"Based on {report.sale_count} recorded sale(s).\n"
                + "\n".join(listed)
                + "\n\nThis counts what you paid for the goods only, not rent or transport."
                + f"\nNext: check the price on {top[-1].product_name} if it is working too hard.")

        return InsightResponse(self._reword(text, facts), InsightIntent.PROFIT,
                               facts=facts, period=period, report=report,
                               rows=[line.strip() for line in listed],
                               used_llm=self._used_llm_last)

    def _compare(self, period: str) -> InsightResponse:
        if period in (Period.LAST_WEEK, Period.ALL):
            period = Period.WEEK
        against = {Period.TODAY: Period.YESTERDAY}.get(period, Period.LAST_WEEK)

        now_report, then_report = self.service.compare(period, against)

        if not now_report.has_data and not then_report.has_data:
            return self._no_data(InsightIntent.COMPARE, period, now_report)
        if not then_report.has_data:
            facts = "\n".join([now_report.as_facts(),
                               f"Nothing recorded for {then_report.label}, "
                               "so there is nothing to compare against."])
            return InsightResponse(
                f"You took {format_rand(now_report.revenue_cents)} "
                f"over {now_report.label}, but there are no sales recorded for "
                f"{then_report.label} yet, so I cannot compare the two.\n\n"
                "Next: keep recording sales and ask again next week.",
                InsightIntent.COMPARE, facts=facts, period=period,
                report=now_report, has_data=True,
            )

        difference = now_report.revenue_cents - then_report.revenue_cents
        direction = "up" if difference > 0 else "down" if difference < 0 else "level"
        facts = "\n".join([
            now_report.as_facts(), "", then_report.as_facts(), "",
            f"Difference: {format_rand(abs(difference))} {direction}.",
        ])
        text = (f"{now_report.label.capitalize()}: "
                f"{format_rand(now_report.revenue_cents)} from "
                f"{now_report.sale_count} sale(s).\n"
                f"{then_report.label.capitalize()}: "
                f"{format_rand(then_report.revenue_cents)} from "
                f"{then_report.sale_count} sale(s).\n"
                f"That is {format_rand(abs(difference))} {direction}.\n\n"
                "Next: look at which products changed the most.")

        return InsightResponse(self._reword(text, facts), InsightIntent.COMPARE,
                               facts=facts, period=period, report=now_report,
                               used_llm=self._used_llm_last)

    def _overview(self, period: str) -> InsightResponse:
        report = self.service.report(period)
        low = self.service.restock_list(limit=3)

        if not report.has_data:
            low_note = ("" if not low else
                        "\n\nWhat I can tell you from stock levels: "
                        + ", ".join(f"{p.name} is down to {p.quantity}" for p in low) + ".")
            response = self._no_data(InsightIntent.OVERVIEW, period, report)
            return InsightResponse(response.text + low_note, InsightIntent.OVERVIEW,
                                   facts=response.facts, period=period,
                                   has_data=False, report=report)

        best = report.best_sellers(3)
        listed = [f"  {i}. {b.as_row()}" for i, b in enumerate(best, 1)]
        facts = "\n".join([report.as_facts(), "Top by units:", *listed])
        if low:
            facts += "\nLow stock right now: " + ", ".join(
                f"{p.name} ({p.quantity} left)" for p in low)

        text = (f"How the shop did over {report.label}:\n"
                f"  {report.sale_count} sale(s), {report.units} item(s)\n"
                f"  {format_rand(report.revenue_cents)} taken, "
                f"{format_rand(report.profit_cents)} gross profit\n"
                "Top by units:\n" + "\n".join(listed))
        if low:
            text += ("\n\nRunning low: "
                     + ", ".join(f"{p.name} ({p.quantity})" for p in low))
        text += "\n\nNext: reorder whatever is both selling well and running low."

        return InsightResponse(self._reword(text, facts), InsightIntent.OVERVIEW,
                               facts=facts, period=period, report=report,
                               rows=[line.strip() for line in listed],
                               used_llm=self._used_llm_last)

    # -------------------------------------------------------- 3. THE WORDS
    _used_llm_last = False

    def _get_llm(self) -> KasiBizLLM | None:
        if not self._llm_ready:
            try:
                self._llm = KasiBizLLM()
            except (ConfigError, LLMError, Exception):
                self._llm = None
            self._llm_ready = True
        return self._llm

    def _reword(self, fallback: str, facts: str) -> str:
        self._used_llm_last = False
        if not self.use_llm or not facts:
            return fallback

        llm = self._get_llm()
        if llm is None:
            return fallback

        try:
            reply = llm.ask(
                f"Explain these recorded figures to the shop owner:\n{facts}",
                system_prompt=INSIGHTS_SYSTEM_PROMPT + "\n" + language_directive(
                    detect_language(fallback).language),
                temperature=0.3, max_tokens=220,
            )
        except LLMError:
            return fallback

        self._used_llm_last = bool(reply.strip())
        return reply.strip() or fallback


# Kept so `from app.agents.insight_agent import InsightAgent` also works.
InsightAgent = InsightsAgent
