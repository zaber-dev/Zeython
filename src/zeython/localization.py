"""Translation strings and per-request locale resolution.

Translations live in flat JSON files, one per locale, under
``resources/lang/`` by convention (``resources/lang/en.json``,
``resources/lang/es.json``, ...) -- a dotted key mapped to its translated
string, e.g. ``{"welcome.title": "Welcome!", "greeting": "Hello, {name}!"}``.
:class:`Translator` loads and caches them, resolving a key against the
current request's locale (with a fallback locale for a missing key) and
substituting ``{name}``-style parameters.

``LocaleMiddleware`` resolves the locale for each request -- an explicit
``?lang=xx`` query parameter, then the ``Accept-Language`` header, then the
configured default -- against whichever locales actually have a
translation file on disk, and makes it available to :func:`current_locale`
for the request's duration via a :class:`~contextvars.ContextVar`, the same
technique :func:`~zeython.request_id.request_id` uses. Translating a string
never needs a ``request`` threaded through every call as a result --
``Translator.t()`` (and the ``t`` global :class:`LocalizationServiceProvider`
registers for Jinja templates) reads the current locale from that
contextvar directly.
"""

from __future__ import annotations

import contextlib
import json
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from zeython.providers import ServiceProvider

_current_locale: ContextVar[str | None] = ContextVar("zeython_locale", default=None)


def current_locale() -> str | None:
    """The current request's resolved locale, or ``None`` outside a request
    handled by :class:`LocaleMiddleware`."""
    return _current_locale.get()


def _parse_accept_language(header: str) -> list[str]:
    """``"en-US,en;q=0.9,es;q=0.8"`` -> ``["en-US", "en", "es"]``, most
    preferred first -- including each tag's base language (``en-US`` ->
    also ``en``) since a translation file is typically named by base
    language, not region. Not a full RFC 4647 implementation, just enough
    to negotiate against whatever locale files actually exist.
    """
    entries: list[tuple[str, float]] = []
    for part in header.split(","):
        part = part.strip()
        if not part:
            continue
        tag, _, q_part = part.partition(";")
        q = 1.0
        if q_part:
            try:
                q = float(q_part.strip().removeprefix("q="))
            except ValueError:
                q = 1.0
        entries.append((tag.strip(), q))

    entries.sort(key=lambda entry: entry[1], reverse=True)

    seen: set[str] = set()
    ordered: list[str] = []
    for tag, _ in entries:
        for candidate in (tag, tag.split("-")[0]):
            if candidate and candidate not in seen:
                seen.add(candidate)
                ordered.append(candidate)
    return ordered


class Translator:
    """Loads ``{locale}.json`` translation files from ``path`` and looks up
    keys by exact match, falling back to ``fallback_locale`` for a key
    missing from the requested locale, and to the key itself (so a missing
    translation degrades to something readable, not a crash) if it's
    missing from the fallback too.
    """

    def __init__(self, path: str | Path, *, default_locale: str = "en", fallback_locale: str | None = None) -> None:
        self.path = Path(path)
        self.default_locale = default_locale
        self.fallback_locale = fallback_locale or default_locale
        self._cache: dict[str, dict[str, str]] = {}

    @property
    def available_locales(self) -> set[str]:
        """Locales with a translation file on disk -- what :class:`LocaleMiddleware`
        negotiates against. Empty for a project that hasn't added any yet,
        in which case every request just resolves to ``default_locale``."""
        if not self.path.is_dir():
            return set()
        return {file.stem for file in self.path.glob("*.json")}

    def _translations_for(self, locale: str) -> dict[str, str]:
        if locale not in self._cache:
            file_path = self.path / f"{locale}.json"
            self._cache[locale] = json.loads(file_path.read_text()) if file_path.is_file() else {}
        return self._cache[locale]

    def t(self, key: str, *, locale: str | None = None, **params: Any) -> str:
        """Translate ``key``, in ``locale`` if given, otherwise
        :func:`current_locale` (or ``default_locale`` outside a request).
        Any keyword arguments fill ``{name}``-style placeholders in the
        translated string via ``str.format`` -- a placeholder with no
        matching argument is left as-is rather than raising.
        """
        resolved_locale = locale or current_locale() or self.default_locale
        translations = self._translations_for(resolved_locale)
        if key not in translations and resolved_locale != self.fallback_locale:
            translations = self._translations_for(self.fallback_locale)
        text = translations.get(key, key)
        if params:
            with contextlib.suppress(KeyError, IndexError):
                text = text.format(**params)
        return text


