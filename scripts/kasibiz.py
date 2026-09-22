"""Day 12 - the Task Coordinator routing real questions to real specialists.

    python scripts/kasibiz.py              # scripted demo across all four agents
    python scripts/kasibiz.py --ai         # same, with AI phrasing
    python scripts/kasibiz.py --chat       # talk to KasiBiz as one assistant
    python scripts/kasibiz.py --routing    # show the intent scoring only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.agents.coordinator import KasiBizCoordinator  # noqa: E402

DEMO_QUESTIONS = [
    "Sawubona!",
    "What can you do?",
    "What is low in stock?",
    "What should I reorder?",
    "I buy bread for R15, what should I sell it for?",
    "Am I making enough profit on Milk 1L?",
    "Write a WhatsApp advert for White Bread with 10% off",
    "What should I promote this week?",
    "How do I register with CIPC?",
    "What records must I keep for SARS?",
    "Yini esiphelile?",
    "Who won the rugby world cup in 1995?",
]

ROUTING_EXAMPLES = [
    "What is low in stock?",
    "I have stock of bread - what should I charge for it?",
    "Write a poster for Coca-Cola",
    "How do I register with CIPC?",
    "Sawubona",
    "is my shop allowed to sell cigarettes",
]


def heading(text: str) -> None:
    print(f"\n{'=' * 74}\n{text}\n{'=' * 74}")


def show_routing_table(coordinator: KasiBizCoordinator) -> None:
    heading("THE ROUTING TABLE - one front door, six destinations")
    print(f"  {'INTENT':<12}{'GOES TO'}")
    for value, specialist in coordinator.routes():
        print(f"  {value:<12}{specialist}")


def show_scoring(coordinator: KasiBizCoordinator) -> None:
    heading("STEP 1 - INTENT CLASSIFICATION (weighted keywords, free, no AI)")
    for question in ROUTING_EXAMPLES:
        print()
        print(coordinator.explain_routing(question))


def run_demo(coordinator: KasiBizCoordinator, using_ai: bool) -> None:
    heading(f"STEP 2 - ONE ASSISTANT, FOUR SPECIALISTS  (AI: {'ON' if using_ai else 'OFF'})")

    for question in DEMO_QUESTIONS:
        response = coordinator.ask(question)
        print(f"\n  OWNER: {question}")
        print(f"  [-> {response.specialist} | {response.decision.method} "
              f"| {response.decision.confidence:.0%} confident"
              f"{' | AI used' if response.used_llm else ''}]")

        lines = response.answer.splitlines()
        for line in lines[:6]:
            print(f"     {line}")
        if len(lines) > 6:
            print(f"     ... ({len(lines) - 6} more lines)")
        if response.sources:
            print(f"     Source: {'; '.join(response.sources)}")
        if response.error:
            print(f"     [error: {response.error}]")


def chat(coordinator: KasiBizCoordinator) -> None:
    heading("KASIBIZ - ask me anything about your shop")
    print("  You no longer have to know which agent to call. Just ask.")
    print("  Try: What is low in stock?  |  What should I charge for bread?")
    print("       Write an advert for White Bread  |  How do I register with CIPC?")
    print("  Type 'quit' to stop.\n")

    while True:
        try:
            question = input("\n  You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question or question.lower() in {"quit", "exit", "q"}:
            break

        response = coordinator.ask(question)
        print(f"  [{response.specialist} | {response.decision.confidence:.0%}]")
        for line in response.answer.splitlines():
            print(f"  KasiBiz: {line}")
        if response.sources:
            print(f"  Source: {'; '.join(response.sources)}")

    print("\n  Sala kahle!")


def main() -> int:
    parser = argparse.ArgumentParser(description="KasiBiz - one assistant, four specialists")
    parser.add_argument("--ai", action="store_true", help="let the specialists use the LLM")
    parser.add_argument("--chat", action="store_true", help="talk to KasiBiz")
    parser.add_argument("--routing", action="store_true", help="show intent scoring only")
    args = parser.parse_args()

    coordinator = KasiBizCoordinator(use_llm=args.ai, use_llm_routing=args.ai)

    if args.routing:
        show_routing_table(coordinator)
        show_scoring(coordinator)
        return 0

    if args.chat:
        chat(coordinator)
        return 0

    show_routing_table(coordinator)
    show_scoring(coordinator)
    run_demo(coordinator, using_ai=args.ai)

    print("\n\nDay 12 complete - the Task Coordinator works.")
    print("The shop owner asks one assistant. It decides who answers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
