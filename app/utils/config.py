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


DEFAULT_DATABASE_URL = "sqlite:///kasibiz.db"
DEFAULT_CHROMA_DB_PATH = "chroma_db"


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    model_name: str
    chroma_db_path: str
    database_url: str


def get_database_url() -> str:
    """Database location only. Deliberately does not require an OpenAI key."""
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL).strip() or DEFAULT_DATABASE_URL


def get_chroma_db_path() -> str:
    """Vector store location only. Deliberately does not require an OpenAI key."""
    return os.getenv("CHROMA_DB_PATH", DEFAULT_CHROMA_DB_PATH).strip() or DEFAULT_CHROMA_DB_PATH


def load_settings() -> Settings:
    """Read settings from the environment, failing loudly when the key is missing."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key:
        raise ConfigError(
            "OPENAI_API_KEY is not set.\n"
            "Fix: create a .env file in the project root containing:\n"
            "    OPENAI_API_KEY=sk-...\n"
            "Get a key from https://platform.openai.com/api-keys\n"
            "The .env file is git-ignored and must never be committed."
        )

    if api_key.startswith("sk-your-"):
        raise ConfigError(
            "OPENAI_API_KEY is still a placeholder value.\n"
            "Fix: replace it in .env with a real key from https://platform.openai.com/api-keys"
        )

    return Settings(
        openai_api_key=api_key,
        model_name=os.getenv("MODEL_NAME", "gpt-4o-mini").strip(),
        chroma_db_path=get_chroma_db_path(),
        database_url=get_database_url(),
    )
