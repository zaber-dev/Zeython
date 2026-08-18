import json
import logging

from zeython.application import _QUIET_LOGGERS, _configure_default_logging
from zeython.config import Config
from zeython.logging import JsonFormatter


def test_configures_root_level_and_quiets_third_party_loggers(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(logging.root, "handlers", [], raising=False)
    for name in _QUIET_LOGGERS:
        monkeypatch.setattr(logging.getLogger(name), "level", logging.NOTSET, raising=False)

    _configure_default_logging(Config.load(tmp_path))

    for name in _QUIET_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING


def test_debug_true_sets_root_level_to_debug(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(logging.root, "handlers", [], raising=False)
    (tmp_path / ".env").write_text("APP_DEBUG=true\n")

    _configure_default_logging(Config.load(tmp_path))

    assert logging.root.level == logging.DEBUG


def test_debug_false_sets_root_level_to_info(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(logging.root, "handlers", [], raising=False)
    (tmp_path / ".env").write_text("APP_DEBUG=false\n")

    _configure_default_logging(Config.load(tmp_path))

    assert logging.root.level == logging.INFO


def test_does_not_override_an_already_configured_root_logger(monkeypatch, tmp_path) -> None:
    # A non-empty handlers list is exactly what `_configure_default_logging`
    # treats as "someone already set up logging" -- it must not touch level
    # or the quieted loggers in that case.
    monkeypatch.setattr(logging.root, "handlers", [logging.NullHandler()], raising=False)
    monkeypatch.setattr(logging.root, "level", logging.CRITICAL, raising=False)
    for name in _QUIET_LOGGERS:
        monkeypatch.setattr(logging.getLogger(name), "level", logging.NOTSET, raising=False)

    _configure_default_logging(Config.load(tmp_path))

    assert logging.root.level == logging.CRITICAL
    for name in _QUIET_LOGGERS:
        assert logging.getLogger(name).level == logging.NOTSET


# -- LOG_FORMAT=json ------------------------------------------------------------------


def test_default_log_format_uses_the_plain_text_formatter(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(logging.root, "handlers", [], raising=False)

    _configure_default_logging(Config.load(tmp_path))

    (handler,) = logging.root.handlers
    assert not isinstance(handler.formatter, JsonFormatter)


def test_log_format_json_installs_the_json_formatter(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(logging.root, "handlers", [], raising=False)
    (tmp_path / ".env").write_text("LOG_FORMAT=json\n")

    _configure_default_logging(Config.load(tmp_path))

    (handler,) = logging.root.handlers
    assert isinstance(handler.formatter, JsonFormatter)


def test_log_format_json_produces_valid_json_lines(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(logging.root, "handlers", [], raising=False)
    (tmp_path / ".env").write_text("LOG_FORMAT=json\n")

    _configure_default_logging(Config.load(tmp_path))
    logging.getLogger("test.json.format").info("hello %s", "world")

    line = capsys.readouterr().err.strip()
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.json.format"
    assert payload["message"] == "hello world"
