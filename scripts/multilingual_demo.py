"""Day 13 - multilingual support and translation accuracy.

    python scripts/multilingual_demo.py          # everything below, free, no AI
    python scripts/multilingual_demo.py --ai     # real translation, needs a key
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.agents.coordinator import KasiBizCoordinator  # noqa: E402
from app.utils.answer_check import verify_figures  # noqa: E402
from app.utils.language import (  # noqa: E402
    Language,
    detect_language,
    language_directive,
    phrase,
    supported_languages,
)

DETECTION_SAMPLES = [
    "What is low in stock?",
    "Sawubona, yini esiphelile?",
    "Molo, yintoni ixabiso lesonka?",
    "Goeie more, hoeveel voorraad het ek?",
    "Ke reke eng hoseng hona?",
    "Dumela, tlhwatlhwa ke bokae?",
    "qwerty zxcvbn",
]

CONVERSATION = [
    "Sawubona",
    "Molo",
    "Goeie more",
    "Dumela",
    "Good morning",
    "Yini esiphelile?",
    "Hoeveel voorraad het ek?",
    "Ngingayithengisa ngamalini into engiyithenge nge-R20?",
    "Hoe registreer ek by CIPC?",
    "qwerty zxcvbn",
]

FACTS = ("White Bread: 24 left. Promotion price: R18.00. Normal price: R20.00. "
         "Customer saves: R2.00 (10.00% off).")

TRANSLATION_SAMPLES = [
    ("English  (faithful)",
     "White Bread is now R18.00, was R20.00. You save R2.00, that is 10% off."),
    ("isiZulu  (faithful)",
     "Isinkwa esimhlophe manje singu-R18.00, besingu-R20.00. Wonga u-R2.00, okungu-10%."),
    ("Afrikaans (faithful)",
     "Witbrood is nou R18.00, was R20.00. Jy spaar R2.00, dit is 10% afslag."),
    ("isiZulu  (price changed)",
     "Isinkwa esimhlophe manje singu-R80.00, besingu-R20.00."),
    ("Afrikaans (percentage changed)",
     "Witbrood is nou R18.00. Jy spaar R2.00, dit is 100% afslag!"),
    ("isiXhosa (figure invented)",
     "Isonka ngoku yi-R18.00. Onga i-R500.00 namhlanje!"),
]


def heading(text: str) -> None:
    print(f"\n{'=' * 76}\n{text}\n{'=' * 76}")


def show_languages() -> None:
    heading("SUPPORTED LANGUAGES")
    print(f"  {'CODE':<6}{'LANGUAGE':<14}{'GREETING'}")
    for language in supported_languages():
        print(f"  {language.value:<6}{language.english_name:<14}"
              f"{phrase('greeting', language)}")


def show_detection() -> None:
    heading("STEP 1 - DETECT THE LANGUAGE (pure Python, no AI, instant)")
    print("  Until today this was left to the model. Now it is decided in code,")
    print("  before the model is called - so we can tell it which language to use.\n")
    print(f"  {'MESSAGE':<48}{'DETECTED':<12}{'CONFIDENCE'}")
    for text in DETECTION_SAMPLES:
        guess = detect_language(text)
        print(f"  {text[:47]:<48}{guess.language.english_name:<12}{guess.confidence:>6.0%}")

    print("\n  Note the last line: when nothing is recognised we stay in English.")
    print("  Guessing wrong is worse than not guessing.")


def show_directive() -> None:
    heading("STEP 2 - TELL THE MODEL, BY NAME")
    print("  This replaces the old instruction 'reply in the same language the owner")
    print("  used', which is what failed on Day 8.\n")
    for language in (Language.ZULU, Language.AFRIKAANS):
        print(f"  {language.english_name}:")
        for line in language_directive(language).split(". "):
            if line.strip():
                print(f"    {line.strip().rstrip('.')}.")
        print()


def show_conversation(coordinator: KasiBizCoordinator) -> None:
    heading("STEP 3 - THE ASSISTANT REPLIES IN THE RIGHT LANGUAGE")
    print("  These replies are fixed translations, not AI output - so they work")
    print("  even with no API key at all.\n")
    for message in CONVERSATION:
        response = coordinator.ask(message)
        detected = response.language.language.english_name if response.language else "?"
        print(f"\n  OWNER  ({detected}): {message}")
        for line in response.answer.splitlines()[:3]:
            print(f"  KASIBIZ: {line}")


def show_accuracy() -> None:
    heading("STEP 4 - DO THE NUMBERS SURVIVE TRANSLATION?")
    print("  We cannot read every language on the team. We can check every figure.")
    print(f"\n  THE FACTS: {FACTS}\n")
    print(f"  {'ANSWER':<32}{'VERDICT':<12}{'PROBLEM'}")

    for label, answer in TRANSLATION_SAMPLES:
        check = verify_figures(FACTS, answer)
        verdict = "OK" if check.is_faithful else "REJECTED"
        problem = "" if check.is_faithful else "invented " + ", ".join(sorted(check.invented))
        print(f"  {label:<32}{verdict:<12}{problem}")

    print("\n  The test is not 'did a number go missing' - a shorter answer is fine.")
    print("  The test is 'did a number appear that was never in the facts'.")
    print("  A figure with no source is, by definition, invented.")


def main() -> int:
    parser = argparse.ArgumentParser(description="KasiBiz multilingual support")
    parser.add_argument("--ai", action="store_true", help="use the LLM for real translation")
    args = parser.parse_args()

    coordinator = KasiBizCoordinator(use_llm=args.ai, use_llm_routing=args.ai)

    show_languages()
    show_detection()
    show_directive()
    show_conversation(coordinator)
    show_accuracy()

    print("\n\nDay 13 complete - multilingual support with verified accuracy.")
    if not args.ai:
        print("Language detection, routing, fixed replies and figure checking all")
        print("run without an API key. Live translation of prose needs the key.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
