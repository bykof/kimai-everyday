import stat

import pytest

from kimai_everyday import config as config_module
from kimai_everyday.types import Config


@pytest.fixture()
def temp_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def test_load_returns_none_when_missing(temp_config_home):
    assert config_module.load() is None


def test_save_then_load_roundtrip(temp_config_home):
    original = Config(
        kimai_url="https://kimai.example.com",
        kimai_token="abc123",
        anthropic_api_key="sk-ant-xxx",
        timezone="Europe/Berlin",
        last_project_id=4,
        last_activity_id=12,
    )
    config_module.save(original)
    loaded = config_module.load()
    assert loaded == original


def test_save_sets_permissions_to_600(temp_config_home):
    config_module.save(
        Config(
            kimai_url="https://kimai.example.com",
            kimai_token="abc",
            anthropic_api_key=None,
            timezone="UTC",
        )
    )
    mode = config_module.config_path().stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_save_omits_optional_fields(temp_config_home):
    config_module.save(
        Config(
            kimai_url="https://kimai.example.com",
            kimai_token="abc",
            anthropic_api_key=None,
            timezone="UTC",
        )
    )
    text = config_module.config_path().read_text(encoding="utf-8")
    assert "anthropic_api_key" not in text
    assert "last_project_id" not in text
    assert "last_activity_id" not in text


def test_config_path_uses_xdg(temp_config_home):
    assert config_module.config_path() == temp_config_home / "kimai-everyday" / "config.toml"
