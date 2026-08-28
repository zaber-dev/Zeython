from zeython import (
    ApiAuthServiceProvider,
    Application,
    AuditLogServiceProvider,
    AuthorizationServiceProvider,
    AuthServiceProvider,
    CacheServiceProvider,
    DatabaseServiceProvider,
    HealthCheckServiceProvider,
    MailServiceProvider,
    MaintenanceModeServiceProvider,
    NotificationServiceProvider,
    OpenApiServiceProvider,
    QueueServiceProvider,
    RateLimitServiceProvider,
    RequestIdServiceProvider,
    RequestProfilerServiceProvider,
    RouteServiceProvider,
    StorageServiceProvider,
    ViewServiceProvider,
    WebSocketHubServiceProvider,
)

from app.Models.notification import Notification
from app.Models.user import User
from app.Providers.app_audit_service_provider import AppAuditServiceProvider
from app.Providers.app_event_service_provider import AppEventServiceProvider
from app.Providers.app_feature_service_provider import AppFeatureServiceProvider
from app.Providers.post_policy_service_provider import PostPolicyServiceProvider

app = Application()
app.register(HealthCheckServiceProvider)
# Stamps every request/response with an X-Request-ID and threads it into
# the logs -- see docs/observability.md.
app.register(RequestIdServiceProvider)
# Registered before DatabaseServiceProvider deliberately: add_middleware()
# prepends (most recently registered wraps outermost), and resolving the
# current actor needs a database session already open -- see
# AuditLogServiceProvider's own docstring for why this one has to come
# first among middleware-adding providers, not last like maintenance mode
# below. Its own boot() only adds a middleware that sets a contextvar
# nothing reads until a model actually calls Model.observe(AuditObserver(...))
# (see AppAuditServiceProvider below), so it's safe to always register --
# see docs/audit-log.md.
app.register(AuditLogServiceProvider)
app.register(DatabaseServiceProvider)
# X-Debug-Duration-Ms/X-Debug-Query-Count/X-Debug-Query-Time-Ms on every
# response, plus the queries a crashed request ran shown on its debug
# page -- see docs/profiling.md. Its own boot() is a no-op unless
# APP_DEBUG is true, same as RequestIdServiceProvider above: nothing to
# get wrong by always registering it.
app.register(RequestProfilerServiceProvider(app))
app.register(ViewServiceProvider)
app.register(StorageServiceProvider)
app.register(CacheServiceProvider)
app.register(RateLimitServiceProvider)
app.register(MailServiceProvider)
app.register(QueueServiceProvider)
app.register(WebSocketHubServiceProvider)
# Multi-channel notifications (mail/database/broadcast) -- see
# docs/notifications.md. `record_model` is the Model the "database"
# channel writes to (app/Models/notification.py); omit it if you only
# ever use "mail"/"broadcast".
app.register(NotificationServiceProvider(app, record_model=Notification))
# Decoupled listeners reacting to app-defined events (UserRegistered, ...)
# -- see docs/events.md. AppEventServiceProvider (app/Providers/) is where
# this app's own listeners are registered.
app.register(AppEventServiceProvider(app))
# Feature flags -- see docs/feature-flags.md. AppFeatureServiceProvider
# (app/Providers/) is where this app's own flags are defined.
app.register(AppFeatureServiceProvider(app))
app.register(AuthServiceProvider(app, user_model=User))
app.register(ApiAuthServiceProvider(app, user_model=User))
app.register(AuthorizationServiceProvider)
app.register(PostPolicyServiceProvider(app))
# Automatic create/update/delete changelog for the models named here --
# see docs/audit-log.md. AppAuditServiceProvider (app/Providers/) is where
# this app's own audited models are declared.
app.register(AppAuditServiceProvider(app))
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
# Dev-only warning when a request fires the same query shape suspiciously
# many times -- catches a forgotten include=(...) before it ships. Its
# own boot() is a no-op unless APP_DEBUG is true, so it's safe to always
# register (and `from zeython import N1QueryDetectionServiceProvider`
# above). See docs/relationships.md#detecting-n1s-automatically.
# app.register(N1QueryDetectionServiceProvider(app))
# Response compression and conditional-GET (ETag/If-None-Match -> 304)
# support -- neither registered by default (and `from zeython import
# GzipServiceProvider, ETagServiceProvider` above). See
# docs/api-standards.md.
# app.register(GzipServiceProvider)
# app.register(ETagServiceProvider)
# Registers every third-party provider a `pip install`ed plugin package
# declares under the "zeython.plugins" entry point -- not registered by
# default since a fresh project has no plugins installed yet (and
# `from zeython import PluginServiceProvider` above). See docs/plugins.md.
# app.register(PluginServiceProvider)
# Translation strings from resources/lang/{locale}.json, and per-request
# locale resolution (?lang=, then Accept-Language, then LOCALE_DEFAULT) --
# not registered by default since a fresh project has no translation
# files yet (and `from zeython import LocalizationServiceProvider` above).
# See docs/localization.md.
# app.register(LocalizationServiceProvider)
# Generates list/create/edit/delete pages for the given models -- not
# registered by default since `guard` (who's allowed in, beyond just being
# logged in) has no safe default to guess. Uncomment, pick a real guard,
# and add `from zeython import AdminServiceProvider` and
# `from app.Models.post import Post` above. See docs/admin.md.
# app.register(AdminServiceProvider(app, models=[Post], guard=lambda user: user.is_admin))
# Row-level multi-tenancy: a model opts in by declaring a `tenant_id`
# column (no mixin needed) and its queries scope to whatever `resolver`
# returns for the request automatically. Not registered by default since
# `resolver` (how a request maps to a tenant) has no safe default to
# guess. Uncomment, pick a real resolver, and add
# `from zeython import TenancyServiceProvider` above. See docs/multi-tenancy.md.
# app.register(TenancyServiceProvider(app, resolver=lambda request: request.headers.get("X-Tenant-ID")))

# `zeython down`/`zeython up` -- see docs/maintenance-mode.md. Kept as the
# very last registration in this file deliberately: the most recently
# registered middleware wraps outermost, and maintenance mode needs to
# intercept a request before anything else runs (including opening a
# database session) -- keep any new middleware-adding provider you add
# above this line, not below it. Its own boot() is a no-op unless
# storage/framework/down.json exists, so it's safe to always register.
app.register(MaintenanceModeServiceProvider)

if __name__ == "__main__":
    app.run()
