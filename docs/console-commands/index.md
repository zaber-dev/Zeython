# Custom Console Commands

Laravel's Artisan and Django's `manage.py` both let an application define its own CLI commands, wired into the same container/config the rest of the app uses. Without that, a one-off script (a data import, a cleanup job, something you want to run from cron) ends up disconnected from the app entirely: its own hand-rolled `Application()` bootstrap, no access to `container.make(...)`, easy to drift from how the real app is actually configured. `zeython command <name>` closes that gap.

## Writing a command

```bash
zeython make command PruneOldPosts
```

```python
# app/Console/Commands/prune_old_posts_command.py
from zeython import Command

class PruneOldPostsCommand(Command):
    """Run with: zeython command prune-old-posts"""

    help = "TODO: describe what this command does."

    async def handle(self, *args: str) -> None:
        ...
```

One file per command in `app/Console/Commands/`, one `Command` subclass per file. `handle()` is async and receives every extra CLI argument as a raw string — there's no typed option parsing, deliberately: it's the same shape `sys.argv` gives you, and you're free to parse it however a given command needs (or ignore it and hardcode behavior).

Inside `handle()`, `self.app`, `self.container`, and `self.config` are the same instances the rest of the app uses:

```python
from zeython.db.session import Database

class PruneOldPostsCommand(Command):
    async def handle(self, *args: str) -> None:
        database: Database = self.container.make(Database)
        async with database.session():
            ...
```

A command runs outside any request, so there's no request-scoped database session automatically available — open one explicitly, as above, the same way any other out-of-request code does.

## Running commands

```bash
zeython commands              # list every discovered command
zeython command prune-old-posts foo --bar=baz
```

`zeython commands` lists every `Command` subclass found in `app/Console/Commands/`, along with its `help` text. `zeython command <name>` runs one, passing every trailing argument through untouched — `foo` and `--bar=baz` above both arrive in `handle()`'s `*args` exactly as typed, including `--`-prefixed ones (they're never parsed as options of the `zeython` CLI itself).

## Naming

The CLI-facing name defaults to the snake_case filename with underscores turned into dashes, and a trailing `_command` dropped — `prune_old_posts_command.py` becomes `prune-old-posts`. Override it with a `name` class attribute for something else entirely (a namespaced style like `reports:send`, for instance):

```python
class SendReportCommand(Command):
    name = "reports:send"
```

## Scheduling

Pointing a bare `cron` entry straight at `zeython command <name>` works, but the schedule itself then lives outside the app entirely — on a server somewhere, not in version control, not reviewed with the code it runs. For recurring tasks defined in code instead (Laravel's `Schedule`, in Python), see [Scheduling](https://zeython.zaber.dev/docs/scheduling/index.md) — `schedule.py`, `zeython schedule run`, one cron entry total, however many tasks you actually schedule.

A generated project includes a working example: `app/Console/Commands/prune_old_posts.py` hard-deletes posts that were soft-deleted more than 30 days ago. Run it by hand with `zeython command prune-old-posts`, or wire it into `schedule.py` for real recurring use.
