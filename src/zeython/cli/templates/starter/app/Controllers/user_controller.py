from starlette.responses import JSONResponse

from app.Models.user import User
from zeython import Controller, NotFoundException


class UserController(Controller):
    """Read-only /users resource. Create an account via POST /register instead —
    that's what hashes the password (see app/Controllers/auth_controller.py)."""

    async def index(self, request):
        users = await User.all()
        return JSONResponse([user.to_dict() for user in users])

    async def show(self, request):
        user = await User.find(int(request.path_params["id"]))
        if user is None:
            raise NotFoundException("User not found")
        return JSONResponse(user.to_dict())
