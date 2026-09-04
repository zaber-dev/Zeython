"""Tests for zeython.localization -- translation strings and per-request
locale resolution.
"""

from __future__ import annotations

from pathlib import Path

from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.localization import (
    LocaleMiddleware,
    LocalizationServiceProvider,
    Translator,
    _parse_accept_language,
    current_locale,
    t,
)
from zeython.testing import client


def _write_locale_files(lang_dir: Path) -> None:
    lang_dir.mkdir(parents=True, exist_ok=True)
    (lang_dir / "en.json").write_text('{"greeting": "Hello, {name}!", "only_in_en": "English only"}')
    (lang_dir / "es.json").write_text('{"greeting": "Hola, {name}!"}')


# -- Translator ---------------------------------------------------------------------------


def test_translates_a_key_in_the_given_locale(tmp_path: Path) -> None:
    _write_locale_files(tmp_path / "lang")
    translator = Translator(tmp_path / "lang", default_locale="en")

    assert translator.t("greeting", locale="es", name="Ana") == "Hola, Ana!"


def test_missing_key_falls_back_to_the_fallback_locale(tmp_path: Path) -> None:
    _write_locale_files(tmp_path / "lang")
    translator = Translator(tmp_path / "lang", default_locale="en", fallback_locale="en")

    assert translator.t("only_in_en", locale="es") == "English only"


def test_missing_key_in_every_locale_returns_the_key_itself(tmp_path: Path) -> None:
    _write_locale_files(tmp_path / "lang")
    translator = Translator(tmp_path / "lang", default_locale="en")

    assert translator.t("nonexistent.key") == "nonexistent.key"


def test_missing_locale_file_behaves_like_an_empty_translation_set(tmp_path: Path) -> None:
    translator = Translator(tmp_path / "does-not-exist", default_locale="en")

    assert translator.t("greeting") == "greeting"
    assert translator.available_locales == set()


def test_params_fill_placeholders_via_str_format(tmp_path: Path) -> None:
    _write_locale_files(tmp_path / "lang")
    translator = Translator(tmp_path / "lang", default_locale="en")

    assert translator.t("greeting", locale="en", name="World") == "Hello, World!"


def test_a_missing_format_argument_leaves_the_raw_string_instead_of_raising(tmp_path: Path) -> None:
    _write_locale_files(tmp_path / "lang")
    translator = Translator(tmp_path / "lang", default_locale="en")

    assert translator.t("greeting", locale="en") == "Hello, {name}!"


def test_a_stray_unescaped_brace_leaves_the_raw_string_instead_of_raising(tmp_path: Path) -> None:
    # Regression guard: a translator pasting a literal "{" or "}" into a
    # translation file (needs doubling to "{{"/"}}" in str.format syntax,
    # an easy slip in ordinary prose) used to raise an uncaught ValueError
    # from str.format() -- ValueError wasn't among the caught exceptions,
    # only KeyError/IndexError -- 500ing every request that hit that key
    # instead of degrading to the raw string the way a missing argument
    # already does.
    lang_dir = tmp_path / "lang"
    lang_dir.mkdir(parents=True, exist_ok=True)
    (lang_dir / "en.json").write_text('{"price": "Total: {", "percent": "Save {0:d}%"}')
    translator = Translator(lang_dir, default_locale="en")

    assert translator.t("price", locale="en", amount=100) == "Total: {"
    assert translator.t("percent", locale="en", amount=100) == "Save {0:d}%"


def test_available_locales_reflects_the_files_on_disk(tmp_path: Path) -> None:
    _write_locale_files(tmp_path / "lang")
    translator = Translator(tmp_path / "lang", default_locale="en")

    assert translator.available_locales == {"en", "es"}


def test_t_uses_current_locale_when_none_is_given_explicitly(tmp_path: Path) -> None:
    _write_locale_files(tmp_path / "lang")
    translator = Translator(tmp_path / "lang", default_locale="en")

    from zeython.localization import _current_locale

    token = _current_locale.set("es")
    try:
        assert translator.t("greeting", name="Ana") == "Hola, Ana!"
    finally:
        _current_locale.reset(token)


# -- _parse_accept_language -----------------------------------------------------------------


def test_parse_accept_language_orders_by_q_value() -> None:
    assert _parse_accept_language("en;q=0.5,es;q=0.9") == ["es", "en"]


