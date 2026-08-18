from zeython import Gate, ServiceProvider

from app.Models.post import Post


class PostPolicyServiceProvider(ServiceProvider):
    """Defines this app's authorization abilities (see docs/authorization.md).

    ``boot()`` -- not ``register()`` -- because it needs the `Gate` that
    `AuthorizationServiceProvider` binds; every provider's `register()` runs
    before any `boot()`, so this is safe regardless of registration order.

    A single closure is enough for one ability -- once a resource
    accumulates several (view/update/delete/...), group them in a Policy
    class instead (``gate.policy(Post, PostPolicy)``), and `Gate.role()`/
    `Gate.permission()` cover role- or permission-gated abilities. See
    "Policies" and "Roles and permissions" in docs/authorization.md.
    """

    def boot(self) -> None:
        gate: Gate = self.container.make(Gate)
        gate.define("delete-post", lambda user, post: isinstance(post, Post) and post.author_id == user.id)
