"""Day 14 - remembering what is being talked about.

Until today every question was answered in complete isolation. A shop owner
could ask "What should I charge for White Bread?" and get a good answer, then
ask "and what about milk?" and be met with a blank stare, because the second
message contains no intent words and no full product name.

That is not how anyone talks. This module fixes it by resolving a follow-up
question into a complete one BEFORE it is routed:

    Owner: "What should I charge for White Bread?"   -> Pricing, White Bread
    Owner: "and what about Milk 1L?"                 -> Pricing (inherited), Milk 1L
    Owner: "how much is it?"                         -> "how much is Milk 1L?"

Two different things are inherited, and they are deliberately separate:

    PRODUCT  when the owner says "it" or "that" and names nothing
    ROUTE    when the owner says "and what about..." and asks nothing specific

Memory also remembers the language, so an owner who greets in isiZulu and then
types a bare "R20" is still answered in isiZulu.

None of this needs the language model. It is ordinary text handling, which
means it is instant, free, testable and works when the AI is unavailable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.utils.language import Language

DEFAULT_MAX_TURNS = 12

# Words that point back at something already mentioned.
PRONOUNS: tuple[str, ...] = (
    "it", "its", "that", "this", "them", "those", "these", "the same",
    "yona", "lona", "lokho", "leyo", "khona",          # isiZulu / isiXhosa
    "dit", "dieselfde", "daardie",                      # Afrikaans
    "seo", "sona", "yona",                              # Sesotho / Setswana
)

# These only refer back when they stand alone. "this week" and "that price" are
# ordinary determiners, and substituting a product into them produces nonsense
# like "what should I promote Simba Chips week?".
DEMONSTRATIVES: frozenset[str] = frozenset({"that", "this", "these", "those"})

# Openings that signal "carry on from what we were just discussing".
FOLLOWUP_MARKERS: tuple[str, ...] = (
    "and what about", "what about", "how about", "and how about",
    "and ", "also", "what of", "same for", "same with", "then what",
    "en wat van", "en die", "wat van",                  # Afrikaans
    "kanti", "futhi", "bese",                           # isiZulu
    "kunjani ngo", "kwaye",                             # isiXhosa
    "ho thweng ka", "le ka",                            # Sesotho
)


@dataclass
class Turn:
    """One exchange, kept so later questions can refer back to it."""

    question: str
    resolved_question: str
    answer: str
    route: str | None = None
    product: str | None = None
    language: Language = Language.ENGLISH
    at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def used_memory(self) -> bool:
        return self.resolved_question != self.question


@dataclass
class Resolution:
    """What memory made of a question before it was routed."""

    original: str
    resolved: str
    inherited_product: str | None = None
    suggested_route: str | None = None
    language: Language | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def used_memory(self) -> bool:
        return bool(self.inherited_product or self.suggested_route)

    def explain(self) -> str:
        if not self.reasons:
            return "No memory needed - the question stands on its own."
        return " ".join(self.reasons)


class ConversationMemory:
    """Short-term memory for one chat. Nothing is stored between sessions."""

    def __init__(self, max_turns: int = DEFAULT_MAX_TURNS) -> None:
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1.")
        self.max_turns = max_turns
        self.turns: list[Turn] = []

    # ------------------------------------------------------- recording
    def remember(self, turn: Turn) -> None:
        self.turns.append(turn)
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]

    def clear(self) -> None:
        self.turns.clear()

    @property
    def is_empty(self) -> bool:
        return not self.turns

    @property
    def last_turn(self) -> Turn | None:
        return self.turns[-1] if self.turns else None

    @property
    def last_product(self) -> str | None:
        for turn in reversed(self.turns):
            if turn.product:
                return turn.product
        return None

    @property
    def last_route(self) -> str | None:
        for turn in reversed(self.turns):
            if turn.route:
                return turn.route
        return None

    @property
    def last_language(self) -> Language | None:
        for turn in reversed(self.turns):
            if turn.language is not Language.ENGLISH:
                return turn.language
        return self.turns[-1].language if self.turns else None

    # -------------------------------------------------------- reading
    @staticmethod
    def find_product(text: str, known_products) -> str | None:
        """Longest match wins, so 'Milk 1L' beats 'Milk'."""
        lowered = text.lower()
        matches = [name for name in known_products if name.lower() in lowered]
        return max(matches, key=len) if matches else None

    @staticmethod
    def has_pronoun(text: str) -> bool:
        lowered = text.lower()
        words = re.findall(r"[a-z']+", lowered)
        joined = " ".join(words)

        for pronoun in PRONOUNS:
            if " " in pronoun:
                if pronoun in joined:
                    return True
            elif pronoun in DEMONSTRATIVES:
                # Only counts when nothing follows it: "what about that?" yes,
                # "this week" no.
                if re.search(rf"\b{pronoun}\b\s*[?.!,]*\s*$", lowered):
                    return True
            elif pronoun in words:
                return True

        return False

    @staticmethod
    def is_followup(text: str) -> bool:
        lowered = " " + text.lower().strip() + " "
        return any(
            lowered.startswith(f" {m.strip()}") or f" {m.strip()} " in lowered
            for m in FOLLOWUP_MARKERS
        )

    # ------------------------------------------------------ resolving
    def resolve(self, question: str, known_products=()) -> Resolution:
        """Turn a follow-up into a question that can stand on its own."""
        resolution = Resolution(original=question, resolved=question)

        if self.is_empty:
            return resolution

        mentioned = self.find_product(question, known_products)
        pronoun = self.has_pronoun(question)
        followup = self.is_followup(question)

        # A product the owner names themselves always wins.
        if not mentioned and (pronoun or followup) and self.last_product:
            resolution.inherited_product = self.last_product
            resolution.resolved = self._substitute(question, self.last_product, pronoun)
            resolution.reasons.append(
                f"'{question.strip()}' refers back to {self.last_product}."
            )

        # Referring back at all - by pronoun or by phrasing - means the owner is
        # still on the same subject, so the previous specialist is a fair guess.
        if (followup or resolution.inherited_product) and self.last_route:
            resolution.suggested_route = self.last_route
            resolution.reasons.append(
                f"Following on, so staying with the {self.last_route} specialist "
                "unless the question says otherwise."
            )

        remembered_language = self.last_language
        if remembered_language and remembered_language is not Language.ENGLISH:
            resolution.language = remembered_language

        return resolution

    @staticmethod
    def _substitute(question: str, product: str, had_pronoun: bool) -> str:
        """Replace a pronoun with the product, or append it to a bare follow-up."""
        if not had_pronoun:
            return f"{question.rstrip(' ?.')} - {product}"

        pattern = re.compile(
            r"\b(" + "|".join(
                re.escape(p) for p in PRONOUNS
                if " " not in p and p not in DEMONSTRATIVES
            ) + r")\b",
            re.IGNORECASE,
        )
        replaced, count = pattern.subn(product, question, count=1)
        return replaced if count else f"{question.rstrip(' ?.')} - {product}"

    # --------------------------------------------------------- review
    def summary(self) -> str:
        if self.is_empty:
            return "Nothing discussed yet."

        lines = [f"Remembering the last {len(self.turns)} exchange(s):"]
        if self.last_product:
            lines.append(f"  Currently discussing: {self.last_product}")
        if self.last_route:
            lines.append(f"  Last specialist: {self.last_route}")
        if self.last_language and self.last_language is not Language.ENGLISH:
            lines.append(f"  Language: {self.last_language.english_name}")
        return "\n".join(lines)

    def transcript(self, limit: int = 5) -> str:
        lines: list[str] = []
        for turn in self.turns[-limit:]:
            lines.append(f"Owner: {turn.question}")
            first_line = turn.answer.splitlines()[0] if turn.answer else ""
            lines.append(f"KasiBiz: {first_line}")
        return "\n".join(lines)
