"""Unit tests for settings validation (no database needed)."""

from pathlib import Path

import pytest

from druksmart_common.config import (
    PLACEHOLDER,
    REPO_ROOT,
    REQUIRED_SETTINGS,
    ConfigError,
    load_settings,
)


def valid_env() -> dict[str, str]:
    return {
        "DRUKSMART_PG_HOST": "localhost",
        "DRUKSMART_PG_PORT": "5433",
        "DRUKSMART_ANALYTICS_DB": "druksmart_analytics",
        "DRUKSMART_APP_DB": "druksmart_app",
        "DRUKSMART_PIPELINE_USER": "pipeline",
        "DRUKSMART_PIPELINE_PASSWORD": "pipeline-secret",
        "DRUKSMART_BI_READER_USER": "bi",
        "DRUKSMART_BI_READER_PASSWORD": "bi-secret",
        "DRUKSMART_APP_USER": "app",
        "DRUKSMART_APP_PASSWORD": "app-secret",
    }


def test_valid_settings_build_role_specific_connections():
    settings = load_settings(valid_env())

    assert settings.pg_port == 5433
    assert settings.pipeline().dbname == "druksmart_analytics"
    assert settings.pipeline().user == "pipeline"
    assert settings.bi_reader().dbname == "druksmart_analytics"
    assert settings.bi_reader().user == "bi"
    assert settings.application().dbname == "druksmart_app"
    assert settings.application().user == "app"


def test_missing_settings_are_named_without_values():
    env = valid_env()
    del env["DRUKSMART_APP_USER"]
    env["DRUKSMART_PIPELINE_PASSWORD"] = "   "

    with pytest.raises(ConfigError) as exc:
        load_settings(env)

    message = str(exc.value)
    assert "DRUKSMART_APP_USER" in message
    assert "DRUKSMART_PIPELINE_PASSWORD" in message
    assert "bi-secret" not in message


def test_placeholder_values_are_rejected():
    env = valid_env()
    env["DRUKSMART_BI_READER_PASSWORD"] = PLACEHOLDER

    with pytest.raises(ConfigError, match="DRUKSMART_BI_READER_PASSWORD"):
        load_settings(env)


@pytest.mark.parametrize("port", ["abc", "0", "70000", "-1"])
def test_invalid_port_is_rejected(port):
    env = valid_env()
    env["DRUKSMART_PG_PORT"] = port

    with pytest.raises(ConfigError, match="DRUKSMART_PG_PORT"):
        load_settings(env)


def test_passwords_are_hidden_from_repr():
    settings = load_settings(valid_env())

    for text in (repr(settings), repr(settings.pipeline()), repr(settings.application())):
        assert "secret" not in text


def test_env_example_documents_every_required_setting_with_placeholder_passwords():
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    entries = dict(
        line.split("=", 1)
        for line in example.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )

    missing = [name for name in REQUIRED_SETTINGS if name not in entries]
    assert not missing, f".env.example is missing {missing}"
    secrets = {k: v for k, v in entries.items() if k.endswith("PASSWORD")}
    assert secrets and all(v == PLACEHOLDER for v in secrets.values())


def test_env_file_is_git_ignored():
    gitignore = (Path(REPO_ROOT) / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in gitignore
    assert "!.env.example" in gitignore
