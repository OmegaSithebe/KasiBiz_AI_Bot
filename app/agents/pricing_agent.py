"""The Pricing Helper: suggests prices and explains them in plain language.

Same three moves as the Stock Agent (Day 7):

    1. UNDERSTAND  what is being asked, and pull any Rand amounts out of the text
    2. CALCULATE   ask PricingService for exact figures - no AI anywhere near this
    3. EXPLAIN     the LLM turns those figures into an explanation the owner gets

Day 8's second requirement is "let the LLM explain the pricing in simple terms",
so the phrasing prompt here is deliberately a teaching prompt, not a summary one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from app.services.pricing_service import PricingService
from app.utils.config import ConfigError
from app.utils.llm_client import KasiBizLLM, LLMError

PRICING_AGENT_PROMPT = (
    "You are the KasiBiz Pricing Helper for a South African spaza shop owner.\n"
    "You will be given PRICING FACTS that were already calculated. Your job is to "
    "explain them so clearly that someone who never studied business understands.\n"
    "\n"
    "LANGUAGE RULE - THIS COMES FIRST AND OVERRIDES EVERYTHING ELSE:\n"
    "Look at the language the owner wrote their question in and reply in THAT "
    "language. If they wrote isiZulu, answer fully in isiZulu. If they wrote "
    "Sesotho, answer fully in Sesotho. Only answer in English if they wrote "
    "English. The facts below are always written in English - that is for you to "
    "read, it is NOT the language you must reply in.\n"
    "\n"
    "Other rules:\n"
    "- Never invent, change or recalculate any number. Use the facts exactly as given.\n"
    "- Explain like you are talking to a friend behind the counter, not writing a report.\n"
    "- When both markup and margin appear, explain the difference in one short line: "
    "markup is measured against what you PAID, margin against what you CHARGE.\n"
    "- Money is South African Rand, already written as R00.00. Do not convert it.\n"
    "- Keep it under 120 words and end with one clear action.\n"
    "- Never give tax or VAT advice. If asked, say the owner should check with SARS."
)


class PricingIntent(str, Enum):
    SUGGEST_PRICE = "suggest_price"
    CHECK_PRICE = "check_price"
    REVIEW_ALL = "review_all"
    WHAT_IF = "what_if"
    EXPLAIN_CONCEPT = "explain_concept"
    UNKNOWN = "unknown"


INTENT_KEYWORDS: dict[PricingIntent, tuple[str, ...]] = {
    PricingIntent.EXPLAIN_CONCEPT: (
        "what is markup", "what is a markup", "what is margin", "what's margin",
        "difference between markup", "markup vs margin", "markup or margin",
        "explain markup", "explain margin", "how does pricing work",
        "what does margin mean", "what does markup mean",
    ),
    PricingIntent.WHAT_IF: (
        "what if", "if i sell", "if i charge", "should i raise", "should i increase",
        "should i drop", "should i lower", "instead of",
    ),
    PricingIntent.REVIEW_ALL: (
        "my prices", "all my prices", "check my prices", "are my prices",
        "price review", "underpriced", "under priced", "too cheap",
        "losing money", "which products", "am i charging enough",
        "amanani", "ditheko",
    ),
    PricingIntent.SUGGEST_PRICE: (
        "what should i charge", "what should i sell", "how much should i",
        "suggest a price", "what price", "price for", "sell it for",
        "i buy", "i pay", "costs me", "bought it for",
        "ngithengise ngamalini", "ngingayithengisa", "malini",
        "ke rekise ka bokae", "theko",
    ),
    PricingIntent.CHECK_PRICE: (
        "am i making profit", "making profit", "how much profit", "am i making money",
        "is my price", "good price", "right price", "enough profit",
        "ngenza inzuzo", "inzuzo", "phaello",
    ),
}

MONEY_PATTERN = re.compile(r"r?\s*(\d+(?:[.,]\d{1,2})?)", re.IGNORECASE)
PERCENT_PATTERN = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*(?:%|percent|per cent)", re.IGNORECASE)


@dataclass
class PricingResponse:
    text: str
    intent: PricingIntent
    facts: str
    used_llm: bool
    product_name: str | None = None
    amounts: list[Decimal] = field(default_factory=list)

    def __str__(self) -> str:
        return self.text


class PricingAgent:
    """Natural-language front door to the shop's pricing."""

    def __init__(
        self,
        service: PricingService | None = None,
        llm: KasiBizLLM | None = None,
        use_llm: bool = True,
    ) -> None:
        self.service = service or PricingService()
        self.use_llm = use_llm
        self._llm = llm
        self._llm_ready = llm is not None

    # ------------------------------------------------ 1. UNDERSTAND
    @staticmethod
    def extract_amounts(text: str) -> list[Decimal]:
        """Pull Rand amounts out of free text, ignoring anything with a % sign."""
        percents = {m.group(1) for m in PERCENT_PATTERN.finditer(text)}
        return [
            Decimal(m.group(1).replace(",", "."))
            for m in MONEY_PATTERN.finditer(text)
            if m.group(1) not in percents
        ]

    @staticmethod
    def extract_percent(text: str) -> Decimal | None:
        match = PERCENT_PATTERN.search(text)
        return Decimal(match.group(1).replace(",", ".")) if match else None

    def _find_product_name(self, text: str) -> str | None:
        matches = [p.name for p in self.service.db.list_products() if p.name.lower() in text]
        return max(matches, key=len) if matches else None

    def detect_intent(self, question: str) -> tuple[PricingIntent, str | None]:
        text = question.lower().strip()
        if not text:
            return PricingIntent.UNKNOWN, None

        product = self._find_product_name(text)

        # Concept questions win outright - they are not about any one product.
        for phrase in INTENT_KEYWORDS[PricingIntent.EXPLAIN_CONCEPT]:
            if phrase in text:
                return PricingIntent.EXPLAIN_CONCEPT, None

        for intent in (
            PricingIntent.WHAT_IF,
            PricingIntent.REVIEW_ALL,
            PricingIntent.SUGGEST_PRICE,
            PricingIntent.CHECK_PRICE,
        ):
            if any(word in text for word in INTENT_KEYWORDS[intent]):
                return intent, product

        if product:
            return PricingIntent.CHECK_PRICE, product
        return PricingIntent.UNKNOWN, None

    # ------------------------------------------------- 2. CALCULATE
    def gather_facts(self, intent: PricingIntent, question: str,
                     product_name: str | None = None) -> str:
        amounts = self.extract_amounts(question)
        markup = self.extract_percent(question)

        if intent is PricingIntent.EXPLAIN_CONCEPT:
            return self._explain_concept_facts()

        if intent is PricingIntent.WHAT_IF:
            return self._what_if_facts(product_name, amounts)

        if intent is PricingIntent.REVIEW_ALL:
            return self.service.review_all().as_text()

        if intent is PricingIntent.SUGGEST_PRICE:
            return self._suggest_facts(product_name, amounts, markup)

        if intent is PricingIntent.CHECK_PRICE:
            return self._check_facts(product_name, amounts)

        return (
            "I can help you with prices. Try asking:\n"
            "  - I buy bread for R15, what should I sell it for?\n"
            "  - Am I making enough profit on Milk 1L?\n"
            "  - Check all my prices\n"
            "  - What if I sell White Bread for R22?\n"
            "  - What is the difference between markup and margin?"
        )

    def _explain_concept_facts(self) -> str:
        example = self.service.suggest_price("15.00", Decimal("33.33"), round_price=False)
        return (
            "MARKUP and MARGIN are two ways of measuring the same profit.\n"
            "Worked example: you buy for R15.00 and sell for R20.00, "
            "so your profit is R5.00.\n"
            "  Markup = profit divided by what you PAID  = R5.00 / R15.00 = 33.33%\n"
            "  Margin = profit divided by what you CHARGE = R5.00 / R20.00 = 25.00%\n"
            "Same R5.00 profit, two different percentages. Shops that think a "
            "33% markup means a 33% margin end up charging too little.\n"
            f"(Check: adding 33.33% markup to R15.00 gives "
            f"{self._rand(example.exact_price_cents)}.)"
        )

    @staticmethod
    def _rand(cents: int) -> str:
        from app.database.sqlite_db import format_rand
        return format_rand(cents)

    def _suggest_facts(self, product_name: str | None, amounts: list[Decimal],
                       markup: Decimal | None) -> str:
        cost: Decimal | None = None
        label = product_name

        if amounts:
            cost = min(amounts)
        elif product_name:
            product = self.service.db.find_by_name(product_name)
            if product:
                cost = Decimal(product.cost_price_cents) / 100

        if cost is None:
            return (
                "To suggest a price I need to know what you paid for it. "
                "Try: 'I buy bread for R15, what should I sell it for?'"
            )

        options = self.service.suggest_price_options(cost)
        recommended = (
            self.service.suggest_price(cost, markup) if markup is not None
            else options["Recommended"]
        )

        lines = [
            f"Cost price: {self._rand(recommended.cost_price_cents)}"
            + (f" ({label})" if label else ""),
            "",
            f"RECOMMENDED: {recommended.as_sentence()}",
            "",
            "Other options:",
        ]
        for name, option in options.items():
            if name == "Recommended" and markup is None:
                continue
            lines.append(
                f"  {name} ({option.requested_markup_percent}% markup): "
                f"sell at {self._rand(option.suggested_price_cents)}, "
                f"profit {self._rand(option.profit_cents)} each"
            )
        return "\n".join(lines)

    def _check_facts(self, product_name: str | None, amounts: list[Decimal]) -> str:
        if product_name:
            analysis = self.service.check_product(product_name)
            if analysis:
                return analysis.as_sentence()

        if len(amounts) >= 2:
            cost, selling = min(amounts), max(amounts)
            return self.service.analyse(cost, selling).as_sentence()

        return (
            "Tell me which product, or give me both numbers. "
            "For example: 'I buy it for R15 and sell for R20, am I making profit?'"
        )

    def _what_if_facts(self, product_name: str | None, amounts: list[Decimal]) -> str:
        if not product_name:
            return "Tell me which product you want to change the price of."
        if not amounts:
            return f"What new price are you thinking of for {product_name}?"

        impact = self.service.price_change_impact(product_name, max(amounts))
        if impact is None:
            return f"The shop does not stock anything called '{product_name}'."

        analysis = self.service.analyse(
            Decimal(impact.cost_price_cents) / 100,
            Decimal(impact.new_price_cents) / 100,
        )
        return f"{impact.as_sentence()}\nAt the new price: {analysis.health.value}. {analysis.health.advice}"

    # --------------------------------------------------- 3. EXPLAIN
    def _get_llm(self) -> KasiBizLLM | None:
        if not self.use_llm:
            return None
        if not self._llm_ready:
            try:
                self._llm = KasiBizLLM()
            except (ConfigError, LLMError, Exception):
                self._llm = None
            self._llm_ready = True
        return self._llm

    def _explain(self, question: str, facts: str) -> tuple[str, bool]:
        llm = self._get_llm()
        if llm is None:
            return facts, False

        prompt = (
            f"The shop owner asked: {question}\n\n"
            f"PRICING FACTS (already calculated - do not change any number):\n{facts}\n\n"
            "Explain this to the owner in simple terms using only these facts."
        )
        try:
            reply = llm.ask(prompt, system_prompt=PRICING_AGENT_PROMPT, temperature=0.4)
        except LLMError:
            return facts, False
        return (reply, True) if reply.strip() else (facts, False)

    # ------------------------------------------------------- public
    def answer(self, question: str) -> PricingResponse:
        intent, product_name = self.detect_intent(question)
        facts = self.gather_facts(intent, question.lower(), product_name)
        text, used_llm = self._explain(question, facts)

        return PricingResponse(
            text=text,
            intent=intent,
            facts=facts,
            used_llm=used_llm,
            product_name=product_name,
            amounts=self.extract_amounts(question.lower()),
        )
