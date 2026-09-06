"""Thin wrapper around the OpenAI Chat Completions API for KasiBiz."""

from __future__ import annotations

from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError

from app.utils.config import Settings, load_settings

KASIBIZ_SYSTEM_PROMPT = (
    "You are KasiBiz, an AI business assistant for South African spaza shop and "
    "township business owners. You help with stock, pricing, marketing, simple "
    "money advice and business registration.\n"
    "Rules:\n"
    "- Use plain, simple language. No jargon, no corporate speak.\n"
    "- Reply in the same language the user writes in (English, isiZulu or Sesotho).\n"
    "- Use South African Rand (R) for money and keep numbers easy to follow.\n"
    "- Keep answers short and practical - give steps the owner can do today.\n"
    "- If you are not sure about a fact (like a legal or SARS requirement), say so "
    "and point the owner to the official source instead of guessing."
)


class LLMError(RuntimeError):
    """Raised when a call to the language model fails."""


class KasiBizLLM:
    """Sends prompts to OpenAI using the KasiBiz persona."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self._client = OpenAI(api_key=self.settings.openai_api_key)

    @property
    def model_name(self) -> str:
        return self.settings.model_name

    def ask(
        self,
        prompt: str,
        system_prompt: str = KASIBIZ_SYSTEM_PROMPT,
        temperature: float = 0.7,
        max_tokens: int = 500,
    ) -> str:
        """Send a single prompt and return the assistant's reply as text."""
        if not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        try:
            response = self._client.chat.completions.create(
                model=self.settings.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except AuthenticationError as exc:
            raise LLMError(
                "OpenAI rejected the API key. Check OPENAI_API_KEY in your .env file."
            ) from exc
        except RateLimitError as exc:
            raise LLMError(
                "Rate limit or quota reached. Check your OpenAI billing/usage, then retry."
            ) from exc
        except APIConnectionError as exc:
            raise LLMError(
                "Could not reach the OpenAI API. Check your internet connection or proxy."
            ) from exc
        except APIStatusError as exc:
            raise LLMError(f"OpenAI returned an error (HTTP {exc.status_code}).") from exc

        content = response.choices[0].message.content
        return (content or "").strip()
