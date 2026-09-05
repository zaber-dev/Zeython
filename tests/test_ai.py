from pathlib import Path
from types import SimpleNamespace

import pytest

from zeython.ai import AI, AIServiceProvider, AnthropicAI, EchoAI, GeminiAI, OpenAIAI
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


def test_openai_provider_without_an_api_key_raises_at_register(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("AI_PROVIDER=openai\n")
    app = Application(Config.load(tmp_path))

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        app.register(AIServiceProvider)


def test_gemini_provider_without_an_api_key_raises_at_register(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("AI_PROVIDER=gemini\n")
    app = Application(Config.load(tmp_path))

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
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


def test_openai_provider_with_a_key_binds_openai_ai(tmp_path: Path) -> None:
    pytest.importorskip("openai")
    (tmp_path / ".env").write_text("AI_PROVIDER=openai\nOPENAI_API_KEY=test-key\nAI_MODEL=gpt-4o\n")
    app = Application(Config.load(tmp_path))
    app.register(AIServiceProvider)

    client = app.container.make(AI)
    assert isinstance(client, OpenAIAI)
    assert client.model == "gpt-4o"


def test_gemini_provider_with_a_key_binds_gemini_ai(tmp_path: Path) -> None:
    pytest.importorskip("google.genai")
    (tmp_path / ".env").write_text("AI_PROVIDER=gemini\nGEMINI_API_KEY=test-key\nAI_MODEL=gemini-2.5-flash\n")
    app = Application(Config.load(tmp_path))
    app.register(AIServiceProvider)

    client = app.container.make(AI)
    assert isinstance(client, GeminiAI)
    assert client.model == "gemini-2.5-flash"


def test_provider_default_model_used_when_ai_model_unset(tmp_path: Path) -> None:
    pytest.importorskip("openai")
    (tmp_path / ".env").write_text("AI_PROVIDER=openai\nOPENAI_API_KEY=test-key\n")
    app = Application(Config.load(tmp_path))
    app.register(AIServiceProvider)

    client = app.container.make(AI)
    assert isinstance(client, OpenAIAI)
    assert client.model == "gpt-4o"


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


# -- OpenAIAI -----------------------------------------------------------------------


async def test_openai_ai_extracts_text_from_the_response() -> None:
    pytest.importorskip("openai")
    ai = OpenAIAI(api_key="test-key", model="gpt-4o")

    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Hello, world!"))]
    )

    async def fake_create(**kwargs: object) -> SimpleNamespace:
        assert kwargs["model"] == "gpt-4o"
        assert kwargs["messages"] == [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hi"},
        ]
        return fake_response

    ai._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))

    response = await ai.complete("hi", system="be terse")

    assert response.text == "Hello, world!"
    assert response.model == "gpt-4o"


def test_openai_ai_without_the_extra_raises_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "openai":
            raise ImportError("No module named 'openai'")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(ImportError, match="pip install zeython"):
        OpenAIAI(api_key="test-key", model="gpt-4o")


# -- GeminiAI -----------------------------------------------------------------------


async def test_gemini_ai_extracts_text_from_the_response() -> None:
    pytest.importorskip("google.genai")
    ai = GeminiAI(api_key="test-key", model="gemini-2.5-flash")

    fake_response = SimpleNamespace(text="Hello, world!")

    async def fake_generate_content(**kwargs: object) -> SimpleNamespace:
        assert kwargs["model"] == "gemini-2.5-flash"
        assert kwargs["contents"] == "hi"
        return fake_response

    ai._client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=fake_generate_content)))

    response = await ai.complete("hi", system="be terse")

    assert response.text == "Hello, world!"
    assert response.model == "gemini-2.5-flash"


def test_gemini_ai_without_the_extra_raises_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "google.genai" or name == "google":
            raise ImportError("No module named 'google.genai'")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(ImportError, match="pip install zeython"):
        GeminiAI(api_key="test-key", model="gemini-2.5-flash")
