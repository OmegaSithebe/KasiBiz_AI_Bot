"""Day 15 - end to end integration tests.

Everything else in the suite tests one piece in isolation, with fakes standing
in for its neighbours. These tests do the opposite: real database, real vector
store, real router, real memory, real specialists, all wired together exactly
as the shop owner will use them.

Only the language model is left out, so the suite stays free and offline. The
specialists fall back to their plain-facts output, which is what we assert on -
and which is also what a shop owner sees when the AI is unavailable.

    python -m pytest tests/test_integration.py -v
"""

from __future__ import annotations

import csv

import pytest

from app.agents.business_advisor_agent import BusinessAdvisorAgent
from app.agents.coordinator import KasiBizCoordinator
from app.agents.insight_agent import InsightsAgent
from app.agents.intent_classifier import Route
from app.agents.inventory_agent import StockAgent
from app.agents.marketing_agent import MarketingAgent
from app.agents.pricing_agent import PricingAgent
from app.agents.sales_agent import SalesAgent
from app.database.sqlite_db import StockDatabase, to_rand
from app.rag.retriever import KnowledgeRetriever
from app.rag.vector_store import KasiBizVectorStore, LocalEmbedder
from app.services.analytics_service import AnalyticsService, Period
from app.services.inventory_service import InventoryService
from app.services.marketing_service import MarketingService
from app.services.pricing_service import PricingService
from app.services.sales_service import SalesService
from app.utils.config import PROJECT_ROOT
from app.utils.language import Language

PRODUCTS_CSV = PROJECT_ROOT / "data" / "products.csv"
DOCUMENTS_ROOT = PROJECT_ROOT / "rag" / "documents"


@pytest.fixture(scope="module")
def shop(tmp_path_factory):
    """A complete, isolated KasiBiz: real data, real documents, no AI."""
    root = tmp_path_factory.mktemp("integration")

    db = StockDatabase(root / "kasibiz.db")
    db.initialise()
    with PRODUCTS_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            db.add_product(
                name=row["name"], category=row["category"], unit=row["unit"],
                cost_price=row["cost_price"], selling_price=row["selling_price"],
                quantity=int(row["quantity"]),
                low_stock_threshold=int(row["low_stock_threshold"]),
            )

    # Create a realistic low-stock situation so the Stock Agent has something to say.
    for name, left in (("Paraffin 1L", 0), ("Candles 6-pack", 1), ("Milk 1L", 2)):
        product = db.find_by_name(name)
        if product:
            db.set_stock(product.id, left)

    store = KasiBizVectorStore(path=root / "chroma",
                               collection_name="integration_knowledge",
                               embedder=LocalEmbedder())
    store.ingest(DOCUMENTS_ROOT)

    return {"db": db, "store": store}


@pytest.fixture()
def kasibiz(shop):
    """A fresh conversation against the shared shop."""
    db, store = shop["db"], shop["store"]
    return KasiBizCoordinator(
        stock_agent=StockAgent(InventoryService(db), use_llm=False),
        sales_agent=SalesAgent(SalesService(db), use_llm=False),
        pricing_agent=PricingAgent(PricingService(db), use_llm=False),
        marketing_agent=MarketingAgent(
            MarketingService(db, shop_name="Mama T Spaza"), use_llm=False),
        advisor_agent=BusinessAdvisorAgent(KnowledgeRetriever(store), use_llm=False),
        insights_agent=InsightsAgent(AnalyticsService(db), use_llm=False),
        use_llm=False,
        use_llm_routing=False,
    )


@pytest.fixture()
def own_shop(tmp_path):
    """A private shop for tests that change stock, so they cannot affect others."""
    db = StockDatabase(tmp_path / "private.db")
    db.initialise()
    db.add_product("White Bread", 15.00, 20.00, quantity=24, unit="loaf")
    db.add_product("Milk 1L", 17.50, 23.00, quantity=6)
    db.add_product("Simba Chips 36g", 6.50, 10.00, quantity=40)
    db.add_product("Candles 6-pack", 18.00, 25.00, quantity=1)
    return db


