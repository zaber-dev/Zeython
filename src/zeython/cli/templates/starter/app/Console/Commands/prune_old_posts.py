from datetime import UTC, datetime, timedelta

from zeython import Command
from zeython.db.session import Database

from app.Models.post import Post


class PruneOldPostsCommand(Command):
    """Hard-deletes posts that were soft-deleted more than 30 days ago.

    Run it: `zeython command prune-old-posts`. A real deployment would call
    this from cron (or a task scheduler) on a schedule, not by hand -- see
    docs/console-commands.md.
    """

    help = "Hard-delete posts soft-deleted more than 30 days ago."

    async def handle(self, *args: str) -> None:
        # Outside a request, so no request-scoped session exists yet --
        # open one explicitly, same as any other out-of-request code.
        database: Database = self.container.make(Database)
        cutoff = datetime.now(UTC) - timedelta(days=30)

        async with database.session():
            candidates = await Post.all(include_deleted=True)
            stale = [post for post in candidates if post.is_deleted and post.deleted_at and post.deleted_at < cutoff]
            for post in stale:
                await post.delete(soft=False)

        print(f"Pruned {len(stale)} post(s) soft-deleted before {cutoff.isoformat()}.")
