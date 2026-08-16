from pathlib import Path
from types import SimpleNamespace

import pytest

from zeython.ai import AI, AIServiceProvider, AnthropicAI, EchoAI
from zeython.application import Application
from zeython.config import Config

# -- EchoAI -----------------------------------------------------------------------


async def test_echo_ai_returns_the_prompt_back() -> None:
    ai = EchoAI()
    response = await ai.complete("hello there")

    assert response.text == "[echo] hello there"
    assert response.model == "echo"


async def test_echo_ai_never_touches_the_network_regardless_of_kwargs() -> None:
    ai = EchoAI()
    response = await ai.complete("prompt", system="be terse", max_tokens=1)
    assert response.text == "[echo] prompt"


# -- AIServiceProvider --------------------------------------------------------------


def test_default_provider_binds_echo_ai(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))
    app.register(AIServiceProvider)

    assert isinstance(app.container.make(AI), EchoAI)


def test_explicit_echo_provider_binds_echo_ai(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("AI_PROVIDER=echo\n")
    app = Application(Config.load(tmp_path))
    app.register(AIServiceProvider)

    assert isinstance(app.container.make(AI), EchoAI)


def test_anthropic_provider_without_an_api_key_raises_at_register(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("AI_PROVIDER=anthropic\n")
    app = Application(Config.load(tmp_path))

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        app.register(AIServiceProvider)


def test_unknown_provider_raises_at_register(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("AI_PROVIDER=bogus\n")
    app = Application(Config.load(tmp_path))

    with pytest.raises(RuntimeError, match="Unknown AI_PROVIDER"):
        app.register(AIServiceProvider)


def test_anthropic_provider_with_a_key_binds_anthropic_ai(tmp_path: Path) -> None:
    pytest.importorskip("anthropic")
    (tmp_path / ".env").write_text("AI_PROVIDER=anthropic\nANTHROPIC_API_KEY=test-key\nAI_MODEL=claude-sonnet-5\n")
    app = Application(Config.load(tmp_path))
    app.register(AIServiceProvider)

    client = app.container.make(AI)
    assert isinstance(client, AnthropicAI)
    assert client.model == "claude-sonnet-5"


# -- AnthropicAI --------------------------------------------------------------------


async def test_anthropic_ai_extracts_text_blocks_from_the_response() -> None:
    pytest.importorskip("anthropic")
    ai = AnthropicAI(api_key="test-key", model="claude-sonnet-5")

    fake_response = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="Hello, "),
            SimpleNamespace(type="text", text="world!"),
        ]
    )

    async def fake_create(**kwargs: object) -> SimpleNamespace:
        assert kwargs["model"] == "claude-sonnet-5"
        assert kwargs["messages"] == [{"role": "user", "content": "hi"}]
        return fake_response

    ai._client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))

    response = await ai.complete("hi")

    assert response.text == "Hello, world!"
    assert response.model == "claude-sonnet-5"


def test_anthropic_ai_without_the_extra_raises_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(ImportError, match="pip install zeython"):
        AnthropicAI(api_key="test-key", model="claude-sonnet-5")
