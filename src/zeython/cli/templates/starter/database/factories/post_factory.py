from zeython import Factory

from app.Models.post import Post


class PostFactory(Factory[Post]):
    model = Post

    def definition(self, sequence: int) -> dict:
        return {
            "title": f"Post {sequence}",
            "body": f"This is the body of post {sequence}.",
            # No default for `author_id` -- a Post always belongs to a User,
            # so pass one explicitly: PostFactory().create(author_id=user.id)
        }
