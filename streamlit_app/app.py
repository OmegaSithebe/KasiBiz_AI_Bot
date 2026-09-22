"""KasiBiz on screen.

The people this is built for may never have used a business system before, and
some of them are serving a customer while they use it. So the screen follows
three rules:

    One job per screen. Big targets. Nothing destructive without a confirmation.

Every figure shown here comes from the same services the terminal version uses.
There are no hard-coded answers and no illustrative charts on this screen.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Streamlit puts this script's own folder first on the import path. Because the
# script is called app.py, "import app.agents" would then resolve to this file
# instead of the app/ package. Drop the script folder and lead with the project
# root. Without this the app starts and immediately dies with
# "No module named 'app.agents'; 'app' is not a package".
_here = str(Path(__file__).resolve().parent)
while _here in sys.path:
    sys.path.remove(_here)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agents.business_advisor_agent import BusinessAdvisorAgent  # noqa: E402
from app.agents.coordinator import KasiBizCoordinator  # noqa: E402
from app.agents.insight_agent import InsightsAgent  # noqa: E402
from app.agents.intents import Route  # noqa: E402
from app.agents.inventory_agent import StockAgent  # noqa: E402
from app.agents.marketing_agent import MarketingAgent  # noqa: E402
from app.agents.pricing_agent import PricingAgent  # noqa: E402
from app.agents.sales_agent import SalesAgent  # noqa: E402
from app.database.sqlite_db import format_rand, get_db  # noqa: E402
from app.services.analytics_service import AnalyticsService, Period  # noqa: E402
from app.services.inventory_service import InventoryService  # noqa: E402
from app.services.marketing_service import MarketingService  # noqa: E402
from app.services.pricing_service import PricingService  # noqa: E402
from app.services.sales_service import SalesError, SalesService  # noqa: E402
from app.utils.config import get_shop_name  # noqa: E402
from app.utils.language import Language  # noqa: E402
from app.utils.logging_setup import get_logger  # noqa: E402

log = get_logger("kasibiz.screen")

LANGUAGES = {
    "English": Language.ENGLISH,
    "isiZulu": Language.ZULU,
    "Sesotho": Language.SOTHO,
}

GREETINGS = {
    "English": "Welcome back. What can I help you with today?",
    "isiZulu": "Siyakwamukela. Ngingakusiza ngani namuhla?",
    "Sesotho": "Re a u amohela. Nka u thusa ka eng kajeno?",
}

QUICK_ACTIONS = [
    ("New Sale", "sale", "Ring up what a customer is buying"),
    ("Check Stock", "What is low in stock?", "See what is running out"),
    ("Sales Insights", "How is business this week?", "What is selling and what is not"),
    ("Profit Help", "Check my prices", "Find prices that are too low"),
    ("Create Advert", "What should I promote?", "A WhatsApp message for customers"),
    ("Business Advice", "How do I register with CIPC?", "CIPC, SARS and the rules"),
]

DISCLAIMER = (
    "Guidance on registration, tax and business matters is for education only. "
    "It is not legal, tax or financial advice. Always confirm with CIPC, SARS "
    "or a qualified adviser before you act."
)


# ------------------------------------------------------------------ the brain
@st.cache_resource(show_spinner=False)
def build_assistant(use_ai: bool):
    """One set of agents, all sharing one database, built once per session.

    The Business Advisor is left for the Coordinator to build on demand. It has
    to open the knowledge base, and most visits never ask it anything.
    """
    db = get_db()
    return KasiBizCoordinator(
        stock_agent=StockAgent(service=InventoryService(db=db), use_llm=use_ai),
        sales_agent=SalesAgent(service=SalesService(db=db), use_llm=use_ai),
        pricing_agent=PricingAgent(service=PricingService(db=db), use_llm=use_ai),
        marketing_agent=MarketingAgent(
            service=MarketingService(db=db, shop_name=get_shop_name()), use_llm=use_ai),
        insights_agent=InsightsAgent(service=AnalyticsService(db=db), use_llm=use_ai),
        use_llm=use_ai,
        use_llm_routing=use_ai,
    )


def assistant() -> KasiBizCoordinator:
    return build_assistant(st.session_state.get("use_ai", False))


def till() -> SalesService:
    return assistant().agent_for(Route.SALES).service


def database():
    return get_db()


# --------------------------------------------------------------------- setup
st.set_page_config(
    page_title="KasiBiz",
    page_icon="K",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .block-container { padding-top: 2.2rem; max-width: 1180px; }
  h1, h2, h3 { letter-spacing: -0.01em; }
  .kb-title { font-size: 2.35rem; font-weight: 750; margin-bottom: 0.1rem;
              color: #17472F; }
  .kb-tagline { font-size: 1.05rem; color: #4A5A52; margin-bottom: 1.4rem; }
  .kb-card { background: #F4F8F5; border: 1px solid #DCE7E0; border-radius: 12px;
             padding: 1.1rem 1.25rem; margin-bottom: 0.9rem; }
  .kb-total { font-size: 2rem; font-weight: 750; color: #17472F; }
  .kb-change { font-size: 2rem; font-weight: 750; color: #A8500F; }
  .kb-label { font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.06em;
              color: #5B6B62; margin-bottom: 0.15rem; }
  .kb-source { font-size: 0.85rem; color: #4A5A52; border-left: 3px solid #9CC3AC;
               padding-left: 0.7rem; margin-top: 0.6rem; }
  .kb-demo { background: #FFF6E5; border: 1px solid #F0D9A8; border-radius: 8px;
             padding: 0.55rem 0.8rem; font-size: 0.85rem; color: #6B4E12; }
  .stButton button { width: 100%; border-radius: 9px; padding: 0.55rem 0.6rem;
                     font-weight: 600; }
  div[data-testid="stMetricValue"] { font-size: 1.5rem; }
</style>
""", unsafe_allow_html=True)


