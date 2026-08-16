from zeython import (
    Application,
    AuthServiceProvider,
    DatabaseServiceProvider,
    RouteServiceProvider,
    StorageServiceProvider,
    ViewServiceProvider,
)

from app.Models.user import User

app = Application()
app.register(DatabaseServiceProvider)
app.register(ViewServiceProvider)
app.register(StorageServiceProvider)
app.register(AuthServiceProvider(app, user_model=User))
app.register(RouteServiceProvider(app, modules=("routes.web",)))

if __name__ == "__main__":
    app.run()
