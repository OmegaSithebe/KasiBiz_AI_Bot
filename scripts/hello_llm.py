"""Day 4 - "Hello World" LLM connection check.

Run from the project root:

    python scripts/hello_llm.py
    python scripts/hello_llm.py "Ngingayithengisa ngamalini i-bread?"
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.utils.config import ConfigError, load_settings  # noqa: E402
from app.utils.llm_client import KasiBizLLM, LLMError  # noqa: E402

DEFAULT_PROMPT = (
    "Sawubona! I run a small spaza shop in Soweto. "
    "Give me three quick tips to sell more airtime and bread this week."
)


def main() -> int:
    prompt = " ".join(sys.argv[1:]).strip() or DEFAULT_PROMPT

    try:
        settings = load_settings()
        llm = KasiBizLLM(settings)
    except ConfigError as exc:
        print(f"[config error] {exc}")
        return 1

    print("KasiBiz - LLM connection test")
    print(f"Model: {settings.model_name}")
    print(f"\nYou:\n{prompt}\n")
    print("KasiBiz is thinking...\n")

    try:
        answer = llm.ask(prompt)
    except LLMError as exc:
        print(f"[llm error] {exc}")
        return 1

    print(f"KasiBiz:\n{answer}\n")
    print("Connection OK - your OpenAI setup works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
