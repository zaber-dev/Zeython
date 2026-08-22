"""Direct tests for zeython.exceptions -- previously only exercised
indirectly through whichever handler happened to raise one of these
(auth's require_auth, storage validation, rate limiting, ...), never the
module's own default/status-code contract or the two exception handlers
themselves in isolation.
"""

import json
from http import HTTPStatus
from pathlib import Path

from zeython.application import Application
from zeython.config import Config
from zeython.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    HTTPException,
    MethodNotAllowedException,
    NotFoundException,
    TooManyRequestsException,
    UnauthorizedException,
    ValidationException,
    default_exception_handlers,
    http_exception_handler,
    unhandled_exception_handler,
)
from zeython.testing import client

# -- Each subclass's status code / default detail --------------------------------------


def test_bad_request_exception_defaults() -> None:
    exc = BadRequestException()
    assert exc.status_code == 400
    assert exc.detail == "The request could not be understood."


def test_unauthorized_exception_defaults() -> None:
    exc = UnauthorizedException()
    assert exc.status_code == 401
    assert exc.detail == "Authentication is required."


def test_forbidden_exception_defaults() -> None:
    exc = ForbiddenException()
    assert exc.status_code == 403
    assert exc.detail == "You do not have permission to perform this action."


def test_not_found_exception_defaults() -> None:
    exc = NotFoundException()
    assert exc.status_code == 404
    assert exc.detail == "The requested resource was not found."


def test_method_not_allowed_exception_defaults() -> None:
    exc = MethodNotAllowedException()
    assert exc.status_code == 405
    assert exc.detail == "This HTTP method is not allowed for this route."


def test_conflict_exception_defaults() -> None:
    exc = ConflictException()
    assert exc.status_code == 409
    assert exc.detail == "The request conflicts with the current state of the resource."


def test_validation_exception_defaults() -> None:
    exc = ValidationException()
    assert exc.status_code == 422
    assert exc.detail == "The given data was invalid."
    assert exc.errors == {}


def test_too_many_requests_exception_defaults() -> None:
    exc = TooManyRequestsException()
    assert exc.status_code == 429
    assert exc.detail == "Too many requests. Please try again later."


def test_a_custom_detail_overrides_the_default() -> None:
    exc = NotFoundException("No post with that id.")
    assert exc.detail == "No post with that id."


def test_headers_default_to_an_empty_dict() -> None:
    exc = ForbiddenException()
    assert exc.headers == {}


def test_headers_are_stored_when_provided() -> None:
    exc = TooManyRequestsException(headers={"Retry-After": "30"})
    assert exc.headers == {"Retry-After": "30"}


def test_validation_exception_stores_field_errors() -> None:
    exc = ValidationException({"email": ["is required"]})
    assert exc.errors == {"email": ["is required"]}


# -- http_exception_handler --------------------------------------------------------------


async def test_http_exception_handler_renders_status_and_detail(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))

    @app.get("/boom")
    async def boom(request):
        raise ConflictException("Already exists.")

    async with client(app) as http:
        response = await http.get("/boom")
        assert response.status_code == 409
        assert response.json() == {"error": "Already exists.", "status": 409}


async def test_http_exception_handler_includes_field_errors_for_validation_exceptions(
    tmp_path: Path,
) -> None:
    app = Application(Config.load(tmp_path))

    @app.get("/invalid")
    async def invalid(request):
        raise ValidationException({"email": ["is required"]})

    async with client(app) as http:
        response = await http.get("/invalid")
        assert response.status_code == 422
        assert response.json()["errors"] == {"email": ["is required"]}


async def test_http_exception_handler_omits_errors_key_when_there_are_none(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))

    @app.get("/invalid")
    async def invalid(request):
        raise ValidationException()

    async with client(app) as http:
        response = await http.get("/invalid")
        assert "errors" not in response.json()


async def test_http_exception_handler_sends_custom_headers(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))

    @app.get("/throttled")
    async def throttled(request):
        raise TooManyRequestsException(headers={"Retry-After": "5"})

    async with client(app) as http:
        response = await http.get("/throttled")
        assert response.headers["Retry-After"] == "5"


# -- API_PROBLEM_JSON=true (RFC 7807) --------------------------------------------------


