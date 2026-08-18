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
```

See [Authorization](authorization.md#policies) for registering a generated policy with `Gate.policy(...)`.

## Custom commands

```bash
zeython commands                     # list every command in app/Console/Commands/
zeython command prune-old-posts      # run one, with any trailing args passed through raw
```

See [Console Commands](console-commands.md) for how to write one.

## Database migrations (Alembic)

```bash
zeython db revision -m "add posts table"   # autogenerate a migration from model changes
zeython db migrate                          # apply all pending migrations
zeython db downgrade                        # revert the most recent migration
zeython db downgrade <revision>
```

These are thin wrappers around `alembic` using the project's `alembic.ini` and
`migrations/` directory, generated automatically by `zeython new`.

## Seeding

```bash
zeython db seed                        # runs DatabaseSeeder
zeython db seed --class UserSeeder      # runs a specific seeder instead
```

See [Factories & Seeders](database-seeding.md).

## Queue worker

```bash
zeython queue work                     # process jobs from a durable queue (QUEUE_DRIVER=redis)
```

Only meaningful with `QUEUE_DRIVER=redis` — the default in-memory queue
already runs its own worker inside your app's process, so there's nothing
for a separate process to pull from. See [Background Jobs](queues.md#queue_driverredis-a-durable-queue).

## Scheduled tasks

```bash
zeython schedule run                   # run every task due this minute -- point cron at this
zeython schedule list                  # list every registered task and its cron expression
```

See [Scheduling](scheduling.md).

## Project introspection

```bash
zeython routes                         # list every registered HTTP route: method(s), path, name
zeython about                          # app name, environment, debug flag, Zeython version, providers
```

Both read your project the same way `zeython serve` does (they import
`main.py`), so what they report is exactly what's actually wired up --
not something separately maintained that can drift from it. An AI coding
agent working in your project gets the same information through
`zeython mcp`'s `list_routes`/`app_info` tools -- see [AI Agents](ai-agents.md).
