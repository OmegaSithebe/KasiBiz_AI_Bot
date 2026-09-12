"""The Marketing Agent: writes WhatsApp adverts, social captions and poster text.

This agent is different from the Stock and Pricing agents, and the difference
matters:

    Stock / Pricing agents  ->  the LLM is a TRANSLATOR.
                                Python decides the answer, the LLM says it nicely.

    Marketing agent         ->  the LLM is a COPYWRITER.
                                Python decides the FACTS and the LIMITS,
                                the LLM genuinely invents the words.

So the creativity is real, but it is fenced in. MarketingService has already
decided the price, the discount and whether there is enough stock. The model
may choose the wording; it may not choose the numbers, and it is never given
an offer the shop cannot honour.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.database.sqlite_db import format_rand
from app.services.marketing_service import (
    Channel,
    MarketingService,
    PromoOffer,
    PromoSafety,
)
from app.utils.config import ConfigError, get_shop_name
from app.utils.llm_client import KasiBizLLM, LLMError

MARKETING_AGENT_PROMPT = (
    "You are the KasiBiz Marketing Helper. You write short adverts for a South "
    "African spaza shop owner to send to customers.\n"
    "\n"
    "LANGUAGE RULE - THIS COMES FIRST AND OVERRIDES EVERYTHING ELSE:\n"
    "Write the advert in the language the owner asked in. If they wrote isiZulu, "
    "write the advert in isiZulu. If Sesotho, write it in Sesotho. Only write in "
    "English if they asked in English. The facts below are always written in "
    "English - that is for you to read, it is NOT the language you must write in.\n"
    "\n"
    "FACT RULE:\n"
    "Use only the prices, savings and stock numbers given to you. Never invent a "
    "price, a discount, a deadline or a product that is not in the facts. Never "
    "promise free delivery, credit, or anything the facts do not mention.\n"
    "\n"
    "STYLE:\n"
    "- Write for real township customers, warm and direct, never corporate.\n"
    "- Follow the format guidance for the channel exactly.\n"
    "- Output ONLY the advert itself. No explanation, no 'Here is your advert'.\n"
    "- Do not use quotation marks around the whole advert."
)


class MarketingIntent(str, Enum):
    WHATSAPP = "whatsapp_advert"
    SOCIAL = "social_caption"
    POSTER = "poster_text"
    ALL_CHANNELS = "all_channels"
    WHAT_TO_PROMOTE = "what_to_promote"
    UNKNOWN = "unknown"


INTENT_KEYWORDS: dict[MarketingIntent, tuple[str, ...]] = {
    MarketingIntent.WHAT_TO_PROMOTE: (
        "what should i promote", "what to promote", "what should i advertise",
        "which product should i", "what special should", "promotion ideas",
        "what must i push", "give me ideas",
    ),
    MarketingIntent.POSTER: (
        "poster", "sign", "window", "cardboard", "print", "board",
        "iphosta", "isibonakaliso",
    ),
    MarketingIntent.SOCIAL: (
        "facebook", "instagram", "social", "caption", "post for", "hashtag", "tiktok",
    ),
    MarketingIntent.WHATSAPP: (
        "whatsapp", "whats app", "status", "broadcast", "group", "message my customers",
        "advert", "advertise", "promo", "promotion", "special",
        "isaziso", "ukumemezela",
    ),
    MarketingIntent.ALL_CHANNELS: (
        "everything", "all channels", "all of them", "full campaign", "campaign",
    ),
}

PERCENT_PATTERN = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*(?:%|percent|per cent)", re.IGNORECASE)

# Matches "2 for R35" and also "2 White Bread for R35", so the product name may
# sit between the quantity and the price. Quantity is capped at two digits so
# that "Coca-Cola 500ml for R18" is not read as a 500-unit bundle.
BUNDLE_PATTERN = re.compile(
    r"\b(\d{1,2})\s*(?:x\s+)?[a-z0-9\s\-.']{0,40}?\bfor\s*r?\s*(\d+(?:[.,]\d{1,2})?)",
    re.IGNORECASE,
)


@dataclass
class MarketingCopy:
    """One finished piece of advertising, plus the facts it was built from."""

    channel: Channel
    text: str
    facts: str
    used_llm: bool
    offer: PromoOffer | None = None
    warning: str = ""

    def __str__(self) -> str:
        return self.text


@dataclass
class MarketingResponse:
    intent: MarketingIntent
    text: str
    facts: str
    used_llm: bool
    pieces: list[MarketingCopy]
    offer: PromoOffer | None = None
    product_name: str | None = None

    def __str__(self) -> str:
        return self.text


class MarketingAgent:
    """Turns a product and an offer into advertising the shop can actually honour."""

    def __init__(
        self,
        service: MarketingService | None = None,
        llm: KasiBizLLM | None = None,
        use_llm: bool = True,
    ) -> None:
        self.service = service or MarketingService(shop_name=get_shop_name())
        self.use_llm = use_llm
        self._llm = llm
        self._llm_ready = llm is not None

    # ------------------------------------------------ 1. UNDERSTAND
    def _find_product_name(self, text: str) -> str | None:
        matches = [p.name for p in self.service.db.list_products() if p.name.lower() in text]
        return max(matches, key=len) if matches else None

    @staticmethod
    def extract_discount(text: str) -> Decimal | None:
        match = PERCENT_PATTERN.search(text)
        return Decimal(match.group(1).replace(",", ".")) if match else None

    @staticmethod
    def extract_bundle(text: str) -> tuple[int, Decimal] | None:
        match = BUNDLE_PATTERN.search(text)
        if not match:
            return None
        return int(match.group(1)), Decimal(match.group(2).replace(",", "."))

    def detect_intent(self, question: str) -> tuple[MarketingIntent, str | None]:
        text = question.lower().strip()
        if not text:
            return MarketingIntent.UNKNOWN, None

        product = self._find_product_name(text)

        for intent in (
            MarketingIntent.WHAT_TO_PROMOTE,
            MarketingIntent.ALL_CHANNELS,
            MarketingIntent.POSTER,
            MarketingIntent.SOCIAL,
            MarketingIntent.WHATSAPP,
        ):
            if any(word in text for word in INTENT_KEYWORDS[intent]):
                return intent, product

        # A bare product name with no channel still means "advertise this".
        if product:
            return MarketingIntent.WHATSAPP, product
        return MarketingIntent.UNKNOWN, None

    # ------------------------------------------------- 2. THE OFFER
    def build_offer_from_question(self, question: str, product_name: str) -> PromoOffer | None:
        text = question.lower()

        bundle = self.extract_bundle(text)
        if bundle:
            units, price = bundle
            return self.service.build_bundle(product_name, units, price)

        discount = self.extract_discount(text)
        if discount is not None:
            return self.service.build_offer(product_name, discount_percent=discount)

        return self.service.suggest_offer(product_name)

    # ---------------------------------------------- 3. WRITE THE COPY
    def _get_llm(self) -> KasiBizLLM | None:
        if not self.use_llm:
            return None
        if not self._llm_ready:
            try:
                self._llm = KasiBizLLM()
            except (ConfigError, LLMError, Exception):
                self._llm = None
            self._llm_ready = True
        return self._llm

    def _template_copy(self, offer: PromoOffer, channel: Channel) -> str:
        """Usable advertising even with no AI at all. Plainer, but it still sells."""
        shop = self.service.shop_name
        price = format_rand(offer.promo_price_cents)

        if channel is Channel.POSTER:
            lines = ["SPECIAL!" if offer.is_discounted else "TODAY", "",
                     offer.name.upper(), "", price]
            if offer.is_discounted:
                lines += [f"(was {format_rand(offer.normal_price_cents)})"]
            lines += ["", "WHILE STOCKS LAST", shop.upper()]
            return "\n".join(lines)

        if channel is Channel.SOCIAL:
            headline = (f"{offer.name} is on special at {price}!"
                        if offer.is_discounted else f"{offer.name} in stock at {price}.")
            body = (f"Save {format_rand(offer.saving_cents)} - "
                    f"that's {offer.discount_percent}% off."
                    if offer.is_discounted else "Come get yours while stock lasts.")
            return (f"{headline}\n{body}\nOnly at {shop}. "
                    f"{offer.product.quantity} available.\n"
                    f"#Spaza #Kasi #Specials #{shop.replace(' ', '')}")

        if offer.offer_type.value == "bundle":
            return (f"*{offer.units_in_offer} {offer.name} for {price}!*\n"
                    f"Normally {format_rand(offer.normal_price_cents)} - "
                    f"you save {format_rand(offer.saving_cents)}.\n"
                    f"Come to {shop} today.")

        if offer.is_discounted:
            return (f"*{offer.name} - now {price}*\n"
                    f"Was {format_rand(offer.normal_price_cents)}, "
                    f"save {format_rand(offer.saving_cents)}!\n"
                    f"Only {offer.product.quantity} left at {shop}.")

        return (f"*{offer.name} - {price}*\n"
                f"In stock now at {shop}.\nCome and get yours.")

    def write_copy(self, question: str, offer: PromoOffer, channel: Channel,
                   occasion: str | None = None) -> MarketingCopy:
        facts = self.service.campaign_brief(offer, channel, occasion)
        fallback = self._template_copy(offer, channel)

        llm = self._get_llm()
        if llm is None:
            return MarketingCopy(channel, fallback, facts, False, offer,
                                 offer.safety.warning)

        prompt = (
            f"The shop owner asked: {question}\n\n"
            f"CAMPAIGN FACTS (use these numbers exactly, invent nothing):\n{facts}\n\n"
            f"Write the {channel.value} now."
        )
        try:
            reply = llm.ask(prompt, system_prompt=MARKETING_AGENT_PROMPT,
                            temperature=0.85, max_tokens=300)
        except LLMError:
            return MarketingCopy(channel, fallback, facts, False, offer,
                                 offer.safety.warning)

        text = reply.strip().strip('"') or fallback
        return MarketingCopy(channel, text, facts, bool(reply.strip()), offer,
                             offer.safety.warning)

    # ------------------------------------------------------- public
    def what_to_promote(self, limit: int = 5) -> str:
        candidates = self.service.suggest_products_to_promote(limit)
        if not candidates:
            return (
                "Nothing is ready for a promotion right now. Every product is either "
                "running low or not making enough profit to discount safely."
            )

        lines = ["Best products to promote right now:", ""]
        for i, c in enumerate(candidates, start=1):
            offer = self.service.suggest_offer(c.name)
            line = f"  {i}. {c.name} - {c.reason}"
            if offer and offer.is_discounted:
                line += (f"\n     Suggested offer: {offer.discount_percent}% off at "
                         f"{format_rand(offer.promo_price_cents)}, "
                         f"still {format_rand(offer.profit_cents)} profit each")
            lines.append(line)
        return "\n".join(lines)

    def answer(self, question: str) -> MarketingResponse:
        intent, product_name = self.detect_intent(question)

        if intent is MarketingIntent.WHAT_TO_PROMOTE:
            facts = self.what_to_promote()
            return MarketingResponse(intent, facts, facts, False, [], None, None)

        if intent is MarketingIntent.UNKNOWN or product_name is None:
            help_text = (
                "Tell me which product to advertise. Try:\n"
                "  - Write a WhatsApp advert for White Bread\n"
                "  - Make a poster for Coca-Cola 500ml with 10% off\n"
                "  - Facebook caption for Simba Chips 36g\n"
                "  - 2 White Bread for R35 - write an advert\n"
                "  - What should I promote this week?"
            )
            return MarketingResponse(MarketingIntent.UNKNOWN, help_text, help_text,
                                     False, [], None, product_name)

        offer = self.build_offer_from_question(question, product_name)
        if offer is None:
            msg = f"The shop does not stock anything called '{product_name}'."
            return MarketingResponse(intent, msg, msg, False, [], None, product_name)

        if offer.safety.blocks_campaign:
            msg = (f"{offer.as_summary()}\n\n"
                   f"I have not written the advert. {offer.safety.warning}")
            return MarketingResponse(intent, msg, offer.as_facts(), False, [],
                                     offer, product_name)

        channels = (
            [Channel.WHATSAPP, Channel.SOCIAL, Channel.POSTER]
            if intent is MarketingIntent.ALL_CHANNELS
            else [{
                MarketingIntent.WHATSAPP: Channel.WHATSAPP,
                MarketingIntent.SOCIAL: Channel.SOCIAL,
                MarketingIntent.POSTER: Channel.POSTER,
            }[intent]]
        )

        pieces = [self.write_copy(question, offer, channel) for channel in channels]
        text = "\n\n".join(
            (f"--- {p.channel.value} ---\n{p.text}" if len(pieces) > 1 else p.text)
            for p in pieces
        )

        return MarketingResponse(
            intent=intent,
            text=text,
            facts=pieces[0].facts,
            used_llm=any(p.used_llm for p in pieces),
            pieces=pieces,
            offer=offer,
            product_name=product_name,
        )