@pytest.fixture()
def trading(own_shop):
    """A coordinator wired to a shop it is allowed to sell from."""
    return KasiBizCoordinator(
        stock_agent=StockAgent(InventoryService(own_shop), use_llm=False),
        sales_agent=SalesAgent(SalesService(own_shop), use_llm=False),
        pricing_agent=PricingAgent(PricingService(own_shop), use_llm=False),
        marketing_agent=MarketingAgent(
            MarketingService(own_shop, shop_name="Mama T Spaza"), use_llm=False),
        insights_agent=InsightsAgent(AnalyticsService(own_shop), use_llm=False),
        use_llm=False,
        use_llm_routing=False,
    )


class TestEverythingIsWiredUp:
    def test_the_shop_has_stock(self, shop):
        assert shop["db"].count_products() == 20

    def test_the_knowledge_base_is_indexed(self, shop):
        assert shop["store"].count() > 0

    @pytest.mark.parametrize("question, specialist", [
        ("What is low in stock?", "Stock Agent"),
        ("What should I charge for White Bread?", "Pricing Helper"),
        ("Write a WhatsApp advert for White Bread", "Marketing Agent"),
        ("How do I register with CIPC?", "Business Advisor"),
        ("The customer wants 2 White Bread", "Sales Agent"),
        ("What is selling well this week?", "Insights Agent"),
    ])
    def test_every_specialist_is_reachable(self, kasibiz, question, specialist):
        assert kasibiz.ask(question).specialist == specialist

    def test_no_specialist_errors(self, kasibiz):
        for question in ("What is low in stock?",
                         "What should I charge for White Bread?",
                         "Write a WhatsApp advert for White Bread",
                         "How do I register with CIPC?"):
            assert kasibiz.ask(question).error == ""

    def test_every_answer_has_content(self, kasibiz):
        for question in ("Sawubona", "What can you do?", "What should I reorder?",
                         "Check my prices", "What should I promote?",
                         "What records must I keep for SARS?"):
            assert len(kasibiz.ask(question).answer.strip()) > 20


class TestRoutingCoverage:
    """Realistic phrasings a shop owner would actually use.

    This is the guard against silent misrouting. When a new phrase is added to a
    specialist but forgotten in the router, a case here should fail.
    """

    @pytest.mark.parametrize("question, route", [
        # Stock
        ("What is low in stock?", Route.STOCK),
        ("What should I reorder?", Route.STOCK),
        ("Anything running out?", Route.STOCK),
        ("Do I have enough White Bread?", Route.STOCK),
        ("How is my stock doing?", Route.STOCK),
        ("Give me a stock report", Route.STOCK),
        ("Yini esiphelile?", Route.STOCK),
        ("Hoeveel voorraad het ek?", Route.STOCK),
        # Pricing
        ("What should I charge for bread?", Route.PRICING),
        ("I buy bread for R15, what should I sell it for?", Route.PRICING),
        ("Am I making profit on Milk 1L?", Route.PRICING),
        ("Check all my prices", Route.PRICING),
        ("What is the difference between markup and margin?", Route.PRICING),
        ("What if I sell White Bread for R25?", Route.PRICING),
        ("How much does it cost me?", Route.PRICING),
        ("Are my prices too cheap?", Route.PRICING),
        ("Ngingayithengisa ngamalini?", Route.PRICING),
        ("Wat is die prys van brood?", Route.PRICING),
        # Marketing
        ("Write a WhatsApp advert for White Bread", Route.MARKETING),
        ("Make a poster for Coca-Cola 500ml", Route.MARKETING),
        ("Facebook caption for Simba Chips 36g", Route.MARKETING),
        ("What should I promote this week?", Route.MARKETING),
        ("10% off White Bread", Route.MARKETING),
        ("Ek wil 'n advertensie he", Route.MARKETING),
        # Advice
        ("How do I register with CIPC?", Route.ADVICE),
        ("What is an annual return?", Route.ADVICE),
        ("What records must I keep for SARS?", Route.ADVICE),
        ("What is beneficial ownership?", Route.ADVICE),
        ("Do I need to pay VAT?", Route.ADVICE),
        ("Hoe registreer ek by CIPC?", Route.ADVICE),
        # Coordinator itself
        ("Sawubona", Route.GREETING),
        ("Molo", Route.GREETING),
        ("Goeie more", Route.GREETING),
        ("What can you do?", Route.HELP),
        ("Who won the rugby world cup?", Route.UNKNOWN),
    ])
    def test_question_reaches_the_right_specialist(self, kasibiz, question, route):
        assert kasibiz.ask(question).route is route


