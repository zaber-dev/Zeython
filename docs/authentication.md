# Authentication

Zeython ships session-based authentication: a signed cookie (Starlette's
`SessionMiddleware`, keyed off `APP_SECRET_KEY`) holding the logged-in user's
ID, [CSRF protection](csrf.md) that comes with it automatically (cookie
auth without it is forgeable from any other site the user's browser has
open), password hashing with no C-extension dependency, and a small set of
functions to check/require a logged-in user in a handler.

This is deliberately scoped to cookie sessions for a server-rendered or
same-origin app. Token-based auth for a separate frontend is a reasonable
thing to add later, but is out of scope here — don't force it into this code
path.

## Setup

```python
# app/Models/user.py
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from zeython import Authenticatable, Model, required, email

class User(Model, Authenticatable):
    __tablename__ = "users"
    __hidden__ = ("password_hash",)          # never serialize this
    __rules__ = {"name": [required()], "email": [required(), email()]}

    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
```

```python
# main.py
from zeython import Application, AuthServiceProvider, DatabaseServiceProvider, RouteServiceProvider
from app.Models.user import User

app = Application()
app.register(DatabaseServiceProvider)
app.register(AuthServiceProvider(app, user_model=User))
app.register(RouteServiceProvider(app, modules=("routes.web",)))
```

`APP_SECRET_KEY` must be set in `.env` — `AuthServiceProvider` raises on boot
if it isn't (`zeython new` generates one for you automatically).

## Registration and login

```python
# app/Controllers/auth_controller.py
from starlette.responses import JSONResponse
from zeython import AuthManager, Controller, UnauthorizedException, ValidationException
from zeython.auth import current_user, login as auth_login, logout as auth_logout
from app.Models.user import User

class AuthController(Controller):
    async def register(self, request):
        data = await request.json()
        password = data.pop("password", None)
        if not password:
            raise ValidationException({"password": ["Password is required."]})

        user = User(**data)
        user.set_password(password)      # from Authenticatable
        await user.save()                 # runs User.__rules__ too
        auth_login(request, user)
        return JSONResponse(user.to_dict(), status_code=201)

    async def login(self, request):
        data = await request.json()
        manager: AuthManager = request.app.state.container.make(AuthManager)
        user = await manager.attempt(data.get("email", ""), data.get("password", ""))
        if user is None:
            raise UnauthorizedException("Invalid email or password.")
        auth_login(request, user)
        return JSONResponse(user.to_dict())

    async def logout(self, request):
        auth_logout(request)
        return JSONResponse({"message": "Logged out."})
```

Note the import aliases (`login as auth_login`): inside a method also named
`login`, the bare name `login` still resolves to the module-level function
(Python scoping doesn't let a method's own name shadow it), but aliasing
avoids the confusion of reading `login(...)` inside `def login(...)`.

## Protecting a route

```python
from zeython.auth import require_auth

async def show(self, request):
    user = await require_auth(request)   # raises UnauthorizedException (401) if not logged in
    ...
```

Use `current_user(request)` instead when the route should work either way
(returns `None` rather than raising):

```python
from zeython.auth import current_user

async def home(self, request):
    user = await current_user(request)
    return render(request, "home.html", {"user": user})
```

## Configuration

| `.env` key | Default | Meaning |
|---|---|---|
| `APP_SECRET_KEY` | *(required)* | Signs the session cookie. Generated automatically by `zeython new`. |
| `SESSION_COOKIE_NAME` | `zeython_session` | Cookie name. |
| `SESSION_MAX_AGE` | `1209600` (14 days) | Cookie lifetime in seconds. |
| `SESSION_HTTPS_ONLY` | `false` | Set `true` once you're serving over HTTPS. |
| `CSRF_ENABLED` | `true` | See [CSRF Protection](csrf.md). |
| `CSRF_COOKIE_NAME` | `csrf_token` | |
| `CSRF_HEADER_NAME` | `X-CSRF-Token` | |

## Password hashing

`zeython.hash_password`/`zeython.verify_password` use PBKDF2-HMAC-SHA256 at
600,000 iterations (OWASP's current minimum recommendation), with stdlib
`hashlib` only — no bcrypt/argon2 C-extension dependency. `Authenticatable`
wraps these as `set_password()`/`check_password()`.
