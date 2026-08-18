from zeython import (
    ApiAuthServiceProvider,
    Application,
    AuthorizationServiceProvider,
    AuthServiceProvider,
    CacheServiceProvider,
    DatabaseServiceProvider,
    HealthCheckServiceProvider,
    MailServiceProvider,
    OpenApiServiceProvider,
    QueueServiceProvider,
    RateLimitServiceProvider,
    RequestIdServiceProvider,
    RouteServiceProvider,
    StorageServiceProvider,
    ViewServiceProvider,
    WebSocketHubServiceProvider,
)

from app.Models.user import User
from app.Providers.post_policy_service_provider import PostPolicyServiceProvider

app = Application()
app.register(HealthCheckServiceProvider)
# Stamps every request/response with an X-Request-ID and threads it into
# the logs -- see docs/observability.md.
app.register(RequestIdServiceProvider)
app.register(DatabaseServiceProvider)
app.register(ViewServiceProvider)
app.register(StorageServiceProvider)
app.register(CacheServiceProvider)
app.register(RateLimitServiceProvider)
app.register(MailServiceProvider)
app.register(QueueServiceProvider)
app.register(WebSocketHubServiceProvider)
app.register(AuthServiceProvider(app, user_model=User))
app.register(ApiAuthServiceProvider(app, user_model=User))
app.register(AuthorizationServiceProvider)
app.register(PostPolicyServiceProvider(app))
app.register(RouteServiceProvider(app, modules=("routes.web",)))
# Live at /docs (Swagger UI) and /openapi.json -- see docs/openapi.md.
# OPENAPI_ENABLED=false in .env turns both off, e.g. in production.
app.register(OpenApiServiceProvider(app, title=app.config.app_name))
# Opt-in CSP/X-Frame-Options/HSTS response headers -- not registered by
# default since a wrong Content-Security-Policy breaks a legitimate app
# silently. Uncomment (and `from zeython import SecurityHeadersServiceProvider`
# above) once you've decided on your own policy, then set it via
# SECURITY_HEADERS_CSP in .env. See docs/security-headers.md.
# app.register(SecurityHeadersServiceProvider)
# Recurring tasks defined in code, run via `zeython schedule run` -- not
# registered by default since there's no schedule.py until you create one
# (and `from zeython import ScheduleServiceProvider` above). See
# docs/scheduling.md.
# app.register(ScheduleServiceProvider(app))
# Reports unhandled exceptions/exhausted job retries/raising scheduled
# tasks to Sentry -- not registered by default since there's no SENTRY_DSN
# until you have a Sentry project (and `pip install zeython[sentry]` plus
# `from zeython import ErrorMonitoringServiceProvider` above). See
# docs/error-monitoring.md.
# app.register(ErrorMonitoringServiceProvider(app))

if __name__ == "__main__":
    app.run()
