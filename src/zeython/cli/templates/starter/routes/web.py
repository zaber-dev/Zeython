from starlette.responses import JSONResponse

from main import app
from zeython.views import render

from app.Controllers.auth_controller import AuthController
from app.Controllers.post_controller import PostController
from app.Controllers.upload_controller import UploadController
from app.Controllers.user_controller import UserController


@app.get("/", name="home")
async def index(request):
    return JSONResponse({"message": "Welcome to {{ project_name }}"})


@app.get("/welcome", name="welcome")
async def welcome(request):
    return render(request, "welcome.html", {"tagline": "Your Zeython app is running."})


app.router.resource("/users", UserController, only=("index", "show"))
app.router.resource("/posts", PostController, only=("index", "show", "store", "destroy"))

auth = AuthController()
app.post("/register", name="auth.register")(auth.register)
app.post("/login", name="auth.login")(auth.login)
app.post("/logout", name="auth.logout")(auth.logout)
app.get("/me", name="auth.me")(auth.me)

# Bearer-token path for clients that can't use cookies -- see docs/api-authentication.md.
app.post("/api/token", name="auth.token")(auth.token)
app.get("/api/me", name="auth.api_me")(auth.api_me)

app.post("/uploads", name="uploads.store")(UploadController().store)