def init_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("language", "English")
    st.session_state.setdefault("page", "Assistant")
    st.session_state.setdefault("use_ai", False)
    st.session_state.setdefault("pending", None)
    st.session_state.setdefault("confirm_sale", False)


init_state()


def say(role: str, text: str, sources=None, specialist: str = "") -> None:
    st.session_state.messages.append(
        {"role": role, "text": text, "sources": sources or [], "specialist": specialist}
    )


def ask_kasibiz(question: str) -> None:
    """Send a question through the real router and record both sides."""
    say("user", question)
    try:
        with st.spinner("Looking it up in your records..."):
            response = assistant().ask(question)
    except Exception:  # the owner must never see a stack trace
        log.exception("the assistant failed on %r", question)
        say("assistant", "Something went wrong on my side. Please try again, "
                         "or use one of the buttons above.")
        return
    say("assistant", response.answer, response.sources, response.specialist)


# ------------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### KasiBiz")
    st.caption(get_shop_name())

    st.session_state.language = st.selectbox(
        "Language / Ulimi / Puo", list(LANGUAGES), index=list(LANGUAGES).index(
            st.session_state.language),
    )

    chosen = st.radio(
        "Go to",
        ["Assistant", "New Sale", "Stock", "Insights"],
        index=["Assistant", "New Sale", "Stock", "Insights"].index(st.session_state.page),
    )
    if chosen != st.session_state.page:
        # Leaving the page also dismisses the receipt. Without this the radio
        # moves but the screen does not, which looks broken.
        st.session_state.page = chosen
        st.session_state.pending = None
        st.session_state.confirm_sale = False
        st.rerun()

    st.divider()

    use_ai = st.toggle(
        "Use AI wording", value=st.session_state.use_ai,
        help="Off: instant, free and works without internet. "
             "On: the same figures, explained more naturally.",
    )
    if use_ai != st.session_state.use_ai:
        st.session_state.use_ai = use_ai
        st.cache_resource.clear()
        st.rerun()

    st.divider()

    db = database()
    st.caption(f"{db.count_products()} products  |  {db.count_sales()} sales recorded")
    st.caption(f"Stock at cost: {format_rand(db.total_stock_value_cents())}")

    if st.button("Start over"):
        assistant().new_conversation()
        st.session_state.messages = []
        st.session_state.pending = None
        st.rerun()


