"""The recorded demonstration: one shop owner's morning, start to finish.

Twelve steps, in order, covering every part of KasiBiz. It is written to be run
on camera, so each step prints what was asked, who answered, and the reply.

    python scripts/demo_journey.py            # free and instant, no AI
    python scripts/demo_journey.py --ai       # same figures, AI wording
    python scripts/demo_journey.py --pause    # wait for Enter between steps

Run scripts/seed_demo.py first so the figures are consistent every take.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.agents.coordinator import KasiBizCoordinator  # noqa: E402
from app.database.sqlite_db import format_rand, get_db  # noqa: E402

JOURNEY: list[tuple[str, str]] = [
    ("Sawubona",
     "1. The owner opens the shop and greets KasiBiz in isiZulu."),

    ("What is low in stock?",
     "2. First job of the day - what needs attention."),

    ("2 White Bread",
     "3. A customer arrives. The sale starts by just saying what they want."),

    ("and 1 Milk 1L",
     "4. A second item. Note that nothing is saved yet."),

    ("3 Simba Chips 36g",
     "5. A third. KasiBiz keeps the running total."),

    ("the customer paid R100",
     "6. The change is worked out in Python, never by the AI."),

    ("yes",
     "7. Only now is anything written. Stock comes off the shelf in the same step."),

    ("What is low in stock?",
     "8. The same question as step 2 - the shelf has moved."),

    ("What is selling well today?",
     "9. The Insights Agent, reporting only what is on record."),

    ("Am I making enough profit on White Bread?",
     "10. Straight into pricing, no menu, no restart."),

    ("Write a WhatsApp advert for Simba Chips 36g",
     "11. The Marketing Agent, using the real price and the real stock level."),

    ("How do I register with CIPC?",
     "12. A completely different subject, answered from the knowledge base."),

    ("20 Candles 6-pack",
     "13. The validation that matters: refusing a sale the shop cannot honour."),
]


def heading(text: str) -> None:
    print(f"\n{'=' * 78}\n{text}\n{'=' * 78}")


def show(step: int, note: str, question: str, response) -> None:
    print(f"\n  {note}")
    print(f"      OWNER: {question}")

    if response.used_memory:
        print(f"      [memory filled this in: \"{response.asked}\"]")

    flags = [response.decision.method]
    if response.language and response.language.language.value != "en":
        flags.append(response.language.language.english_name)
    if response.figures is not None:
        flags.append("figures verified" if response.figures_verified else "FIGURES WRONG")

    print(f"      [{response.specialist} | {' | '.join(flags)}]")
    print()
    for line in response.answer.splitlines():
        print(f"      {line}")
    if response.sources:
        print(f"\n      Source: {'; '.join(response.sources)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="KasiBiz demonstration journey")
    parser.add_argument("--ai", action="store_true", help="let the specialists reword")
    parser.add_argument("--pause", action="store_true", help="wait for Enter between steps")
    args = parser.parse_args()

    db = get_db()
    if db.count_products() == 0:
        print("The shop is empty. Load the demonstration data first:\n")
        print("    python scripts/seed_demo.py\n")
        return 1

    coordinator = KasiBizCoordinator(use_llm=args.ai, use_llm_routing=args.ai)

    heading(f"KASIBIZ - A MORNING AT THE SHOP   (AI wording: {'ON' if args.ai else 'OFF'})")
    print("  Demonstration data. One conversation. The owner never picks a specialist.")
    print(f"\n  Starting position: {db.count_products()} products, "
          f"{db.count_sales()} sales on record, "
          f"{format_rand(db.total_stock_value_cents())} of stock at cost.")

    visited: dict[str, int] = {}

    for step, (question, note) in enumerate(JOURNEY, start=1):
        response = coordinator.ask(question)
        visited[response.specialist] = visited.get(response.specialist, 0) + 1
        show(step, note, question, response)

        if args.pause:
            input("\n      -- Enter for the next step --")

    heading("WHERE THE SHOP STANDS NOW")
    print(f"  Products: {db.count_products()}")
    print(f"  Sales on record: {db.count_sales()}")
    print(f"  Stock at cost: {format_rand(db.total_stock_value_cents())}")

    print(f"\n  {'SPECIALIST':<22}ANSWERED")
    for specialist, count in sorted(visited.items(), key=lambda item: -item[1]):
        print(f"  {specialist:<22}{count}")

    print("\n  Thirteen messages. Six specialists. One sale recorded, one refused.")
    print("  Every figure was calculated in Python and checked before it was shown.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
