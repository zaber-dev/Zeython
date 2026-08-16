# Docker

A generated project ships a `Dockerfile`, `docker-compose.yml`, and
`.dockerignore` -- a working container from `zeython new` onward, not
something you have to bolt on before a first deployment.

## Building and running

```bash
docker compose up --build
```

This builds the image, runs pending migrations, and starts the server on
`http://localhost:8000`. `docker compose` reads `.env` for configuration
(copy `.env.example` to `.env` first, same as running locally) --
`.dockerignore` deliberately excludes `.env` from the build context itself,
so a secret never ends up baked into an image layer.

Without compose:

```bash
docker build -t my-app .
docker run -p 8000:8000 --env-file .env my-app
```

## What the image does

- **Multi-stage build.** A `builder` stage installs dependencies into a
  venv; the final image copies just that venv plus the app source -- no
  pip build cache, no dev tooling, in the shipped image.
- **Runs as a non-root user.** `appuser`, not root.
- **Migrates on startup.** The container's `CMD` runs
  `alembic upgrade head` before starting `uvicorn`. A single-container
  deployment doesn't need anything fancier; running more than one replica
  usually means moving the migration into its own one-shot job so N
  containers starting together don't race to run it.
- **A `HEALTHCHECK`** hits [`/up`](health-check.md) -- Docker (and anything
  reading `docker inspect`, like a Compose `depends_on: condition:
  service_healthy`) can tell when the app is actually ready, not just when
  the process started.

## Postgres, Redis

The default `DATABASE_URL` is SQLite, and caching/rate-limiting default to
in-memory -- fine for a single container, not for anything you'd run more
than one replica of (see [Redis](redis.md)). `docker-compose.yml` includes
commented-out `db` (Postgres) and `redis` services with the config you'd
uncomment to switch -- **uncommenting them alone isn't enough**: also add
the matching database driver (`asyncpg` for Postgres) to `pyproject.toml`'s
dependencies and set `DATABASE_URL`/point `RedisCache`/`RedisRateLimiter`
at the `redis` service in `main.py`.

## Persisting data

`docker-compose.yml` mounts `./storage` (uploaded files -- see
[File Storage](storage.md)) onto the host by default. The default SQLite
database file lives *inside* the container unless you also uncomment the
`database.db` volume mount -- otherwise `docker compose down` takes your
data with it.
