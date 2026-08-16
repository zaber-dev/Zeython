from zeython import Application, DatabaseServiceProvider, RouteServiceProvider, ViewServiceProvider

app = Application()
app.register(DatabaseServiceProvider)
app.register(ViewServiceProvider)
app.register(RouteServiceProvider(app, modules=("routes.web",)))

if __name__ == "__main__":
    app.run()
