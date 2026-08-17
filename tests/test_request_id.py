import io
import logging
from pathlib import Path

from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.request_id import (
    RequestIdLogFilter,
    RequestIdMiddleware,
    RequestIdServiceProvider,
    _install_log_filter,
    request_id,
)
from zeython.testing import client


def _make_app(tmp_path: Path, **middleware_kwargs) -> Application:
    app = Application(Config.load(tmp_path))
    app.add_middleware(RequestIdMiddleware, **middleware_kwargs)

    @app.get("/")
    async def index(request):
        return JSONResponse({"request_id": request_id()})

    return app


# -- Header stamping ------------------------------------------------------------------------


async def test_a_request_with_no_header_gets_a_generated_id(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/")
        response_id = response.headers["X-Request-ID"]
        assert response_id  # non-empty
        assert response.json()["request_id"] == response_id


async def test_the_callers_own_header_is_echoed_back_unchanged(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/", headers={"X-Request-ID": "caller-supplied-id"})
        assert response.headers["X-Request-ID"] == "caller-supplied-id"
        assert response.json()["request_id"] == "caller-supplied-id"


async def test_two_requests_with_no_header_get_different_ids(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        first = await http.get("/")
        second = await http.get("/")
        assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


async def test_header_name_is_configurable(tmp_path: Path) -> None:
    app = _make_app(tmp_path, header_name="X-Correlation-ID")

    async with client(app) as http:
        response = await http.get("/", headers={"X-Correlation-ID": "abc"})
        assert response.headers["X-Correlation-ID"] == "abc"
        assert "X-Request-ID" not in response.headers


async def test_request_id_is_none_outside_of_a_request() -> None:
    assert request_id() is None


# -- Wired via RequestIdServiceProvider ------------------------------------------------------


async def test_service_provider_stamps_a_header(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))
    app.register(RequestIdServiceProvider)

    @app.get("/")
    async def index(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        response = await http.get("/")
        assert response.headers["X-Request-ID"]


async def test_service_provider_reads_a_configurable_header_name(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("APP_SECRET_KEY=test\nREQUEST_ID_HEADER=X-Trace-ID\n")
    app = Application(Config.load(tmp_path))
    app.register(RequestIdServiceProvider)

    @app.get("/")
    async def index(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        response = await http.get("/")
        assert response.headers["X-Trace-ID"]
        assert "X-Request-ID" not in response.headers


# -- Logging context --------------------------------------------------------------------------


def test_log_filter_attaches_the_current_request_id_to_a_record() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", None, None)
    filtr = RequestIdLogFilter()

    filtr.filter(record)
    assert record.request_id == "-"  # no request in flight


async def test_log_filter_sees_the_id_set_by_the_middleware_during_a_request(tmp_path: Path) -> None:
    captured: list[str] = []

    class _CapturingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(getattr(record, "request_id", "MISSING"))

    logger = logging.getLogger("test_request_id_capture")
    logger.setLevel(logging.INFO)
    handler = _CapturingHandler()
    handler.addFilter(RequestIdLogFilter())
    logger.addHandler(handler)
    logger.propagate = False

    app = _make_app(tmp_path)

    @app.get("/log")
    async def do_log(request):
        logger.info("inside a request")
        return JSONResponse({"request_id": request_id()})

    try:
        async with client(app) as http:
            response = await http.get("/log")
            assert captured == [response.headers["X-Request-ID"]]
    finally:
        logger.removeHandler(handler)


def test_install_log_filter_handles_records_propagated_from_a_child_logger() -> None:
    # Regression test: the filter must be attached to each root *handler*,
    # not to the root *logger* -- a Logger-level filter only runs for
    # records that logger originates directly via its own .info()/etc.,
    # never for records propagated up from a child logger's .callHandlers(),
    # which is how almost every real log line (uvicorn's, an app module's
    # own __name__ logger) actually reaches the root handlers. Caught by a
    # real E2E run: a generated project crashed with `KeyError: 'request_id'`
    # on its very first uvicorn log line once the format string included
    # %(request_id)s but the filter never got a chance to set it.
    original_handlers = logging.root.handlers[:]
    original_level = logging.root.level
    logging.root.handlers = []
    try:
        buffer = io.StringIO()
        handler = logging.StreamHandler(buffer)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
        logging.root.addHandler(handler)
        logging.root.setLevel(logging.INFO)

        _install_log_filter()

        child = logging.getLogger("zeython_test_request_id_child_logger")
        child.setLevel(logging.INFO)
        child.handlers = []
        child.propagate = True

        child.info("hello from a child logger")  # must not raise

        assert "[-]" in buffer.getvalue()
    finally:
        logging.root.handlers = original_handlers
        logging.root.setLevel(original_level)
