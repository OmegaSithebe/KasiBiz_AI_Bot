"""The Sales Agent: serving a customer in ordinary words.

This is the first agent that CHANGES something. Stock, Pricing, Marketing and
Advice all read. This one takes money and moves stock off a shelf, so it is
built around one rule the others do not need:

    Nothing is written until the owner says yes.

The agent holds a basket, adds to it, adds it up and asks for confirmation. Only
then does it call the service, which writes the sale and reduces the stock in a
single transaction. Every figure it quotes comes from the calculation engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from app.agents.intents import (
    Route,
    SalesIntent,
    is_cancellation,
    is_confirmation,
    keywords_for,
)
from app.database.sqlite_db import format_rand
from app.services.calculation_service import InsufficientPaymentError
from app.services.sales_service import (
    AmbiguousProductError,
    Basket,
    CompletedSale,
    EmptyBasketError,
    NotEnoughStockError,
    SalesError,
    SalesService,
    UnknownProductError,
)
from app.utils.config import ConfigError, get_shop_name
from app.utils.language import detect_language, language_directive
from app.utils.llm_client import KasiBizLLM, LLMError

SALES_SYSTEM_PROMPT = (
    "You are the till assistant in a South African spaza shop.\n"
    "- You will be given the EXACT figures for a sale. Repeat them and nothing else.\n"
    "- NEVER change, round or recalculate a number. Not one cent.\n"
    "- Never invent a product, a price, a quantity or an amount of change.\n"
    "- Speak to the shop owner, not the customer.\n"
    "- Be brief. Two or three short lines.\n"
    "- Money is South African Rand, already written as R00.00. Do not convert it."
)

INTENT_KEYWORDS: dict[SalesIntent, tuple[str, ...]] = keywords_for(Route.SALES, SalesIntent)

# "2 bread", "2 x bread", "two loaves of bread"
QUANTITY_PATTERN = re.compile(r"\b(\d{1,3})\s*(?:x\s*)?", re.IGNORECASE)

WORD_NUMBERS: dict[str, int] = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "a dozen": 12,
    "kunye": 1, "mbili": 2, "ntathu": 3,                      # isiZulu / isiXhosa
    "nngwe": 1, "pedi": 2, "tharo": 3,                        # Sesotho / Setswana
    "een": 1, "twee": 2, "drie": 3,                           # Afrikaans
}

MONEY_PATTERN = re.compile(r"r\s*(\d+(?:[.,]\d{1,2})?)", re.IGNORECASE)
BARE_NUMBER = re.compile(r"\b(\d+(?:[.,]\d{1,2})?)\b")


@dataclass
class SalesResponse:
    """What the till says back, plus the facts behind it."""

    text: str
    intent: SalesIntent
    facts: str
    used_llm: bool = False
    product_name: str | None = None
    basket: Basket | None = None
    sale: CompletedSale | None = None
    needs_confirmation: bool = False
    error: str = ""
    options: list[str] = field(default_factory=list)

    @property
    def committed(self) -> bool:
        return self.sale is not None

    def __str__(self) -> str:
        return self.text


class SalesAgent:
    """Natural-language front door to the till."""

    def __init__(
        self,
        service: SalesService | None = None,
        llm: KasiBizLLM | None = None,
        use_llm: bool = True,
    ) -> None:
        self.service = service or SalesService()
        self.use_llm = use_llm
        self._llm = llm
        self._llm_ready = llm is not None

    # ------------------------------------------------- state the router asks about
    @property
    def awaiting_confirmation(self) -> bool:
        """True while a basket is open. The Coordinator uses this to keep 'yes' here."""
        return self.service.has_open_basket

    # ------------------------------------------------------------ 1. UNDERSTAND
    def detect_intent(self, question: str) -> tuple[SalesIntent, str | None]:
        text = question.lower().strip()
        if not text:
            return SalesIntent.UNKNOWN, None

        product = self._find_product_name(text)

        if is_cancellation(text):
            return SalesIntent.CANCEL, product
        if is_confirmation(text) and self.awaiting_confirmation:
            return SalesIntent.CONFIRM, product

        if product and any(w in text for w in INTENT_KEYWORDS[SalesIntent.REMOVE_ITEM]):
            return SalesIntent.REMOVE_ITEM, product

        # "2 White Bread, they paid R50" is one message doing two jobs. The item
        # has to go on the basket before anything can be paid for.
        if product and self.extract_quantity(text, product) is not None:
            return SalesIntent.ADD_ITEM, product

        for intent in (
            SalesIntent.PAYMENT,
            SalesIntent.START_SALE,
            SalesIntent.SHOW_BASKET,
            SalesIntent.ADD_ITEM,
        ):
            if any(word in text for word in INTENT_KEYWORDS[intent]):
                return intent, product

        if product:
            return SalesIntent.ADD_ITEM, product

        # No product we recognise, but clearly an attempt to sell something.
        # Treated as an add so the owner gets a real explanation, not help text.
        if re.search(r"\d", text) or self._guess_unknown_product(text):
            return SalesIntent.ADD_ITEM, None

        return SalesIntent.UNKNOWN, None

    def _find_product_name(self, text: str) -> str | None:
        matches = [p.name for p in self.service.db.list_products() if p.name.lower() in text]
        return max(matches, key=len) if matches else None

    @staticmethod
    def extract_quantity(text: str, product_name: str | None = None) -> int | None:
        """The number of units asked for, or None when the owner did not say."""
        haystack = text.lower()
        if product_name:
            # "Coca-Cola 500ml" must not be read as 500 units.
            haystack = haystack.replace(product_name.lower(), " @ ")

        for word, value in WORD_NUMBERS.items():
            if re.search(rf"\b{re.escape(word)}\b\s*@", haystack):
                return value

        match = re.search(r"\b(\d{1,3})\b\s*(?:x\s*)?@", haystack)
        if match:
            return int(match.group(1))

        leading = re.match(r"\s*(\d{1,3})\b", haystack)
        if leading:
            return int(leading.group(1))
        return None

    @staticmethod
    def extract_payment(text: str) -> Decimal | None:
        """What the customer handed over. Prefers an explicit R amount."""
        money = MONEY_PATTERN.search(text)
        if money:
            return Decimal(money.group(1).replace(",", "."))

        if any(word in text.lower() for word in ("paid", "gave", "handed", "kleingeld", "with")):
            numbers = BARE_NUMBER.findall(text)
            if numbers:
                return Decimal(numbers[-1].replace(",", "."))
        return None

    # -------------------------------------------------------------- 2. ACT
    def answer(self, question: str) -> SalesResponse:
        intent, product = self.detect_intent(question)

        handlers = {
            SalesIntent.CANCEL: self._cancel,
            SalesIntent.CONFIRM: self._confirm,
            SalesIntent.START_SALE: self._start,
            SalesIntent.SHOW_BASKET: self._show,
            SalesIntent.REMOVE_ITEM: self._remove,
            SalesIntent.PAYMENT: self._pay,
            SalesIntent.ADD_ITEM: self._add,
        }
        handler = handlers.get(intent)
        if handler is None:
            return self._help()

        try:
            return handler(question, product)
        except (SalesError, InsufficientPaymentError) as exc:
            return self._problem(intent, exc, product)

    # ------------------------------------------------------------ handlers
    def _start(self, question: str, product: str | None) -> SalesResponse:
        self.service.start_sale()
        if product:
            return self._add(question, product)
        return SalesResponse(
            "New sale started. What is the customer buying?",
            SalesIntent.START_SALE, facts="", basket=self.service.current_basket(),
        )

    def _add(self, question: str, product: str | None) -> SalesResponse:
        if not product:
            named = self._guess_unknown_product(question)
            if named:
                # Raises Unknown or Ambiguous, both of which explain themselves.
                self.service.match_product(named)
            return SalesResponse(
                "Which product is the customer buying? Tell me the name and how many, "
                "for example: 2 White Bread.",
                SalesIntent.ADD_ITEM, facts="", basket=self.service.basket,
            )

        quantity = self.extract_quantity(question, product)
        if quantity is None:
            quantity = 1

        basket = self.service.current_basket()
        self.service.add_item(product, quantity, basket=basket)

        payment = self.extract_payment(question)
        if payment is not None:
            return self._apply_payment(payment, basket, product)

        return SalesResponse(
            f"Added.\n{basket.as_summary()}\n\nAnything else, or how much did they pay?",
            SalesIntent.ADD_ITEM, facts=basket.as_facts(),
            product_name=product, basket=basket,
        )

    def _remove(self, question: str, product: str | None) -> SalesResponse:
        basket = self.service.basket
        if basket is None or basket.is_empty:
            return SalesResponse("The basket is already empty.", SalesIntent.REMOVE_ITEM,
                                 facts="", basket=basket)
        if not product:
            return SalesResponse("Which item should I take off?", SalesIntent.REMOVE_ITEM,
                                 facts="", basket=basket)

        removed = self.service.remove_item(product, basket=basket)
        if not removed:
            return SalesResponse(f"{product} is not on this basket.",
                                 SalesIntent.REMOVE_ITEM, facts="",
                                 product_name=product, basket=basket)
        return SalesResponse(
            f"Removed {product}.\n{basket.as_summary()}",
            SalesIntent.REMOVE_ITEM, facts=basket.as_facts(),
            product_name=product, basket=basket,
        )

    def _show(self, question: str, product: str | None) -> SalesResponse:
        basket = self.service.basket
        if basket is None or basket.is_empty:
            return SalesResponse(
                "No sale in progress. Say what the customer is buying to start one.",
                SalesIntent.SHOW_BASKET, facts="",
            )

        payment = self.extract_payment(question)
        if payment is not None:
            return self._apply_payment(payment, basket, product)

        ready, reason = self.service.ready_to_confirm(basket)
        prompt = "Say 'yes' to save it." if ready else reason
        return SalesResponse(f"{basket.as_summary()}\n\n{prompt}",
                             SalesIntent.SHOW_BASKET, facts=basket.as_facts(),
                             basket=basket, needs_confirmation=ready)

    def _pay(self, question: str, product: str | None) -> SalesResponse:
        basket = self.service.basket
        if basket is None or basket.is_empty:
            raise EmptyBasketError("There is nothing in the basket to pay for yet.")

        payment = self.extract_payment(question)
        if payment is None:
            return SalesResponse(
                f"The total is {format_rand(basket.total_cents)}. "
                "How much did the customer give you?",
                SalesIntent.PAYMENT, facts=basket.as_facts(), basket=basket,
            )
        return self._apply_payment(payment, basket, product)

    def _apply_payment(self, amount: Decimal, basket: Basket,
                       product: str | None) -> SalesResponse:
        change = self.service.set_payment(amount, basket=basket)
        facts = basket.as_facts()
        text = (f"{basket.as_summary()}\n\n"
                f"Give {format_rand(change)} change.\n"
                "Say 'yes' to save this sale, or 'cancel' to throw it away.")
        return SalesResponse(self._maybe_reword(text, facts), SalesIntent.PAYMENT,
                             facts=facts, product_name=product, basket=basket,
                             needs_confirmation=True,
                             used_llm=self._used_llm_last)

    def _confirm(self, question: str, product: str | None) -> SalesResponse:
        basket = self.service.basket
        if basket is None or basket.is_empty:
            return SalesResponse("There is no sale waiting to be saved.",
                                 SalesIntent.CONFIRM, facts="")

        sale = self.service.confirm_sale(basket)
        self.service.basket = None
        facts = sale.as_facts()

        return SalesResponse(
            f"Saved.\n\n{sale.as_receipt(get_shop_name())}\n\nStock has been updated.",
            SalesIntent.CONFIRM, facts=facts, sale=sale,
        )

    def _cancel(self, question: str, product: str | None) -> SalesResponse:
        message = self.service.cancel_sale()
        return SalesResponse(message, SalesIntent.CANCEL, facts="")

    def _help(self) -> SalesResponse:
        return SalesResponse(
            "I can ring up a sale for you. Try:\n"
            "  '2 White Bread and 1 Milk 1L'\n"
            "  'they paid R50'\n"
            "  'yes' to save it, or 'cancel' to start again.",
            SalesIntent.UNKNOWN, facts="",
        )

    def _problem(self, intent: SalesIntent, exc: Exception,
                 product: str | None) -> SalesResponse:
        options: list[str] = []
        if isinstance(exc, AmbiguousProductError):
            options = exc.matches
        elif isinstance(exc, UnknownProductError):
            options = exc.suggestions

        return SalesResponse(str(exc), intent, facts="", product_name=product,
                             basket=self.service.basket, error=str(exc), options=options)

    def _guess_unknown_product(self, question: str) -> str | None:
        """Pull out what looks like a product name so an unknown item gets a real answer."""
        cleaned = re.sub(
            r"\b(sell|sold|add|buy|bought|wants?|give|please|customer|a|an|the|and|of|to|me|i)\b",
            " ", question.lower())
        cleaned = re.sub(r"\br?\s*\d+(?:[.,]\d+)?\b", " ", cleaned)
        cleaned = re.sub(r"[^\w\s]", " ", cleaned).strip()
        return " ".join(cleaned.split()) or None

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

    def _maybe_reword(self, fallback: str, facts: str) -> str:
        """The AI is optional here. The till must work when it is not there."""
        self._used_llm_last = False
        if not self.use_llm or not facts:
            return fallback

        llm = self._get_llm()
        if llm is None:
            return fallback

        try:
            reply = llm.ask(
                f"Tell the shop owner about this sale:\n{facts}",
                system_prompt=SALES_SYSTEM_PROMPT + "\n" + language_directive(
                    detect_language(fallback).language),
                temperature=0.2, max_tokens=140,
            )
        except LLMError:
            return fallback

        self._used_llm_last = True
        return f"{fallback}\n\n{reply.strip()}" if reply.strip() else fallback