# --------------------------------------------------------------------- header
st.markdown('<div class="kb-title">KasiBiz</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="kb-tagline">Your shop assistant. Ring up sales, watch your stock, '
    'check your prices and get straight answers about running the business.</div>',
    unsafe_allow_html=True,
)


def empty_shop_notice() -> bool:
    """A blank shop must explain itself instead of showing empty tables."""
    if database().count_products():
        return False
    st.info(
        "**There are no products yet.**\n\n"
        "Load the demonstration shop from a terminal:\n\n"
        "```\npython scripts/seed_demo.py\n```\n\n"
        "Or add your first product on the **Stock** page."
    )
    return True


# ===================================================================== ASSISTANT
def page_assistant() -> None:
    st.markdown("#### Quick actions")
    columns = st.columns(3)
    for index, (label, question, hint) in enumerate(QUICK_ACTIONS):
        with columns[index % 3]:
            if st.button(label, key=f"qa_{index}", help=hint):
                if question == "sale":
                    st.session_state.page = "New Sale"
                    st.rerun()
                ask_kasibiz(question)
                st.rerun()

    st.divider()

    if not st.session_state.messages:
        st.markdown(
            f'<div class="kb-card">{GREETINGS[st.session_state.language]}<br><br>'
            "Try: <i>What is low in stock?</i> &nbsp;|&nbsp; "
            "<i>2 White Bread and 1 Milk 1L</i> &nbsp;|&nbsp; "
            "<i>How do I register with CIPC?</i></div>",
            unsafe_allow_html=True,
        )

    for message in st.session_state.messages:
        with st.chat_message("user" if message["role"] == "user" else "assistant"):
            if message["role"] == "assistant" and message["specialist"]:
                st.caption(f"Answered using your shop's records - {message['specialist']}")
            st.markdown(message["text"].replace("\n", "  \n"))
            if message["sources"]:
                st.markdown(
                    '<div class="kb-source">Source: '
                    + "; ".join(message["sources"]) + "</div>",
                    unsafe_allow_html=True,
                )
                st.caption(DISCLAIMER)

    question = st.chat_input("Ask KasiBiz anything about your shop...")
    if question:
        ask_kasibiz(question)
        st.rerun()


