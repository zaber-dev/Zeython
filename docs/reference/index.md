# API Reference

This section is generated directly from the docstrings in `src/zeython/` -- if it disagrees with the narrative docs elsewhere in this site, the narrative docs are describing intent and usage, and this reference is describing the actual current signatures. When in doubt, trust this section (or better, the source).

It's organized the same way the framework itself is, roughly matching the "Digging Deeper" grouping in the nav:

- **Core**

  ______________________________________________________________________

  `Application`, `Container`, `Config`, service providers, `Router`/`Controller`, `Views`, exceptions, validation.

  [Reference](https://zeython.zaber.dev/docs/reference/core/index.md)

- **Database**

  ______________________________________________________________________

  `Model`, `Database`, `Page`, transactions, N+1 detection, factories & seeders.

  [Reference](https://zeython.zaber.dev/docs/reference/database/index.md)

- **Security**

  ______________________________________________________________________

  Session auth, API token auth, RBAC authorization, CSRF, security headers, password hashing, multi-tenancy.

  [Reference](https://zeython.zaber.dev/docs/reference/security/index.md)

- **HTTP & APIs**

  ______________________________________________________________________

  Rate limiting, ETags, gzip, request IDs, OpenAPI generation.

  [Reference](https://zeython.zaber.dev/docs/reference/http-api/index.md)

- **Jobs & Realtime**

  ______________________________________________________________________

  Queues, the scheduler, WebSockets, mail.

  [Reference](https://zeython.zaber.dev/docs/reference/jobs-realtime/index.md)

- **Operations**

  ______________________________________________________________________

  Health checks, logging, error monitoring, caching, storage.

  [Reference](https://zeython.zaber.dev/docs/reference/operations/index.md)

- **Extensibility**

  ______________________________________________________________________

  Console commands, the plugin registry, localization, the admin panel, AI integration.

  [Reference](https://zeython.zaber.dev/docs/reference/extensibility/index.md)

Most of these classes and functions are also re-exported from the top-level `zeython` package, so `from zeython import Application` and `from zeython.application import Application` reach the same object -- import from whichever is clearer at the call site.
