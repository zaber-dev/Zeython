from starlette.responses import JSONResponse

from main import app
from zeython.views import render
from zeython.websockets import WebSocket, WebSocketDisconnect, WebSocketHub

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

# Two-factor auth (TOTP) -- see docs/mfa.md. /mfa/challenge completes a
# login that returned {"mfa_required": true} above; the other three
# manage a *logged-in* user's own enrollment.
app.post("/mfa/challenge", name="auth.mfa_challenge")(auth.mfa_challenge)
app.post("/mfa/enroll", name="auth.mfa_enroll")(auth.mfa_enroll)
app.post("/mfa/confirm", name="auth.mfa_confirm")(auth.mfa_confirm)
app.post("/mfa/disable", name="auth.mfa_disable")(auth.mfa_disable)

# Bearer-token path for clients that can't use cookies -- see docs/api-authentication.md.
app.post("/api/token", name="auth.token")(auth.token)
app.get("/api/me", name="auth.api_me")(auth.api_me)

# "Sign in with Google/GitHub/Microsoft" -- see docs/oauth.md. Commented
# out along with OAuthServiceProvider's registration in main.py until you
# have real provider credentials; `{provider}` matches whatever `name=`
# you gave the provider there (e.g. "google").
# app.get("/auth/{provider}/redirect", name="auth.oauth_redirect")(auth.oauth_redirect)
# app.get("/auth/{provider}/callback", name="auth.oauth_callback")(auth.oauth_callback)

app.post("/uploads", name="uploads.store")(UploadController().store)


# A minimal broadcast chat room -- see docs/websockets.md. Connect with a
# WebSocket client at ws://localhost:8000/ws/chat; every message a client
# sends is relayed to every *other* connected client.
@app.websocket("/ws/chat", name="chat")
async def chat(websocket: WebSocket) -> None:
    hub: WebSocketHub = websocket.app.state.container.make(WebSocketHub)
    if not await hub.connect(websocket):
        return  # Origin not in WEBSOCKET_ALLOWED_ORIGINS -- already closed.
    try:
        while True:
            message = await websocket.receive_text()
            await hub.broadcast(message, exclude=websocket)
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(websocket)
