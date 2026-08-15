from pathlib import Path

from zeython.config import Config


def test_env_file_values_are_loaded(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("APP_NAME=Test App\nAPP_DEBUG=true\nAPP_PORT=9001\n")

    config = Config.load(tmp_path)

    assert config.app_name == "Test App"
    assert config.debug is True
    assert config.port == 9001


def test_get_supports_dot_path_lookup(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DATABASE_URL=sqlite+aiosqlite:///./test.db\n")

    config = Config.load(tmp_path)

    assert config.get("database.url") == "sqlite+aiosqlite:///./test.db"
    assert config.database_url == "sqlite+aiosqlite:///./test.db"


def test_get_falls_back_to_default_when_missing(tmp_path: Path) -> None:
    config = Config.load(tmp_path)

    assert config.get("nonexistent.key", "fallback") == "fallback"


def test_real_process_environment_overrides_env_file(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("APP_NAME=From File\n")
    monkeypatch.setenv("APP_NAME", "From Environment")

    config = Config.load(tmp_path)

    assert config.app_name == "From Environment"


def test_secret_key_raises_when_unset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    config = Config.load(tmp_path)

    import pytest

    with pytest.raises(RuntimeError):
        _ = config.secret_key
