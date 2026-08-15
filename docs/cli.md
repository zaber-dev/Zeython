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
```

## Database migrations (Alembic)

```bash
zeython db revision -m "add posts table"   # autogenerate a migration from model changes
zeython db migrate                          # apply all pending migrations
zeython db downgrade                        # revert the most recent migration
zeython db downgrade <revision>
```

These are thin wrappers around `alembic` using the project's `alembic.ini` and
`migrations/` directory, generated automatically by `zeython new`.
