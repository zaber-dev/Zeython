from pathlib import Path

from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.security_headers import SecurityHeadersMiddleware, SecurityHeadersServiceProvider
from zeython.testing import client


def _make_app(tmp_path: Path, **middleware_kwargs) -> Application:
    app = Application(Config.load(tmp_path))
    app.add_middleware(SecurityHeadersMiddleware, **middleware_kwargs)

    @app.get("/")
    async def index(request):
        return JSONResponse({"ok": True})

    return app


# -- Defaults -----------------------------------------------------------------------------


async def test_default_headers_are_present(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


async def test_csp_is_unset_by_default(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/")
        assert "Content-Security-Policy" not in response.headers


async def test_hsts_is_unset_by_default(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/")
        assert "Strict-Transport-Security" not in response.headers


# -- Configuring each header ----------------------------------------------------------------


async def test_content_security_policy_is_sent_when_provided(tmp_path: Path) -> None:
    app = _make_app(tmp_path, content_security_policy="default-src 'self'")

    async with client(app) as http:
        response = await http.get("/")
        assert response.headers["Content-Security-Policy"] == "default-src 'self'"


async def test_frame_options_can_be_overridden(tmp_path: Path) -> None:
    app = _make_app(tmp_path, frame_options="SAMEORIGIN")

    async with client(app) as http:
        response = await http.get("/")
        assert response.headers["X-Frame-Options"] == "SAMEORIGIN"


async def test_frame_options_none_omits_the_header(tmp_path: Path) -> None:
    app = _make_app(tmp_path, frame_options=None)

    async with client(app) as http:
        response = await http.get("/")
        assert "X-Frame-Options" not in response.headers


async def test_content_type_options_false_omits_the_header(tmp_path: Path) -> None:
    app = _make_app(tmp_path, content_type_options=False)

    async with client(app) as http:
        response = await http.get("/")
        assert "X-Content-Type-Options" not in response.headers


async def test_referrer_policy_can_be_overridden(tmp_path: Path) -> None:
    app = _make_app(tmp_path, referrer_policy="no-referrer")

    async with client(app) as http:
        response = await http.get("/")
        assert response.headers["Referrer-Policy"] == "no-referrer"


async def test_referrer_policy_none_omits_the_header(tmp_path: Path) -> None:
    app = _make_app(tmp_path, referrer_policy=None)

    async with client(app) as http:
        response = await http.get("/")
        assert "Referrer-Policy" not in response.headers


async def test_hsts_true_sends_the_header_with_the_max_age(tmp_path: Path) -> None:
    app = _make_app(tmp_path, hsts=True, hsts_max_age=600)

    async with client(app) as http:
        response = await http.get("/")
        assert response.headers["Strict-Transport-Security"] == "max-age=600; includeSubDomains"


# -- Wired via SecurityHeadersServiceProvider, not registered by default ------------------


async def test_service_provider_reads_config_and_applies_headers(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test\n"
        "SECURITY_HEADERS_CSP=default-src 'self'\n"
        "SECURITY_HEADERS_FRAME_OPTIONS=SAMEORIGIN\n"
        "SECURITY_HEADERS_HSTS=true\n"
        "SECURITY_HEADERS_HSTS_MAX_AGE=3600\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(SecurityHeadersServiceProvider)

    @app.get("/")
    async def index(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        response = await http.get("/")
        assert response.headers["Content-Security-Policy"] == "default-src 'self'"
        assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
        assert response.headers["Strict-Transport-Security"] == "max-age=3600; includeSubDomains"


async def test_not_registered_by_default_means_no_headers(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))

    @app.get("/")
    async def index(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        response = await http.get("/")
        assert "X-Frame-Options" not in response.headers
        assert "X-Content-Type-Options" not in response.headers
