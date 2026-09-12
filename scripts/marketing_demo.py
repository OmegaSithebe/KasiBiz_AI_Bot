"""Day 9 - the Marketing Agent in action.

    python scripts/marketing_demo.py             # templates only (free, no AI)
    python scripts/marketing_demo.py --ai        # same offers, AI writes the copy
    python scripts/marketing_demo.py --chat --ai # write your own adverts
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Adverts contain emoji, and the default Windows console codec (cp1252) cannot
# encode them. Without this the whole demo crashes on the first bread emoji.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.agents.marketing_agent import MarketingAgent  # noqa: E402
from app.database.sqlite_db import format_rand, get_db  # noqa: E402
from app.services.marketing_service import MarketingService, PromoSafety  # noqa: E402
from app.utils.config import get_shop_name  # noqa: E402

DEMO_REQUESTS = [
    "Write a WhatsApp advert for White Bread with 10% off",
    "Facebook caption for Simba Chips 36g",
    "Make a poster for Coca-Cola 500ml",
    "2 White Bread for R35 - write an advert",
    "Ngenzele isaziso se-WhatsApp se-Coca-Cola 500ml",
]

REFUSAL_REQUESTS = [
    "Write an advert for Paraffin 1L",
    "50% off White Bread, write a poster",
]


def heading(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")


def show_candidates(service: MarketingService, agent: MarketingAgent) -> None:
    heading("STEP 1 - WHAT IS WORTH PROMOTING (pure Python, no AI)")
    print(agent.what_to_promote())
    print("\n  Products that are running low are deliberately excluded - advertising")
    print("  something you are about to run out of loses customers, it does not win them.")


def show_offer_maths(service: MarketingService) -> None:
    heading("STEP 2 - WHAT EACH PROMOTION ACTUALLY COSTS")
    print(f"  {'PRODUCT':<20}{'OFFER':<16}{'WAS':>9}{'NOW':>9}"
          f"{'SAVE':>9}{'PROFIT':>9}  VERDICT")

    examples = [
        ("White Bread", {"discount_percent": 10}),
        ("White Bread", {"discount_percent": 30}),
        ("Coca-Cola 500ml", {"discount_percent": 15}),
        ("Simba Chips 36g", {"discount_percent": 20}),
        ("Paraffin 1L", {"discount_percent": 10}),
    ]
    for name, kwargs in examples:
        offer = service.build_offer(name, **kwargs)
        if offer is None:
            continue
        label = f"{kwargs['discount_percent']}% off"
        print(f"  {offer.name[:19]:<20}{label:<16}"
              f"{format_rand(offer.normal_price_cents):>9}"
              f"{format_rand(offer.promo_price_cents):>9}"
              f"{format_rand(offer.saving_cents):>9}"
              f"{format_rand(offer.profit_cents):>9}  {offer.safety.value}")

    bundle = service.build_bundle("White Bread", 2, "35.00")
    if bundle:
        print(f"  {bundle.name[:19]:<20}{'2 for R35':<16}"
              f"{format_rand(bundle.normal_price_cents):>9}"
              f"{format_rand(bundle.promo_price_cents):>9}"
              f"{format_rand(bundle.saving_cents):>9}"
              f"{format_rand(bundle.profit_cents):>9}  {bundle.safety.value}")

    print("\n  How much discount can each product actually afford?")
    for name in ("White Bread", "Coca-Cola 500ml", "Simba Chips 36g"):
        headroom = service.max_safe_discount_percent(name)
        if headroom is not None:
            print(f"    {name:<20} break-even at {headroom}% off")


def show_refusals(agent: MarketingAgent) -> None:
    heading("STEP 3 - THE ADVERTS IT REFUSES TO WRITE")
    for request in REFUSAL_REQUESTS:
        response = agent.answer(request)
        print(f"\n  OWNER: {request}")
        for line in response.text.splitlines():
            print(f"  KASIBIZ: {line}" if line.strip() else "")


def run_requests(agent: MarketingAgent, using_ai: bool) -> None:
    heading(f"STEP 4 - THE COPY  (AI copywriter: {'ON' if using_ai else 'OFF - templates'})")
    for request in DEMO_REQUESTS:
        response = agent.answer(request)
        print(f"\n  OWNER: {request}")
        print(f"  [{response.intent.value}"
              + (f" / {response.product_name}" if response.product_name else "")
              + f" | AI used: {response.used_llm}]")
        if response.offer:
            print(f"  [offer: {response.offer.as_summary()}]")
        print("  " + "-" * 60)
        for line in response.text.splitlines():
            print(f"  | {line}")
        print("  " + "-" * 60)


def chat(agent: MarketingAgent) -> None:
    heading("CHAT - write your own adverts (blank line or 'quit' to stop)")
    print("  Try: Write a WhatsApp advert for White Bread with 10% off")
    print("       Make a poster for Coca-Cola 500ml")
    print("       Full campaign for Simba Chips 36g")
    print("       What should I promote this week?")
    while True:
        try:
            request = input("\n  You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not request or request.lower() in {"quit", "exit", "q"}:
            break
        response = agent.answer(request)
        print(f"  [{response.intent.value} | AI: {response.used_llm}]")
        for line in response.text.splitlines():
            print(f"  | {line}")
    print("\n  Sala kahle!")


def main() -> int:
    parser = argparse.ArgumentParser(description="KasiBiz Marketing Agent demo")
    parser.add_argument("--ai", action="store_true", help="let the LLM write the copy")
    parser.add_argument("--chat", action="store_true", help="write your own adverts")
    args = parser.parse_args()

    db = get_db()
    if db.count_products() == 0:
        print("No products found. Run this first:")
        print("    python scripts/db_demo.py --seed")
        return 1

    service = MarketingService(db, shop_name=get_shop_name())
    agent = MarketingAgent(service, use_llm=args.ai)
    print(f"Shop name: {service.shop_name}  (set SHOP_NAME in .env to change it)")

    show_candidates(service, agent)
    show_offer_maths(service)
    show_refusals(agent)

    if args.chat:
        chat(agent)
    else:
        run_requests(agent, using_ai=args.ai)
        print("\n\nDay 9 complete - the Marketing Agent works.")
        if not args.ai:
            print("Run with --ai to see the language model write the copy instead.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
