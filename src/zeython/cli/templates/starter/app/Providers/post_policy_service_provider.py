from zeython import Gate, ServiceProvider

from app.Models.post import Post


class PostPolicyServiceProvider(ServiceProvider):
    """Defines this app's authorization abilities (see docs/authorization.md).

    ``boot()`` -- not ``register()`` -- because it needs the `Gate` that
    `AuthorizationServiceProvider` binds; every provider's `register()` runs
    before any `boot()`, so this is safe regardless of registration order.
    """

    def boot(self) -> None:
        gate: Gate = self.container.make(Gate)
        gate.define("delete-post", lambda user, post: isinstance(post, Post) and post.author_id == user.id)
