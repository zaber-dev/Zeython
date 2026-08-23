# CLI Reference

## Project scaffolding

```bash
zeython new "My Blog"                # creates ./my_blog
zeython new "My Blog" --path ~/code/blog
```

## Development server

```bash
zeython serve                        # reads host/port/reload from .env
zeython serve --host 0.0.0.0 --port 8080 --no-reload
zeython serve --app my_app:app       # if your ASGI app isn't main:app
```

## Code generators

```bash
zeython make model Post              # app/Models/post.py, wired into app/Models/__init__.py
zeython make controller Post         # app/Controllers/post_controller.py (PostController)
zeython make middleware RequestLogger  # app/Middleware/request_logger.py
zeython make provider Payment        # app/Providers/payment_service_provider.py
zeython make job SendWelcomeEmail    # app/Jobs/send_welcome_email_job.py
zeython make command PruneOldPosts   # app/Console/Commands/prune_old_posts_command.py
zeython make factory Post            # database/factories/post_factory.py
zeython make seeder User             # database/seeders/user_seeder.py
zeython make policy Post             # app/Policies/post_policy.py (PostPolicy)
zeython make notification InvoicePaid # app/Notifications/invoice_paid_notification.py
```

See [Authorization](https://zeython.zaber.dev/docs/authorization/#policies) for registering a generated policy with `Gate.policy(...)`.

## Custom commands

```bash
zeython commands                     # list every command in app/Console/Commands/
zeython command prune-old-posts      # run one, with any trailing args passed through raw
```

See [Console Commands](https://zeython.zaber.dev/docs/console-commands/index.md) for how to write one.

## Database migrations (Alembic)

```bash
zeython db revision -m "add posts table"   # autogenerate a migration from model changes
zeython db migrate                          # apply all pending migrations
zeython db downgrade                        # revert the most recent migration
zeython db downgrade <revision>
```

These are thin wrappers around `alembic` using the project's `alembic.ini` and `migrations/` directory, generated automatically by `zeython new`.

## Seeding

```bash
zeython db seed                        # runs DatabaseSeeder
zeython db seed --class UserSeeder      # runs a specific seeder instead
```

See [Factories & Seeders](https://zeython.zaber.dev/docs/database-seeding/index.md).

## Queue worker

```bash
zeython queue work                     # process jobs from a durable queue (QUEUE_DRIVER=redis)
```

Only meaningful with `QUEUE_DRIVER=redis` — the default in-memory queue already runs its own worker inside your app's process, so there's nothing for a separate process to pull from. See [Background Jobs](https://zeython.zaber.dev/docs/queues/#queue_driverredis-a-durable-queue).

## Scheduled tasks

```bash
zeython schedule run                   # run every task due this minute -- point cron at this
zeython schedule list                  # list every registered task and its cron expression
```

See [Scheduling](https://zeython.zaber.dev/docs/scheduling/index.md).

## Project introspection

```bash
zeython routes                         # list every registered HTTP route: method(s), path, name
zeython about                          # app name, environment, debug flag, Zeython version, providers
```

Both read your project the same way `zeython serve` does (they import `main.py`), so what they report is exactly what's actually wired up -- not something separately maintained that can drift from it. An AI coding agent working in your project gets the same information through `zeython mcp`'s `list_routes`/`app_info` tools -- see [AI Agents](https://zeython.zaber.dev/docs/ai-agents/index.md).

## Maintenance mode

```bash
zeython down                           # every request gets a 503 until `zeython up`
zeython down --message "Deploying, back in 5" --retry 300 --allow 1.2.3.4
zeython up                             # bring the app back
```

See [Maintenance Mode](https://zeython.zaber.dev/docs/maintenance-mode/index.md).

## Tinker (interactive REPL)

```bash
zeython tinker
```

Drops into a Python REPL with your app, container, config, and every `Model` subclass in `app/Models/` already imported by name -- mirrors Laravel's `artisan tinker`. Wrap an async call in `run(...)` to execute it; each one commits immediately on success (or rolls back on an exception), the same as a real request:

```pycon
>>> run(Post.all())
[<Post id=1>, <Post id=2>]
>>> post = run(Post.create(title="Hello", body="..."))
>>> run(post.update(title="Hello, world"))
>>> run(post.delete())
```

`app`/`container`/`config` are also in scope, for anything that needs them directly (`container.make(SomeService)`, `config.get("app.debug")`).
