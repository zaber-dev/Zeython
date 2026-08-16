from starlette.responses import JSONResponse, Response

from zeython import Cache, Controller, NotFoundException
from zeython.auth import require_auth
from zeython.authorization import authorize
from zeython.openapi import describe, model_schema

from app.Models.post import Post

_INDEX_CACHE_KEY = "posts:index"
_POST_SCHEMA = model_schema(Post)


class PostController(Controller):
    """Demonstrates relationship loading (see docs/relationships.md) and
    caching a read path (see docs/caching.md).

    Posts are always fetched with `include=("author",)`: touching
    `post.author` without eager-loading it raises `MissingGreenlet` in an
    async session, not a normal lazy load like you'd get with sync
    SQLAlchemy -- eager-loading is what makes it safe.
    """

    @describe(
        summary="List posts",
        tags=["posts"],
        responses={200: {"description": "The post list", "content": {
            "application/json": {"schema": {"type": "array", "items": _POST_SCHEMA}},
        }}},
    )
    async def index(self, request):
        cache: Cache = request.app.state.container.make(Cache)

        async def fetch():
            posts = await Post.all(include=("author",))
            return [post.to_dict(include=("author",)) for post in posts]

        return JSONResponse(await cache.remember(_INDEX_CACHE_KEY, 30, fetch))

    async def show(self, request):
        post = await Post.find(int(request.path_params["id"]), include=("author",))
        if post is None:
            raise NotFoundException("Post not found")
        return JSONResponse(post.to_dict(include=("author",)))

    @describe(
        summary="Create a post",
        tags=["posts"],
        request_body={"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}}},
        responses={201: {"description": "The created post", "content": {
            "application/json": {"schema": _POST_SCHEMA},
        }}},
    )
    async def store(self, request):
        user = await require_auth(request)
        data = await request.json()
        # Assigning the relationship directly (not just author_id) keeps it
        # loaded in memory, so to_dict(include=("author",)) works immediately
        # without a second query.
        post = await Post.create(title=data.get("title"), body=data.get("body"), author=user)

        cache: Cache = request.app.state.container.make(Cache)
        await cache.forget(_INDEX_CACHE_KEY)

        return JSONResponse(post.to_dict(include=("author",)), status_code=201)

    async def destroy(self, request):
        post = await Post.find(int(request.path_params["id"]))
        if post is None:
            raise NotFoundException("Post not found")

        # See docs/authorization.md and app/Providers/post_policy_service_provider.py
        # -- only the post's own author may delete it.
        await authorize(request, "delete-post", post)
        await post.delete()

        cache: Cache = request.app.state.container.make(Cache)
        await cache.forget(_INDEX_CACHE_KEY)

        # A 204 response must have an empty body -- JSONResponse(None, ...)
        # would still serialize a "null" body, which a real HTTP server
        # rejects (Content-Length mismatch) even though it looks fine
        # against the in-process test client. Response() has no body.
        return Response(status_code=204)
