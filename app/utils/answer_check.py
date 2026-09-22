"""Day 13 - checking that the numbers survive translation.

Translating an answer into isiZulu or Afrikaans means handing the facts to a
language model and getting back prose we cannot read as easily. The risk is that
a figure quietly changes on the way through: R18.00 becomes R80.00, 10% becomes
100%, or a price appears that was never in the facts at all.

So every figure in the model's answer is checked against the figures it was
given. The important test is not "did a number go missing" - a good answer may
legitimately leave one out - but "did a number appear from nowhere". A figure in
the answer that is not in the facts is, by definition, invented.

This runs in pure Python. It works whether or not the AI is available, and it
works for languages nobody on the team can read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MONEY_PATTERN = re.compile(r"R\s?(\d[\d\s,]*(?:\.\d{1,2})?)", re.IGNORECASE)
PERCENT_PATTERN = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*%")


def _normalise_money(raw: str) -> str:
    """'1 234,56' and '1,234.56' both become '1234.56' so they compare equal."""
    cleaned = raw.replace(" ", "").replace(",", "")
    if "." in cleaned:
        whole, _, fraction = cleaned.partition(".")
        return f"{int(whole)}.{fraction.ljust(2, '0')[:2]}"
    return f"{int(cleaned)}.00"


def _normalise_percent(raw: str) -> str:
    value = float(raw.replace(",", "."))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def extract_money(text: str) -> set[str]:
    return {_normalise_money(m.group(1)) for m in MONEY_PATTERN.finditer(text or "")}


def extract_percentages(text: str) -> set[str]:
    return {_normalise_percent(m.group(1)) for m in PERCENT_PATTERN.finditer(text or "")}


@dataclass
class FigureCheck:
    """The result of comparing an answer's figures against its source facts."""

    invented_money: set[str] = field(default_factory=set)
    invented_percentages: set[str] = field(default_factory=set)
    missing_money: set[str] = field(default_factory=set)
    source_money: set[str] = field(default_factory=set)
    answer_money: set[str] = field(default_factory=set)

    @property
    def is_faithful(self) -> bool:
        """True when the answer invented no figure that was not in the facts."""
        return not self.invented_money and not self.invented_percentages

    @property
    def invented(self) -> set[str]:
        return ({f"R{m}" for m in self.invented_money}
                | {f"{p}%" for p in self.invented_percentages})

    def as_text(self) -> str:
        if self.is_faithful:
            checked = len(self.answer_money)
            return f"Figures verified: {checked} money value(s) all traced back to the facts."
        return ("FIGURES DO NOT MATCH THE FACTS. Invented: "
                + ", ".join(sorted(self.invented)))


def verify_figures(source_facts: str, answer: str) -> FigureCheck:
    """Compare every Rand amount and percentage in the answer against the facts."""
    source_money = extract_money(source_facts)
    answer_money = extract_money(answer)
    source_percent = extract_percentages(source_facts)
    answer_percent = extract_percentages(answer)

    return FigureCheck(
        invented_money=answer_money - source_money,
        invented_percentages=answer_percent - source_percent,
        missing_money=source_money - answer_money,
        source_money=source_money,
        answer_money=answer_money,
    )
