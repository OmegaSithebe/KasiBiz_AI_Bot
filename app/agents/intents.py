"""The single source of truth for what a shop owner's words mean.

Before this module there were two separate keyword lists. The Coordinator kept
ROUTE_PATTERNS to decide WHICH specialist answers, and every specialist kept its
own INTENT_KEYWORDS to decide WHAT that specialist should do. Those are two
genuinely different jobs, but they shared vocabulary that had to be typed out
twice - and forgetting the second copy did not raise an error. It quietly sent
the question to the wrong place. That cost us three bugs (Days 13, 14 and 15).

Now there is one table. Both layers are derived from it:

    VOCABULARY  ->  router_patterns()   which specialist answers
                ->  agent_keywords()    what that specialist does

A phrase is written once. If it should route but not select a sub-task, leave
`intent` as None. If it should select a sub-task but is too common to route on,
set `weight=0`. Either way the gap is visible on the line itself instead of
being invisible across two files.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# A route needs at least this much evidence before we trust it.
MIN_SCORE_TO_ROUTE = 2

# Score at which the evidence is strong on its own. One weight-4 phrase such as
# "what should i charge" is enough; a single weight-2 word is not.
STRONG_SCORE = 4

# If the best and second-best scores are this close, the question is ambiguous.
AMBIGUITY_MARGIN = 1

# Weight given to a phrase that must never influence routing on its own.
NEVER_ROUTES = 0


class Route(str, Enum):
    STOCK = "stock"
    SALES = "sales"
    PRICING = "pricing"
    MARKETING = "marketing"
    ADVICE = "advice"
    INSIGHTS = "insights"
    GREETING = "greeting"
    HELP = "help"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    UNKNOWN = "unknown"

    @property
    def specialist(self) -> str:
        return _SPECIALISTS[self.value]

    @property
    def is_specialist(self) -> bool:
        """True for routes that hand off to an agent rather than being answered inline."""
        return self in _SPECIALIST_ROUTES


_SPECIALISTS: dict[str, str] = {
    "stock": "Stock Agent",
    "sales": "Sales Agent",
    "pricing": "Pricing Helper",
    "marketing": "Marketing Agent",
    "advice": "Business Advisor",
    "insights": "Insights Agent",
    "greeting": "Coordinator",
    "help": "Coordinator",
    "confirm": "Coordinator",
    "cancel": "Coordinator",
    "unknown": "Coordinator",
}

_SPECIALIST_ROUTES = frozenset({
    Route.STOCK, Route.SALES, Route.PRICING,
    Route.MARKETING, Route.ADVICE, Route.INSIGHTS,
})


# ---------------------------------------------------------------- sub-intents
# String values, so each specialist can keep its own typed Enum without this
# module having to import any of them.
class StockIntent(str, Enum):
    LOW_STOCK = "low_stock"
    REORDER = "reorder"
    CHECK_PRODUCT = "check_product"
    SUMMARY = "summary"
    UNKNOWN = "unknown"


class SalesIntent(str, Enum):
    START_SALE = "start_sale"
    ADD_ITEM = "add_item"
    REMOVE_ITEM = "remove_item"
    PAYMENT = "payment"
    SHOW_BASKET = "show_basket"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    UNKNOWN = "unknown"


class InsightIntent(str, Enum):
    BEST_SELLERS = "best_sellers"
    SLOW_MOVERS = "slow_movers"
    LOW_STOCK = "low_stock"
    SALES_TOTAL = "sales_total"
    PROFIT = "profit"
    COMPARE = "compare"
    OVERVIEW = "overview"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Phrase:
    """One thing an owner might say, and what it means at both layers."""

    text: str
    route: Route
    intent: str | None = None
    weight: int = 3

    @property
    def routes(self) -> bool:
        return self.weight > NEVER_ROUTES


def _p(text: str, route: Route, intent=None, weight: int = 3) -> Phrase:
    return Phrase(text, route, getattr(intent, "value", intent), weight)


S, SA, P, M, A, I = (Route.STOCK, Route.SALES, Route.PRICING,
                     Route.MARKETING, Route.ADVICE, Route.INSIGHTS)

VOCABULARY: tuple[Phrase, ...] = (
    # ------------------------------------------------------------- STOCK
    _p("what is low", S, StockIntent.LOW_STOCK, 4),
    _p("running low", S, StockIntent.LOW_STOCK, 4),
    _p("running out", S, StockIntent.LOW_STOCK, 4),
    _p("low in stock", S, StockIntent.LOW_STOCK, 4),
    _p("out of stock", S, StockIntent.LOW_STOCK, 4),
    _p("do i have enough", S, StockIntent.CHECK_PRODUCT, 4),
    _p("how many.* left", S, None, 4),
    _p("what should i reorder", S, StockIntent.REORDER, 4),
    _p("how is my stock", S, StockIntent.SUMMARY, 4),
    _p("shopping list", S, StockIntent.REORDER, 3),
    _p("stock take", S, StockIntent.SUMMARY, 3),
    _p("in stock", S, None, 3),
    _p("reorder", S, StockIntent.REORDER, 3),
    _p("restock", S, StockIntent.REORDER, 3),
    _p("stock level", S, None, 3),
    _p("stock report", S, StockIntent.SUMMARY, 3),
    _p("stock", S, None, 2),
    _p("shelf", S, None, 2),
    _p("supplier", S, StockIntent.REORDER, 2),
    _p("delivery", S, None, 2),
    # Stock vocabulary too common to route on, but still meaningful to the agent.
    _p("re-order", S, StockIntent.REORDER, NEVER_ROUTES),
    _p("re-stock", S, StockIntent.REORDER, NEVER_ROUTES),
    _p("order", S, StockIntent.REORDER, NEVER_ROUTES),
    _p("buy more", S, StockIntent.REORDER, NEVER_ROUTES),
    _p("must i buy", S, StockIntent.REORDER, NEVER_ROUTES),
    _p("should i buy", S, StockIntent.REORDER, NEVER_ROUTES),
    _p("low", S, StockIntent.LOW_STOCK, NEVER_ROUTES),
    _p("run out", S, StockIntent.LOW_STOCK, NEVER_ROUTES),
    _p("finished", S, StockIntent.LOW_STOCK, NEVER_ROUTES),
    _p("finish", S, StockIntent.LOW_STOCK, NEVER_ROUTES),
    _p("almost out", S, StockIntent.LOW_STOCK, NEVER_ROUTES),
    _p("nearly out", S, StockIntent.LOW_STOCK, NEVER_ROUTES),
    _p("short", S, StockIntent.LOW_STOCK, NEVER_ROUTES),
    _p("empty", S, StockIntent.LOW_STOCK, NEVER_ROUTES),
    _p("summary", S, StockIntent.SUMMARY, NEVER_ROUTES),
    _p("overview", S, StockIntent.SUMMARY, NEVER_ROUTES),
    _p("how is the stock", S, StockIntent.SUMMARY, NEVER_ROUTES),
    _p("everything", S, StockIntent.SUMMARY, NEVER_ROUTES),
    _p("how much stock", S, StockIntent.SUMMARY, NEVER_ROUTES),
    _p("total stock", S, StockIntent.SUMMARY, NEVER_ROUTES),
    # isiZulu / isiXhosa / Sesotho / Setswana / Afrikaans
    _p("phelile", S, StockIntent.LOW_STOCK, 3),
    _p("kuphelile", S, StockIntent.LOW_STOCK, 3),
    _p("iphelile", S, StockIntent.LOW_STOCK, 3),
    _p("fedile", S, StockIntent.LOW_STOCK, 3),
    _p("ndinayo", S, None, 3),
    _p("voorraad", S, None, 4),
    _p("raak op", S, StockIntent.LOW_STOCK, 4),
    _p("min voorraad", S, StockIntent.LOW_STOCK, 4),
    _p("sekuphelile", S, StockIntent.LOW_STOCK, NEVER_ROUTES),
    _p("kancane", S, StockIntent.LOW_STOCK, NEVER_ROUTES),
    _p("se felile", S, StockIntent.LOW_STOCK, NEVER_ROUTES),
    _p("haufi le ho fela", S, StockIntent.LOW_STOCK, NEVER_ROUTES),
    _p("sele iphelile", S, StockIntent.LOW_STOCK, NEVER_ROUTES),
    _p("op raak", S, StockIntent.LOW_STOCK, NEVER_ROUTES),
    _p("thenga", S, StockIntent.REORDER, NEVER_ROUTES),
    _p("ngithenge", S, StockIntent.REORDER, NEVER_ROUTES),
    _p("kufanele ngithenge", S, StockIntent.REORDER, NEVER_ROUTES),
    _p("reka", S, StockIntent.REORDER, NEVER_ROUTES),
    _p("ke reke", S, StockIntent.REORDER, NEVER_ROUTES),
    _p("ke lokela ho reka", S, StockIntent.REORDER, NEVER_ROUTES),
    _p("isitoko sami", S, StockIntent.SUMMARY, NEVER_ROUTES),
    _p("impahla", S, StockIntent.SUMMARY, NEVER_ROUTES),
    _p("setoko", S, StockIntent.SUMMARY, NEVER_ROUTES),
    _p("thepa", S, StockIntent.SUMMARY, NEVER_ROUTES),
    _p("hoeveel voorraad", S, StockIntent.SUMMARY, NEVER_ROUTES),
    _p("voorraad het ek", S, StockIntent.SUMMARY, NEVER_ROUTES),

    # ------------------------------------------------------------- SALES
    _p("new sale", SA, SalesIntent.START_SALE, 4),
    _p("start a sale", SA, SalesIntent.START_SALE, 4),
    _p("record a sale", SA, SalesIntent.START_SALE, 4),
    _p("make a sale", SA, SalesIntent.START_SALE, 4),
    _p("serve a customer", SA, SalesIntent.START_SALE, 4),
    _p("ring up", SA, SalesIntent.START_SALE, 4),
    _p("customer wants", SA, SalesIntent.ADD_ITEM, 4),
    _p("customer is buying", SA, SalesIntent.ADD_ITEM, 4),
    _p("customer bought", SA, SalesIntent.ADD_ITEM, 4),
    _p("i sold", SA, SalesIntent.ADD_ITEM, 4),
    _p("just sold", SA, SalesIntent.ADD_ITEM, 4),
    _p("sell them", SA, SalesIntent.ADD_ITEM, 4),
    _p("add another", SA, SalesIntent.ADD_ITEM, 4),
    _p("add to the basket", SA, SalesIntent.ADD_ITEM, 4),
    _p("the basket", SA, SalesIntent.SHOW_BASKET, 4),
    _p("basket", SA, SalesIntent.SHOW_BASKET, 3),
    _p("how much change", SA, SalesIntent.PAYMENT, 4),
    _p("their change", SA, SalesIntent.PAYMENT, 4),
    _p("give change", SA, SalesIntent.PAYMENT, 4),
    _p("change for", SA, SalesIntent.PAYMENT, 4),
    _p("customer paid", SA, SalesIntent.PAYMENT, 4),
    _p("he paid", SA, SalesIntent.PAYMENT, 4),
    _p("she paid", SA, SalesIntent.PAYMENT, 4),
    _p("they paid", SA, SalesIntent.PAYMENT, 4),
    _p("paid me", SA, SalesIntent.PAYMENT, 4),
    _p("paid with", SA, SalesIntent.PAYMENT, 4),
    _p("pays with", SA, SalesIntent.PAYMENT, 4),
    _p("what is the total", SA, SalesIntent.SHOW_BASKET, 4),
    _p("what do they owe", SA, SalesIntent.SHOW_BASKET, 4),
    _p("checkout", SA, SalesIntent.SHOW_BASKET, 4),
    _p("till", SA, None, 2),
    _p("remove", SA, SalesIntent.REMOVE_ITEM, NEVER_ROUTES),
    _p("take off", SA, SalesIntent.REMOVE_ITEM, NEVER_ROUTES),
    _p("take out", SA, SalesIntent.REMOVE_ITEM, NEVER_ROUTES),
    _p("paid", SA, SalesIntent.PAYMENT, NEVER_ROUTES),
    _p("tendered", SA, SalesIntent.PAYMENT, NEVER_ROUTES),
    # A bare verb stem for "sell" cannot route: isiZulu "-thengis-" and Afrikaans
    # "verkoop" mean both "sell this" (a sale) and "sell it for how much"
    # (a pricing question). Only the past tense is unambiguous.
    _p("thengisa", SA, SalesIntent.ADD_ITEM, NEVER_ROUTES),
    _p("verkoop", SA, SalesIntent.ADD_ITEM, NEVER_ROUTES),
    _p("ngithengisile", SA, SalesIntent.ADD_ITEM, 3),
    _p("uthenge", SA, SalesIntent.ADD_ITEM, 3),
    _p("rekisitse", SA, SalesIntent.ADD_ITEM, 3),
    _p("kleingeld", SA, SalesIntent.PAYMENT, 4),

    # ----------------------------------------------------------- PRICING
    _p("what should i charge", P, "suggest_price", 4),
    _p("what should i sell", P, "suggest_price", 4),
    _p("how much should i", P, "suggest_price", 4),
    _p("am i making profit", P, "check_price", 4),
    _p("making enough profit", P, "check_price", 4),
    _p("check my prices", P, "review_all", 4),
    _p("are my prices", P, "review_all", 4),
    _p("markup", P, None, 4),
    _p("margin", P, None, 4),
    _p("underpriced", P, "review_all", 4),
    _p("what if i sell", P, "what_if", 4),
    _p("what if i charge", P, "what_if", 4),
    _p("if i sell", P, "what_if", 4),
    _p("if i charge", P, "what_if", 4),
    _p("should i raise the price", P, "what_if", 4),
    _p("raise the price", P, "what_if", 4),
    _p("how much does it cost", P, None, 4),
    _p("what does it cost", P, None, 4),
    _p("what price", P, "suggest_price", 3),
    _p("selling price", P, None, 3),
    _p("cost price", P, None, 3),
    _p("mark up", P, None, 3),
    _p("cost me", P, None, 3),
    _p("too cheap", P, "review_all", 3),
    _p("too expensive", P, None, 3),
    _p("losing money", P, "review_all", 3),
    _p("price", P, None, 2),
    _p("profit", P, None, 2),
    _p("charge", P, None, 2),
    _p("what is markup", P, "explain_concept", NEVER_ROUTES),
    _p("what is a markup", P, "explain_concept", NEVER_ROUTES),
    _p("what is margin", P, "explain_concept", NEVER_ROUTES),
    _p("what's margin", P, "explain_concept", NEVER_ROUTES),
    _p("difference between markup", P, "explain_concept", NEVER_ROUTES),
    _p("markup vs margin", P, "explain_concept", NEVER_ROUTES),
    _p("markup or margin", P, "explain_concept", NEVER_ROUTES),
    _p("explain markup", P, "explain_concept", NEVER_ROUTES),
    _p("explain margin", P, "explain_concept", NEVER_ROUTES),
    _p("how does pricing work", P, "explain_concept", NEVER_ROUTES),
    _p("what does margin mean", P, "explain_concept", NEVER_ROUTES),
    _p("what does markup mean", P, "explain_concept", NEVER_ROUTES),
    _p("what if", P, "what_if", NEVER_ROUTES),
    _p("should i raise", P, "what_if", NEVER_ROUTES),
    _p("should i increase", P, "what_if", NEVER_ROUTES),
    _p("should i drop", P, "what_if", NEVER_ROUTES),
    _p("should i lower", P, "what_if", NEVER_ROUTES),
    _p("instead of", P, "what_if", NEVER_ROUTES),
    _p("my prices", P, "review_all", NEVER_ROUTES),
    _p("all my prices", P, "review_all", NEVER_ROUTES),
    _p("price review", P, "review_all", NEVER_ROUTES),
    _p("under priced", P, "review_all", NEVER_ROUTES),
    _p("which products", P, "review_all", NEVER_ROUTES),
    _p("am i charging enough", P, "review_all", NEVER_ROUTES),
    _p("suggest a price", P, "suggest_price", NEVER_ROUTES),
    _p("price for", P, "suggest_price", NEVER_ROUTES),
    _p("sell it for", P, "suggest_price", NEVER_ROUTES),
    _p("i buy", P, "suggest_price", NEVER_ROUTES),
    _p("i pay", P, "suggest_price", NEVER_ROUTES),
    _p("costs me", P, "suggest_price", NEVER_ROUTES),
    _p("bought it for", P, "suggest_price", NEVER_ROUTES),
    _p("making profit", P, "check_price", NEVER_ROUTES),
    _p("how much profit", P, "check_price", NEVER_ROUTES),
    _p("am i making money", P, "check_price", NEVER_ROUTES),
    _p("is my price", P, "check_price", NEVER_ROUTES),
    _p("good price", P, "check_price", NEVER_ROUTES),
    _p("right price", P, "check_price", NEVER_ROUTES),
    _p("enough profit", P, "check_price", NEVER_ROUTES),
    _p("ngamalini", P, "suggest_price", 3),
    _p("inzuzo", P, "check_price", 3),
    _p("theko", P, "suggest_price", 3),
    _p("phaello", P, "check_price", 3),
    _p("ixabiso", P, None, 3),
    _p("ndifumana", P, None, 3),
    _p("prys", P, None, 4),
    _p("wins", P, None, 4),
    _p("hoeveel moet ek vra", P, "suggest_price", 4),
    _p("tlhwatlhwa", P, None, 3),
    _p("poelo", P, None, 3),
    _p("amanani", P, "review_all", NEVER_ROUTES),
    _p("ditheko", P, "review_all", NEVER_ROUTES),
    _p("ngithengise ngamalini", P, "suggest_price", NEVER_ROUTES),
    _p("ngingayithengisa", P, "suggest_price", NEVER_ROUTES),
    _p("malini", P, "suggest_price", NEVER_ROUTES),
    _p("ke rekise ka bokae", P, "suggest_price", NEVER_ROUTES),
    _p("ngenza inzuzo", P, "check_price", NEVER_ROUTES),

    # --------------------------------------------------------- MARKETING
    _p("whatsapp advert", M, "whatsapp_advert", 4),
    _p("write.* advert", M, None, 4),
    _p("social media", M, "social_caption", 4),
    _p("facebook", M, "social_caption", 4),
    _p("instagram", M, "social_caption", 4),
    _p("poster", M, "poster_text", 4),
    _p("caption", M, "social_caption", 4),
    _p("what should i promote", M, "what_to_promote", 4),
    _p("what should i advertise", M, "what_to_promote", 4),
    _p("advert", M, "whatsapp_advert", 3),
    _p("advertise", M, "whatsapp_advert", 3),
    _p("promotion", M, "whatsapp_advert", 3),
    _p("promote", M, None, 3),
    _p("special", M, "whatsapp_advert", 3),
    _p("campaign", M, "all_channels", 3),
    _p("discount", M, None, 3),
    _p("% off", M, None, 3),
    _p("customers know", M, None, 3),
    _p("tell my customers", M, None, 3),
    _p("what to promote", M, "what_to_promote", NEVER_ROUTES),
    _p("which product should i", M, "what_to_promote", NEVER_ROUTES),
    _p("what special should", M, "what_to_promote", NEVER_ROUTES),
    _p("promotion ideas", M, "what_to_promote", NEVER_ROUTES),
    _p("what must i push", M, "what_to_promote", NEVER_ROUTES),
    _p("give me ideas", M, "what_to_promote", NEVER_ROUTES),
    _p("sign", M, "poster_text", NEVER_ROUTES),
    _p("window", M, "poster_text", NEVER_ROUTES),
    _p("cardboard", M, "poster_text", NEVER_ROUTES),
    _p("print", M, "poster_text", NEVER_ROUTES),
    _p("board", M, "poster_text", NEVER_ROUTES),
    _p("social", M, "social_caption", NEVER_ROUTES),
    _p("post for", M, "social_caption", NEVER_ROUTES),
    _p("hashtag", M, "social_caption", NEVER_ROUTES),
    _p("tiktok", M, "social_caption", NEVER_ROUTES),
    _p("whatsapp", M, "whatsapp_advert", NEVER_ROUTES),
    _p("whats app", M, "whatsapp_advert", NEVER_ROUTES),
    _p("status", M, "whatsapp_advert", NEVER_ROUTES),
    _p("broadcast", M, "whatsapp_advert", NEVER_ROUTES),
    _p("group", M, "whatsapp_advert", NEVER_ROUTES),
    _p("message my customers", M, "whatsapp_advert", NEVER_ROUTES),
    _p("promo", M, "whatsapp_advert", NEVER_ROUTES),
    _p("all channels", M, "all_channels", NEVER_ROUTES),
    _p("all of them", M, "all_channels", NEVER_ROUTES),
    _p("full campaign", M, "all_channels", NEVER_ROUTES),
    _p("everything", M, "all_channels", NEVER_ROUTES),
    _p("isaziso", M, "whatsapp_advert", 3),
    _p("intengiso", M, None, 3),
    _p("ukumemezela", M, "whatsapp_advert", NEVER_ROUTES),
    _p("iphosta", M, "poster_text", NEVER_ROUTES),
    _p("isibonakaliso", M, "poster_text", NEVER_ROUTES),
    _p("advertensie", M, "whatsapp_advert", 4),
    _p("plakkaat", M, "poster_text", 4),
    _p("papatso", M, None, 3),

    # ------------------------------------------------------------ ADVICE
    _p("how do i register", A, None, 4),
    _p("register my business", A, None, 4),
    _p("register a company", A, None, 4),
    _p("annual return", A, None, 4),
    _p("beneficial ownership", A, None, 4),
    _p("deregistration", A, None, 4),
    _p("company registration", A, None, 4),
    _p("food safety", A, None, 4),
    _p("what records", A, None, 4),
    _p("cipc", A, None, 4),
    _p("sars", A, None, 4),
    _p("bizportal", A, None, 4),
    _p("vat", A, None, 4),
    _p("tax", A, None, 3),
    _p("register", A, None, 3),
    _p("compliance", A, None, 3),
    _p("director", A, None, 3),
    _p("pty", A, None, 3),
    _p("legal", A, None, 3),
    _p("licence", A, None, 3),
    _p("license", A, None, 3),
    _p("permit", A, None, 3),
    _p("regulation", A, None, 3),
    _p("receipts", A, None, 2),
    _p("bhalisa", A, None, 3),
    _p("intela", A, None, 3),
    _p("lekgetho", A, None, 3),
    _p("ukubhalisa", A, None, 3),
    _p("irhafu", A, None, 3),
    _p("registreer", A, None, 4),
    _p("belasting", A, None, 4),

    # ---------------------------------------------------------- INSIGHTS
    _p("selling well", I, InsightIntent.BEST_SELLERS, 4),
    _p("best seller", I, InsightIntent.BEST_SELLERS, 4),
    _p("best selling", I, InsightIntent.BEST_SELLERS, 4),
    _p("top selling", I, InsightIntent.BEST_SELLERS, 4),
    _p("what sells", I, InsightIntent.BEST_SELLERS, 4),
    _p("what sold", I, InsightIntent.BEST_SELLERS, 4),
    _p("most popular", I, InsightIntent.BEST_SELLERS, 4),
    _p("slow moving", I, InsightIntent.SLOW_MOVERS, 4),
    _p("slow movers", I, InsightIntent.SLOW_MOVERS, 4),
    _p("not selling", I, InsightIntent.SLOW_MOVERS, 4),
    _p("moving slowly", I, InsightIntent.SLOW_MOVERS, 4),
    _p("sitting on the shelf", I, InsightIntent.SLOW_MOVERS, 4),
    _p("how much did i make", I, InsightIntent.SALES_TOTAL, 4),
    _p("how much did i sell", I, InsightIntent.SALES_TOTAL, 4),
    _p("did i take", I, InsightIntent.SALES_TOTAL, 4),
    _p("money did i take", I, InsightIntent.SALES_TOTAL, 4),
    _p("sales today", I, InsightIntent.SALES_TOTAL, 4),
    _p("sales this week", I, InsightIntent.SALES_TOTAL, 4),
    _p("total sales", I, InsightIntent.SALES_TOTAL, 4),
    _p("my sales", I, InsightIntent.SALES_TOTAL, 4),
    _p("takings", I, InsightIntent.SALES_TOTAL, 4),
    _p("turnover", I, InsightIntent.SALES_TOTAL, 4),
    _p("revenue", I, InsightIntent.SALES_TOTAL, 4),
    _p("gross profit", I, InsightIntent.PROFIT, 4),
    _p("how much profit did", I, InsightIntent.PROFIT, 4),
    _p("profit did i make", I, InsightIntent.PROFIT, 4),
    _p("profit this week", I, InsightIntent.PROFIT, 4),
    _p("profit today", I, InsightIntent.PROFIT, 4),
    _p("how is business", I, InsightIntent.OVERVIEW, 4),
    _p("how was today", I, InsightIntent.OVERVIEW, 4),
    _p("business report", I, InsightIntent.OVERVIEW, 4),
    _p("sales report", I, InsightIntent.OVERVIEW, 4),
    _p("how is the shop doing", I, InsightIntent.OVERVIEW, 4),
    _p("insights", I, InsightIntent.OVERVIEW, 4),
    _p("compared to", I, InsightIntent.COMPARE, 4),
    _p("compare", I, InsightIntent.COMPARE, 3),
    _p("better than last", I, InsightIntent.COMPARE, 4),
    _p("worse than last", I, InsightIntent.COMPARE, 4),
    # "What needs restocking" belongs to the Stock Agent, which reads the shelf
    # directly. Kept here only so the Insights Agent understands it if asked.
    _p("what needs restocking", I, InsightIntent.LOW_STOCK, NEVER_ROUTES),
    _p("needs restocking", I, InsightIntent.LOW_STOCK, NEVER_ROUTES),
    _p("dayisa", I, InsightIntent.BEST_SELLERS, NEVER_ROUTES),
    _p("verkope", I, InsightIntent.SALES_TOTAL, 4),
    _p("besigheid", I, InsightIntent.OVERVIEW, 3),

    # ---------------------------------------------------------- GREETING
    _p("good morning", Route.GREETING, None, 4),
    _p("good afternoon", Route.GREETING, None, 4),
    _p("good evening", Route.GREETING, None, 4),
    _p("sawubona", Route.GREETING, None, 4),
    _p("molo", Route.GREETING, None, 4),
    _p("dumela", Route.GREETING, None, 4),
    _p("sanibonani", Route.GREETING, None, 4),
    _p("molweni", Route.GREETING, None, 4),
    _p("goeie more", Route.GREETING, None, 4),
    _p("goeiemore", Route.GREETING, None, 4),
    _p("hallo", Route.GREETING, None, 4),
    _p("hello", Route.GREETING, None, 3),
    _p("hi there", Route.GREETING, None, 3),
    _p("hey", Route.GREETING, None, 3),
    _p("howzit", Route.GREETING, None, 3),

    # -------------------------------------------------------------- HELP
    _p("what can you do", Route.HELP, None, 4),
    _p("what can you help", Route.HELP, None, 4),
    _p("how do you work", Route.HELP, None, 4),
    _p("what do you do", Route.HELP, None, 4),
    _p("who are you", Route.HELP, None, 4),
    _p("help me", Route.HELP, None, 3),
    _p("ungangisiza", Route.HELP, None, 3),
    _p("ungenzani", Route.HELP, None, 3),
    _p("ungandinceda", Route.HELP, None, 3),
    _p("wat kan jy doen", Route.HELP, None, 4),
    _p("wie is jy", Route.HELP, None, 4),
)


# ----------------------------------------------------------- derived views
def router_patterns() -> dict[Route, tuple[tuple[str, int], ...]]:
    """Layer 1: which specialist answers. Only phrases with a weight."""
    grouped: dict[Route, list[tuple[str, int]]] = {}
    for phrase in VOCABULARY:
        if phrase.routes:
            grouped.setdefault(phrase.route, []).append((phrase.text, phrase.weight))
    return {route: tuple(items) for route, items in grouped.items()}


def agent_keywords(route: Route) -> dict[str, tuple[str, ...]]:
    """Layer 2: what that specialist should do. Only phrases with a sub-intent."""
    grouped: dict[str, list[str]] = {}
    for phrase in VOCABULARY:
        if phrase.route is route and phrase.intent:
            grouped.setdefault(phrase.intent, []).append(phrase.text)
    return {intent: tuple(items) for intent, items in grouped.items()}


def keywords_for(route: Route, enum_cls) -> dict:
    """agent_keywords() keyed by a specialist's own Enum, total over its members."""
    raw = agent_keywords(route)
    return {member: tuple(raw.get(member.value, ())) for member in enum_cls}


