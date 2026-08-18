import json
import logging

from zeython.logging import JsonFormatter
from zeython.request_id import RequestIdLogFilter, _current_request_id


def _make_record(msg: str = "hello", *, level: int = logging.INFO, exc_info=None, extra: dict | None = None):
    record = logging.LogRecord(
        name="app.test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    for key, value in (extra or {}).items():
        setattr(record, key, value)
    return record


def test_formats_a_basic_record_as_json_with_the_expected_fields() -> None:
    payload = json.loads(JsonFormatter().format(_make_record("hello world")))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["message"] == "hello world"
    assert "timestamp" in payload


def test_message_formatting_applies_args_before_serializing() -> None:
    record = logging.LogRecord(
        name="app.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="order %s for %s", args=("42", "Ada"), exc_info=None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "order 42 for Ada"


def test_extra_fields_are_included_in_the_payload() -> None:
    record = _make_record(extra={"order_id": 42, "amount": 9.99})

    payload = json.loads(JsonFormatter().format(record))

    assert payload["order_id"] == 42
    assert payload["amount"] == 9.99


def test_extra_field_with_a_non_json_native_value_falls_back_to_str() -> None:
    class Unserializable:
        def __str__(self) -> str:
            return "unserializable-repr"

    record = _make_record(extra={"thing": Unserializable()})

    payload = json.loads(JsonFormatter().format(record))

    assert payload["thing"] == "unserializable-repr"


def test_exception_info_is_rendered_as_a_traceback_string() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _make_record("failed", level=logging.ERROR, exc_info=sys.exc_info())

    payload = json.loads(JsonFormatter().format(record))

    assert "ValueError: boom" in payload["exception"]


def test_no_exception_key_when_the_record_has_no_exc_info() -> None:
    payload = json.loads(JsonFormatter().format(_make_record()))

    assert "exception" not in payload


def test_no_request_id_key_when_the_record_has_no_request_id_attribute() -> None:
    payload = json.loads(JsonFormatter().format(_make_record()))

    assert "request_id" not in payload


def test_request_id_key_present_once_the_request_id_filter_has_run() -> None:
    record = _make_record()
    RequestIdLogFilter().filter(record)  # simulates what the installed handler filter does

    payload = json.loads(JsonFormatter().format(record))

    assert payload["request_id"] == "-"  # outside any request


def test_request_id_key_carries_the_current_requests_id() -> None:
    token = _current_request_id.set("abc-123")
    try:
        record = _make_record()
        RequestIdLogFilter().filter(record)
    finally:
        _current_request_id.reset(token)

    payload = json.loads(JsonFormatter().format(record))

    assert payload["request_id"] == "abc-123"


def test_each_log_line_is_valid_standalone_json_not_pretty_printed() -> None:
    line = JsonFormatter().format(_make_record())

    assert "\n" not in line
    json.loads(line)  # doesn't raise
