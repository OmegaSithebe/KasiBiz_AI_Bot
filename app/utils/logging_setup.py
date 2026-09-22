"""Somewhere for KasiBiz to write down what went wrong.

The shop owner must never see a stack trace. That is a deliberate decision, but
it left a hole: when a specialist failed, the cause disappeared with it, and a
demo that misbehaved could not be diagnosed afterwards.

So there are two audiences now, and they get different things:

    THE OWNER    a calm sentence on screen
    THE LOG      the exception, the question, and which specialist was asked

The log goes to the console and, when KASIBIZ_LOG_FILE is set, to a file as
well. Nothing here is required for the app to run.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.utils.config import PROJECT_ROOT

DEFAULT_LEVEL = "INFO"
FORMAT = "%(asctime)s  %(levelname)-7s %(name)-22s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure(level: str | None = None, log_file: str | Path | None = None) -> None:
    """Set up logging once. Safe to call from anywhere, including Streamlit reruns."""
    global _configured
    if _configured:
        return

    chosen = (level or os.getenv("KASIBIZ_LOG_LEVEL", DEFAULT_LEVEL)).upper()
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    target = log_file or os.getenv("KASIBIZ_LOG_FILE", "").strip()
    if target:
        path = Path(target)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))

    logging.basicConfig(
        level=getattr(logging, chosen, logging.INFO),
        format=FORMAT,
        datefmt=DATE_FORMAT,
        handlers=handlers,
        force=True,
    )
    # Chroma and httpx are chatty enough to bury our own lines.
    for noisy in ("chromadb", "httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    configure()
    return logging.getLogger(name)
