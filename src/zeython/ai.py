"""AI-assisted app features: a small, provider-agnostic LLM client bound in
the container, for calling a model from your own request handlers and jobs.

This is a different thing from ``zeython.mcp``: that module lets an AI
*agent* introspect and operate on a Zeython project (Laravel Boost's role).
This module lets a Zeython *app* call an LLM as part of its own logic --
summarizing text, drafting a reply, classifying input -- the same role
Vercel's AI SDK or LangChain's chat models play, kept to a fraction of the
surface area.

Requires the ``ai`` extra (``pip install zeython[ai]``) only if you use
:class:`AnthropicAI`, :class:`OpenAIAI`, or :class:`GeminiAI`; the
interface and :class:`EchoAI` have no extra dependency.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from zeython.providers import ServiceProvider


@dataclass(frozen=True)
class AIResponse:
    text: str
    model: str


class AI(ABC):
    """A chat-style completion client."""

    @abstractmethod
    async def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024) -> AIResponse:
        """Send ``prompt`` (plus optional ``system`` instructions) and return the model's reply."""


class EchoAI(AI):
    """Returns the prompt back, unmodified, with no network call.

    The default (``AI_PROVIDER=echo``) -- the same role :class:`~zeython.mail.LogMailer`
    and :class:`~zeython.queue.InMemoryQueue` play for their subsystems: a
    fresh ``zeython new`` project (and its tests) work immediately without
    external credentials. Switch to :class:`AnthropicAI` (``AI_PROVIDER=anthropic``)
    once you have an API key. See docs/ai.md.
    """

    async def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024) -> AIResponse:
        return AIResponse(text=f"[echo] {prompt}", model="echo")


class AnthropicAI(AI):
    """Calls the Anthropic API via the official SDK. Requires the ``ai`` extra
    (``pip install zeython[ai]``)."""

    def __init__(self, *, api_key: str, model: str) -> None:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise ImportError(
                "AnthropicAI requires the anthropic package. Install it with: pip install zeython[ai]"
            ) from exc

        self._client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024) -> AIResponse:
        message = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        return AIResponse(text=text, model=self.model)


class OpenAIAI(AI):
    """Calls the OpenAI API via the official SDK. Requires the ``ai`` extra
    (``pip install zeython[ai]``)."""

    def __init__(self, *, api_key: str, model: str) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError(
                "OpenAIAI requires the openai package. Install it with: pip install zeython[ai]"
            ) from exc

        self._client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024) -> AIResponse:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
        )
        text = response.choices[0].message.content or ""
        return AIResponse(text=text, model=self.model)


class GeminiAI(AI):
    """Calls the Google Gemini API via the official ``google-genai`` SDK.
    Requires the ``ai`` extra (``pip install zeython[ai]``)."""

    def __init__(self, *, api_key: str, model: str) -> None:
        try:
            from google import genai
        except ImportError as exc:
            raise ImportError(
                "GeminiAI requires the google-genai package. Install it with: pip install zeython[ai]"
            ) from exc

        self._client = genai.Client(api_key=api_key)
        self.model = model

    async def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024) -> AIResponse:
        from google.genai import types

        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system or None,
                max_output_tokens=max_tokens,
            ),
        )
        return AIResponse(text=response.text or "", model=self.model)


class AIServiceProvider(ServiceProvider):
    """Binds an :class:`AI` client into the container from ``.env``.

    - ``AI_PROVIDER`` -- ``echo`` (default, no network/credentials),
      ``anthropic``, ``openai``, or ``gemini``
    - ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` / ``GEMINI_API_KEY`` --
      required for the matching provider
    - ``AI_MODEL`` -- the model name for whichever provider is active;
      defaults to a current model for that provider if unset

    Not registered by default -- opt in with ``app.register(AIServiceProvider)``
    once your app actually calls an LLM.
    """

    _DEFAULT_MODELS = {
        "anthropic": "claude-sonnet-5",
        "openai": "gpt-4o",
        "gemini": "gemini-2.5-flash",
    }

    def register(self) -> None:
        provider = self.config.get("ai.provider", "echo")
        client: AI
        if provider == "echo":
            client = EchoAI()
        elif provider in self._DEFAULT_MODELS:
            env_key = f"{provider}_api_key"
            api_key = self.config.get(env_key, "")
            if not api_key:
                raise RuntimeError(
                    f"AI_PROVIDER={provider} requires {env_key.upper()} to be set in .env. "
                    "Use AI_PROVIDER=echo (the default) for local dev/tests without an API key."
                )
            model = self.config.get("ai.model", self._DEFAULT_MODELS[provider])
            if provider == "anthropic":
                client = AnthropicAI(api_key=api_key, model=model)
            elif provider == "openai":
                client = OpenAIAI(api_key=api_key, model=model)
            else:
                client = GeminiAI(api_key=api_key, model=model)
        else:
            raise RuntimeError(f"Unknown AI_PROVIDER: {provider!r}")
        self.container.singleton(AI, lambda: client)


__all__ = ["AI", "AIResponse", "EchoAI", "AnthropicAI", "OpenAIAI", "GeminiAI", "AIServiceProvider"]
