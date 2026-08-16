from pathlib import Path

from zeython.application import Application
from zeython.config import Config
from zeython.providers import ViewServiceProvider
from zeython.testing import client
from zeython.views import Views, render


def _make_app(tmp_path: Path) -> Application:
    return Application(Config.load(tmp_path), base_path=tmp_path)


async def test_render_returns_html_from_a_template(tmp_path: Path) -> None:
    views_dir = tmp_path / "resources" / "views"
    views_dir.mkdir(parents=True)
    (views_dir / "hello.html").write_text("<h1>Hello {{ name }}</h1>")

    app = _make_app(tmp_path)
    app.register(ViewServiceProvider)

    @app.get("/hello")
    async def hello(request):
        return render(request, "hello.html", {"name": "Ada"})

    async with client(app) as http:
        response = await http.get("/hello")

    assert response.status_code == 200
    assert "Hello Ada" in response.text
    assert response.headers["content-type"].startswith("text/html")


async def test_views_path_is_configurable(tmp_path: Path) -> None:
    custom_dir = tmp_path / "custom_templates"
    custom_dir.mkdir()
    (custom_dir / "page.html").write_text("custom directory works")

    (tmp_path / ".env").write_text(f"VIEWS_PATH={custom_dir}\n")
    app = _make_app(tmp_path)
    app.register(ViewServiceProvider)

    @app.get("/page")
    async def page(request):
        return render(request, "page.html")

    async with client(app) as http:
        response = await http.get("/page")

    assert response.status_code == 200
    assert "custom directory works" in response.text


def test_views_object_can_be_used_directly(tmp_path: Path) -> None:
    (tmp_path / "direct.html").write_text("direct")
    views = Views(tmp_path)

    assert views.directory == tmp_path