# ------------------------------------------------- conversational control
CONFIRM_WORDS: tuple[str, ...] = (
    "yes", "yebo", "ja", "ewe", "ee", "confirm", "confirmed", "correct",
    "that's right", "thats right", "save it", "save the sale", "done",
    "go ahead", "proceed", "ok", "okay", "sharp", "kulungile", "ho lokile",
)

CANCEL_WORDS: tuple[str, ...] = (
    "cancel", "cancel it", "no", "cha", "nee", "hayi", "stop", "forget it",
    "forget about it", "never mind", "nevermind", "start over", "start again",
    "scrap it", "clear the basket", "go back", "undo", "tlohela", "yeka",
)


def _word_hit(text: str, words: tuple[str, ...]) -> bool:
    import re
    cleaned = re.sub(r"[^\w\s']", " ", text.lower()).strip()
    padded = f" {re.sub(r'[ ]+', ' ', cleaned)} "
    return any(f" {word} " in padded for word in words)


def is_confirmation(text: str) -> bool:
    """True for a plain yes. Deliberately strict - it commits money to the books."""
    return _word_hit(text, CONFIRM_WORDS) and not _word_hit(text, CANCEL_WORDS)


def is_cancellation(text: str) -> bool:
    return _word_hit(text, CANCEL_WORDS)


ROUTE_PATTERNS = router_patterns()
