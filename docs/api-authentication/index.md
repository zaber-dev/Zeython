# API Authentication

`zeython.api_auth` is a separate path from [Authentication](https://zeython.zaber.dev/docs/authentication/index.md)'s cookie sessions, for clients that can't carry a cookie jar — a mobile app, a separate SPA, a server-to-server caller. The two never mix in one handler: a signed cookie and a bearer token are verified differently, and a handler should be unambiguous about which one it expects.

## Getting a token

```bash
curl -X POST http://127.0.0.1:8000/api/token \
  -H 'Content-Type: application/json' \
  -d '{"email": "ada@example.com", "password": "hunter2"}'
# {"token": "...", "token_type": "Bearer"}
```

`zeython new` wires this into `AuthController.token` — it checks credentials the same way `/login` does (`AuthManager.attempt`), then issues a token instead of setting a cookie. Throttled the same way `/login` is (see [Rate Limiting](https://zeython.zaber.dev/docs/rate-limiting/index.md)).

## Using a token

```bash
curl http://127.0.0.1:8000/api/me -H 'Authorization: Bearer <token>'
```

```python
from zeython.api_auth import require_api_auth

async def api_me(self, request):
    user = await require_api_auth(request)
    return JSONResponse(user.to_dict())
```

`require_api_auth` raises `UnauthorizedException` (401) for a missing or invalid token, same shape as `require_auth` for cookie sessions. `current_api_user` is the non-raising version, returning `None` instead.

## Registering

```python
from zeython import ApiAuthServiceProvider

app.register(ApiAuthServiceProvider(app, user_model=User))
```

Configuration (`.env`): `API_TOKEN_EXPIRES_IN` — seconds, default 30 days.

## How tokens work, and what that trades away

Tokens are signed with `itsdangerous` (already a framework dependency — Starlette's own session cookie uses it too), reusing `APP_SECRET_KEY`. No new dependency, no migration, no token table to set up.

The trade-off: **a token can't be revoked before it expires.** There's no server-side record of it to delete — verifying a token means checking its signature and timestamp, not looking anything up. Rotating `APP_SECRET_KEY` invalidates every token at once (same as it already invalidates every session), but there's no way to invalidate one token, or one user's tokens, without that.

If your app needs "sign this device out remotely" or "list a user's active sessions," that requires a stateful design — a database table of issued tokens you can query and delete rows from. Implement your own `TokenManager`-shaped class against that table and bind it in `TokenManager`'s place; nothing else in the framework assumes the stateless implementation.

## Combining with authorization

`authorize()` (see [Authorization](https://zeython.zaber.dev/docs/authorization/index.md)) works the same way regardless of which auth path produced the user — it just needs a user object:

```python
async def destroy(self, request):
    user = await require_api_auth(request)
    post = await Post.find(int(request.path_params["id"]))
    gate: Gate = request.app.state.container.make(Gate)
    if not await gate.allows(user, "delete-post", post):
        raise ForbiddenException("...")
    await post.delete()
```

(`authorize()` itself calls `require_auth`, the cookie-session version — for a bearer-token handler, call `require_api_auth` first and use `gate.allows` directly, as above, rather than `authorize()`.)