def test_parse_accept_language_includes_the_base_language_of_a_region_tag() -> None:
    assert _parse_accept_language("en-US") == ["en-US", "en"]


def test_parse_accept_language_defaults_missing_q_to_1() -> None:
    assert _parse_accept_language("fr,en;q=0.5") == ["fr", "en"]


# -- LocaleMiddleware -----------------------------------------------------------------------


def _app_with_locale_middleware(tmp_path: Path) -> Application:
    _write_locale_files(tmp_path / "lang")
    translator = Translator(tmp_path / "lang", default_locale="en")
    app = Application(Config.load(tmp_path))
    app.add_middleware(LocaleMiddleware, translator=translator)

    @app.get("/")
    async def index(request):
        return JSONResponse({"locale": current_locale()})

    return app


async def test_defaults_to_the_translators_default_locale(tmp_path: Path) -> None:
    app = _app_with_locale_middleware(tmp_path)

    async with client(app) as http:
        response = await http.get("/")

    assert response.json()["locale"] == "en"


async def test_query_param_overrides_the_default(tmp_path: Path) -> None:
    app = _app_with_locale_middleware(tmp_path)

    async with client(app) as http:
        response = await http.get("/?lang=es")

    assert response.json()["locale"] == "es"


async def test_an_unavailable_query_param_locale_is_ignored(tmp_path: Path) -> None:
    app = _app_with_locale_middleware(tmp_path)

    async with client(app) as http:
        response = await http.get("/?lang=xx")

    assert response.json()["locale"] == "en"


async def test_accept_language_header_is_used_when_no_query_param_is_given(tmp_path: Path) -> None:
    app = _app_with_locale_middleware(tmp_path)

    async with client(app) as http:
        response = await http.get("/", headers={"Accept-Language": "es,en;q=0.5"})

    assert response.json()["locale"] == "es"


async def test_query_param_takes_priority_over_accept_language(tmp_path: Path) -> None:
    app = _app_with_locale_middleware(tmp_path)

    async with client(app) as http:
        response = await http.get("/?lang=es", headers={"Accept-Language": "en"})

    assert response.json()["locale"] == "es"


async def test_locale_is_none_outside_a_request(tmp_path: Path) -> None:
    assert current_locale() is None


# -- LocalizationServiceProvider --------------------------------------------------------------


async def test_provider_binds_a_translator_and_registers_the_middleware(tmp_path: Path) -> None:
    _write_locale_files(tmp_path / "resources" / "lang")
    app = Application(Config.load(tmp_path), base_path=tmp_path)
    app.register(LocalizationServiceProvider)

    @app.get("/")
    async def index(request):
        return JSONResponse({"message": t(request, "greeting", name="World")})

    async with client(app) as http:
        response = await http.get("/")

    assert response.json()["message"] == "Hello, World!"


async def test_provider_respects_locale_env_config(tmp_path: Path) -> None:
    _write_locale_files(tmp_path / "resources" / "lang")
    (tmp_path / ".env").write_text("LOCALE_DEFAULT=es\n")
    app = Application(Config.load(tmp_path), base_path=tmp_path)
    app.register(LocalizationServiceProvider)

    @app.get("/")
    async def index(request):
        return JSONResponse({"message": t(request, "greeting", name="Ana")})

    async with client(app) as http:
        response = await http.get("/")

    assert response.json()["message"] == "Hola, Ana!"


async def test_provider_registers_t_as_a_jinja_global_when_views_are_registered(tmp_path: Path) -> None:
    from zeython.providers import ViewServiceProvider
    from zeython.views import Views

    lang_dir = tmp_path / "resources" / "lang"
    _write_locale_files(lang_dir)
    views_dir = tmp_path / "resources" / "views"
    views_dir.mkdir(parents=True)
    (views_dir / "hello.html").write_text("{{ t('greeting', name=name) }}")

    app = Application(Config.load(tmp_path), base_path=tmp_path)
    app.register(ViewServiceProvider)
    app.register(LocalizationServiceProvider)

    @app.get("/")
    async def index(request):
        from zeython.views import render

        return render(request, "hello.html", {"name": "World"})

    async with client(app) as http:
        response = await http.get("/")

    assert response.text == "Hello, World!"
    assert app.container.make(Views).environment.globals["t"] == app.container.make(Translator).t
