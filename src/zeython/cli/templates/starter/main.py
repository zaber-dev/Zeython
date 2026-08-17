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
    RouteServiceProvider,
    StorageServiceProvider,
    ViewServiceProvider,
    WebSocketHubServiceProvider,
)

from app.Models.user import User
from app.Providers.post_policy_service_provider import PostPolicyServiceProvider

app = Application()
app.register(HealthCheckServiceProvider)
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

if __name__ == "__main__":
    app.run()
