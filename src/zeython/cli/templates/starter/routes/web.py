from app.Controllers.user_controller import UserController
from main import app
from starlette.responses import JSONResponse


@app.get("/", name="home")
async def index(request):
    return JSONResponse({"message": "Welcome to {{ project_name }}"})


app.router.resource("/users", UserController, only=("index", "show", "store"))
