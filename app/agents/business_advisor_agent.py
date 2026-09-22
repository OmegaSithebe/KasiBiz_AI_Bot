"""Day 11 - the Business Advisor: answers from our documents, and cites them.

This is the first agent whose facts come from a document library rather than
from the shop's own database. The shape is the same as every other agent:

    1. RETRIEVE  find the passages that answer the question (no AI)
    2. GROUND    build a prompt containing ONLY those passages
    3. ANSWER    the LLM writes the reply, restricted to that context
    4. CITE      the source file is attached to every answer

Rule that makes this trustworthy: if the knowledge base has nothing relevant,
the agent says so and points the owner at the official source. It does not fall
back on the model's general knowledge, because that is exactly where confident
wrong answers about SARS and CIPC come from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.rag.retriever import KnowledgeRetriever, RetrievedContext
from app.utils.config import ConfigError
from app.utils.language import detect_language, language_directive
from app.utils.llm_client import KasiBizLLM, LLMError

ADVISOR_PROMPT = (
    "You are the KasiBiz Business Advisor for a South African spaza shop owner.\n"
    "\n"
    "LANGUAGE RULE - THIS COMES FIRST AND OVERRIDES EVERYTHING ELSE:\n"
    "Reply in the language the owner asked in. If they wrote isiZulu, answer in "
    "isiZulu. If Sesotho, answer in Sesotho. Only answer in English if they wrote "
    "English. The source passages are in English - that is for you to read, it is "
    "NOT the language you must reply in.\n"
    "\n"
    "GROUNDING RULE - THIS IS WHY YOU EXIST:\n"
    "Answer ONLY from the SOURCE PASSAGES provided. Do not add facts from your own "
    "training, even if you are confident they are correct. If the passages do not "
    "answer the question, say plainly that our guides do not cover it and tell the "
    "owner to check the official source (CIPC at bizportal.gov.za, or SARS at "
    "sars.gov.za). Never invent a fee, a deadline, a form number or a threshold.\n"
    "\n"
    "STYLE:\n"
    "- Plain, everyday words. The owner may never have studied business.\n"
    "- Short. Use numbered steps when describing a process.\n"
    "- Money in South African Rand.\n"
    "- Do not mention 'passages', 'context' or 'documents' - just answer.\n"
    "- End with one clear next step the owner can take."
)

NO_CONTEXT_REPLY = (
    "Our guides do not cover that yet, so I do not want to guess.\n"
    "For company registration questions, check CIPC at https://bizportal.gov.za\n"
    "For tax questions, check SARS at https://www.sars.gov.za"
)

NOT_BUILT_REPLY = (
    "The knowledge base has not been built yet.\n"
    "Run this once to load the guides:\n"
    "    python scripts/rag_ingest.py"
)


class AdviceTopic(str, Enum):
    REGISTRATION = "registration"
    TAXATION = "taxation"
    BUSINESS = "business"
    INVENTORY = "inventory"
    GENERAL = "general"


TOPIC_KEYWORDS: dict[AdviceTopic, tuple[str, ...]] = {
    AdviceTopic.REGISTRATION: (
        "cipc", "register", "registration", "bizportal", "pty", "company name",
        "director", "annual return", "beneficial ownership", "deregister",
        "bhalisa", "ngwadisa",
    ),
    AdviceTopic.TAXATION: (
        "sars", "tax", "vat", "receipt", "invoice", "record keeping", "efiling",
        "intela", "lekgetho",
    ),
    AdviceTopic.INVENTORY: (
        "stock", "reorder", "shelf", "stocktake", "expiry", "slow moving",
    ),
}


@dataclass
class AdviceResponse:
    """An answer, the sources behind it, and whether the AI was involved."""

    question: str
    answer: str
    sources: list[str] = field(default_factory=list)
    used_llm: bool = False
    grounded: bool = False
    confidence: float = 0.0
    topic: AdviceTopic = AdviceTopic.GENERAL
    context: RetrievedContext | None = None

    @property
    def answer_with_citation(self) -> str:
        if not self.sources:
            return self.answer
        return f"{self.answer}\n\nSource: {'; '.join(self.sources)}"

    def __str__(self) -> str:
        return self.answer_with_citation


class BusinessAdvisorAgent:
    """Answers business questions from the KasiBiz document library."""

    def __init__(
        self,
        retriever: KnowledgeRetriever | None = None,
        llm: KasiBizLLM | None = None,
        use_llm: bool = True,
    ) -> None:
        self.retriever = retriever or KnowledgeRetriever()
        self.use_llm = use_llm
        self._llm = llm
        self._llm_ready = llm is not None

    # ------------------------------------------------------ 1. topic
    @staticmethod
    def detect_topic(question: str) -> AdviceTopic:
        text = question.lower()
        for topic in (AdviceTopic.REGISTRATION, AdviceTopic.TAXATION, AdviceTopic.INVENTORY):
            if any(word in text for word in TOPIC_KEYWORDS[topic]):
                return topic
        return AdviceTopic.GENERAL

    # --------------------------------------------------- 3. the LLM
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

    @staticmethod
    def _summarise_context(context: RetrievedContext) -> str:
        """Readable fallback when there is no language model available."""
        lines = ["Here is what our guides say:", ""]
        for result in context.results:
            body = " ".join(result.text.split())
            lines.append(f"From {result.title}:")
            lines.append(f"  {body}")
            lines.append("")
        return "\n".join(lines).strip()

    def _generate(self, question: str, context: RetrievedContext) -> tuple[str, bool]:
        llm = self._get_llm()
        if llm is None:
            return self._summarise_context(context), False

        prompt = (
            f"{language_directive(detect_language(question).language)}\n\n"
            f"SOURCE PASSAGES:\n{context.as_prompt_context()}\n\n"
            f"SHOP OWNER'S QUESTION: {question}\n\n"
            "Answer using only the passages above."
        )
        try:
            reply = llm.ask(prompt, system_prompt=ADVISOR_PROMPT,
                            temperature=0.2, max_tokens=500)
        except LLMError:
            return self._summarise_context(context), False

        return (reply.strip(), True) if reply.strip() else (self._summarise_context(context), False)

    # ------------------------------------------------------- public
    def ask(self, question: str, category: str | None = None) -> AdviceResponse:
        if not question.strip():
            raise ValueError("Question cannot be empty.")

        topic = self.detect_topic(question)

        if not self.retriever.is_ready:
            return AdviceResponse(question=question, answer=NOT_BUILT_REPLY, topic=topic)

        context = self.retriever.retrieve(question, category=category)

        if not context.has_context:
            return AdviceResponse(
                question=question,
                answer=NO_CONTEXT_REPLY,
                topic=topic,
                grounded=False,
                context=context,
            )

        answer, used_llm = self._generate(question, context)

        return AdviceResponse(
            question=question,
            answer=answer,
            sources=context.sources,
            used_llm=used_llm,
            grounded=True,
            confidence=context.best_score,
            topic=topic,
            context=context,
        )

    def what_can_i_ask(self) -> str:
        if not self.retriever.is_ready:
            return NOT_BUILT_REPLY

        topics = ", ".join(self.retriever.topics())
        return (
            f"I can answer from our guides on: {topics}.\n\n"
            "For example:\n"
            "  - How do I register with CIPC?\n"
            "  - What is an annual return?\n"
            "  - What records must I keep for SARS?\n"
            "  - What is beneficial ownership?\n"
            "  - How do I know if I am making a profit?"
        )
