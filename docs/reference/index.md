# API Reference

This section is generated directly from the docstrings in `src/zeython/` --
if it disagrees with the narrative docs elsewhere in this site, the
narrative docs are describing intent and usage, and this reference is
describing the actual current signatures. When in doubt, trust this section
(or better, the source).

It's organized the same way the framework itself is, roughly matching the
"Digging Deeper" grouping in the nav:

<div class="grid cards" markdown>

-   :material-cube-outline:{ .lg .middle } **Core**

    ---

    `Application`, `Container`, `Config`, service providers,
    `Router`/`Controller`, `Views`, exceptions, validation.

    [:octicons-arrow-right-24: Reference](core.md)

-   :material-database-outline:{ .lg .middle } **Database**

    ---

    `Model`, `Database`, `Page`, transactions, N+1 detection, factories
    & seeders.

    [:octicons-arrow-right-24: Reference](database.md)

-   :material-shield-lock-outline:{ .lg .middle } **Security**

    ---

    Session auth, API token auth, RBAC authorization, CSRF, security
    headers, password hashing, multi-tenancy.

    [:octicons-arrow-right-24: Reference](security.md)

-   :material-api:{ .lg .middle } **HTTP & APIs**

    ---

    Rate limiting, ETags, gzip, request IDs, OpenAPI generation.

    [:octicons-arrow-right-24: Reference](http-api.md)

-   :material-clock-fast:{ .lg .middle } **Jobs & Realtime**

    ---

    Queues, the scheduler, WebSockets, mail.

    [:octicons-arrow-right-24: Reference](jobs-realtime.md)

-   :material-server-outline:{ .lg .middle } **Operations**

    ---

    Health checks, logging, error monitoring, caching, storage.

    [:octicons-arrow-right-24: Reference](operations.md)

-   :material-puzzle-outline:{ .lg .middle } **Extensibility**

    ---

    Console commands, the plugin registry, localization, the admin
    panel, AI integration.

    [:octicons-arrow-right-24: Reference](extensibility.md)

</div>

Most of these classes and functions are also re-exported from the
top-level `zeython` package, so `from zeython import Application` and
`from zeython.application import Application` reach the same object --
import from whichever is clearer at the call site.
