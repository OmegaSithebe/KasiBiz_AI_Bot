"""The Stock Agent: answers stock questions in the owner's own words.

How it works, in three moves:

    1. UNDERSTAND  work out what the owner is asking (no AI needed - keywords)
    2. LOOK UP     get the exact facts from InventoryService (no AI - pure Python)
    3. PHRASE      ask the LLM to say those facts back naturally, in their language

The LLM never invents a number. If it is unavailable, the agent still answers
using the plain facts, because a shop owner must never be left with nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.agents.intents import Route, keywords_for
from app.services.inventory_service import InventoryService
from app.utils.config import ConfigError
from app.utils.language import detect_language, language_directive
from app.utils.llm_client import KasiBizLLM, LLMError

STOCK_AGENT_PROMPT = (
    "You are the KasiBiz Stock Assistant for a South African spaza shop owner.\n"
    "You will be given STOCK FACTS that were calculated from the owner's own "
    "database. Your job is only to present those facts clearly.\n"
    "Rules:\n"
    "- Never invent, change or recalculate any number. Use the facts exactly as given.\n"
    "- Reply in the same language the owner used (English, isiZulu or Sesotho).\n"
    "- Use plain, everyday words. No business jargon.\n"
    "- Keep it short. Lead with what is most urgent.\n"
    "- Money is South African Rand, already formatted as R00.00. Do not convert it.\n"
    "- End with one clear action the owner can take today."
)


class Intent(str, Enum):
    LOW_STOCK = "low_stock"
    REORDER = "reorder"
    CHECK_PRODUCT = "check_product"
    SUMMARY = "summary"
    UNKNOWN = "unknown"


# Derived from the one vocabulary table in app/agents/intents.py, so a new
# phrase is added once and reaches both the router and this agent.
INTENT_KEYWORDS: dict[Intent, tuple[str, ...]] = keywords_for(Route.STOCK, Intent)


@dataclass
class AgentResponse:
    """What the agent gives back: the words, plus the facts behind them."""

    text: str
    intent: Intent
    facts: str
    used_llm: bool
    product_name: str | None = None
    alerts: list = field(default_factory=list)

    def __str__(self) -> str:
        return self.text


class StockAgent:
    """Natural-language front door to the shop's stock."""

    def __init__(
        self,
        service: InventoryService | None = None,
        llm: KasiBizLLM | None = None,
        use_llm: bool = True,
    ) -> None:
        self.service = service or InventoryService()
        self.use_llm = use_llm
        self._llm = llm
        self._llm_ready = llm is not None

    # ------------------------------------------------- 1. UNDERSTAND
    def detect_intent(self, question: str) -> tuple[Intent, str | None]:
        """Decide what is being asked, and about which product if named."""
        text = question.lower().strip()
        if not text:
            return Intent.UNKNOWN, None

        # A named product wins: "should I reorder bread?" is about bread.
        named = self._find_product_name(text)
        if named:
            return Intent.CHECK_PRODUCT, named

        for intent in (Intent.REORDER, Intent.LOW_STOCK, Intent.SUMMARY):
            if any(word in text for word in INTENT_KEYWORDS[intent]):
                return intent, None

        return Intent.UNKNOWN, None

    def _find_product_name(self, text: str) -> str | None:
        """Match the longest product name mentioned, so 'Milk 1L' beats 'Milk'."""
        matches = [
            p.name for p in self.service.db.list_products()
            if p.name.lower() in text
        ]
        return max(matches, key=len) if matches else None

    # ---------------------------------------------------- 2. LOOK UP
    def gather_facts(self, intent: Intent, product_name: str | None = None):
        """Return (facts_text, alerts). Every number here comes from the database."""
        if intent is Intent.CHECK_PRODUCT and product_name:
            alert = self.service.check_product(product_name)
            if alert is None:
                return f"The shop does not stock anything called '{product_name}'.", []
            return alert.as_sentence() + f"\nAdvice: {alert.urgency.advice}", [alert]

        if intent is Intent.REORDER:
            plan = self.service.get_reorder_plan()
            return plan.as_text(), plan.alerts

        if intent is Intent.LOW_STOCK:
            alerts = self.service.get_low_stock()
            if not alerts:
                return "Nothing is running low. Every product is above its alert level.", []
            lines = [f"{len(alerts)} product(s) are running low, most urgent first:", ""]
            lines += [f"  - {a.as_sentence()}" for a in alerts]
            return "\n".join(lines), alerts

        if intent is Intent.SUMMARY:
            summary = self.service.get_summary()
            alerts = self.service.get_low_stock()
            text = summary.as_text()
            if alerts:
                worst = alerts[0]
                text += f"\nMost urgent: {worst.name} ({worst.urgency.value})."
            return text, alerts

        return (
            "I can help with stock questions. Try asking:\n"
            "  - What is low in stock?\n"
            "  - What should I reorder?\n"
            "  - Do I have enough bread?\n"
            "  - How is my stock doing?",
            [],
        )

    # ----------------------------------------------------- 3. PHRASE
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

    def _phrase(self, question: str, facts: str) -> tuple[str, bool]:
        """Ask the LLM to say the facts naturally. Falls back to the raw facts."""
        llm = self._get_llm()
        if llm is None:
            return facts, False

        guess = detect_language(question)
        prompt = (
            f"{language_directive(guess.language)}\n\n"
            f"The shop owner asked: {question}\n\n"
            f"STOCK FACTS (already calculated - do not change any number):\n{facts}\n\n"
            "Answer the owner directly using only these facts."
        )
        try:
            reply = llm.ask(prompt, system_prompt=STOCK_AGENT_PROMPT, temperature=0.3)
        except LLMError:
            return facts, False
        return (reply, True) if reply.strip() else (facts, False)

    # -------------------------------------------------------- public
    def answer(self, question: str) -> AgentResponse:
        """The one method the rest of the app calls."""
        intent, product_name = self.detect_intent(question)
        facts, alerts = self.gather_facts(intent, product_name)
        text, used_llm = self._phrase(question, facts)

        return AgentResponse(
            text=text,
            intent=intent,
            facts=facts,
            used_llm=used_llm,
            product_name=product_name,
            alerts=alerts,
        )