# ====================================================================== NEW SALE
def page_new_sale() -> None:
    if empty_shop_notice():
        return

    service = till()
    basket = service.basket
    products = database().list_products()
    in_stock = [p for p in products if p.quantity > 0]

    left, right = st.columns([5, 4], gap="large")

    with left:
        st.markdown("#### 1. What is the customer buying?")

        if not in_stock:
            st.warning("Everything is out of stock. Add stock before making a sale.")
            return

        with st.form("add_item", clear_on_submit=True):
            choice = st.selectbox(
                "Product",
                in_stock,
                format_func=lambda p: f"{p.name} - {format_rand(p.selling_price_cents)} "
                                      f"({p.quantity} left)",
            )
            quantity = st.number_input("How many?", min_value=1,
                                       max_value=max(choice.quantity, 1), value=1, step=1)
            if st.form_submit_button("Add to basket", type="primary"):
                try:
                    service.add_item(choice.name, int(quantity))
                    st.rerun()
                except SalesError as exc:
                    st.error(str(exc))

        st.caption("You can also type it on the Assistant page, "
                   "for example: *2 White Bread and 1 Milk 1L*.")

    with right:
        st.markdown("#### 2. The basket")

        if basket is None or basket.is_empty:
            st.markdown('<div class="kb-card">Nothing in the basket yet. '
                        'Add the first item on the left.</div>', unsafe_allow_html=True)
            return

        for index, line in enumerate(basket.lines):
            row, action = st.columns([6, 1])
            row.write(f"**{line.quantity} x {line.product_name}**  \n"
                      f"{format_rand(line.unit_price_cents)} each  =  "
                      f"**{format_rand(line.line_total_cents)}**")
            if action.button("Remove", key=f"rm_{index}"):
                service.remove_item(line.product_name, basket=basket)
                st.rerun()

        st.divider()
        st.markdown(f'<div class="kb-label">Total to pay</div>'
                    f'<div class="kb-total">{format_rand(basket.total_cents)}</div>',
                    unsafe_allow_html=True)

        st.markdown("#### 3. Payment")
        paid = st.number_input(
            "How much did the customer give you? (R)",
            min_value=0.0, step=5.0, format="%.2f",
            value=float(basket.total_cents) / 100,
        )

        short = basket.total_cents - int(round(paid * 100))
        if short > 0:
            st.error(f"That is {format_rand(short)} short. "
                     "The sale cannot be completed yet.")
        else:
            change = int(round(paid * 100)) - basket.total_cents
            st.markdown(f'<div class="kb-label">Change to give</div>'
                        f'<div class="kb-change">{format_rand(change)}</div>',
                        unsafe_allow_html=True)

            st.markdown("#### 4. Confirm")
            if not st.session_state.confirm_sale:
                if st.button("Save this sale", type="primary"):
                    st.session_state.confirm_sale = True
                    st.rerun()
            else:
                st.warning(f"Save {basket.item_count} item(s) for "
                           f"{format_rand(basket.total_cents)} and take the stock "
                           "off the shelf?")
                yes, no = st.columns(2)
                if yes.button("Yes, save it", type="primary"):
                    try:
                        service.set_payment(paid, basket=basket)
                        sale = service.confirm_sale(basket)
                        service.basket = None
                        st.session_state.confirm_sale = False
                        st.session_state.pending = sale
                        st.rerun()
                    except SalesError as exc:
                        st.session_state.confirm_sale = False
                        st.error(str(exc))
                if no.button("No, go back"):
                    st.session_state.confirm_sale = False
                    st.rerun()

        if st.button("Cancel this sale"):
            st.info(service.cancel_sale(basket))
            st.session_state.confirm_sale = False
            st.rerun()


def show_receipt() -> None:
    sale = st.session_state.pending
    if sale is None:
        return
    st.success(f"Sale #{sale.sale_id} saved. Stock has been updated.")
    left, right = st.columns([3, 2])
    with left:
        st.code(sale.as_receipt(get_shop_name()), language=None)
    with right:
        st.metric("Total", format_rand(sale.total_cents))
        st.metric("Change given", format_rand(sale.change_cents))
        st.metric("Profit on this sale", format_rand(sale.profit_cents))
    if st.button("Start the next sale", type="primary"):
        st.session_state.pending = None
        st.rerun()


# ========================================================================= STOCK
def page_stock() -> None:
    products = database().list_products()

    st.markdown("#### Add or top up stock")
    with st.expander("Add a new product, or add stock to one you already have"):
        existing = st.selectbox(
            "Product", ["-- a new product --"] + [p.name for p in products])

        if existing == "-- a new product --":
            with st.form("new_product", clear_on_submit=True):
                columns = st.columns(2)
                name = columns[0].text_input("Product name")
                unit = columns[1].text_input("Unit", value="each")
                cost = columns[0].number_input("You pay (R)", min_value=0.0, step=1.0)
                price = columns[1].number_input("You sell for (R)", min_value=0.0, step=1.0)
                quantity = columns[0].number_input("How many now?", min_value=0, step=1)
                alert = columns[1].number_input("Warn me below", min_value=0, value=5, step=1)

                if st.form_submit_button("Add product", type="primary"):
                    if not name.strip():
                        st.error("Give the product a name.")
                    elif price < cost:
                        st.warning("You would sell this for less than you paid. "
                                   "Check the prices before saving.")
                    else:
                        try:
                            database().add_product(
                                name=name, cost_price=cost, selling_price=price,
                                quantity=int(quantity), unit=unit or "each",
                                low_stock_threshold=int(alert))
                            st.success(f"{name} added.")
                            st.rerun()
                        except Exception as exc:
                            log.warning("could not add product %r: %s", name, exc)
                            st.error(str(exc))
        else:
            product = database().get_by_name(existing)
            st.caption(f"{product.quantity} {product.unit} on the shelf now.")
            extra = st.number_input("How many did you receive?", min_value=1, step=1)
            if st.button("Add to the shelf", type="primary"):
                database().adjust_stock(product.id, int(extra))
                st.success(f"{existing} is now "
                           f"{database().get_by_name(existing).quantity}.")
                st.rerun()

    if empty_shop_notice():
        return

    st.markdown("#### What is on the shelf")

    low = [p for p in products if p.is_low_stock]
    if low:
        st.warning("**Running low:** "
                   + ", ".join(f"{p.name} ({p.quantity} left)" for p in low))

    st.dataframe(
        [{
            "Product": p.name,
            "In stock": p.quantity,
            "Unit": p.unit,
            "You pay": format_rand(p.cost_price_cents),
            "You sell": format_rand(p.selling_price_cents),
            "Profit each": format_rand(p.profit_per_unit_cents),
            "Warn below": p.low_stock_threshold,
        } for p in products],
        width="stretch", hide_index=True,
    )


