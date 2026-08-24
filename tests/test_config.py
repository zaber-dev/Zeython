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


def test_an_all_digit_secret_key_stays_a_string(tmp_path: Path) -> None:
    # Regression guard: _coerce() used to run unconditionally on every
    # value, including keys meant to stay opaque strings -- an all-digit
    # secret (a plausible, if sloppy, dev value) silently became a Python
    # int instead of a str, crashing the first time anything tried to
    # sign something with it (itsdangerous requires bytes/str).
    (tmp_path / ".env").write_text("APP_SECRET_KEY=12345678\n")

    config = Config.load(tmp_path)

    assert config.secret_key == "12345678"
    assert isinstance(config.secret_key, str)


def test_a_secret_shaped_value_that_looks_like_a_bool_stays_a_string(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("API_TOKEN=true\n")

    config = Config.load(tmp_path)

    assert config.get("api.token") == "true"


def test_debug_defaults_to_false_with_no_env_var_set_at_all(tmp_path: Path, monkeypatch) -> None:
    # Regression guard: debug used to fall back to `environment !=
    # "production"`, which defaults to True the moment APP_ENV is simply
    # left unset -- an easy omission on a real deployment, silently
    # serving full tracebacks/SQL/debug HTML to any client. debug is now
    # False unless APP_DEBUG is explicitly set, independent of APP_ENV.
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("APP_DEBUG", raising=False)

    config = Config.load(tmp_path)

    assert config.environment == "development"
    assert config.debug is False


def test_debug_defaults_to_false_even_with_app_env_left_as_development(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("APP_DEBUG", raising=False)
    (tmp_path / ".env").write_text("APP_ENV=development\n")

    config = Config.load(tmp_path)

    assert config.debug is False


def test_debug_is_true_when_explicitly_set(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("APP_DEBUG", raising=False)
    (tmp_path / ".env").write_text("APP_DEBUG=true\n")

    config = Config.load(tmp_path)

    assert config.debug is True


def test_non_secret_keys_are_still_type_coerced(tmp_path: Path) -> None:
    # The fix must not regress ordinary boolean/int coercion for keys
    # that aren't secret-shaped -- many providers rely on it (e.g.
    # bool(self.config.get("csrf.enabled", True)) only works because
    # "false" is already coerced to the boolean False before that cast).
    (tmp_path / ".env").write_text("FEATURE_ENABLED=false\nMAX_ITEMS=42\n")

    config = Config.load(tmp_path)

    assert config.get("feature.enabled") is False
    assert config.get("max.items") == 42
