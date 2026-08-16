from zeython import (
    Application,
    AuthorizationServiceProvider,
    AuthServiceProvider,
    CacheServiceProvider,
    DatabaseServiceProvider,
    MailServiceProvider,
    QueueServiceProvider,
    RateLimitServiceProvider,
    RouteServiceProvider,
    StorageServiceProvider,
    ViewServiceProvider,
)

from app.Models.user import User
from app.Providers.post_policy_service_provider import PostPolicyServiceProvider

app = Application()
app.register(DatabaseServiceProvider)
app.register(ViewServiceProvider)
app.register(StorageServiceProvider)
app.register(CacheServiceProvider)
app.register(RateLimitServiceProvider)
app.register(MailServiceProvider)
app.register(QueueServiceProvider)
app.register(AuthServiceProvider(app, user_model=User))
app.register(AuthorizationServiceProvider)
app.register(PostPolicyServiceProvider(app))
app.register(RouteServiceProvider(app, modules=("routes.web",)))

if __name__ == "__main__":
    app.run()
