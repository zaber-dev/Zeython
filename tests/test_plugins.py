"""Tests for zeython.plugins -- discovering third-party ServiceProviders
declared under the "zeython.plugins" entry-point group.

entry_points() itself isn't exercised against a real installed package here
(that would mean shipping a second throwaway distribution into the test
environment) -- monkeypatched fakes cover discover_plugins()'s own logic,
and the docs/plugins.md walkthrough is E2E-verified separately against a
real pip-installed plugin package.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from zeython.application import Application
from zeython.config import Config
from zeython.plugins import PluginServiceProvider, discover_plugins
from zeython.providers import ServiceProvider


class _FakeEntryPoint:
    def __init__(self, value: Any) -> None:
        self._value = value

    def load(self) -> Any:
        return self._value


class _RecordingPlugin(ServiceProvider):
    events: list[str] = []

    def register(self) -> None:
        _RecordingPlugin.events.append("register")

    def boot(self) -> None:
        _RecordingPlugin.events.append("boot")


def _app(tmp_path: Path) -> Application:
    (tmp_path / ".env").write_text("APP_SECRET_KEY=test\n")
    return Application(Config.load(tmp_path))


def test_discover_plugins_returns_nothing_when_none_are_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("zeython.plugins.entry_points", lambda group: [])

    assert discover_plugins() == []


def test_discover_plugins_loads_every_entry_point_in_the_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "zeython.plugins.entry_points",
        lambda group: [_FakeEntryPoint(_RecordingPlugin)] if group == "zeython.plugins" else [],
    )

    assert discover_plugins() == [_RecordingPlugin]


def test_plugin_service_provider_registers_every_discovered_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _RecordingPlugin.events = []
    monkeypatch.setattr("zeython.plugins.entry_points", lambda group: [_FakeEntryPoint(_RecordingPlugin)])
    app = _app(tmp_path)

    app.register(PluginServiceProvider)

    assert any(isinstance(provider, _RecordingPlugin) for provider in app.providers)
    assert _RecordingPlugin.events == ["register"]


def test_discovered_plugins_boot_during_the_apps_normal_boot_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _RecordingPlugin.events = []
    monkeypatch.setattr("zeython.plugins.entry_points", lambda group: [_FakeEntryPoint(_RecordingPlugin)])
    app = _app(tmp_path)
    app.register(PluginServiceProvider)

    app.boot()

    assert _RecordingPlugin.events == ["register", "boot"]


def test_plugin_service_provider_is_a_noop_with_no_plugins_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("zeython.plugins.entry_points", lambda group: [])
    app = _app(tmp_path)

    app.register(PluginServiceProvider)
    app.boot()

    assert len(app.providers) == 1  # just PluginServiceProvider itself
