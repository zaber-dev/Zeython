"""Declarative validation rules for :class:`zeython.db.Model` fields."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

Check = Callable[[Any], bool]


class Rule:
    """A single named validation rule with a default error message."""

    def __init__(self, check: Check, message: str) -> None:
        self.check = check
        self.message = message

    def __call__(self, value: Any) -> bool:
        return self.check(value)


def required(message: str = "This field is required.") -> Rule:
    return Rule(lambda value: value is not None and value != "", message)


def min_length(length: int, message: str | None = None) -> Rule:
    return Rule(
        lambda value: value is None or len(str(value)) >= length,
        message or f"Must be at least {length} characters.",
    )


def max_length(length: int, message: str | None = None) -> Rule:
    return Rule(
        lambda value: value is None or len(str(value)) <= length,
        message or f"Must be at most {length} characters.",
    )


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def email(message: str = "Must be a valid email address.") -> Rule:
    return Rule(lambda value: value is not None and bool(_EMAIL_RE.match(str(value))), message)


def one_of(choices: tuple[Any, ...], message: str | None = None) -> Rule:
    return Rule(
        lambda value: value is None or value in choices,
        message or f"Must be one of: {', '.join(str(c) for c in choices)}.",
    )


def matches(pattern: str, message: str = "Invalid format.") -> Rule:
    compiled = re.compile(pattern)
    return Rule(lambda value: value is None or bool(compiled.match(str(value))), message)


def validate(data: dict[str, Any], rules: dict[str, list[Rule]]) -> dict[str, list[str]]:
    """Run declarative rules against a plain dict -- the same rule sets you'd
    write for :attr:`zeython.db.Model.__rules__`, applied to a request
    payload, query params, or any other dict that isn't (or isn't yet) a
    model instance. Does not raise; raise ``ValidationException(errors)``
    yourself if that's what you want when ``errors`` is non-empty.

    ``Model.validate()`` is this function applied to a model instance's own
    field values -- kept in sync with it deliberately, so a rule set means
    the same thing whether it's checked against a model or a plain dict.
    """
    errors: dict[str, list[str]] = {}
    for field, field_rules in rules.items():
        value = data.get(field)
        for rule in field_rules:
            if not rule(value):
                errors.setdefault(field, []).append(rule.message)
    return errors


__all__ = ["Rule", "required", "min_length", "max_length", "email", "one_of", "matches", "validate"]
