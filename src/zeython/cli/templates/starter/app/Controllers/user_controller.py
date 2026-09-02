from starlette.responses import JSONResponse

from app.Models.user import User
from zeython import BadRequestException, Controller, NotFoundException


class UserController(Controller):
    """Read-only /users resource. Create an account via POST /register instead —
    that's what hashes the password (see app/Controllers/auth_controller.py)."""

    async def index(self, request):
        # See docs/database.md#pagination -- ?page=2&per_page=10, defaults below.
        try:
            page = int(request.query_params.get("page", 1))
            per_page = int(request.query_params.get("per_page", 20))
        except ValueError as exc:
            raise BadRequestException("'page' and 'per_page' must be integers.") from exc
        try:
            result = await User.paginate(page=page, per_page=per_page)
        except ValueError as exc:
            raise BadRequestException(str(exc)) from exc
        return JSONResponse(result.to_dict(request=request))

    async def show(self, request):
        user = await User.find(int(request.path_params["id"]))
        if user is None:
            raise NotFoundException("User not found")
        return JSONResponse(user.to_dict())
