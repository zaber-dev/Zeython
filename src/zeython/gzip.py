"""Response compression: wires Starlette's own ``GZipMiddleware`` in as an
opt-in provider, configurable via ``.env`` instead of a bare
``app.add_middleware(GZipMiddleware, ...)`` call. See docs/api-standards.md.
"""

from __future__ import annotations

from zeython.providers import ServiceProvider


class GzipServiceProvider(ServiceProvider):
    """Compresses any response at or above ``GZIP_MINIMUM_SIZE`` bytes
    whose client sent ``Accept-Encoding: gzip`` -- not registered by
    default::

        # main.py
        app.register(GzipServiceProvider)

    Configurable via ``.env``:

    - ``GZIP_MINIMUM_SIZE`` -- default ``500``. Responses smaller than
      this aren't worth the CPU cost of compressing.
    - ``GZIP_COMPRESS_LEVEL`` -- default ``9`` (Starlette's own default;
      1 is fastest/least compression, 9 is slowest/most).
    """

    def boot(self) -> None:
        from starlette.middleware.gzip import GZipMiddleware

        self.app.add_middleware(
            GZipMiddleware,
            minimum_size=int(self.config.get("gzip.minimum_size", 500)),
            compresslevel=int(self.config.get("gzip.compress_level", 9)),
        )


__all__ = ["GzipServiceProvider"]
