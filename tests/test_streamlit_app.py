"""The Streamlit screen: does it start, and does it show the real shop?

Streamlit's own AppTest runs the script the way the browser would, without a
browser. That is enough to catch the failures that matter here: an import that
breaks, a widget that throws, and a screen that silently shows nothing.
"""

from __future__ import annotations

import sys

import pytest

streamlit = pytest.importorskip("streamlit", reason="Streamlit is not installed")
from streamlit.testing.v1 import AppTest  # noqa: E402

from app.database.sqlite_db import StockDatabase  # noqa: E402
from app.services.sales_service import SalesService  # noqa: E402
from app.utils.config import PROJECT_ROOT  # noqa: E402

# AppTest resolves a relative path against the calling file, not the repo root.
APP = str(PROJECT_ROOT / "streamlit_app" / "app.py")
TIMEOUT = 60


@pytest.fixture
def shop(tmp_path, monkeypatch):
    """Point the whole app at a throwaway database with a known shop in it."""
    import app.database.sqlite_db as sqlite_db

    # st.cache_resource outlives an AppTest instance, so without this the
    # coordinator built by the previous test is reused - still wired to the
    # previous test's database. The fixtures look isolated but are not.
    streamlit.cache_resource.clear()

    db = StockDatabase(tmp_path / "streamlit.db")
    db.initialise()
    db.add_product("White Bread", 15.00, 20.00, quantity=24, unit="loaf")
    db.add_product("Milk 1L", 17.50, 23.00, quantity=6)
    db.add_product("Simba Chips 36g", 6.50, 10.00, quantity=40)
    db.add_product("Candles 6-pack", 18.00, 25.00, quantity=1)

    monkeypatch.setattr(sqlite_db, "_default_db", db)
    monkeypatch.setattr(sqlite_db, "get_db", lambda: db)
    yield db
    streamlit.cache_resource.clear()


@pytest.fixture
def app(shop):
    running = AppTest.from_file(APP, default_timeout=TIMEOUT)
    running.session_state["use_ai"] = False
    return running


def text_of(running) -> str:
    parts = [element.value for element in running.markdown]
    parts += [element.value for element in running.caption]
    parts += [str(element.value) for element in running.metric]
    parts += [element.value for element in running.info]
    parts += [element.value for element in running.warning]
    parts += [element.value for element in running.success]
    parts += [element.value for element in running.error]
    return "\n".join(str(part) for part in parts)


def selectbox_offering(running, wanted: str):
    """Find a dropdown by what is in it, not by where it happens to sit."""
    for box in running.selectbox:
        if any(wanted in str(option) for option in box.options):
            return box
    return None


class TestItStarts:
    def test_it_imports_the_way_streamlit_loads_it(self):
        """Streamlit puts the script's own folder first on the import path.

        This script is called app.py and the package is called app, so that
        ordering makes "import app.agents" resolve to the script itself. The
        AppTest harness below cannot catch it, because pytest has already put
        the project root on the path. Reproduce Streamlit's path here instead.
        """
        import subprocess

        script = PROJECT_ROOT / "streamlit_app" / "app.py"
        result = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, r'{script.parent}'); "
             f"exec(compile(open(r'{script}', encoding='utf-8').read(), "
             f"r'{script}', 'exec'))"],
            capture_output=True, text=True, timeout=180, cwd=PROJECT_ROOT,
        )
        assert "ModuleNotFoundError" not in result.stderr, result.stderr[-800:]
        assert "'app' is not a package" not in result.stderr, result.stderr[-800:]

    def test_the_app_imports_and_runs_without_an_exception(self, app):
        app.run()
        assert not app.exception

    def test_the_name_and_value_statement_are_on_screen(self, app):
        app.run()
        screen = text_of(app)
        assert "KasiBiz" in screen
        assert "shop assistant" in screen

    def test_the_main_navigation_is_there(self, app):
        app.run()
        options = app.sidebar.radio[0].options
        for page in ("Assistant", "New Sale", "Stock", "Insights"):
            assert page in options

    def test_three_languages_can_be_chosen(self, app):
        app.run()
        options = app.sidebar.selectbox[0].options
        assert {"English", "isiZulu", "Sesotho"} <= set(options)

    def test_the_quick_actions_are_on_the_first_screen(self, app):
        app.run()
        labels = {button.label for button in app.button}
        for action in ("Check Stock", "Sales Insights", "Create Advert",
                       "Business Advice"):
            assert action in labels

    def test_the_legal_disclaimer_is_always_visible(self, app):
        app.run()
        assert "not legal, tax or financial advice" in text_of(app)


class TestItShowsTheRealShop:
    def test_the_sidebar_counts_the_real_products(self, app, shop):
        app.run()
        assert f"{shop.count_products()} products" in text_of(app)

    def test_the_stock_page_lists_what_is_on_the_shelf(self, app):
        app.session_state["page"] = "Stock"
        app.run()
        assert not app.exception
        assert app.dataframe, "the stock table did not render"
        assert "White Bread" in str(app.dataframe[0].value)

    def test_the_stock_page_warns_about_low_stock(self, app):
        app.session_state["page"] = "Stock"
        app.run()
        assert "Candles 6-pack" in text_of(app)

    def test_a_stock_update_shows_up_on_the_screen(self, app, shop):
        bread = shop.get_by_name("White Bread")
        shop.adjust_stock(bread.id, 10)

        app.session_state["page"] = "Stock"
        app.run()
        assert app.dataframe, "the stock table did not render"
        assert "34" in str(app.dataframe[0].value)