class TestOneChatAcrossAllFour:
    """The Day 15 question: can a single conversation move between specialists?"""

    def test_a_shop_owners_morning(self, kasibiz):
        journey = [
            ("Sawubona", Route.GREETING),
            ("What is low in stock?", Route.STOCK),
            ("What should I reorder?", Route.STOCK),
            ("What should I charge for White Bread?", Route.PRICING),
            ("am I making enough profit on it?", Route.PRICING),
            ("write a WhatsApp advert for it", Route.MARKETING),
            ("and what about Coca-Cola 500ml?", Route.MARKETING),
            ("How do I register with CIPC?", Route.ADVICE),
            ("What records must I keep for SARS?", Route.ADVICE),
            ("What is low in stock?", Route.STOCK),
        ]

        for question, expected in journey:
            response = kasibiz.ask(question)
            assert response.route is expected, f"{question!r} went to {response.specialist}"
            assert response.answer.strip()
            assert response.error == ""

    def test_the_subject_survives_three_handoffs(self, kasibiz):
        kasibiz.ask("Do I have enough Coca-Cola 500ml?")       # stock
        kasibiz.ask("how much does it cost me?")               # pricing
        response = kasibiz.ask("write an advert for it")       # marketing

        assert response.route is Route.MARKETING
        assert "Coca-Cola 500ml" in response.answer

    def test_changing_subject_always_wins(self, kasibiz):
        kasibiz.ask("What should I charge for White Bread?")
        assert kasibiz.ask("How do I register with CIPC?").route is Route.ADVICE

    def test_memory_is_recorded_across_specialists(self, kasibiz):
        kasibiz.ask("What should I charge for White Bread?")
        kasibiz.ask("write an advert for it")

        assert kasibiz.memory.last_product == "White Bread"
        assert kasibiz.memory.last_route == "marketing"

    def test_a_new_conversation_starts_clean(self, kasibiz):
        kasibiz.ask("What should I charge for White Bread?")
        kasibiz.new_conversation()

        assert kasibiz.memory.is_empty
        assert kasibiz.ask("how much is it?").used_memory is False

    def test_ten_turns_leave_memory_bounded(self, kasibiz):
        for _ in range(10):
            kasibiz.ask("What is low in stock?")
        assert len(kasibiz.memory.turns) <= kasibiz.memory.max_turns


