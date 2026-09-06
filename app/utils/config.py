"""Central configuration for KasiBiz, loaded from the .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or malformed."""


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    model_name: str
    chroma_db_path: str
    database_url: str


def load_settings() -> Settings:
    """Read settings from the environment, failing loudly when the key is missing."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key:
        raise ConfigError(
            "OPENAI_API_KEY is not set.\n"
            "Fix: copy .env.example to .env and paste your own OpenAI key into it."
        )

    if api_key.startswith("sk-your-"):
        raise ConfigError(
            "OPENAI_API_KEY is still the placeholder value from .env.example.\n"
            "Fix: replace it in .env with a real key from https://platform.openai.com/api-keys"
        )

    return Settings(
        openai_api_key=api_key,
        model_name=os.getenv("MODEL_NAME", "gpt-4o-mini").strip(),
        chroma_db_path=os.getenv("CHROMA_DB_PATH", "chroma_db").strip(),
        database_url=os.getenv("DATABASE_URL", "sqlite:///kasibiz.db").strip(),
    )
