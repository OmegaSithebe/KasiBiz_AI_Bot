"""Day 11 - the Business Advisor answering from real documents, with citations.

    python scripts/advisor_demo.py             # documents only, free, no AI
    python scripts/advisor_demo.py --ai        # AI writes the answer, still grounded
    python scripts/advisor_demo.py --chat --ai # ask your own questions

Build the knowledge base first:
    python scripts/rag_ingest.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.agents.business_advisor_agent import BusinessAdvisorAgent  # noqa: E402
from app.rag.retriever import KnowledgeRetriever  # noqa: E402
from app.rag.vector_store import (  # noqa: E402
    KasiBizVectorStore,
    LocalEmbedder,
    OpenAIEmbedder,
    VectorStoreError,
)
from app.utils.config import ConfigError  # noqa: E402

DEMO_QUESTIONS = [
    "How do I register with CIPC?",
    "What is an annual return and do I still submit one if my company is dormant?",
    "What records must I keep for SARS?",
    "What is beneficial ownership?",
    "How do I know if I am making a profit?",
    "Who won the rugby world cup in 1995?",
]


def heading(text: str) -> None:
    print(f"\n{'=' * 74}\n{text}\n{'=' * 74}")


def build_retriever(use_local: bool) -> KnowledgeRetriever:
    if use_local:
        return KnowledgeRetriever(KasiBizVectorStore(embedder=LocalEmbedder()))
    try:
        return KnowledgeRetriever(KasiBizVectorStore(embedder=OpenAIEmbedder()))
    except (ConfigError, VectorStoreError):
        return KnowledgeRetriever(KasiBizVectorStore(embedder=LocalEmbedder()))


def show_retrieval(retriever: KnowledgeRetriever, question: str) -> None:
    heading("STEP 1 - RETRIEVE (no AI yet - this is just searching by meaning)")
    print(f"  Question: {question}\n")

    context = retriever.retrieve(question)
    if not context.has_context:
        print("  Nothing in the knowledge base is close enough to this question.")
        return

    for i, result in enumerate(context.results, start=1):
        preview = " ".join(result.text.split())[:130]
        print(f"  [{i}] {result.as_citation()}   similarity {result.score}")
        print(f"      {preview}...\n")

    print(f"  These {len(context.results)} passages - and nothing else - are what the")
    print("  language model will be allowed to use.")


def ask_all(agent: BusinessAdvisorAgent, using_ai: bool) -> None:
    heading(f"STEP 2 - ANSWER and CITE  (AI: {'ON' if using_ai else 'OFF - documents only'})")

    for question in DEMO_QUESTIONS:
        response = agent.ask(question)
        print(f"\n  OWNER: {question}")
        print(f"  [topic: {response.topic.value} | grounded: {response.grounded}"
              f" | AI: {response.used_llm}"
              f" | confidence: {response.confidence:.2f}]")
        print("  " + "-" * 62)
        for line in response.answer.splitlines():
            print(f"  | {line}")
        if response.sources:
            print("  |")
            print(f"  | Source: {'; '.join(response.sources)}")
        print("  " + "-" * 62)


def chat(agent: BusinessAdvisorAgent) -> None:
    heading("CHAT - ask your own business questions (blank line or 'quit' to stop)")
    print(agent.what_can_i_ask())
    while True:
        try:
            question = input("\n  You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question or question.lower() in {"quit", "exit", "q"}:
            break

        response = agent.ask(question)
        print(f"  [{response.topic.value} | grounded: {response.grounded} "
              f"| AI: {response.used_llm}]")
        for line in response.answer.splitlines():
            print(f"  KasiBiz: {line}")
        if response.sources:
            print(f"  Source: {'; '.join(response.sources)}")
    print("\n  Sala kahle!")


def main() -> int:
    parser = argparse.ArgumentParser(description="KasiBiz Business Advisor demo")
    parser.add_argument("--ai", action="store_true", help="let the LLM write the answer")
    parser.add_argument("--local", action="store_true", help="force the offline embedder")
    parser.add_argument("--chat", action="store_true", help="ask your own questions")
    args = parser.parse_args()

    retriever = build_retriever(args.local or not args.ai)

    if not retriever.is_ready:
        print("The knowledge base is empty. Build it first:")
        print("    python scripts/rag_ingest.py --local")
        return 1

    print(f"Knowledge base: {retriever.store.count()} passages from "
          f"{len(retriever.store.sources())} documents")
    print(f"Embedder: {retriever.store.embedder.name}")

    agent = BusinessAdvisorAgent(retriever, use_llm=args.ai)

    if args.chat:
        chat(agent)
        return 0

    show_retrieval(retriever, "How do I register with CIPC?")
    ask_all(agent, using_ai=args.ai)

    print("\n\nDay 11 complete - the Business Advisor answers from real documents")
    print("and cites where every answer came from.")
    if not args.ai:
        print("Run with --ai to let the language model write the answers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
