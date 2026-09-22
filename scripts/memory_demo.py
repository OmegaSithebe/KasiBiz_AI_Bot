"""Day 14 - conversation memory in action.

    python scripts/memory_demo.py          # scripted conversations, free, no AI
    python scripts/memory_demo.py --ai     # same, with AI phrasing
    python scripts/memory_demo.py --chat   # have your own conversation
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.agents.coordinator import KasiBizCoordinator  # noqa: E402

PRICING_CONVERSATION = [
    "What should I charge for White Bread?",
    "and what about Milk 1L?",
    "am I making enough profit on it?",
    "what if I sell it for R25?",
]

MIXED_CONVERSATION = [
    "Do I have enough Coca-Cola 500ml?",
    "how much does it cost me?",
    "write a WhatsApp advert for it",
    "and what about Simba Chips 36g?",
]

ZULU_CONVERSATION = [
    "Sawubona",
    "Yini esiphelile?",
    "Ngingayithengisa ngamalini i-White Bread?",
]


def heading(text: str) -> None:
    print(f"\n{'=' * 76}\n{text}\n{'=' * 76}")


def run_conversation(coordinator: KasiBizCoordinator, messages, title: str) -> None:
    heading(title)
    coordinator.new_conversation()

    for message in messages:
        response = coordinator.ask(message)

        print(f"\n  OWNER: {message}")

        if response.used_memory:
            print(f"  [memory: \"{message}\" -> \"{response.asked}\"]")
            for reason in response.resolution.reasons:
                print(f"           {reason}")

        print(f"  [-> {response.specialist} | routed by {response.decision.method}]")

        for line in response.answer.splitlines()[:4]:
            print(f"     {line}")

    print(f"\n  {coordinator.memory.summary()}")


def show_without_memory(coordinator: KasiBizCoordinator) -> None:
    heading("THE PROBLEM - the same conversation with memory switched off")
    coordinator.new_conversation()
    forgetful = KasiBizCoordinator(use_llm=False, use_llm_routing=False, remember=False)

    for message in PRICING_CONVERSATION[:3]:
        response = forgetful.ask(message)
        print(f"\n  OWNER: {message}")
        print(f"  [-> {response.specialist}]")
        print(f"     {response.answer.splitlines()[0]}")

    print("\n  Notice the second and third answers. Without memory, 'and what about")
    print("  Milk 1L?' and 'am I making enough profit on it?' have no idea what")
    print("  is being discussed, so KasiBiz cannot help.")


def chat(coordinator: KasiBizCoordinator) -> None:
    heading("CHAT - KasiBiz now remembers what you are discussing")
    print("  Try this sequence:")
    print("    What should I charge for White Bread?")
    print("    and what about Milk 1L?")
    print("    am I making enough profit on it?")
    print("\n  Type 'forget' to start a fresh conversation, 'memory' to see what")
    print("  is remembered, or 'quit' to stop.\n")

    while True:
        try:
            message = input("\n  You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not message or message.lower() in {"quit", "exit", "q"}:
            break
        if message.lower() == "forget":
            coordinator.new_conversation()
            print("  [conversation cleared]")
            continue
        if message.lower() == "memory":
            print(f"  {coordinator.memory.summary()}")
            continue

        response = coordinator.ask(message)
        if response.used_memory:
            print(f"  [understood as: {response.asked}]")
        print(f"  [{response.specialist}]")
        for line in response.answer.splitlines():
            print(f"  KasiBiz: {line}")
        if response.sources:
            print(f"  Source: {'; '.join(response.sources)}")

    print("\n  Sala kahle!")


def main() -> int:
    parser = argparse.ArgumentParser(description="KasiBiz conversation memory")
    parser.add_argument("--ai", action="store_true", help="let the specialists use the LLM")
    parser.add_argument("--chat", action="store_true", help="have your own conversation")
    args = parser.parse_args()

    coordinator = KasiBizCoordinator(use_llm=args.ai, use_llm_routing=args.ai)

    if args.chat:
        chat(coordinator)
        return 0

    show_without_memory(coordinator)
    run_conversation(coordinator, PRICING_CONVERSATION,
                     "CONVERSATION 1 - the product follows the discussion")
    run_conversation(coordinator, MIXED_CONVERSATION,
                     "CONVERSATION 2 - the product survives changing specialist")
    run_conversation(coordinator, ZULU_CONVERSATION,
                     "CONVERSATION 3 - the language is remembered too")

    print("\n\nDay 14 complete - KasiBiz remembers what is being discussed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
