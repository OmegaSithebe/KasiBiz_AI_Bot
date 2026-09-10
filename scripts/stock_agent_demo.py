"""Day 7 - the Stock Agent in action.

    python scripts/stock_agent_demo.py             # scripted demo (no AI, free)
    python scripts/stock_agent_demo.py --ai        # same demo, AI phrasing on
    python scripts/stock_agent_demo.py --chat      # ask your own questions
    python scripts/stock_agent_demo.py --chat --ai # chat with AI phrasing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.inventory_agent import StockAgent  # noqa: E402
from app.database.sqlite_db import format_rand, get_db  # noqa: E402
from app.services.inventory_service import InventoryService, Urgency  # noqa: E402

DEMO_QUESTIONS = [
    "What's low in stock?",
    "What should I reorder?",
    "Do I have enough White Bread?",
    "How much Paraffin 1L is left?",
    "How is my stock doing?",
    "Yini esiphelile?",
    "What is the weather tomorrow?",
]


def heading(text: str) -> None:
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


def create_low_stock_situation(service: InventoryService) -> None:
    """Force a realistic 'busy Saturday' so the agent has something to report."""
    heading("SETUP - simulating a busy trading day")

    sales = {"Paraffin 1L": None, "Milk 1L": 2, "Sugar 1kg": 5, "Candles 6-pack": 1}
    for name, leave_behind in sales.items():
        product = service.db.find_by_name(name)
        if product is None:
            continue
        target = 0 if leave_behind is None else leave_behind
        if product.quantity != target:
            service.db.set_stock(product.id, target)
            print(f"  Sold down {product.name}: {product.quantity} -> {target}")


def show_rules(service: InventoryService) -> None:
    heading("THE REORDER RULE - the same logic every single time")
    print("  Quantity = 0                      -> OUT OF STOCK")
    print("  Quantity <= half the alert level  -> CRITICAL")
    print("  Quantity <= the alert level       -> LOW")
    print("  Quantity above the alert level    -> OK")
    print(f"\n  Reorder quantity = (alert level x {service.restock_multiplier})"
          " - what is on the shelf now")

    print("\n  Worked example from your own data:")
    alert = service.check_product("Milk 1L")
    if alert:
        p = alert.product
        print(f"    {p.name}: {p.quantity} on the shelf, alert level {p.low_stock_threshold}")
        print(f"    -> {alert.urgency.value}")
        print(f"    -> target {p.low_stock_threshold * service.restock_multiplier}, "
              f"so order {alert.suggested_reorder_qty}")
        print(f"    -> costs {format_rand(alert.reorder_cost_cents)}, "
              f"returns {format_rand(alert.expected_profit_cents)} profit")


def show_alerts(service: InventoryService) -> None:
    heading("STEP 1 - THE FACTS (pure Python, no AI, always exact)")
    alerts = service.get_low_stock()
    if not alerts:
        print("  Nothing is low.")
        return

    print(f"  {'PRODUCT':<22}{'QTY':>4}{'ALERT':>7}  {'URGENCY':<14}{'ORDER':>6}{'COST':>10}")
    for a in alerts:
        print(f"  {a.name[:21]:<22}{a.quantity:>4}{a.alert_level:>7}  "
              f"{a.urgency.value:<14}{a.suggested_reorder_qty:>6}"
              f"{format_rand(a.reorder_cost_cents):>10}")

    plan = service.get_reorder_plan()
    print(f"\n  Order total: {format_rand(plan.total_cost_cents)}")
    print(f"  Profit once sold: {format_rand(plan.total_expected_profit_cents)}")


def run_questions(agent: StockAgent, using_ai: bool) -> None:
    heading(f"STEP 2 - THE AGENT ANSWERS  (AI phrasing: {'ON' if using_ai else 'OFF'})")
    for question in DEMO_QUESTIONS:
        response = agent.answer(question)
        print(f"\n  OWNER: {question}")
        print(f"  [understood as: {response.intent.value}"
              + (f" / {response.product_name}" if response.product_name else "")
              + f" | AI used: {response.used_llm}]")
        for i, line in enumerate(response.text.splitlines()):
            label = "KASIBIZ:" if i == 0 else "        "
            print(f"  {label} {line}")


def chat(agent: StockAgent) -> None:
    heading("CHAT - ask your own stock questions (blank line or 'quit' to stop)")
    print("  Try: What's low in stock?  |  What should I reorder?  |  "
          "Do I have enough bread?")
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
    parser = argparse.ArgumentParser(description="KasiBiz Stock Agent demo")
    parser.add_argument("--ai", action="store_true", help="use the LLM to phrase answers")
    parser.add_argument("--chat", action="store_true", help="ask your own questions")
    parser.add_argument("--keep", action="store_true", help="do not simulate sales")
    args = parser.parse_args()

    db = get_db()
    service = InventoryService(db)

    if db.count_products() == 0:
        print("No products found. Run this first:")
        print("    python scripts/db_demo.py --seed")
        return 1

    agent = StockAgent(service, use_llm=args.ai)

    if not args.keep:
        create_low_stock_situation(service)

    show_rules(service)
    show_alerts(service)

    if args.chat:
        chat(agent)
    else:
        run_questions(agent, using_ai=args.ai)
        print("\n\nDay 7 complete - the Stock Agent works.")
        if not args.ai:
            print("Run with --ai to see the same facts phrased by the language model.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
