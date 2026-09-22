"""Day 12 - the Task Coordinator: deciding which specialist answers each question.

This is the missing piece from the original architecture diagram (issue C2). Up
to now every agent had to be called directly by name. The owner does not know
they are talking to four different agents - they just type a question.

    Owner  ->  COORDINATOR  ->  Stock Agent
                            ->  Pricing Helper
                            ->  Marketing Agent
                            ->  Business Advisor

Intent classification is done in two tiers, cheapest first:

    TIER 1  weighted keyword scoring   free, instant, explainable, ~90% of traffic
    TIER 2  ask the language model     only when tier 1 is genuinely torn

That ordering matters. A router that calls an LLM on every message pays for and
waits on an AI request before any real work begins. Rules handle the clear cases
for nothing, and the model is kept for the hard ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.agents.intents import (
    AMBIGUITY_MARGIN,
    MIN_SCORE_TO_ROUTE,
    ROUTE_PATTERNS,
    STRONG_SCORE,
    Route,
    router_patterns,
)
from app.utils.config import ConfigError
from app.utils.llm_client import KasiBizLLM, LLMError

ROUTER_PROMPT = (
    "You classify a South African spaza shop owner's message into exactly one "
    "category. Reply with ONE word from this list and nothing else:\n"
    "stock    - what is running out, what to reorder, stock levels\n"
    "sales    - recording a sale, a basket, payment, customer change\n"
    "pricing  - what to charge, profit, markup, margin, checking prices\n"
    "marketing- adverts, promotions, posters, social media captions\n"
    "advice   - CIPC, SARS, tax, registration, compliance, regulations\n"
    "insights - what is selling well, slow movers, sales totals, takings\n"
    "greeting - a greeting with no question\n"
    "help     - asking what the assistant can do\n"
    "unknown  - none of the above\n"
    "The message may be in English, isiZulu or Sesotho."
)


# (pattern, weight). Multi-word phrases are worth more than single words because
# they are far less likely to appear by accident.
ROUTE_PATTERNS: dict[Route, tuple[tuple[str, int], ...]] = {
    Route.STOCK: (
        ("what is low", 4), ("running low", 4), ("running out", 4), ("low in stock",  4),
        ("what should i reorder", 4), ("shopping list", 3), ("out of stock", 4),
        ("do i have enough", 4), ("how many.* left", 4), ("stock take", 3),
        ("in stock", 3), ("reorder", 3), ("restock", 3), ("stock level", 3),
        ("stock report", 3), ("how is my stock", 4),
        ("stock", 2), ("shelf", 2), ("supplier", 2), ("delivery", 2),
        ("phelile", 3), ("kuphelile", 3), ("fedile", 3),
        ("iphelile", 3), ("ndinayo", 3),                      # isiXhosa
        ("voorraad", 4), ("raak op", 4), ("min voorraad", 4),  # Afrikaans
    ),
    Route.PRICING: (
        ("what should i charge", 4), ("what should i sell", 4), ("how much should i", 4),
        ("am i making profit", 4), ("making enough profit", 4), ("check my prices", 4),
        ("are my prices", 4), ("markup", 4), ("margin", 4), ("underpriced", 4),
        ("what if i sell", 4), ("what if i charge", 4), ("if i sell", 4),
        ("if i charge", 4), ("should i raise the price", 4), ("raise the price", 4),
        ("what price", 3), ("selling price", 3), ("cost price", 3), ("mark up", 3),
        ("cost me", 3), ("how much does it cost", 4), ("what does it cost", 4),
        ("too cheap", 3), ("too expensive", 3), ("losing money", 3),
        ("price", 2), ("profit", 2), ("charge", 2),
        ("ngamalini", 3), ("inzuzo", 3), ("theko", 3), ("phaello", 3),
        ("ixabiso", 3), ("ndifumana", 3),                      # isiXhosa
        ("prys", 4), ("wins", 4), ("hoeveel moet ek vra", 4),  # Afrikaans
        ("tlhwatlhwa", 3), ("poelo", 3),                       # Setswana
    ),
    Route.MARKETING: (
        ("whatsapp advert", 4), ("write.* advert", 4), ("social media", 4),
        ("facebook", 4), ("instagram", 4), ("poster", 4), ("caption", 4),
        ("what should i promote", 4), ("what should i advertise", 4),
        ("advert", 3), ("advertise", 3), ("promotion", 3), ("promote", 3),
        ("special", 3), ("campaign", 3), ("discount", 3), ("% off", 3),
        ("customers know", 3), ("tell my customers", 3),
        ("isaziso", 3),
        ("intengiso", 3),                                      # isiXhosa
        ("advertensie", 4), ("plakkaat", 4),                   # Afrikaans
        ("papatso", 3),                                        # Sesotho / Setswana
    ),
    Route.ADVICE: (
        ("how do i register", 4), ("register my business", 4), ("register a company", 4),
        ("annual return", 4), ("beneficial ownership", 4), ("deregistration", 4),
        ("company registration", 4), ("food safety", 4), ("what records", 4),
        ("cipc", 4), ("sars", 4), ("bizportal", 4), ("vat", 4),
        ("tax", 3), ("register", 3), ("compliance", 3), ("director", 3),
        ("pty", 3), ("legal", 3), ("licence", 3), ("license", 3), ("permit", 3),
        ("receipts", 2), ("regulation", 3),
        ("bhalisa", 3), ("intela", 3), ("lekgetho", 3),
        ("ukubhalisa", 3), ("irhafu", 3),                      # isiXhosa
        ("registreer", 4), ("belasting", 4),                   # Afrikaans
    ),
    Route.GREETING: (
        ("good morning", 4), ("good afternoon", 4), ("good evening", 4),
        ("sawubona", 4), ("molo", 4), ("dumela", 4), ("sanibonani", 4),
        ("molweni", 4), ("goeie more", 4), ("goeiemore", 4), ("hallo", 4),
        ("hello", 3), ("hi there", 3), ("hey", 3), ("howzit", 3),
    ),
    Route.HELP: (
        ("what can you do", 4), ("what can you help", 4), ("how do you work", 4),
        ("what do you do", 4), ("help me", 3), ("who are you", 4),
        ("ungangisiza", 3), ("ungenzani", 3),
        ("ungandinceda", 3),                                   # isiXhosa
        ("wat kan jy doen", 4), ("wie is jy", 4),              # Afrikaans
    ),
}

ROUTER_PROMPT = (
    "You classify a South African spaza shop owner's message into exactly one "
    "category. Reply with ONE word from this list and nothing else:\n"
    "stock    - what is running out, what to reorder, stock levels\n"
    "pricing  - what to charge, profit, markup, margin, checking prices\n"
    "marketing- adverts, promotions, posters, social media captions\n"
    "advice   - CIPC, SARS, tax, registration, compliance, regulations\n"
    "greeting - a greeting with no question\n"
    "help     - asking what the assistant can do\n"
    "unknown  - none of the above\n"
    "The message may be in English, isiZulu or Sesotho."
)


@dataclass
class RouteDecision:
    """Which specialist was chosen, how sure we are, and why."""

    route: Route
    confidence: float
    method: str                     # "rules", "llm" or "default"
    scores: dict[Route, int] = field(default_factory=dict)
    matched: list[str] = field(default_factory=list)
    ambiguous: bool = False

    @property
    def specialist(self) -> str:
        return self.route.specialist

    def explain(self) -> str:
        if self.method == "rules" and self.matched:
            return (f"Matched {', '.join(repr(m) for m in self.matched[:4])} "
                    f"-> {self.specialist} ({self.confidence:.0%} confident)")
        if self.method == "llm":
            return f"Keywords were unclear, so the model chose {self.specialist}"
        return f"No clear match -> {self.specialist}"


class IntentClassifier:
    """Tier 1: weighted keyword scoring. Free, instant and explainable."""

    def __init__(self, patterns: dict[Route, tuple[tuple[str, int], ...]] | None = None) -> None:
        self.patterns = patterns or router_patterns()

    def score(self, message: str) -> tuple[dict[Route, int], dict[Route, list[str]]]:
        text = " " + re.sub(r"\s+", " ", message.lower().strip()) + " "
        scores: dict[Route, int] = {}
        matches: dict[Route, list[str]] = {}

        for route, patterns in self.patterns.items():
            total = 0
            hits: list[str] = []
            for pattern, weight in patterns:
                found = (re.search(pattern, text) if any(c in pattern for c in ".*[]")
                         else pattern in text)
                if found:
                    total += weight
                    hits.append(pattern)
            if total:
                scores[route] = total
                matches[route] = hits

        return scores, matches

    def classify(self, message: str) -> RouteDecision:
        if not message.strip():
            return RouteDecision(Route.UNKNOWN, 0.0, "default")

        scores, matches = self.score(message)
        if not scores:
            return RouteDecision(Route.UNKNOWN, 0.0, "default", scores={})

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_route, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0

        # Confidence needs BOTH halves. Dominance alone would rate a single stray
        # word at 100% simply because nothing else matched.
        total = sum(scores.values())
        evidence = min(top_score / STRONG_SCORE, 1.0)
        dominance = top_score / total if total else 0.0
        confidence = round(evidence * dominance, 4)

        if top_score < MIN_SCORE_TO_ROUTE:
            return RouteDecision(Route.UNKNOWN, confidence, "default",
                                 scores=scores, matched=matches.get(top_route, []))

        ambiguous = (top_score - second_score) <= AMBIGUITY_MARGIN and second_score >= MIN_SCORE_TO_ROUTE

        return RouteDecision(
            route=top_route,
            confidence=confidence,
            method="rules",
            scores=scores,
            matched=matches.get(top_route, []),
            ambiguous=ambiguous,
        )


class LLMIntentClassifier:
    """Tier 2: ask the model, but only when the rules are genuinely torn."""

    def __init__(self, llm: KasiBizLLM | None = None) -> None:
        self._llm = llm
        self._ready = llm is not None

    def _get_llm(self) -> KasiBizLLM | None:
        if not self._ready:
            try:
                self._llm = KasiBizLLM()
            except (ConfigError, LLMError, Exception):
                self._llm = None
            self._ready = True
        return self._llm

    def classify(self, message: str) -> Route | None:
        llm = self._get_llm()
        if llm is None:
            return None
        try:
            reply = llm.ask(message, system_prompt=ROUTER_PROMPT,
                            temperature=0, max_tokens=10)
        except LLMError:
            return None

        word = reply.strip().lower().split()[0].strip(".,:;!") if reply.strip() else ""
        try:
            return Route(word)
        except ValueError:
            return None
