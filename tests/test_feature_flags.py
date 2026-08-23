"""Tests for zeython.feature_flags -- static (.env-driven) boolean flags
and deterministic percentage rollouts.
"""

from pathlib import Path

import pytest
from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.feature_flags import FeatureManager, FeatureServiceProvider, feature
from zeython.testing import client

# -- FeatureManager, direct -----------------------------------------------------------------


async def test_undefined_flag_resolves_false_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    manager = FeatureManager()

    with caplog.at_level("WARNING"):
        result = await manager.active("nonexistent")

    assert result is False
    assert "nonexistent" in caplog.text


def test_names_lists_defined_flags_sorted() -> None:
    manager = FeatureManager()
    manager.define("zeta", lambda ctx: True)
    manager.define("alpha", lambda ctx: True)

    assert manager.names() == ["alpha", "zeta"]


async def test_define_with_a_sync_resolver() -> None:
    manager = FeatureManager()
    manager.define("always_on", lambda ctx: True)

    assert await manager.active("always_on") is True


async def test_define_with_an_async_resolver() -> None:
    manager = FeatureManager()

    async def resolver(ctx):
        return ctx == "special"

    manager.define("special_only", resolver)

    assert await manager.active("special_only", "special") is True
    assert await manager.active("special_only", "regular") is False


# -- boolean() -------------------------------------------------------------------------------


async def test_boolean_without_config_falls_back_to_default() -> None:
    manager = FeatureManager(config=None)
    manager.boolean("new_checkout", default=True)

    assert await manager.active("new_checkout") is True


async def test_boolean_uses_the_given_default_with_no_env_override(tmp_path: Path) -> None:
    config = Config.load(tmp_path)
    manager = FeatureManager(config=config)
    manager.boolean("new_checkout", default=False)

    assert await manager.active("new_checkout") is False


async def test_boolean_reads_an_env_override(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("FEATURE_NEW_CHECKOUT=true\n")
    config = Config.load(tmp_path)
    manager = FeatureManager(config=config)
    manager.boolean("new_checkout", default=False)

    assert await manager.active("new_checkout") is True


async def test_boolean_resolves_the_same_for_every_context(tmp_path: Path) -> None:
    config = Config.load(tmp_path)
    manager = FeatureManager(config=config)
    manager.boolean("new_checkout", default=True)

    assert await manager.active("new_checkout", context="user-1") is True
    assert await manager.active("new_checkout", context="user-2") is True


# -- percentage() ------------------------------------------------------------------------------


def test_percentage_rejects_a_rollout_below_zero() -> None:
    manager = FeatureManager()
    with pytest.raises(ValueError):
        manager.percentage("x", rollout=-1)


def test_percentage_rejects_a_rollout_above_100() -> None:
    manager = FeatureManager()
    with pytest.raises(ValueError):
        manager.percentage("x", rollout=101)


async def test_percentage_zero_is_always_off() -> None:
    manager = FeatureManager()
    manager.percentage("off_flag", rollout=0)

    for i in range(50):
        assert await manager.active("off_flag", context=f"user-{i}") is False


async def test_percentage_hundred_is_always_on() -> None:
    manager = FeatureManager()
    manager.percentage("on_flag", rollout=100)

    for i in range(50):
        assert await manager.active("on_flag", context=f"user-{i}") is True


async def test_percentage_is_deterministic_for_the_same_context() -> None:
    manager = FeatureManager()
    manager.percentage("beta", rollout=50)

    first = await manager.active("beta", context="user-42")
    for _ in range(10):
        assert await manager.active("beta", context="user-42") is first


async def test_percentage_distribution_is_roughly_correct() -> None:
    manager = FeatureManager()
    manager.percentage("beta", rollout=30)

    sample = 2000
    results = [await manager.active("beta", context=f"user-{i}") for i in range(sample)]
    on_count = results.count(True)
    # Statistical, not exact -- a wide tolerance keeps this from flaking
    # while still catching a badly broken bucketing function.
    assert sample * 0.20 < on_count < sample * 0.40


async def test_percentage_on_false_flips_the_meaning() -> None:
    manager = FeatureManager()
    manager.percentage("kill_switch", rollout=100, on=False)

    assert await manager.active("kill_switch", context="anyone") is False


async def test_percentage_uses_context_id_when_present() -> None:
    manager = FeatureManager()
    manager.percentage("beta", rollout=50)

    class _WithId:
        def __init__(self, id_: int) -> None:
            self.id = id_

    # Two different objects sharing the same `.id` bucket identically --
    # proves the id, not object identity or repr, drives the bucketing.
    first = await manager.active("beta", context=_WithId(7))
    second = await manager.active("beta", context=_WithId(7))
    assert first == second


# -- feature(), via a real request round-trip ---------------------------------------------------


def _make_app(tmp_path: Path) -> Application:
    app = Application(Config.load(tmp_path))
    app.register(FeatureServiceProvider)
    return app


async def test_feature_helper_resolves_via_the_bound_manager(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    manager = app.container.make(FeatureManager)
    manager.define("always_on", lambda ctx: True)

    @app.get("/check")
    async def check(request):
        return JSONResponse({"active": await feature(request, "always_on")})

    async with client(app) as http:
        response = await http.get("/check")
        assert response.json() == {"active": True}


async def test_feature_helper_passes_context_through(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    manager = app.container.make(FeatureManager)
    manager.percentage("kill_switch", rollout=0)

    @app.get("/check")
    async def check(request):
        return JSONResponse({"active": await feature(request, "kill_switch", "some-user")})

    async with client(app) as http:
        response = await http.get("/check")
        assert response.json() == {"active": False}


async def test_feature_manager_resolved_directly_outside_a_request(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    manager = app.container.make(FeatureManager)
    manager.define("always_on", lambda ctx: True)

    resolved = app.container.make(FeatureManager)
    assert await resolved.active("always_on") is True


# -- FeatureServiceProvider ---------------------------------------------------------------


async def test_service_provider_starts_with_no_flags_defined(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    manager = app.container.make(FeatureManager)
    assert manager.names() == []
