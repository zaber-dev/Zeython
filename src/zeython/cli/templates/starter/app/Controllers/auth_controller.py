from starlette.responses import JSONResponse

from zeython import AuthManager, Controller, UnauthorizedException, ValidationException
from zeython.api_auth import TokenManager, require_api_auth
from zeython.auth import current_user
from zeython.auth import login as auth_login
from zeython.auth import logout as auth_logout
from zeython.events import emit
from zeython.feature_flags import feature
from zeython.mfa import complete_challenge, confirm, disable, enroll
from zeython.mfa import start_challenge as start_mfa_challenge
from zeython.notifications import notify
from zeython.queue import dispatch
from zeython.rate_limit import client_ip, throttle

from app.Events.user_registered import UserRegistered
from app.Jobs.send_welcome_email_job import SendWelcomeEmailJob
from app.Models.user import User
from app.Notifications.welcome_notification import WelcomeNotification


class AuthController(Controller):
    """Registration, login, logout, the current-user endpoint, and
    two-factor auth (TOTP) enrollment -- see docs/mfa.md.

    Session-based: a successful register/login sets a signed cookie (see
    AuthServiceProvider in main.py); logout clears it. See docs/authentication.md.

    `token`/`api_me` are the separate bearer-token path for clients that
    can't use cookies (a mobile app, a separate SPA) -- see
    docs/api-authentication.md. The two never mix in one handler: a cookie
    session and a bearer token are verified differently and a handler
    should be unambiguous about which one it expects.

    Login and register are throttled per client IP (see docs/rate-limiting.md)
    -- without this, an attacker can try passwords against /login as fast as
    the network allows.
    """

    async def register(self, request):
        await throttle(request, key=f"register:{client_ip(request)}", limit=5, window=3600)

        data = await request.json()
        password = data.pop("password", None)
        if not password:
            raise ValidationException({"password": ["Password is required."]})

        # User.__rules__ (app/Models/user.py) validates name/email on save().
        user = User(**data)
        user.set_password(password)
        await user.save()

        # Runs in the background (see docs/queues.md) so the response doesn't
        # wait on whatever sending an email actually involves.
        await dispatch(request, SendWelcomeEmailJob(to_email=user.email, name=user.name))

        # A second, independent reaction to the signup -- see docs/events.md.
        # Add more listeners in AppEventServiceProvider without touching this
        # handler at all.
        await emit(request, UserRegistered(user_id=user.id, email=user.email))

        # An in-app record of the signup (see docs/notifications.md) --
        # separate from the welcome *email* above: this is what a "you have
        # notifications" UI would read via unread_notifications(user, Notification).
        await notify(request, user, WelcomeNotification())

        auth_login(request, user)
        return JSONResponse(user.to_dict(), status_code=201)

    async def login(self, request):
        await throttle(request, key=f"login:{client_ip(request)}", limit=5, window=60)

        data = await request.json()
        manager: AuthManager = request.app.state.container.make(AuthManager)
        user = await manager.attempt(data.get("email", ""), data.get("password", ""))
        if user is None:
            raise UnauthorizedException("Invalid email or password.")

        if user.mfa_enabled:
            # Password alone isn't enough -- see docs/mfa.md. No session
            # cookie yet; current_user()/require_auth() still return
            # nothing until POST /mfa/challenge succeeds.
            start_mfa_challenge(request, user)
            return JSONResponse({"mfa_required": True})

        auth_login(request, user)
        return JSONResponse(user.to_dict())

    async def logout(self, request):
        auth_logout(request)
        return JSONResponse({"message": "Logged out."})

    async def mfa_challenge(self, request):
        await throttle(request, key=f"mfa-challenge:{client_ip(request)}", limit=5, window=60)

        data = await request.json()
        user = await complete_challenge(request, data.get("code", ""))
        if user is None:
            raise UnauthorizedException("Invalid or expired code.")
        return JSONResponse(user.to_dict())

    async def mfa_enroll(self, request):
        user = await current_user(request)
        if user is None:
            raise UnauthorizedException("Authentication required.")

        enrollment = await enroll(user, account_name=user.email)
        return JSONResponse({"secret": enrollment.secret, "uri": enrollment.uri})

    async def mfa_confirm(self, request):
        user = await current_user(request)
        if user is None:
            raise UnauthorizedException("Authentication required.")

        data = await request.json()
        recovery_codes = await confirm(user, data.get("code", ""))
        # The only time these are ever visible in plaintext -- see docs/mfa.md.
        return JSONResponse({"recovery_codes": recovery_codes})

    async def mfa_disable(self, request):
        user = await current_user(request)
        if user is None:
            raise UnauthorizedException("Authentication required.")

        await disable(user)
        return JSONResponse({"message": "Two-factor authentication disabled."})

    async def me(self, request):
        user = await current_user(request)
        if user is None:
            raise UnauthorizedException("Not logged in.")

        data = user.to_dict()
        # A real feature check (see docs/feature-flags.md and
        # AppFeatureServiceProvider) -- the same user always gets the same
        # answer, since beta_dashboard is a deterministic rollout keyed by
        # this user's own id.
        data["features"] = {"beta_dashboard": await feature(request, "beta_dashboard", user)}
        return JSONResponse(data)

    async def token(self, request):
        await throttle(request, key=f"api-token:{client_ip(request)}", limit=5, window=60)

        data = await request.json()
        manager: AuthManager = request.app.state.container.make(AuthManager)
        user = await manager.attempt(data.get("email", ""), data.get("password", ""))
        if user is None:
            raise UnauthorizedException("Invalid email or password.")

        tokens: TokenManager = request.app.state.container.make(TokenManager)
        return JSONResponse({"token": tokens.issue(user), "token_type": "Bearer"})

    async def api_me(self, request):
        user = await require_api_auth(request)
        return JSONResponse(user.to_dict())
