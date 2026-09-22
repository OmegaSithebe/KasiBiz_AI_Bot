"""Day 12 - the Task Coordinator: one front door to the whole of KasiBiz.

Closes issue C2. This is the box at the centre of the Day 2 architecture
diagram that had never been built.

The shop owner types one question. The coordinator works out which specialist
should answer it, hands it over, and returns the reply along with a record of
how the decision was made.

Every specialist is created lazily, so a coordinator still starts up when the
knowledge base has not been indexed or the database is empty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.agents.intent_classifier import (
    IntentClassifier,
    LLMIntentClassifier,
    Route,
    RouteDecision,
)
from app.agents.intents import STRONG_SCORE, is_cancellation, is_confirmation
from app.utils.answer_check import FigureCheck, verify_figures
from app.utils.conversation import ConversationMemory, Resolution, Turn
from app.utils.language import Language, LanguageGuess, detect_language, phrase
from app.utils.logging_setup import get_logger

log = get_logger("kasibiz.coordinator")


def greeting_reply(language: Language = Language.ENGLISH) -> str:
    return f"{phrase('greeting', language)}\n{phrase('ask_me_about', language)}"


def unknown_reply(language: Language = Language.ENGLISH) -> str:
    return (
        f"{phrase('not_sure', language)}\n"
        "Try: 'What is low in stock?' or 'How do I register with CIPC?'"
    )


GREETING_REPLY = greeting_reply()

HELP_REPLY = (
    "I can help you with six things. Just ask in your own words.\n"
    "\n"
    "STOCK      What is low in stock?  |  What should I reorder?\n"
    "SALES      2 White Bread and 1 Milk 1L  |  they paid R50\n"
    "PRICING    I buy bread for R15, what should I sell it for?\n"
    "MARKETING  Write a WhatsApp advert for White Bread\n"
    "INSIGHTS   What is selling well?  |  How much did I take this week?\n"
    "ADVICE     How do I register with CIPC?  |  What records does SARS want?\n"
    "\n"
    "You can write in English, isiZulu, isiXhosa, Afrikaans, Sesotho or Setswana."
)

NOTHING_TO_CONFIRM = (
    "There is nothing waiting for a yes or no right now.\n"
    "To start a sale, tell me what the customer is buying, "
    "for example: 2 White Bread."
)

# "2 White Bread" is how a shop owner actually rings something up, and it
# contains no keyword at all. It has to be recognised by its shape instead.
STARTS_WITH_A_QUANTITY = re.compile(r"^\s*(\d{1,3})\s*(?:x\s*)?[a-z]", re.IGNORECASE)
QUANTITY_BEFORE_NAME = re.compile(r"(\d{1,3})\s*(?:x\s*)?$")

UNKNOWN_REPLY = unknown_reply()


@dataclass
class CoordinatorResponse:
    """One answer, plus a full record of how it was routed and checked."""

    question: str
    answer: str
    decision: RouteDecision
    agent_response: Any = None
    sources: list[str] | None = None
    used_llm: bool = False
    error: str = ""
    language: LanguageGuess | None = None
    figures: FigureCheck | None = None
    resolution: Resolution | None = None

    @property
    def route(self) -> Route:
        return self.decision.route

    @property
    def specialist(self) -> str:
        return self.decision.specialist

    @property
    def used_memory(self) -> bool:
        return self.resolution is not None and self.resolution.used_memory

    @property
    def asked(self) -> str:
        """The question after memory filled in anything that was left unsaid."""
        return self.resolution.resolved if self.resolution else self.question

    @property
    def figures_verified(self) -> bool:
        """True when no figure in the answer was invented. None means unchecked."""
        return self.figures is None or self.figures.is_faithful

    def __str__(self) -> str:
        return self.answer


class KasiBizCoordinator:
    """Routes a shop owner's question to the right specialist."""

    def __init__(
        self,
        stock_agent=None,
        pricing_agent=None,
        marketing_agent=None,
        advisor_agent=None,
        sales_agent=None,
        insights_agent=None,
        classifier: IntentClassifier | None = None,
        llm_classifier: LLMIntentClassifier | None = None,
        use_llm: bool = True,
        use_llm_routing: bool = True,
        memory: ConversationMemory | None = None,
        remember: bool = True,
    ) -> None:
        self.classifier = classifier or IntentClassifier()
        self.use_llm = use_llm
        self.use_llm_routing = use_llm_routing
        self.memory = memory or ConversationMemory()
        self.remember = remember
        self._llm_classifier = llm_classifier

        self._agents: dict[Route, Any] = {
            Route.STOCK: stock_agent,
            Route.SALES: sales_agent,
            Route.PRICING: pricing_agent,
            Route.MARKETING: marketing_agent,
            Route.ADVICE: advisor_agent,
            Route.INSIGHTS: insights_agent,
        }

    # -------------------------------------------------- lazy specialists
    def _build(self, route: Route):
        """Create a specialist only when it is first needed."""
        if route is Route.STOCK:
            from app.agents.inventory_agent import StockAgent
            return StockAgent(use_llm=self.use_llm)
        if route is Route.SALES:
            from app.agents.sales_agent import SalesAgent
            return SalesAgent(use_llm=self.use_llm)
        if route is Route.PRICING:
            from app.agents.pricing_agent import PricingAgent
            return PricingAgent(use_llm=self.use_llm)
        if route is Route.MARKETING:
            from app.agents.marketing_agent import MarketingAgent
            return MarketingAgent(use_llm=self.use_llm)
        if route is Route.ADVICE:
            from app.agents.business_advisor_agent import BusinessAdvisorAgent
            return BusinessAdvisorAgent(use_llm=self.use_llm)
        if route is Route.INSIGHTS:
            from app.agents.insight_agent import InsightsAgent
            return InsightsAgent(use_llm=self.use_llm)
        return None

    def agent_for(self, route: Route):
        if route not in self._agents:
            return None
        if self._agents[route] is None:
            self._agents[route] = self._build(route)
        return self._agents[route]

    # ------------------------------------------------------- 1. ROUTE
    def route_question(self, question: str) -> RouteDecision:
        decision = self.classifier.classify(question)

        needs_help = decision.ambiguous or decision.route is Route.UNKNOWN
        if not (needs_help and self.use_llm_routing):
            return decision

        classifier = self._llm_classifier or LLMIntentClassifier()
        self._llm_classifier = classifier

        chosen = classifier.classify(question)
        if chosen is None:
            return decision

        return RouteDecision(
            route=chosen,
            confidence=decision.confidence or 0.5,
            method="llm",
            scores=decision.scores,
            matched=decision.matched,
            ambiguous=False,
        )

    # ------------------------------------------------------ 2. DISPATCH
    @staticmethod
    def _call(agent, route: Route, question: str):
        """Each specialist has its own entry point. This is the only place that knows."""
        if route is Route.ADVICE:
            return agent.ask(question)
        return agent.answer(question)

    def ask(self, question: str) -> CoordinatorResponse:
        if not question.strip():
            raise ValueError("Question cannot be empty.")

        resolution = self.memory.resolve(question, self.known_products())
        asked = resolution.resolved

        guess = detect_language(question)
        # A bare follow-up like "R20" carries no language clues, so keep the
        # language the owner has been using.
        if guess.confidence == 0 and resolution.language:
            guess = LanguageGuess(language=resolution.language, confidence=0.5)

        decision = self.route_question(asked)

        # Only lean on the remembered route when this question has no view of its own.
        if decision.route is Route.UNKNOWN and resolution.suggested_route:
            decision = RouteDecision(
                route=Route(resolution.suggested_route),
                confidence=0.5,
                method="memory",
                scores=decision.scores,
                matched=decision.matched,
            )

        decision = self._mind_the_till(asked, decision)

        response = self._answer(question, asked, decision, guess, resolution)
        if self.remember:
            self.memory.remember(Turn(
                question=question,
                resolved_question=asked,
                answer=response.answer,
                route=decision.route.value if decision.route in self._agents else None,
                product=self._product_of(response, asked),
                language=guess.language,
            ))
        return response

    def known_products(self) -> list[str]:
        """Product names memory can match against. Empty if the shop has none."""
        for route in (Route.STOCK, Route.SALES, Route.PRICING, Route.MARKETING):
            agent = self._agents.get(route)
            service = getattr(agent, "service", None)
            db = getattr(service, "db", None)
            if db is not None:
                try:
                    return [p.name for p in db.list_products()]
                except Exception:
                    return []
        try:
            from app.database.sqlite_db import get_db
            return [p.name for p in get_db().list_products()]
        except Exception:
            return []

    def _product_of(self, response: CoordinatorResponse, asked: str) -> str | None:
        named = getattr(response.agent_response, "product_name", None)
        if named:
            return named
        return self.memory.find_product(asked, self.known_products())

    def _answer(self, question, asked, decision, guess, resolution) -> CoordinatorResponse:
        if decision.route is Route.GREETING:
            return CoordinatorResponse(question, greeting_reply(guess.language),
                                       decision, language=guess, resolution=resolution)
        if decision.route is Route.HELP:
            return CoordinatorResponse(question, HELP_REPLY, decision,
                                       language=guess, resolution=resolution)
        if decision.route in (Route.CONFIRM, Route.CANCEL):
            return CoordinatorResponse(question, NOTHING_TO_CONFIRM, decision,
                                       language=guess, resolution=resolution)
        if decision.route is Route.UNKNOWN:
            return CoordinatorResponse(question, unknown_reply(guess.language),
                                       decision, language=guess, resolution=resolution)

        try:
            agent = self.agent_for(decision.route)
        except Exception as exc:
            log.exception("could not build the %s", decision.specialist)
            return CoordinatorResponse(
                question,
                f"The {decision.specialist} is not available right now.",
                decision, error=str(exc), language=guess, resolution=resolution,
            )

        if agent is None:
            log.warning("no agent registered for route %s", decision.route.value)
            return CoordinatorResponse(
                question, unknown_reply(guess.language), decision,
                error=f"No agent registered for {decision.route.value}",
                language=guess, resolution=resolution,
            )

        try:
            result = self._call(agent, decision.route, asked)
        except Exception as exc:
            # The owner gets a sentence. The reason goes to .error and the log,
            # where it can be read without alarming anyone.
            log.exception("%s failed on %r", decision.specialist, asked)
            return CoordinatorResponse(
                question,
                f"The {decision.specialist} could not answer that right now. "
                "Please try again in a moment.",
                decision, error=str(exc), language=guess, resolution=resolution,
            )

        answer = str(getattr(result, "text", None) or getattr(result, "answer", ""))
        facts = self._facts_of(result)
        figures = verify_figures(facts, answer) if facts else None

        if figures is not None and not figures.is_faithful:
            log.error("%s quoted a figure that is not in its facts: %s",
                      decision.specialist, figures.invented_money)

        return CoordinatorResponse(
            question=question,
            answer=answer,
            decision=decision,
            agent_response=result,
            sources=list(getattr(result, "sources", []) or []) or None,
            used_llm=bool(getattr(result, "used_llm", False)),
            language=guess,
            figures=figures,
            resolution=resolution,
        )

    def new_conversation(self) -> None:
        """Forget everything. Used when a different shop owner starts talking."""
        self.memory.clear()
        till = self._agents.get(Route.SALES)
        if till is not None and getattr(till, "service", None) is not None:
            till.service.cancel_sale()

    # ------------------------------------------------------- the open till
    @property
    def sale_in_progress(self) -> bool:
        """True while a basket is on the counter waiting to be confirmed."""
        till = self._agents.get(Route.SALES)
        return bool(till is not None and getattr(till, "awaiting_confirmation", False))

    def _mind_the_till(self, asked: str, decision: RouteDecision) -> RouteDecision:
        """A basket on the counter changes what a short message probably means.

        "yes" means nothing on its own, but it means a great deal when there is
        an unsaved sale. The owner can still change the subject outright - that
        needs strong evidence, not a stray keyword.
        """
        confirming = is_confirmation(asked)
        cancelling = is_cancellation(asked)

        if not self.sale_in_progress:
            if decision.route is not Route.UNKNOWN:
                return decision
            if confirming or cancelling:
                return RouteDecision(
                    Route.CONFIRM if confirming else Route.CANCEL,
                    1.0, "control", scores=decision.scores,
                )
            if self._looks_like_a_basket_line(asked):
                return RouteDecision(Route.SALES, 0.7, "shape",
                                     scores=decision.scores, matched=decision.matched)
            return decision

        if confirming or cancelling:
            return RouteDecision(Route.SALES, 1.0, "till",
                                 scores=decision.scores, matched=decision.matched)

        if decision.route in (Route.GREETING, Route.HELP):
            return decision

        changed_subject = (
            decision.route.is_specialist
            and decision.route is not Route.SALES
            and decision.scores.get(decision.route, 0) >= STRONG_SCORE
        )
        if changed_subject:
            return decision

        return RouteDecision(Route.SALES, max(decision.confidence, 0.6), "till",
                             scores=decision.scores, matched=decision.matched)

    def _looks_like_a_basket_line(self, text: str) -> bool:
        """A quantity in front of a product name, with no other clue to go on."""
        if STARTS_WITH_A_QUANTITY.match(text):
            return True

        lowered = text.lower()
        for name in self.known_products():
            position = lowered.find(name.lower())
            if position > 0 and QUANTITY_BEFORE_NAME.search(lowered[:position]):
                return True
        return False

    @staticmethod
    def _facts_of(result) -> str:
        """The calculated facts behind an answer, whatever the specialist calls them."""
        facts = getattr(result, "facts", "") or ""
        if facts:
            return facts
        context = getattr(result, "context", None)
        return context.as_prompt_context() if context is not None else ""

    # --------------------------------------------------------- extras
    def explain_routing(self, question: str) -> str:
        """Show the scoring without answering. Useful for tuning and for demos."""
        decision = self.classifier.classify(question)
        if not decision.scores:
            return f"'{question}' -> no keywords matched -> {Route.UNKNOWN.specialist}"

        ranked = sorted(decision.scores.items(), key=lambda item: item[1], reverse=True)
        lines = [f"'{question}'"]
        for route, score in ranked:
            marker = "  <-- chosen" if route is decision.route else ""
            lines.append(f"    {route.value:<10} score {score:>2}{marker}")
        lines.append(f"    confidence {decision.confidence:.0%}"
                     + ("  (AMBIGUOUS - would ask the model)" if decision.ambiguous else ""))
        return "\n".join(lines)

    @staticmethod
    def routes() -> list[tuple[str, str]]:
        return [(route.value, route.specialist) for route in Route]