class TestTheAgentsAgreeWithEachOther:
    """Different specialists must never quote different numbers for the same product."""

    def test_selling_price_is_the_same_everywhere(self, kasibiz, shop):
        """Pricing and Marketing both quote the price - they must never disagree."""
        product = shop["db"].get_by_name("White Bread")
        price = f"R{to_rand(product.selling_price_cents):.2f}"

        pricing = kasibiz.ask("Am I making profit on White Bread?")
        marketing = kasibiz.ask("Write an advert for White Bread")

        assert price in pricing.answer
        assert price in marketing.answer

    def test_stock_answers_report_quantity_not_price(self, kasibiz):
        """A stock question is about how many are left, not what they cost."""
        answer = kasibiz.ask("Do I have enough White Bread?").answer
        assert "24" in answer and "in stock" in answer

    def test_stock_level_is_the_same_everywhere(self, kasibiz, shop):
        quantity = str(shop["db"].get_by_name("Coca-Cola 500ml").quantity)

        stock = kasibiz.ask("Do I have enough Coca-Cola 500ml?")
        marketing = kasibiz.ask("Write an advert for Coca-Cola 500ml")

        assert quantity in stock.answer
        assert quantity in marketing.answer

    def test_an_out_of_stock_product_is_refused_by_marketing(self, kasibiz):
        low = kasibiz.ask("What is low in stock?")
        advert = kasibiz.ask("Write an advert for Paraffin 1L")

        assert "Paraffin 1L" in low.answer
        assert "have not written the advert" in advert.answer

    def test_no_answer_ever_invents_a_figure(self, kasibiz):
        for question in ("What is low in stock?",
                         "What should I charge for White Bread?",
                         "Write a WhatsApp advert for White Bread",
                         "Am I making profit on Milk 1L?"):
            response = kasibiz.ask(question)
            assert response.figures_verified, f"{question!r} invented a figure"

    def test_a_refusal_does_not_look_like_an_invented_figure(self, kasibiz):
        """A refusal quotes real figures, so it must not be flagged as made up."""
        response = kasibiz.ask("Write an advert for Paraffin 1L")
        assert "have not written the advert" in response.answer
        assert response.figures_verified

    def test_a_time_phrase_is_not_treated_as_a_product_reference(self, kasibiz):
        kasibiz.ask("Write an advert for Simba Chips 36g")
        response = kasibiz.ask("What should I promote this week?")

        assert response.asked == "What should I promote this week?"
        assert "Best products to promote" in response.answer


class TestMultilingualEndToEnd:
    def test_a_whole_conversation_in_zulu(self, kasibiz):
        greeting = kasibiz.ask("Sawubona")
        assert "Sawubona" in greeting.answer
        assert greeting.language.language is Language.ZULU

        stock = kasibiz.ask("Yini esiphelile?")
        assert stock.route is Route.STOCK
        assert stock.answer.strip()

    def test_a_whole_conversation_in_afrikaans(self, kasibiz):
        greeting = kasibiz.ask("Goeie more")
        assert "Hallo" in greeting.answer

        stock = kasibiz.ask("Hoeveel voorraad het ek?")
        assert stock.route is Route.STOCK

    def test_switching_language_mid_conversation(self, kasibiz):
        kasibiz.ask("Sawubona")
        response = kasibiz.ask("What is low in stock?")
        assert response.route is Route.STOCK


class TestResilience:
    """One missing piece must never take the whole assistant down."""

    def test_it_runs_with_no_knowledge_base(self, shop, tmp_path):
        empty = KasiBizVectorStore(path=tmp_path / "empty",
                                   collection_name="empty_knowledge",
                                   embedder=LocalEmbedder())
        coordinator = KasiBizCoordinator(
            stock_agent=StockAgent(InventoryService(shop["db"]), use_llm=False),
            advisor_agent=BusinessAdvisorAgent(KnowledgeRetriever(empty), use_llm=False),
            use_llm=False, use_llm_routing=False,
        )

        assert coordinator.ask("What is low in stock?").answer.strip()
        assert "not been built" in coordinator.ask("How do I register with CIPC?").answer

    def test_it_runs_with_an_empty_shop(self, tmp_path, shop):
        empty_db = StockDatabase(tmp_path / "empty.db")
        empty_db.initialise()

        coordinator = KasiBizCoordinator(
            stock_agent=StockAgent(InventoryService(empty_db), use_llm=False),
            pricing_agent=PricingAgent(PricingService(empty_db), use_llm=False),
            use_llm=False, use_llm_routing=False,
        )

        assert coordinator.ask("What is low in stock?").answer.strip()
        assert coordinator.ask("Check my prices").answer.strip()

    def test_one_broken_specialist_does_not_stop_the_others(self, shop):
        class Broken:
            def answer(self, question):
                raise RuntimeError("database is locked")

        coordinator = KasiBizCoordinator(
            stock_agent=Broken(),
            pricing_agent=PricingAgent(PricingService(shop["db"]), use_llm=False),
            use_llm=False, use_llm_routing=False,
        )

        broken = coordinator.ask("What is low in stock?")
        working = coordinator.ask("Am I making profit on White Bread?")

        assert "could not answer" in broken.answer
        assert working.error == ""
        assert "White Bread" in working.answer

    def test_every_answer_works_with_the_ai_switched_off(self, kasibiz):
        for question in ("What is low in stock?",
                         "What should I charge for White Bread?",
                         "Write an advert for White Bread",
                         "How do I register with CIPC?"):
            response = kasibiz.ask(question)
            assert response.used_llm is False
            assert len(response.answer.strip()) > 20


