"""Day 8 - the Pricing Helper in action.

    python scripts/pricing_demo.py             # scripted demo (no AI, free)
    python scripts/pricing_demo.py --ai        # same figures, AI explanations
    python scripts/pricing_demo.py --chat      # ask your own pricing questions
    python scripts/pricing_demo.py --chat --ai
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.pricing_agent import PricingAgent  # noqa: E402
from app.database.sqlite_db import format_rand, get_db  # noqa: E402
from app.services.pricing_service import PricingService  # noqa: E402

DEMO_QUESTIONS = [
    "I buy bread for R15, what should I sell it for?",
    "What is the difference between markup and margin?",
    "Am I making enough profit on Milk 1L?",
    "Check all my prices",
    "What if I sell White Bread for R22?",
    "Ngingayithengisa ngamalini into engiyithenge nge-R20?",
]


def heading(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")


def show_markup_vs_margin(service: PricingService) -> None:
    heading("THE IDEA THAT SAVES SHOPS MONEY - markup is not margin")
    suggestion = service.suggest_price("15.00", "33.33", round_price=False)
    analysis = service.analyse("15.00", "20.00")

    print("  You buy for R15.00 and sell for R20.00. Profit is R5.00.\n")
    print(f"    MARKUP = R5.00 / R15.00 (what you PAID)   = {analysis.markup_percent}%")
    print(f"    MARGIN = R5.00 / R20.00 (what you CHARGE) = {analysis.margin_percent}%")
    print("\n  Same R5.00. Two very different percentages.")
    print("  A shop that thinks '33% markup' means '33% margin' charges too little.")
    print(f"\n  Check: R15.00 plus 33.33% markup = "
          f"{format_rand(suggestion.exact_price_cents)}")


def show_price_ladder(service: PricingService) -> None:
    heading("STEP 1 - THE MATHS (pure Python, exact, no AI)")
    cost = "15.00"
    print(f"  If a loaf costs you {format_rand(1500)}:\n")
    print(f"  {'OPTION':<14}{'MARKUP':>8}{'EXACT':>10}{'YOU CHARGE':>12}"
          f"{'PROFIT':>9}{'MARGIN':>9}")
    for name, option in service.suggest_price_options(cost).items():
        print(f"  {name:<14}{str(option.requested_markup_percent) + '%':>8}"
              f"{format_rand(option.exact_price_cents):>10}"
              f"{format_rand(option.suggested_price_cents):>12}"
              f"{format_rand(option.profit_cents):>9}"
              f"{str(option.actual_margin_percent) + '%':>9}")

    print("\n  Note the EXACT and YOU CHARGE columns. Prices are rounded to 50c")
    print("  because a spaza shop takes cash and R20.25 is easier than R20.19.")

    print("\n  Working backwards instead - 'I want a 30% margin on a R15 item':")
    target = service.price_for_target_margin("15.00", 30)
    print(f"    charge {format_rand(target.suggested_price_cents)} "
          f"-> margin {target.actual_margin_percent}%, "
          f"profit {format_rand(target.profit_cents)}")


def show_shop_review(service: PricingService) -> None:
    heading("STEP 2 - A HEALTH CHECK ON EVERY PRICE IN THE SHOP")
    review = service.review_all()
    print(f"  {'PRODUCT':<22}{'COST':>9}{'SELL':>9}{'PROFIT':>9}"
          f"{'MARKUP':>9}{'MARGIN':>9}  VERDICT")
    for a in review.analyses:
        print(f"  {(a.product_name or '')[:21]:<22}"
              f"{format_rand(a.cost_price_cents):>9}"
              f"{format_rand(a.selling_price_cents):>9}"
              f"{format_rand(a.profit_cents):>9}"
              f"{str(a.markup_percent) + '%':>9}"
              f"{str(a.margin_percent) + '%':>9}  {a.health.value}")

    print(f"\n  Average margin across the shop: {review.average_margin_percent}%")
    print(f"  Products needing attention: {len(review.needs_attention)}")
    print("\n  Note: Airtime sits near 5% margin and is NOT flagged. Every shop in")
    print("  the country sells airtime at that margin, so the rule is category-aware.")


def run_questions(agent: PricingAgent, using_ai: bool) -> None:
    heading(f"STEP 3 - THE HELPER EXPLAINS  (AI explanations: {'ON' if using_ai else 'OFF'})")
    for question in DEMO_QUESTIONS:
        response = agent.answer(question)
        print(f"\n  OWNER: {question}")
        print(f"  [understood as: {response.intent.value}"
              + (f" / {response.product_name}" if response.product_name else "")
              + f" | AI used: {response.used_llm}]")
        for i, line in enumerate(response.text.splitlines()):
            print(f"  {'KASIBIZ:' if i == 0 else '        '} {line}")


def chat(agent: PricingAgent) -> None:
    heading("CHAT - ask your own pricing questions (blank line or 'quit' to stop)")
    print("  Try: I buy bread for R15, what should I sell it for?")
    print("       What is the difference between markup and margin?")
    print("       Check all my prices")
    while True:
        try:
            question = input("\n  You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question or question.lower() in {"quit", "exit", "q"}:
            break
        response = agent.answer(question)
        print(f"  [{response.intent.value} | AI: {response.used_llm}]")
        for line in response.text.splitlines():
            print(f"  KasiBiz: {line}")
    print("\n  Sala kahle!")


def main() -> int:
    parser = argparse.ArgumentParser(description="KasiBiz Pricing Helper demo")
    parser.add_argument("--ai", action="store_true", help="let the LLM explain")
    parser.add_argument("--chat", action="store_true", help="ask your own questions")
    args = parser.parse_args()

    db = get_db()
    if db.count_products() == 0:
        print("No products found. Run this first:")
        print("    python scripts/db_demo.py --seed")
        return 1

    service = PricingService(db)
    agent = PricingAgent(service, use_llm=args.ai)

    show_markup_vs_margin(service)
    show_price_ladder(service)
    show_shop_review(service)

    if args.chat:
        chat(agent)
    else:
        run_questions(agent, using_ai=args.ai)
        print("\n\nDay 8 complete - the Pricing Helper works.")
        if not args.ai:
            print("Run with --ai to see the language model explain the same figures.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
