from zeython import Application, DatabaseServiceProvider, RouteServiceProvider

app = Application()
app.register(DatabaseServiceProvider)
app.register(RouteServiceProvider(app, modules=("routes.web",)))

if __name__ == "__main__":
    app.run()
