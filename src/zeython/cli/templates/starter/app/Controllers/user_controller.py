from starlette.responses import JSONResponse

from app.Models.user import User
from zeython import Controller, NotFoundException, ValidationException


class UserController(Controller):
    """Handles requests for the /users resource."""

    async def index(self, request):
        users = await User.all()
        return JSONResponse([user.to_dict() for user in users])

    async def show(self, request):
        user = await User.find(int(request.path_params["id"]))
        if user is None:
            raise NotFoundException("User not found")
        return JSONResponse(user.to_dict())

    async def store(self, request):
        data = await request.json()
        if not data.get("email"):
            raise ValidationException({"email": ["Email is required."]})
        user = await User.create(**data)
        return JSONResponse(user.to_dict(), status_code=201)
