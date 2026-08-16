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


__all__ = ["Rule", "required", "min_length", "max_length", "email", "one_of", "matches"]