async def test_default_error_format_is_unchanged_without_api_problem_json(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))

    @app.get("/boom")
    async def boom(request):
        raise NotFoundException("gone")

    async with client(app) as http:
        response = await http.get("/boom")
        assert response.headers["content-type"] == "application/json"
        assert response.json() == {"error": "gone", "status": 404}


async def test_api_problem_json_renders_rfc7807_shape(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("API_PROBLEM_JSON=true\n")
    app = Application(Config.load(tmp_path))

    @app.get("/boom")
    async def boom(request):
        raise NotFoundException("gone")

    async with client(app) as http:
        response = await http.get("/boom")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": "gone",
    }


async def test_api_problem_json_includes_errors_extension_for_validation(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("API_PROBLEM_JSON=true\n")
    app = Application(Config.load(tmp_path))

    @app.get("/invalid")
    async def invalid(request):
        raise ValidationException({"email": ["is required"]})

    async with client(app) as http:
        response = await http.get("/invalid")

    body = response.json()
    assert body["title"] == HTTPStatus(422).phrase
    assert body["errors"] == {"email": ["is required"]}


async def test_api_problem_json_preserves_custom_headers(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("API_PROBLEM_JSON=true\n")
    app = Application(Config.load(tmp_path))

    @app.get("/throttled")
    async def throttled(request):
        raise TooManyRequestsException(headers={"Retry-After": "5"})

    async with client(app) as http:
        response = await http.get("/throttled")

    assert response.headers["Retry-After"] == "5"


async def test_api_problem_json_for_unhandled_exception_called_directly(tmp_path: Path) -> None:
    class _FakeState:
        debug = False
        config = Config.load(tmp_path, env_file=".env-problem-json")

    class _FakeApp:
        state = _FakeState()

    class _FakeRequest:
        app = _FakeApp()

    (tmp_path / ".env-problem-json").write_text("API_PROBLEM_JSON=true\n")
    _FakeState.config = Config.load(tmp_path, env_file=".env-problem-json")

    response = await unhandled_exception_handler(_FakeRequest(), ValueError("boom"))

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    body = json.loads(response.body)
    assert body == {
        "type": "about:blank",
        "title": "Internal Server Error",
        "status": 500,
        "detail": "An unexpected error occurred.",
    }


async def test_api_problem_json_includes_exception_detail_in_debug(tmp_path: Path) -> None:
    class _FakeState:
        debug = True
        config = Config.load(tmp_path, env_file=".env-problem-json-debug")

    class _FakeApp:
        state = _FakeState()

    class _FakeRequest:
        app = _FakeApp()

    (tmp_path / ".env-problem-json-debug").write_text("API_PROBLEM_JSON=true\n")
    _FakeState.config = Config.load(tmp_path, env_file=".env-problem-json-debug")

    response = await unhandled_exception_handler(_FakeRequest(), ValueError("boom"))

    body = json.loads(response.body)
    assert body["exception"] == "ValueError: boom"
    assert body["traceback"] == ["ValueError: boom\n"]


async def test_api_problem_json_omits_traceback_when_not_debug(tmp_path: Path) -> None:
    class _FakeState:
        debug = False
        config = Config.load(tmp_path, env_file=".env-problem-json-no-debug")

    class _FakeApp:
        state = _FakeState()

    class _FakeRequest:
        app = _FakeApp()

    (tmp_path / ".env-problem-json-no-debug").write_text("API_PROBLEM_JSON=true\n")
    _FakeState.config = Config.load(tmp_path, env_file=".env-problem-json-no-debug")

    response = await unhandled_exception_handler(_FakeRequest(), ValueError("boom"))

    body = json.loads(response.body)
    assert "traceback" not in body
    assert "exception" not in body


# -- unhandled_exception_handler -----------------------------------------------------------
#
# Not exercisable end-to-end through zeython.testing.client(): httpx's
# ASGITransport defaults to raise_server_exceptions=True, and Starlette's
# ServerErrorMiddleware always re-raises the original exception to the test
# transport after handling it (a deliberate Starlette behavior -- so a
# route's bug fails the test loudly instead of being silently swallowed by
# its own 500 handler), regardless of whether a registered Exception
# handler produced a response. A real deployed app never has this
# transport-level re-raise -- see the direct function-level tests below,
# and docs/testing.md doesn't claim this handler is client()-testable.


# -- default_exception_handlers / handler functions in isolation ---------------------------


def test_default_exception_handlers_maps_http_exception_and_exception() -> None:
    handlers = default_exception_handlers()
    assert handlers[HTTPException] is http_exception_handler
    assert handlers[Exception] is unhandled_exception_handler


async def test_http_exception_handler_called_directly_builds_a_json_response() -> None:
    response = await http_exception_handler(None, NotFoundException("gone"))
    assert response.status_code == 404
    assert response.body == b'{"error":"gone","status":404}'


async def test_unhandled_exception_handler_called_directly_defaults_to_no_debug_info() -> None:
    class _FakeState:
        pass

    class _FakeApp:
        state = _FakeState()

    class _FakeRequest:
        app = _FakeApp()

    response = await unhandled_exception_handler(_FakeRequest(), ValueError("boom"))
    assert response.status_code == 500
    assert b"exception" not in response.body
    assert b"traceback" not in response.body


async def test_unhandled_exception_handler_called_directly_includes_exception_detail_in_debug() -> None:
    class _FakeState:
        debug = True

    class _FakeApp:
        state = _FakeState()

    class _FakeRequest:
        app = _FakeApp()

    response = await unhandled_exception_handler(_FakeRequest(), ValueError("boom"))
    assert response.status_code == 500
    body = json.loads(response.body)
    assert body["exception"] == "ValueError: boom"
    assert body["traceback"] == ["ValueError: boom\n"]


async def test_unhandled_exception_handler_traceback_includes_real_frames_in_debug() -> None:
    class _FakeState:
        debug = True

    class _FakeApp:
        state = _FakeState()

    class _FakeRequest:
        app = _FakeApp()

    def _raise() -> None:
        raise ValueError("boom")

    try:
        _raise()
    except ValueError as exc:
        response = await unhandled_exception_handler(_FakeRequest(), exc)

    body = json.loads(response.body)
    full_traceback = "".join(body["traceback"])
    assert "Traceback (most recent call last):" in full_traceback
    assert "_raise" in full_traceback
    assert "ValueError: boom" in full_traceback


# -- unhandled_exception_handler: HTML debug page ------------------------------------


class _FakeURL:
    path = "/broken"


class _FakeHtmlRequest:
    method = "GET"
    url = _FakeURL()
    headers = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

    class app:  # noqa: N801
        class state:
            debug = True


def _raise_boom() -> None:
    raise ValueError("boom")


async def test_html_debug_page_rendered_for_browser_request_in_debug_mode() -> None:
    try:
        _raise_boom()
    except ValueError as exc:
        response = await unhandled_exception_handler(_FakeHtmlRequest(), exc)

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("text/html")

    body = response.body.decode()
    assert "ValueError" in body
    assert "boom" in body
    assert "_raise_boom" in body
    assert "GET /broken" in body


async def test_html_debug_page_omitted_when_debug_is_false() -> None:
    class _FakeRequest(_FakeHtmlRequest):
        class app:  # noqa: N801
            class state:
                debug = False

    response = await unhandled_exception_handler(_FakeRequest(), ValueError("boom"))

    assert response.headers["content-type"].startswith("application/json")


async def test_html_debug_page_omitted_for_non_html_accept_header() -> None:
    class _FakeRequest(_FakeHtmlRequest):
        headers = {"accept": "application/json"}

    response = await unhandled_exception_handler(_FakeRequest(), ValueError("boom"))

    assert response.headers["content-type"].startswith("application/json")


async def test_problem_json_takes_priority_over_html_debug_page(tmp_path: Path) -> None:
    (tmp_path / ".env-problem-json-html").write_text("API_PROBLEM_JSON=true\n")
    config = Config.load(tmp_path, env_file=".env-problem-json-html")

    class _FakeRequest(_FakeHtmlRequest):
        class app:  # noqa: N801
            class state:
                debug = True

    _FakeRequest.app.state.config = config

    response = await unhandled_exception_handler(_FakeRequest(), ValueError("boom"))

    assert response.headers["content-type"].startswith("application/problem+json")
