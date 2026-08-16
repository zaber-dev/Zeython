"""A `/up` health-check endpoint -- what load balancers, container
orchestrators (Kubernetes liveness/readiness probes), and uptime monitors
expect an app to expose. Nothing here is optional infrastructure a real
deployment can skip; this is the one thing every one of them needs.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse

from zeython.db import Database
from zeython.providers import ServiceProvider


class HealthCheckServiceProvider(ServiceProvider):
    """Registers a health-check endpoint (``/up`` by default).

    Reports ``{"status": "ok", "checks": {...}}`` with a ``200``, or
    ``{"status": "error", "checks": {...}}`` with a ``503`` if any check
    fails -- the status code is what a load balancer/orchestrator actually
    acts on, so a monitoring tool never needs to parse the body just to know
    whether to route traffic here.

    Currently checks database connectivity (a real ``SELECT 1``, not just
    "is a URL configured") when :class:`~zeython.db.Database` is bound in
    the container -- skipped entirely for an app with no database.

    - ``HEALTH_CHECK_ENABLED`` -- default ``true``; set ``false`` to turn
      the endpoint off entirely (e.g. if you don't want it publicly
      reachable and probe something else internally instead).
    - ``HEALTH_CHECK_PATH`` -- default ``/up``.
    """

    def boot(self) -> None:
        if not bool(self.config.get("health_check.enabled", True)):
            return
        path = self.config.get("health_check.path", "/up")

        async def health(request: Request) -> JSONResponse:
            checks: dict[str, str] = {}
            healthy = True

            if self.container.has(Database):
                database = self.container.make(Database)
                try:
                    async with database.engine.connect() as connection:
                        await connection.execute(text("SELECT 1"))
                    checks["database"] = "ok"
                except Exception:
                    checks["database"] = "error"
                    healthy = False

            body: dict[str, Any] = {"status": "ok" if healthy else "error", "checks": checks}
            return JSONResponse(body, status_code=200 if healthy else 503)

        self.app.get(path, name="health")(health)


__all__ = ["HealthCheckServiceProvider"]
