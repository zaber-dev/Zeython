# Localization

Translation strings live in flat JSON files, one per locale, under
`resources/lang/`:

```json
// resources/lang/en.json
{
  "welcome.title": "Welcome!",
  "greeting": "Hello, {name}!"
}
```

```json
// resources/lang/es.json
{
  "welcome.title": "¡Bienvenido!",
  "greeting": "Hola, {name}!"
}
```

## Setup

```python
# main.py
from zeython import Application, LocalizationServiceProvider

app = Application()
app.register(LocalizationServiceProvider)
```

Registering it does two things: binds a `Translator` that loads and
caches those files, and adds `LocaleMiddleware`, which resolves a locale
for every request and makes it available to `Translator` without a
`request` threaded through every call.

## Translating in a controller

```python
from starlette.responses import JSONResponse
from zeython.localization import t

class WelcomeController(Controller):
    async def index(self, request):
        return JSONResponse({"message": t(request, "welcome.title")})
```

`t(request, key, **params)` follows the same shape as
[`render(request, ...)`](views.md) and
[`dispatch(request, job)`](queues.md): an explicit `request` first
argument, everything else resolved from the app it belongs to.

## Translating in a view

```html
<!-- resources/views/welcome.html -->
<h1>{{ t("welcome.title") }}</h1>
<p>{{ t("greeting", name=user.name) }}</p>
```

No `request` needed here — `LocalizationServiceProvider` registers `t` as
a Jinja global (if [`ViewServiceProvider`](views.md) is registered too),
and `Translator` resolves the current locale from the same request the
template is being rendered for internally.

## Parameters

A `{name}`-style placeholder in a translation string is filled from
keyword arguments via `str.format`:

```python
t(request, "greeting", name="Ana")   # "Hello, Ana!" (locale=en)
```

A placeholder with no matching argument is left as-is rather than
raising — a missing translation parameter shouldn't 500 a page that would
otherwise render fine. Same for a stray unescaped `{`/`}` a translator
left in a translation string by mistake (a literal brace needs doubling
to `{{`/`}}` in `str.format` syntax, an easy slip in ordinary prose) — a
typo in a translation file shouldn't 500 every request that hits it
either.

## How the locale is resolved

For each request, in order:

1. An explicit `?lang=xx` query parameter — a language switcher link can
   force this regardless of anything else, as long as `xx` has a matching
   translation file.
2. The `Accept-Language` header, matched against whichever locales
   actually have a translation file on disk (`en-US` also matches an
   `en.json` file if there's no more specific `en-US.json`).
3. `LOCALE_DEFAULT` (default `en`), if neither of the above resolves to
   an available locale — including when no translation files exist yet
   at all.

Read it back with `current_locale()`:

```python
from zeython.localization import current_locale

locale = current_locale()   # "es", or None outside a request
```

## A missing key or locale never crashes a request

- A key missing from the resolved locale falls back to `LOCALE_FALLBACK`
  (default: same as `LOCALE_DEFAULT`).
- A key missing from both is returned as-is — `t(request, "no.such.key")`
  renders `"no.such.key"`, a visibly-wrong-but-harmless string instead of
  a 500, the same trade-off Laravel and Django's translation layers make.
- A locale with no translation file at all behaves like an empty file —
  every key falls through to the fallback locale, or to the key itself.

## Configuration

| `.env` key | Default | Meaning |
|---|---|---|
| `LOCALE_PATH` | `resources/lang` | Where translation files live, relative to the project root. |
| `LOCALE_DEFAULT` | `en` | Used when nothing else resolves a locale. |
| `LOCALE_FALLBACK` | same as `LOCALE_DEFAULT` | Used when a key is missing from the resolved locale's file. |
| `LOCALE_QUERY_PARAM` | `lang` | The query parameter a link can use to force a locale (`?lang=es`). |

## Outside a request

A background job or a script has no request to resolve a locale from --
`current_locale()` returns `None` there, so `Translator.t()` falls back to
`LOCALE_DEFAULT`. Pass `locale=` explicitly to translate in a specific
locale regardless:

```python
translator = app.container.make(Translator)
translator.t("welcome.title", locale="es")
```
