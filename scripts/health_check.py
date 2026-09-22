"""Day 15 - is KasiBiz actually wired up and ready to run?

Checks every component in turn and reports what is working, what is missing and
what to do about it. Run this before a demo, after a deployment, or whenever
something is behaving oddly.

    python scripts/health_check.py          # everything except the paid AI call
    python scripts/health_check.py --ai     # include a live OpenAI check
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OK = "PASS"
WARN = "WARN"
FAIL = "FAIL"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def check_configuration() -> Check:
    from app.utils.config import PROJECT_ROOT, get_chroma_db_path, get_database_url

    if not (PROJECT_ROOT / ".env").exists():
        return Check("Configuration", FAIL, ".env file not found",
                     "Create .env in the project root - see handbook section 7.1")

    return Check("Configuration", OK,
                 f"database={get_database_url()}, chroma={get_chroma_db_path()}")


def check_api_key() -> Check:
    from app.utils.config import ConfigError, load_settings

    try:
        settings = load_settings()
    except ConfigError as exc:
        return Check("OpenAI key", FAIL, str(exc).splitlines()[0],
                     "Add OPENAI_API_KEY to .env")

    return Check("OpenAI key", OK,
                 f"present ({len(settings.openai_api_key)} chars), model {settings.model_name}")


def check_database() -> Check:
    from app.database.sqlite_db import format_rand, get_db

    try:
        db = get_db()
        count = db.count_products()
    except Exception as exc:
        return Check("Stock database", FAIL, str(exc),
                     "Run: python scripts/seed_demo.py")

    if count == 0:
        return Check("Stock database", WARN, "connected, but no products",
                     "Run: python scripts/seed_demo.py")

    return Check("Stock database", OK,
                 f"{count} products, {format_rand(db.total_stock_value_cents())} at cost")


def check_sales_tables() -> Check:
    from app.database.sqlite_db import get_db

    try:
        db = get_db()
        count = db.count_sales()
        db.list_sale_items()
    except Exception as exc:
        return Check("Sales history", FAIL, str(exc),
                     "The sales tables are missing. Run: python scripts/seed_demo.py")

    if count == 0:
        return Check("Sales history", WARN, "no sales recorded yet",
                     "Insights will have nothing to report. "
                     "Run: python scripts/seed_demo.py")

    return Check("Sales history", OK, f"{count} sale(s) on record")


def check_knowledge_base() -> Check:
    try:
        from app.rag.vector_store import KasiBizVectorStore, LocalEmbedder
        store = KasiBizVectorStore(embedder=LocalEmbedder())
        count = store.count()
    except Exception as exc:
        return Check("Knowledge base", FAIL, str(exc),
                     "Run: python scripts/rag_ingest.py --local")

    if count == 0:
        return Check("Knowledge base", WARN, "ChromaDB is empty",
                     "Run: python scripts/rag_ingest.py --local")

    return Check("Knowledge base", OK,
                 f"{count} passages from {len(store.sources())} documents")


def check_specialists() -> list[Check]:
    from app.agents.coordinator import KasiBizCoordinator
    from app.agents.intent_classifier import Route

    coordinator = KasiBizCoordinator(use_llm=False, use_llm_routing=False)
    checks: list[Check] = []

    for route in (Route.STOCK, Route.SALES, Route.PRICING,
                  Route.MARKETING, Route.ADVICE, Route.INSIGHTS):
        try:
            agent = coordinator.agent_for(route)
            status = OK if agent is not None else FAIL
            detail = type(agent).__name__ if agent else "could not be created"
            checks.append(Check(f"  {route.specialist}", status, detail))
        except Exception as exc:
            checks.append(Check(f"  {route.specialist}", FAIL, str(exc)[:60]))

    return checks


def check_the_till() -> Check:
    """A whole sale, on a throwaway database, so nothing real is touched."""
    import logging
    import tempfile
    from pathlib import Path

    from app.database.sqlite_db import StockDatabase
    from app.services.sales_service import SalesService

    # This writes a real sale, which logs. Keep it out of the report.
    till_log = logging.getLogger("kasibiz.till")
    previous = till_log.level
    till_log.setLevel(logging.WARNING)

    try:
        with tempfile.TemporaryDirectory() as folder:
            db = StockDatabase(Path(folder) / "check.db")
            db.initialise()
            db.add_product("Test Loaf", 15.00, 20.00, quantity=10)

            till = SalesService(db=db)
            till.add_item("Test Loaf", 2)
            change = till.set_payment(50)
            sale = till.confirm_sale()
            left = db.get_by_name("Test Loaf").quantity

        if (sale.total_cents, change, left) != (4000, 1000, 8):
            return Check("The till", FAIL,
                         f"total={sale.total_cents} change={change} stock={left}",
                         "Check app/services/calculation_service.py")

        return Check("The till", OK,
                     "2 x R20.00 = R40.00, R10.00 change, stock 10 -> 8")
    except Exception as exc:
        return Check("The till", FAIL, str(exc)[:70])
    finally:
        till_log.setLevel(previous)


def check_insights_refuse_to_guess() -> Check:
    """An empty shop must say it has nothing, not invent a best seller."""
    import tempfile
    from pathlib import Path

    from app.agents.insight_agent import InsightsAgent
    from app.database.sqlite_db import StockDatabase
    from app.services.analytics_service import AnalyticsService

    try:
        with tempfile.TemporaryDirectory() as folder:
            db = StockDatabase(Path(folder) / "books.db")
            db.initialise()
            agent = InsightsAgent(service=AnalyticsService(db=db), use_llm=False)
            response = agent.answer("What is selling well?")

        if response.has_data:
            return Check("Insights honesty", FAIL,
                         "reported data for a shop with no sales")
        return Check("Insights honesty", OK,
                     "an empty shop is told there is nothing to report")
    except Exception as exc:
        return Check("Insights honesty", FAIL, str(exc)[:70])


def check_routing() -> Check:
    from app.agents.intent_classifier import IntentClassifier, Route

    samples = {
        "What is low in stock?": Route.STOCK,
        "What should I charge for bread?": Route.PRICING,
        "Write a WhatsApp advert": Route.MARKETING,
        "How do I register with CIPC?": Route.ADVICE,
        "The customer wants 2 loaves": Route.SALES,
        "What is selling well this week?": Route.INSIGHTS,
    }

    classifier = IntentClassifier()
    wrong = [q for q, expected in samples.items()
             if classifier.classify(q).route is not expected]

    if wrong:
        return Check("Router", FAIL, f"{len(wrong)} of {len(samples)} misrouted: {wrong[0]}",
                     "Check VOCABULARY in app/agents/intents.py")

    return Check("Router", OK, f"all {len(samples)} sample questions routed correctly")


def check_languages() -> Check:
    from app.utils.language import Language, detect_language, supported_languages

    samples = {
        "What is low in stock?": Language.ENGLISH,
        "Sawubona, yini esiphelile?": Language.ZULU,
        "Molo, yintoni ixabiso?": Language.XHOSA,
        "Goeie more, hoeveel voorraad?": Language.AFRIKAANS,
    }
    wrong = [q for q, expected in samples.items()
             if detect_language(q).language is not expected]

    if wrong:
        return Check("Languages", WARN, f"{len(wrong)} misdetected: {wrong[0]}",
                     "Check LANGUAGE_MARKERS in app/utils/language.py")

    return Check("Languages", OK, f"{len(supported_languages())} supported, samples all correct")


def check_memory() -> Check:
    from app.utils.conversation import ConversationMemory, Turn

    memory = ConversationMemory()
    memory.remember(Turn("q", "q", "a", route="pricing", product="White Bread"))
    resolved = memory.resolve("how much is it?", ["White Bread"]).resolved

    if "White Bread" not in resolved:
        return Check("Conversation memory", FAIL, "a follow-up was not resolved")

    return Check("Conversation memory", OK, f"'how much is it?' -> '{resolved}'")


def check_figure_verification() -> Check:
    from app.utils.answer_check import verify_figures

    faithful = verify_figures("Price R18.00", "Now R18.00").is_faithful
    caught = not verify_figures("Price R18.00", "Now R80.00").is_faithful

    if not (faithful and caught):
        return Check("Figure verification", FAIL, "the checker is not catching invented figures")

    return Check("Figure verification", OK, "faithful answers pass, invented figures rejected")


def check_end_to_end() -> Check:
    from app.agents.coordinator import KasiBizCoordinator

    coordinator = KasiBizCoordinator(use_llm=False, use_llm_routing=False)
    try:
        response = coordinator.ask("What is low in stock?")
    except Exception as exc:
        return Check("End to end", FAIL, str(exc)[:70])

    if not response.answer.strip():
        return Check("End to end", FAIL, "an empty answer came back")

    return Check("End to end", OK,
                 f"question -> {response.specialist} -> {len(response.answer)} character answer")


def check_live_ai() -> Check:
    from app.utils.config import ConfigError
    from app.utils.llm_client import KasiBizLLM, LLMError

    try:
        reply = KasiBizLLM().ask("Reply with exactly: ok", temperature=0, max_tokens=5)
    except (ConfigError, LLMError) as exc:
        return Check("Live AI call", FAIL, str(exc).splitlines()[0],
                     "Check the key at https://platform.openai.com/api-keys")

    return Check("Live AI call", OK, f"OpenAI replied: {reply[:30]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="KasiBiz health check")
    parser.add_argument("--ai", action="store_true", help="include a live OpenAI call")
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("KASIBIZ HEALTH CHECK")
    print("=" * 70)

    checks: list[Check] = [
        check_configuration(),
        check_api_key(),
        check_database(),
        check_sales_tables(),
        check_knowledge_base(),
        Check("Specialists", "", ""),
    ]
    checks += check_specialists()
    checks += [
        check_routing(),
        check_languages(),
        check_memory(),
        check_figure_verification(),
        check_the_till(),
        check_insights_refuse_to_guess(),
        check_end_to_end(),
    ]
    if args.ai:
        checks.append(check_live_ai())

    print()
    for check in checks:
        if not check.status:
            print(f"\n{check.name}")
            continue
        print(f"  [{check.status}] {check.name:<24} {check.detail}")
        if check.fix:
            print(f"         -> {check.fix}")

    failures = [c for c in checks if c.status == FAIL]
    warnings = [c for c in checks if c.status == WARN]

    print("\n" + "=" * 70)
    if failures:
        print(f"NOT READY - {len(failures)} failure(s), {len(warnings)} warning(s)")
        print("Fix the items marked FAIL above, then run this again.")
        return 1
    if warnings:
        print(f"READY WITH WARNINGS - {len(warnings)} warning(s)")
        print("KasiBiz will run, but some features will be limited.")
        return 0

    print("ALL SYSTEMS READY")
    print("Start with: python scripts/kasibiz.py --chat --ai")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