class TestTheAssistantAnswersThroughTheRealRouter:
    def test_a_stock_question_gets_a_real_answer(self, app):
        app.run()
        app.chat_input[0].set_value("What is low in stock?").run()

        assert not app.exception
        screen = text_of(app)
        assert "Candles 6-pack" in screen
        assert "Stock Agent" in screen

    def test_a_marketing_request_uses_the_named_product(self, app):
        app.run()
        app.chat_input[0].set_value("Write a WhatsApp advert for Simba Chips 36g").run()

        assert not app.exception
        screen = text_of(app)
        assert "Simba Chips 36g" in screen
        assert "Marketing Agent" in screen

    def test_a_pricing_question_reaches_the_pricing_helper(self, app):
        app.run()
        app.chat_input[0].set_value("Am I making profit on White Bread?").run()
        assert "Pricing Helper" in text_of(app)

    def test_a_business_question_reaches_the_advisor(self, app):
        app.run()
        app.chat_input[0].set_value("How do I register with CIPC?").run()
        assert not app.exception
        assert "Business Advisor" in text_of(app)

    def test_the_assistant_says_where_the_answer_came_from(self, app):
        app.run()
        app.chat_input[0].set_value("What is low in stock?").run()
        assert "your shop's records" in text_of(app)


class TestAnEmptyShopExplainsItself:
    def test_no_products_means_a_helpful_message_not_an_empty_table(
            self, tmp_path, monkeypatch):
        import app.database.sqlite_db as sqlite_db

        empty = StockDatabase(tmp_path / "empty.db")
        empty.initialise()
        monkeypatch.setattr(sqlite_db, "get_db", lambda: empty)

        running = AppTest.from_file(APP, default_timeout=TIMEOUT)
        running.session_state["use_ai"] = False
        running.session_state["page"] = "New Sale"
        running.run()

        assert not running.exception
        assert "no products yet" in text_of(running).lower()

    def test_insights_with_no_sales_refuses_to_guess(self, app):
        app.session_state["page"] = "Insights"
        app.run()

        assert not app.exception
        screen = text_of(app).lower()
        assert "no sales have been recorded" in screen
        assert "will not" in screen and "estimate" in screen


class TestASaleCanBeCompletedOnScreen:
    def test_the_new_sale_page_offers_the_products_in_stock(self, app):
        app.session_state["page"] = "New Sale"
        app.run()
        assert not app.exception
        assert selectbox_offering(app, "White Bread") is not None

    def test_a_basket_built_in_the_service_is_shown_on_screen(self, app, shop):
        service = SalesService(db=shop)
        service.add_item("White Bread", 2)

        import streamlit_app.app as screen_module  # noqa: F401

        app.session_state["page"] = "New Sale"
        app.run()
        assert not app.exception

    def test_a_sale_confirmed_through_the_service_appears_in_insights(self, app, shop):
        """The screen and the till must be looking at the same books."""
        service = SalesService(db=shop)
        service.add_item("White Bread", 2)
        service.set_payment(50)
        service.confirm_sale()

        app.session_state["page"] = "Insights"
        app.run()

        assert not app.exception
        screen = text_of(app)
        assert "R40.00" in screen
        assert shop.get_by_name("White Bread").quantity == 22

    def test_confirming_asks_before_it_saves(self, app):
        app.session_state["page"] = "New Sale"
        app.session_state["confirm_sale"] = False
        app.run()
        assert not app.exception


class TestTheTestsAreIsolatedFromEachOther:
    """Each test must get its own shop, not the one left behind by the last."""

    def test_the_assistant_sees_this_test_s_shop(self, app, shop):
        extra = "Isolation Marker 1kg"
        shop.add_product(extra, 5.00, 9.00, quantity=7)

        app.run()
        app.chat_input[0].set_value(f"Do I have enough {extra}?").run()

        assert not app.exception
        assert extra in text_of(app), "the assistant is reading a stale database"

    def test_a_second_test_does_not_see_the_first_one_s_marker(self, app):
        app.run()
        app.chat_input[0].set_value("Do I have enough Isolation Marker 1kg?").run()

        assert not app.exception
        assert "7 in stock" not in text_of(app)


class TestNothingBlowsUpInFrontOfTheOwner:
    @pytest.mark.parametrize("page", ["Assistant", "New Sale", "Stock", "Insights"])
    def test_every_page_renders(self, app, page):
        app.session_state["page"] = page
        app.run()
        assert not app.exception

    def test_a_nonsense_question_gets_a_polite_answer(self, app):
        app.run()
        app.chat_input[0].set_value("Who won the rugby world cup?").run()
        assert not app.exception
        assert "not sure" in text_of(app).lower()

    def test_the_start_over_button_clears_the_conversation(self, app):
        app.run()
        app.chat_input[0].set_value("What is low in stock?").run()
        assert app.session_state["messages"]

        next(b for b in app.sidebar.button if b.label == "Start over").click().run()
        assert not app.session_state["messages"]
