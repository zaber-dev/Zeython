from starlette.responses import JSONResponse

from zeython import AuthManager, Controller, UnauthorizedException, ValidationException
from zeython.auth import current_user
from zeython.auth import login as auth_login
from zeython.auth import logout as auth_logout

from app.Models.user import User


class AuthController(Controller):
    """Registration, login, logout, and the current-user endpoint.

    Session-based: a successful register/login sets a signed cookie (see
    AuthServiceProvider in main.py); logout clears it. See docs/authentication.md.
    """

    async def register(self, request):
        data = await request.json()
        password = data.pop("password", None)
        if not password:
            raise ValidationException({"password": ["Password is required."]})

        # User.__rules__ (app/Models/user.py) validates name/email on save().
        user = User(**data)
        user.set_password(password)
        await user.save()

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

    async def me(self, request):
        user = await current_user(request)
        if user is None:
            raise UnauthorizedException("Not logged in.")
        return JSONResponse(user.to_dict())
