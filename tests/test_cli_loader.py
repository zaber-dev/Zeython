"""Direct tests for zeython.cli.loader -- previously only exercised
indirectly through zeython.mcp.introspect (which re-exports load_app) and
zeython.database.seeder's tests.

_import_main() caches the "main" module by name and reloads it on a
second call rather than re-importing, and sync_project_modules() tracks
the last project root in a module-level global -- both process-wide state
that would otherwise leak between tests (and between this file and
test_mcp.py/test_seeder.py, which also call load_app). Every test here
resets both explicitly rather than relying on run order.
"""

import sys
from pathlib import Path

import pytest

from zeython.cli.loader import load_app, sync_project_modules

#: Captured once, before any test in this file runs load_app() and starts
#: accumulating entries -- see _isolate_loader_global_state below.
_PRISTINE_SYS_PATH = list(sys.path)


@pytest.fixture(autouse=True)
def _isolate_loader_global_state(monkeypatch: pytest.MonkeyPatch) -> None:
    import zeython.cli.loader as loader_module

    monkeypatch.setattr(loader_module, "_current_project_root", None)
    monkeypatch.delitem(sys.modules, "main", raising=False)
    # load_app() now removes the *previous* project's root from sys.path
    # when switching to a new one (see test_load_app_raises_module_not_found_
    # for_a_project_with_no_main_py_after_a_different_project_was_loaded
    # below) -- but this fixture still resets to the pristine, pre-any-test
    # baseline (not just "whatever sys.path looked like when this test
    # started") as a belt-and-suspenders guard against any test in this
    # file leaking sys.path state into a later one for an unrelated reason.
    monkeypatch.setattr(sys, "path", list(_PRISTINE_SYS_PATH))


def _make_minimal_project(project_root: Path, app_name: str) -> Path:
    (project_root / ".env").write_text(f"APP_NAME={app_name}\nAPP_SECRET_KEY=test\n")
    (project_root / "main.py").write_text(
        "from zeython import Application\n\napp = Application()\n"
    )
    return project_root


# -- load_app -----------------------------------------------------------------------------


def test_load_app_returns_the_projects_app_object(tmp_path: Path) -> None:
    project = _make_minimal_project(tmp_path, "Loader Test App")
    app = load_app(project)
    assert app.config.app_name == "Loader Test App"


def test_load_app_restores_the_previous_working_directory(tmp_path: Path) -> None:
    project = _make_minimal_project(tmp_path, "Loader Test App")
    cwd_before = Path.cwd()

    load_app(project)

    assert Path.cwd() == cwd_before


def test_load_app_restores_the_working_directory_even_if_main_fails_to_import(
    tmp_path: Path,
) -> None:
    (tmp_path / "main.py").write_text("raise RuntimeError('boom')\n")
    cwd_before = Path.cwd()

    with pytest.raises(RuntimeError, match="boom"):
        load_app(tmp_path)

    assert Path.cwd() == cwd_before


def test_load_app_raises_module_not_found_without_a_main_py(tmp_path: Path) -> None:
    with pytest.raises(ModuleNotFoundError):
        load_app(tmp_path)


def test_load_app_raises_module_not_found_for_a_project_with_no_main_py_after_a_different_project_was_loaded(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    # Regression guard: "main" wasn't among sync_project_modules()'s
    # tracked packages, and load_app() never removed a previous project's
    # root from sys.path either -- so after successfully loading project
    # A, asking to load project B (which has no main.py of its own) hit
    # _import_main()'s "main" in sys.modules branch, which just reloaded
    # A's already-cached module (still resolvable via A's leftover
    # sys.path entry) instead of raising. load_app(B) would silently
    # return A's Application -- a completely different, stale project --
    # with no error at all.
    project_a = tmp_path_factory.mktemp("loader_project_a")
    _make_minimal_project(project_a, "Project A")
    load_app(project_a)

    project_b = tmp_path_factory.mktemp("loader_project_b")  # deliberately no main.py

    with pytest.raises(ModuleNotFoundError):
        load_app(project_b)


def test_load_app_raises_attribute_error_when_main_has_no_app(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("not_app = object()\n")

    with pytest.raises(AttributeError):
        load_app(tmp_path)


def test_load_app_reloads_main_rather_than_reusing_a_stale_cached_module(tmp_path: Path) -> None:
    project = _make_minimal_project(tmp_path, "First Name")
    first = load_app(project)
    assert first.config.app_name == "First Name"

    # Editing main.py and reloading proves a fresh exec happened -- the
    # returned Application is a new object, not the first call's cached one.
    (project / "main.py").write_text("from zeython import Application\n\napp = Application()\n")
    second = load_app(project)

    assert second is not first


# -- sync_project_modules ------------------------------------------------------------------


def test_sync_project_modules_purges_app_package_on_a_project_switch(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    project_a = tmp_path_factory.mktemp("loader_project_a")
    (project_a / "app").mkdir()
    (project_a / "app" / "__init__.py").write_text("MARKER = 'a'\n")

    project_b = tmp_path_factory.mktemp("loader_project_b")
    (project_b / "app").mkdir()
    (project_b / "app" / "__init__.py").write_text("MARKER = 'b'\n")

    sys.path.insert(0, str(project_a))
    try:
        sync_project_modules(project_a)
        import app as app_pkg

        assert app_pkg.MARKER == "a"
    finally:
        sys.path.remove(str(project_a))

    sys.path.insert(0, str(project_b))
    try:
        sync_project_modules(project_b)
        import app as app_pkg  # noqa: F811 -- re-import after the purge, deliberately

        assert app_pkg.MARKER == "b"
    finally:
        sys.path.remove(str(project_b))
        sys.modules.pop("app", None)


def test_sync_project_modules_is_a_noop_for_the_same_project_root_twice(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").touch()

    sys.path.insert(0, str(tmp_path))
    try:
        sync_project_modules(tmp_path)
        import app as app_pkg

        app_pkg.set_by_test = "still here"

        sync_project_modules(tmp_path)  # same root -- must not purge

        assert sys.modules["app"].set_by_test == "still here"
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("app", None)
