"""AI-assisted app features: a small, provider-agnostic LLM client bound in
the container, for calling a model from your own request handlers and jobs.

This is a different thing from ``zeython.mcp``: that module lets an AI
*agent* introspect and operate on a Zeython project (Laravel Boost's role).
This module lets a Zeython *app* call an LLM as part of its own logic --
summarizing text, drafting a reply, classifying input -- the same role
Vercel's AI SDK or LangChain's chat models play, kept to a fraction of the
surface area.

Requires the ``ai`` extra (``pip install zeython[ai]``) only if you use
:class:`AnthropicAI`; the interface and :class:`EchoAI` have no extra
dependency.
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


class AIServiceProvider(ServiceProvider):
    """Binds an :class:`AI` client into the container from ``.env``.

    - ``AI_PROVIDER`` -- ``echo`` (default, no network/credentials) or ``anthropic``
    - ``ANTHROPIC_API_KEY`` -- required when ``AI_PROVIDER=anthropic``
    - ``AI_MODEL`` -- default ``claude-sonnet-5``, only used by the ``anthropic`` provider

    Not registered by default -- opt in with ``app.register(AIServiceProvider)``
    once your app actually calls an LLM.
    """

    def register(self) -> None:
        provider = self.config.get("ai.provider", "echo")
        client: AI
        if provider == "echo":
            client = EchoAI()
        elif provider == "anthropic":
            api_key = self.config.get("anthropic_api_key", "")
            if not api_key:
                raise RuntimeError(
                    "AI_PROVIDER=anthropic requires ANTHROPIC_API_KEY to be set in .env. "
                    "Use AI_PROVIDER=echo (the default) for local dev/tests without an API key."
                )
            client = AnthropicAI(api_key=api_key, model=self.config.get("ai.model", "claude-sonnet-5"))
        else:
            raise RuntimeError(f"Unknown AI_PROVIDER: {provider!r}")
        self.container.singleton(AI, lambda: client)


__all__ = ["AI", "AIResponse", "EchoAI", "AnthropicAI", "AIServiceProvider"]
