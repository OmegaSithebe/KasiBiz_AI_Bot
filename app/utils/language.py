"""Day 13 - working out which language the shop owner is speaking.

Until today KasiBiz relied entirely on an instruction in the prompt: "reply in
the same language the owner used". That is a request, not a guarantee, and it
already failed once on Day 8 when an isiZulu question came back in English.

This module makes the decision in Python, before the model is ever called, so:

    1. We can TELL the model which language to use, by name.
    2. Fixed replies (greetings, help text, refusals) can be translated without
       any AI at all - which matters most when the AI is unavailable.
    3. The choice is testable and explainable.

HONEST WARNING: the word lists below were assembled by a non-native speaker.
isiZulu and isiXhosa are closely related, as are Sesotho and Setswana, so
confusion between those pairs is expected. This remains open issue M9 and needs
a native-speaker review before any pilot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Language(str, Enum):
    ENGLISH = "en"
    ZULU = "zu"
    XHOSA = "xh"
    AFRIKAANS = "af"
    SOTHO = "st"
    TSWANA = "tn"

    @property
    def english_name(self) -> str:
        return {
            "en": "English", "zu": "isiZulu", "xh": "isiXhosa",
            "af": "Afrikaans", "st": "Sesotho", "tn": "Setswana",
        }[self.value]

    @property
    def native_name(self) -> str:
        return {
            "en": "English", "zu": "isiZulu", "xh": "isiXhosa",
            "af": "Afrikaans", "st": "Sesotho", "tn": "Setswana",
        }[self.value]


# (word, weight). Weight 3 means the word is distinctive enough to decide on its
# own; weight 1 means it is shared with a related language.
LANGUAGE_MARKERS: dict[Language, tuple[tuple[str, int], ...]] = {
    Language.ZULU: (
        ("sawubona", 3), ("sanibonani", 3), ("ngiyabonga", 3), ("yebo", 3),
        ("yini", 3), ("ngamalini", 3), ("kanjani", 3), ("ngicela", 3),
        ("ngingakwazi", 3), ("ngingayithengisa", 3), ("ngenzele", 3),
        ("isitolo", 3), ("impahla", 3), ("izimpahla", 3), ("inzuzo", 3),
        ("ngithenge", 3), ("ngithengise", 3), ("kuphelile", 3), ("esiphelile", 3),
        ("ngi", 1), ("uku", 1), ("phelile", 2), ("thenga", 2), ("thengisa", 2),
        ("imali", 2), ("malini", 2), ("kusele", 2), ("isaziso", 2), ("ukudla", 2),
    ),
    Language.XHOSA: (
        ("molo", 3), ("molweni", 3), ("enkosi", 3), ("yintoni", 3),
        ("ndicela", 3), ("ndingathanda", 3), ("kunjani", 3), ("ndifuna", 3),
        ("ixabiso", 3), ("intengiso", 3), ("kutheni", 3), ("ndiza", 3),
        ("ivenkile", 3), ("iimpahla", 3), ("ndi", 1), ("ingaba", 2),
        ("malini", 1), ("imali", 1), ("thenga", 1),
    ),
    Language.AFRIKAANS: (
        ("goeie more", 3), ("goeiemore", 3), ("dankie", 3), ("asseblief", 3),
        ("hoeveel", 3), ("voorraad", 3), ("winkel", 3), ("wins", 3),
        ("prys", 3), ("moet ek", 3), ("wat is", 3), ("hoe gaan", 3),
        ("registreer", 3), ("belasting", 3), ("afslag", 3), ("plakkaat", 3),
        ("die", 2), ("nie", 2), ("ekke", 2), ("jy", 2), ("my", 1),
        ("ek", 2), ("hoe", 2), ("het", 2), ("jou", 2), ("wil", 2),
        ("geld", 2), ("koop", 2), ("verkoop", 2), ("advertensie", 3),
        ("watter", 3), ("kan ek", 3), ("baie", 2),
    ),
    Language.SOTHO: (
        ("dumela", 3), ("kea leboha", 3), ("ke leboha", 3), ("joang", 3),
        ("hobaneng", 3), ("ke reke", 3), ("ke rekise", 3), ("bokae", 3),
        ("phaello", 3), ("theko", 3), ("setsi", 2), ("chelete", 2),
        ("thepa", 2), ("fedile", 3), ("lekgetho", 3), ("ho reka", 3),
        ("nka", 2), ("eng", 1),
    ),
    Language.TSWANA: (
        ("dumela", 1), ("ke a leboga", 3), ("go reka", 3), ("tlhwatlhwa", 3),
        ("poelo", 3), ("madi", 2), ("thoto", 3), ("lebenkele", 3),
        ("jang", 2), ("goreng", 3), ("bokae", 1),
    ),
}

# Strong English signals, used to stop a single shared word tipping the balance.
ENGLISH_MARKERS = (
    ("what", 2), ("how", 2), ("should", 2), ("stock", 2), ("price", 2),
    ("profit", 2), ("advert", 2), ("register", 2), ("the", 1), ("my", 1),
    ("is", 1), ("do", 1), ("i", 1), ("much", 2), ("reorder", 2), ("sell", 2),
    ("buy", 2), ("write", 2), ("low", 1), ("need", 1),
)

MIN_SCORE_TO_SWITCH = 3


@dataclass
class LanguageGuess:
    language: Language
    confidence: float
    scores: dict[Language, int] = field(default_factory=dict)
    matched: list[str] = field(default_factory=list)

    @property
    def is_english(self) -> bool:
        return self.language is Language.ENGLISH

    def explain(self) -> str:
        if not self.matched:
            return f"No distinctive words found - defaulting to {self.language.english_name}"
        return (f"Matched {', '.join(repr(w) for w in self.matched[:4])} "
                f"-> {self.language.english_name} ({self.confidence:.0%} confident)")


def _score(text: str, markers) -> tuple[int, list[str]]:
    total = 0
    hits: list[str] = []
    for word, weight in markers:
        pattern = rf"\b{re.escape(word)}\b" if " " not in word else re.escape(word)
        if re.search(pattern, text):
            total += weight
            hits.append(word)
    return total, hits


def detect_language(text: str) -> LanguageGuess:
    """Work out which language a message is in. English is the safe default."""
    if not text or not text.strip():
        return LanguageGuess(Language.ENGLISH, 0.0)

    clean = " " + re.sub(r"[^\w\s]", " ", text.lower()) + " "
    clean = re.sub(r"\s+", " ", clean)

    scores: dict[Language, int] = {}
    matches: dict[Language, list[str]] = {}

    english_score, english_hits = _score(clean, ENGLISH_MARKERS)
    if english_score:
        scores[Language.ENGLISH] = english_score
        matches[Language.ENGLISH] = english_hits

    for language, markers in LANGUAGE_MARKERS.items():
        total, hits = _score(clean, markers)
        if total:
            scores[language] = total
            matches[language] = hits

    if not scores:
        return LanguageGuess(Language.ENGLISH, 0.0)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_language, top_score = ranked[0]

    # Only move away from English on real evidence, since a wrong switch is
    # far more damaging than staying in English.
    if top_language is not Language.ENGLISH and top_score < MIN_SCORE_TO_SWITCH:
        top_language, top_score = Language.ENGLISH, scores.get(Language.ENGLISH, 0)

    total = sum(scores.values())
    confidence = round(top_score / total, 4) if total else 0.0

    return LanguageGuess(
        language=top_language,
        confidence=confidence,
        scores=scores,
        matched=matches.get(top_language, []),
    )


def language_directive(language: Language) -> str:
    """The instruction handed to the model, naming the language explicitly."""
    if language is Language.ENGLISH:
        return "Write your entire reply in English."
    return (
        f"Write your ENTIRE reply in {language.english_name}. "
        f"The facts you are given are in English - that is for you to read, not "
        f"the language to answer in. Do not mix in English sentences. "
        f"Keep all numbers, Rand amounts and percentages exactly as given."
    )


# ---------------------------------------------------- fixed phrases
# These are shown when there is no AI available, so they must be translated
# rather than generated. English is always present as the fallback.
PHRASES: dict[str, dict[Language, str]] = {
    "greeting": {
        Language.ENGLISH: "Hello! I am KasiBiz, your shop assistant.",
        Language.ZULU: "Sawubona! NgiyiKasiBiz, umsizi wesitolo sakho.",
        Language.XHOSA: "Molo! NdiyiKasiBiz, umncedisi wevenkile yakho.",
        Language.AFRIKAANS: "Hallo! Ek is KasiBiz, jou winkel-assistent.",
        Language.SOTHO: "Dumela! Ke KasiBiz, mothusi wa lebenkele la hao.",
        Language.TSWANA: "Dumela! Ke KasiBiz, mothusi wa lebenkele la gago.",
    },
    "ask_me_about": {
        Language.ENGLISH: "Ask me about your stock, your prices, adverts for your "
                          "customers, or business questions like registering with CIPC.",
        Language.ZULU: "Ngibuze ngempahla yakho, amanani akho, izikhangiso zamakhasimende "
                       "akho, noma imibuzo yebhizinisi njengokubhalisa ne-CIPC.",
        Language.XHOSA: "Ndibuze ngempahla yakho, amaxabiso akho, iintengiso zabathengi "
                        "bakho, okanye imibuzo yeshishini njengokubhalisa kwi-CIPC.",
        Language.AFRIKAANS: "Vra my oor jou voorraad, jou pryse, advertensies vir jou "
                            "kliente, of besigheidsvrae soos registrasie by CIPC.",
        Language.SOTHO: "Mpotse ka thepa ya hao, ditheko tsa hao, dipapatso tsa bareki "
                        "ba hao, kapa dipotso tsa kgwebo jwalo ka ho ngodisa CIPC.",
        Language.TSWANA: "Mpotse ka thoto ya gago, ditlhwatlhwa tsa gago, dipapatso tsa "
                         "barekisi ba gago, kgotsa dipotso tsa kgwebo jaaka go kwadisa CIPC.",
    },
    "not_sure": {
        Language.ENGLISH: "I am not sure what you are asking. I can help with stock, "
                          "prices, adverts and business questions like CIPC and SARS.",
        Language.ZULU: "Angiqiniseki ukuthi ubuza ngani. Ngingasiza ngempahla, amanani, "
                       "izikhangiso nemibuzo yebhizinisi njenge-CIPC ne-SARS.",
        Language.XHOSA: "Andiqinisekanga ukuba ubuza ntoni. Ndingakunceda ngempahla, "
                        "amaxabiso, iintengiso nemibuzo yeshishini efana ne-CIPC ne-SARS.",
        Language.AFRIKAANS: "Ek is nie seker wat jy vra nie. Ek kan help met voorraad, "
                            "pryse, advertensies en besigheidsvrae soos CIPC en SARS.",
        Language.SOTHO: "Ha ke na bonnete ba seo o se botsang. Nka thusa ka thepa, ditheko, "
                        "dipapatso le dipotso tsa kgwebo jwalo ka CIPC le SARS.",
        Language.TSWANA: "Ga ke tlhomamisege gore o botsa eng. Nka thusa ka thoto, "
                         "ditlhwatlhwa, dipapatso le dipotso tsa kgwebo jaaka CIPC le SARS.",
    },
    "no_guides": {
        Language.ENGLISH: "Our guides do not cover that yet, so I do not want to guess.",
        Language.ZULU: "Imihlahlandlela yethu ayikuhlanganisi lokho okwamanje, ngakho "
                       "angifuni ukuqagela.",
        Language.XHOSA: "Izikhokelo zethu azikagubungeli oko okwangoku, ngoko andifuni "
                        "ukuqashela.",
        Language.AFRIKAANS: "Ons gidse dek dit nog nie, so ek wil nie raai nie.",
        Language.SOTHO: "Ditataiso tsa rona ha di so akaretse seo, kahoo ha ke batle ho hakanya.",
        Language.TSWANA: "Dikaelo tsa rona ga di ise di akaretse seo, ka jalo ga ke batle go akanya.",
    },
    "check_official": {
        Language.ENGLISH: "Please check the official source.",
        Language.ZULU: "Sicela uhlole umthombo osemthethweni.",
        Language.XHOSA: "Nceda ujonge umthombo osemthethweni.",
        Language.AFRIKAANS: "Kyk asseblief na die amptelike bron.",
        Language.SOTHO: "Ka kopo sheba mohloli wa semmuso.",
        Language.TSWANA: "Tsweetswee lebelela motswedi wa semmuso.",
    },
    "source": {
        Language.ENGLISH: "Source",
        Language.ZULU: "Umthombo",
        Language.XHOSA: "Umthombo",
        Language.AFRIKAANS: "Bron",
        Language.SOTHO: "Mohloli",
        Language.TSWANA: "Motswedi",
    },
}


def phrase(key: str, language: Language = Language.ENGLISH) -> str:
    """Look up a fixed phrase, falling back to English if untranslated."""
    options = PHRASES.get(key)
    if not options:
        raise KeyError(f"No phrase registered for {key!r}.")
    return options.get(language) or options[Language.ENGLISH]


def supported_languages() -> list[Language]:
    return list(Language)