class TestAuditability:
    """Everything needed to explain an answer afterwards."""

    def test_the_routing_decision_is_recorded(self, kasibiz):
        decision = kasibiz.ask("What is low in stock?").decision
        assert decision.method and decision.scores and decision.confidence > 0

    def test_advice_answers_cite_their_source(self, kasibiz):
        response = kasibiz.ask("How do I register with CIPC?")
        assert response.sources
        assert any(".md" in source for source in response.sources)

    def test_the_detected_language_is_recorded(self, kasibiz):
        assert kasibiz.ask("Sawubona").language.language is Language.ZULU

    def test_the_resolved_question_is_recorded(self, kasibiz):
        kasibiz.ask("What should I charge for White Bread?")
        response = kasibiz.ask("how much is it?")
        assert response.asked != response.question
        assert "White Bread" in response.asked

    def test_figures_are_checked_on_factual_answers(self, kasibiz):
        assert kasibiz.ask("What is low in stock?").figures is not None


class TestASaleFromStartToFinish:
    """The full till journey, through the router, exactly as an owner types it."""

    def test_a_complete_sale_reduces_stock(self, trading, own_shop):
        trading.ask("2 White Bread")
        trading.ask("1 Milk 1L")
        trading.ask("the customer paid R100")
        response = trading.ask("yes")

        assert response.agent_response.committed
        assert own_shop.count_sales() == 1
        assert own_shop.get_by_name("White Bread").quantity == 22
        assert own_shop.get_by_name("Milk 1L").quantity == 5

    def test_the_total_and_change_are_right(self, trading):
        trading.ask("2 White Bread")
        trading.ask("1 Milk 1L")
        response = trading.ask("the customer paid R100")

        assert "R63.00" in response.answer
        assert "R37.00" in response.answer

    def test_a_cancelled_sale_leaves_stock_untouched(self, trading, own_shop):
        trading.ask("3 White Bread")
        trading.ask("they paid R100")
        trading.ask("cancel it")

        assert own_shop.count_sales() == 0
        assert own_shop.get_by_name("White Bread").quantity == 24

    def test_an_unconfirmed_sale_leaves_stock_untouched(self, trading, own_shop):
        trading.ask("3 White Bread")
        trading.ask("they paid R100")

        assert own_shop.count_sales() == 0
        assert own_shop.get_by_name("White Bread").quantity == 24

    def test_an_unknown_product_is_explained(self, trading):
        assert "does not stock" in trading.ask("2 Caviar").answer

    def test_not_enough_stock_is_refused_before_anything_is_written(
            self, trading, own_shop):
        response = trading.ask("5 Candles 6-pack")
        assert "only 1" in response.answer
        assert own_shop.count_sales() == 0

    def test_insufficient_payment_is_refused(self, trading, own_shop):
        trading.ask("2 White Bread")
        response = trading.ask("they paid R30")

        assert "not enough" in response.answer.lower()
        assert own_shop.count_sales() == 0

    def test_confirming_twice_records_one_sale(self, trading, own_shop):
        trading.ask("2 White Bread")
        trading.ask("they paid R50")
        trading.ask("yes")
        trading.ask("yes")

        assert own_shop.count_sales() == 1
        assert own_shop.get_by_name("White Bread").quantity == 22

    def test_yes_with_nothing_pending_changes_nothing(self, trading, own_shop):
        response = trading.ask("yes")
        assert own_shop.count_sales() == 0
        assert "nothing waiting" in response.answer.lower()


