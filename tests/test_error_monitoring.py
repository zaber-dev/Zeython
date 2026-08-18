from pathlib import Path

import pytest

import zeython.error_monitoring as error_monitoring
from zeython.application import Application
from zeython.config import Config
from zeython.error_monitoring import ErrorMonitoringServiceProvider, init_sentry, report_exception

# -- report_exception() is always safe to call --------------------------------------


@pytest.fixture(autouse=True)
def _reset_initialized_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    # init_sentry() sets a module-level flag; isolate each test from
    # whatever an earlier test in this file left it as.
    monkeypatch.setattr(error_monitoring, "_initialized", False)


def test_report_exception_is_a_no_op_when_sentry_was_never_initialized() -> None:
    # Must not raise -- this is what makes it safe to call unconditionally
    # from exceptions.py/queue.py/schedule.py regardless of whether an app
    # configured error monitoring at all.
    report_exception(ValueError("boom"), some_tag="value")


def test_report_exception_ignores_none_valued_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    class _FakeScope:
        def set_tag(self, key: str, value: object) -> None:
            calls.append((key, value))

    class _FakeScopeManager:
        def __enter__(self) -> _FakeScope:
            return _FakeScope()

        def __exit__(self, *args: object) -> None:
            return None

    class _FakeSentrySdk:
        @staticmethod
        def new_scope() -> _FakeScopeManager:
            return _FakeScopeManager()

        @staticmethod
        def capture_exception(exc: BaseException) -> None:
            pass

    monkeypatch.setattr(error_monitoring, "_initialized", True)
    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", _FakeSentrySdk())

    report_exception(ValueError("boom"), present="yes", absent=None)

    assert calls == [("present", "yes")]


def test_report_exception_calls_capture_exception_when_initialized(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = []

    class _FakeScope:
        def set_tag(self, key: str, value: object) -> None:
            pass

    class _FakeScopeManager:
        def __enter__(self) -> _FakeScope:
            return _FakeScope()

        def __exit__(self, *args: object) -> None:
            return None

    class _FakeSentrySdk:
        @staticmethod
        def new_scope() -> _FakeScopeManager:
            return _FakeScopeManager()

        @staticmethod
        def capture_exception(exc: BaseException) -> None:
            captured.append(exc)

    monkeypatch.setattr(error_monitoring, "_initialized", True)
    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", _FakeSentrySdk())

    exc = ValueError("boom")
    report_exception(exc)

    assert captured == [exc]


# -- init_sentry() -------------------------------------------------------------------


def test_init_sentry_raises_a_clear_import_error_without_the_extra_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _fake_import(name: str, *args: object, **kwargs: object):
        if name == "sentry_sdk":
            raise ImportError("no module named sentry_sdk")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    with pytest.raises(ImportError, match=r"pip install zeython\[sentry\]"):
        init_sentry("https://example.com/1")


def test_init_sentry_calls_sentry_sdk_init_with_the_given_options(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    class _FakeSentrySdk:
        @staticmethod
        def init(**kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", _FakeSentrySdk())

    init_sentry("https://example.com/1", environment="production", release="1.0.0", traces_sample_rate=0.1)

    assert calls == [
        {
            "dsn": "https://example.com/1",
            "environment": "production",
            "release": "1.0.0",
            "traces_sample_rate": 0.1,
        }
    ]
    assert error_monitoring._initialized is True


# -- ErrorMonitoringServiceProvider ---------------------------------------------------


def test_provider_is_a_no_op_when_sentry_dsn_is_not_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(error_monitoring, "init_sentry", lambda *a, **kw: calls.append((a, kw)))

    app = Application(Config.load(tmp_path))
    ErrorMonitoringServiceProvider(app).register()

    assert calls == []


def test_provider_calls_init_sentry_when_sentry_dsn_is_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test\nSENTRY_DSN=https://example.com/1\nSENTRY_TRACES_SAMPLE_RATE=0.2\n"
    )
    calls = []
    monkeypatch.setattr(error_monitoring, "init_sentry", lambda *a, **kw: calls.append((a, kw)))

    app = Application(Config.load(tmp_path))
    ErrorMonitoringServiceProvider(app).register()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("https://example.com/1",)
    assert kwargs["traces_sample_rate"] == 0.2