class LocaleMiddleware:
    """Pure ASGI middleware: resolves the request's locale and sets it as a
    contextvar for :func:`current_locale` (readable via
    :class:`Translator` without a ``request`` in hand) for the request's
    duration.
    """

    def __init__(self, app: Any, *, translator: Translator, query_param: str = "lang") -> None:
        self.app = app
        self.translator = translator
        self.query_param = query_param

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = _current_locale.set(self._resolve_locale(scope))
        try:
            await self.app(scope, receive, send)
        finally:
            _current_locale.reset(token)

    def _resolve_locale(self, scope: dict) -> str:
        available = self.translator.available_locales

        query_string = (scope.get("query_string") or b"").decode("latin-1")
        requested = parse_qs(query_string).get(self.query_param, [None])[0]
        if requested and requested in available:
            return requested

        headers = dict(scope.get("headers") or [])
        accept_language = headers.get(b"accept-language")
        if accept_language:
            for candidate in _parse_accept_language(accept_language.decode("latin-1")):
                if candidate in available:
                    return candidate

        return self.translator.default_locale


class LocalizationServiceProvider(ServiceProvider):
    """Binds a :class:`Translator` and registers :class:`LocaleMiddleware`.

    - ``LOCALE_PATH`` -- default ``resources/lang`` under the project root.
    - ``LOCALE_DEFAULT`` -- default ``en``. Used when nothing else resolves
      a locale (no ``?lang=``/``Accept-Language`` match, or outside a
      request entirely).
    - ``LOCALE_FALLBACK`` -- default: same as ``LOCALE_DEFAULT``. Used when
      a key exists in some locale's file but not the requested one.
    - ``LOCALE_QUERY_PARAM`` -- default ``lang``. The query parameter a
      link can use to force a locale, e.g. ``?lang=es``.

    Also registers ``t`` as a Jinja global if :class:`~zeython.views.ViewServiceProvider`
    is registered, so a template can call ``{{ t("welcome.title") }}``
    directly -- see docs/localization.md.
    """

    def register(self) -> None:
        translator = Translator(
            self.config.get("locale.path", str(self.app.base_path / "resources" / "lang")),
            default_locale=self.config.get("locale.default", "en"),
            fallback_locale=self.config.get("locale.fallback"),
        )
        self.container.singleton(Translator, lambda: translator)

    def boot(self) -> None:
        translator = self.container.make(Translator)
        self.app.add_middleware(
            LocaleMiddleware,
            translator=translator,
            query_param=self.config.get("locale.query_param", "lang"),
        )

        from zeython.views import Views

        if self.container.has(Views):
            self.container.make(Views).environment.globals["t"] = translator.t


def t(request: Any, key: str, **params: Any) -> str:
    """Translate ``key`` using the app's registered :class:`Translator`, in
    the current request's resolved locale. Usage inside a controller,
    exactly like :func:`~zeython.views.render`/:func:`~zeython.queue.dispatch`::

        from zeython.localization import t

        async def show(self, request):
            return JSONResponse({"message": t(request, "welcome.title")})

    Inside a Jinja template, call ``t(...)`` directly instead --
    :class:`LocalizationServiceProvider` registers it as a template global,
    no ``request`` needed there. Outside a request entirely (a job, a
    script), resolve the translator directly instead:
    ``app.container.make(Translator).t(key)``.
    """
    container = request.app.state.container
    translator: Translator = container.make(Translator)
    return translator.t(key, **params)


__all__ = [
    "LocaleMiddleware",
    "LocalizationServiceProvider",
    "Translator",
    "current_locale",
    "t",
]