class TestTheBasketIsNotHijacked:
    """An open basket changes what a short message means - but not a clear one."""

    def test_yes_goes_to_the_till_while_a_sale_is_open(self, trading):
        trading.ask("2 White Bread")
        trading.ask("they paid R50")
        assert trading.ask("yes").route is Route.SALES

    def test_a_clear_change_of_subject_still_wins(self, trading):
        trading.ask("2 White Bread")
        assert trading.ask("How do I register with CIPC?").route is not Route.SALES

    def test_a_stock_question_mid_sale_still_reaches_stock(self, trading):
        trading.ask("2 White Bread")
        assert trading.ask("What is low in stock?").route is Route.STOCK

    def test_the_basket_survives_a_detour(self, trading, own_shop):
        trading.ask("2 White Bread")
        trading.ask("What is low in stock?")
        trading.ask("they paid R50")
        trading.ask("yes")

        assert own_shop.count_sales() == 1

    def test_a_confirmation_does_not_leak_into_the_next_task(self, trading):
        trading.ask("2 White Bread")
        trading.ask("they paid R50")
        trading.ask("yes")
        assert trading.ask("yes").route is not Route.SALES


class TestSalesShowUpInInsights:
    """The till and the books must be looking at the same numbers."""

    def test_a_recorded_sale_appears_in_the_report(self, trading, own_shop):
        trading.ask("2 White Bread")
        trading.ask("they paid R50")
        trading.ask("yes")

        response = trading.ask("How much did I take today?")
        assert response.specialist == "Insights Agent"
        assert "R40.00" in response.answer

    def test_the_best_seller_is_what_was_actually_sold(self, trading):
        for _ in range(3):
            trading.new_conversation()
            trading.ask("2 White Bread")
            trading.ask("they paid R50")
            trading.ask("yes")

        assert "White Bread" in trading.ask("What is selling well today?").answer

    def test_insights_refuse_to_guess_before_any_sale(self, trading):
        response = trading.ask("What is selling well today?")
        assert "no sales recorded" in response.answer.lower()

    def test_profit_matches_the_recorded_sale(self, trading, own_shop):
        trading.ask("2 White Bread")
        trading.ask("they paid R50")
        trading.ask("yes")

        report = AnalyticsService(own_shop).report(Period.TODAY)
        assert report.revenue_cents == 4000
        assert report.profit_cents == 1000
        assert "R10.00" in trading.ask("What was my profit today?").answer


class TestTopicSwitchingAcrossSixAgents:
    def test_one_conversation_visits_every_specialist(self, kasibiz):
        journey = [
            ("What is low in stock?", "Stock Agent"),
            ("What should I charge for White Bread?", "Pricing Helper"),
            ("Write a WhatsApp advert for it", "Marketing Agent"),
            ("How do I register with CIPC?", "Business Advisor"),
            ("What is selling well this week?", "Insights Agent"),
            ("The customer wants 2 White Bread", "Sales Agent"),
        ]
        for question, specialist in journey:
            assert kasibiz.ask(question).specialist == specialist, question

    def test_the_subject_follows_the_owner_into_a_sale(self, trading):
        trading.ask("What should I charge for White Bread?")
        response = trading.ask("the customer wants 2 of them")
        assert response.route is Route.SALES
        assert "White Bread" in response.answer

    def test_language_choice_does_not_break_the_journey(self, trading, own_shop):
        trading.ask("Sawubona")
        trading.ask("2 White Bread")
        trading.ask("they paid R50")
        trading.ask("yebo")
        assert own_shop.count_sales() == 1
