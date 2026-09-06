"""Day 4 checks for the OpenAI connection.

Offline checks always run. The live API call only runs when a real
OPENAI_API_KEY is present in .env:

    pytest tests/test_llm_connection.py -v -s
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.utils.config import ConfigError, load_settings  # noqa: E402
from app.utils.llm_client import KasiBizLLM  # noqa: E402


def _settings_or_skip():
    try:
        return load_settings()
    except ConfigError as exc:
        pytest.skip(f"No usable OPENAI_API_KEY: {exc}")


def test_settings_load():
    settings = _settings_or_skip()
    assert settings.openai_api_key.startswith("sk-")
    assert settings.model_name


def test_empty_prompt_is_rejected():
    _settings_or_skip()
    llm = KasiBizLLM()
    with pytest.raises(ValueError):
        llm.ask("   ")


def test_live_hello_world():
    _settings_or_skip()
    llm = KasiBizLLM()
    answer = llm.ask("Reply with exactly: KasiBiz is online.", temperature=0, max_tokens=20)
    print(f"\nModel replied: {answer}")
    assert "kasibiz" in answer.lower()
