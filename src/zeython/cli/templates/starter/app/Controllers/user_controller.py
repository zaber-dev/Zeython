from starlette.responses import JSONResponse

from app.Models.user import User
from zeython import Controller, NotFoundException


class UserController(Controller):
    """Read-only /users resource. Create an account via POST /register instead —
    that's what hashes the password (see app/Controllers/auth_controller.py)."""

    async def index(self, request):
        # See docs/database.md#pagination -- ?page=2&per_page=10, defaults below.
        page = int(request.query_params.get("page", 1))
        per_page = int(request.query_params.get("per_page", 20))
        result = await User.paginate(page=page, per_page=per_page)
        return JSONResponse(
            {
                "items": [user.to_dict() for user in result.items],
                "page": result.page,
                "per_page": result.per_page,
                "total": result.total,
                "total_pages": result.total_pages,
                "has_next": result.has_next,
                "has_prev": result.has_prev,
            }
        )

    async def show(self, request):
        user = await User.find(int(request.path_params["id"]))
        if user is None:
            raise NotFoundException("User not found")
        return JSONResponse(user.to_dict())