# ====================================================================== INSIGHTS
def page_insights() -> None:
    if empty_shop_notice():
        return

    analytics = AnalyticsService(db=database())

    period_label = st.radio(
        "Show me", ["Today", "This week", "This month"], horizontal=True, index=1)
    period = {"Today": Period.TODAY, "This week": Period.WEEK,
              "This month": Period.MONTH}[period_label]

    report = analytics.report(period)

    if not report.has_data:
        st.info(
            f"**No sales have been recorded for {report.label}.**\n\n"
            "KasiBiz only reports what is actually on record - it will not "
            "estimate. Ring up a sale on the **New Sale** page, then come back."
        )
        low = analytics.restock_list(limit=5)
        if low:
            st.markdown("What I can tell you from your stock levels right now:")
            for product in low:
                st.write(f"- **{product.name}**: {product.quantity} left "
                         f"(warn below {product.low_stock_threshold})")
        return

    st.caption(f"Counted from {report.sale_count} recorded sale(s) over {report.label}.")

    columns = st.columns(4)
    columns[0].metric("Money taken", format_rand(report.revenue_cents))
    columns[1].metric("Gross profit", format_rand(report.profit_cents),
                      f"{report.margin_percent}% of sales")
    columns[2].metric("Sales", report.sale_count)
    columns[3].metric("Items sold", report.units)

    st.divider()
    left, right = st.columns(2, gap="large")

    with left:
        st.markdown("##### Selling best")
        for index, product in enumerate(report.best_sellers(5), 1):
            st.write(f"**{index}. {product.product_name}** - {product.units} sold, "
                     f"{format_rand(product.revenue_cents)}")

    with right:
        st.markdown("##### Moving slowest")
        movers, _ = analytics.slow_movers(period, limit=5)
        for index, mover in enumerate(movers, 1):
            sold = "none sold" if mover.never_sold else f"{mover.units_sold} sold"
            st.write(f"**{index}. {mover.product_name}** - {sold}, "
                     f"{mover.quantity} on the shelf")

    st.divider()
    st.markdown("##### Ask about your figures")
    question = st.text_input(
        "For example: what was my profit this week?",
        placeholder="What is selling well?", label_visibility="collapsed")
    if question:
        answer = InsightsAgent(service=analytics,
                               use_llm=st.session_state.use_ai).answer(question)
        st.markdown(f'<div class="kb-card">{answer.text}</div>'.replace("\n", "<br>"),
                    unsafe_allow_html=True)


# ========================================================================= ROUTE
if st.session_state.pending is not None:
    show_receipt()
else:
    page = st.session_state.page
    if page == "Assistant":
        page_assistant()
    elif page == "New Sale":
        page_new_sale()
    elif page == "Stock":
        page_stock()
    else:
        page_insights()

st.divider()
st.caption(DISCLAIMER)
