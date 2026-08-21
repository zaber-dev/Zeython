# API Reference

This section is generated directly from the docstrings in `src/zeython/` --
if it disagrees with the narrative docs elsewhere in this site, the
narrative docs are describing intent and usage, and this reference is
describing the actual current signatures. When in doubt, trust this section
(or better, the source).

It's organized the same way the framework itself is, roughly matching the
"Digging Deeper" grouping in the nav:

- **[Core](core.md)** -- `Application`, `Container`, `Config`, service
  providers, `Router`/`Controller`, `Views`, exceptions, validation.
- **[Database](database.md)** -- `Model`, `Database`, `Page`, transactions,
  N+1 detection, factories & seeders.
- **[Security](security.md)** -- session auth, API token auth, RBAC
  authorization, CSRF, security headers, password hashing, multi-tenancy.
- **[HTTP & APIs](http-api.md)** -- rate limiting, ETags, gzip, request IDs,
  OpenAPI generation.
- **[Jobs & Realtime](jobs-realtime.md)** -- queues, the scheduler,
  WebSockets, mail.
- **[Operations](operations.md)** -- health checks, logging, error
  monitoring, caching, storage.
- **[Extensibility](extensibility.md)** -- console commands, the plugin
  registry, localization, the admin panel, AI integration.

Most of these classes and functions are also re-exported from the
top-level `zeython` package, so `from zeython import Application` and
`from zeython.application import Application` reach the same object --
import from whichever is clearer at the call site.
