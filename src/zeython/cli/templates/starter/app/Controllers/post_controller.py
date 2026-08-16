from starlette.responses import JSONResponse

from zeython import Controller, NotFoundException
from zeython.auth import require_auth

from app.Models.post import Post


class PostController(Controller):
    """Demonstrates relationship loading (see docs/relationships.md).

    Posts are always fetched with `include=("author",)`: touching
    `post.author` without eager-loading it raises `MissingGreenlet` in an
    async session, not a normal lazy load like you'd get with sync
    SQLAlchemy -- eager-loading is what makes it safe.
    """

    async def index(self, request):
        posts = await Post.all(include=("author",))
        return JSONResponse([post.to_dict(include=("author",)) for post in posts])

    async def show(self, request):
        post = await Post.find(int(request.path_params["id"]), include=("author",))
        if post is None:
            raise NotFoundException("Post not found")
        return JSONResponse(post.to_dict(include=("author",)))

    async def store(self, request):
        user = await require_auth(request)
        data = await request.json()
        # Assigning the relationship directly (not just author_id) keeps it
        # loaded in memory, so to_dict(include=("author",)) works immediately
        # without a second query.
        post = await Post.create(title=data.get("title"), body=data.get("body"), author=user)
        return JSONResponse(post.to_dict(include=("author",)), status_code=201)
