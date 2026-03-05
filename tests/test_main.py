"""main.py 단위 테스트"""

import os
from unittest.mock import patch

import pytest

from main import _load_json_env, validate_config

# --- _load_json_env ---


def test_load_json_env_empty():
    with patch.dict(os.environ, {}, clear=True):
        result = _load_json_env("TEST_VAR", {"default": True})
    assert result == {"default": True}


def test_load_json_env_valid():
    with patch.dict(os.environ, {"TEST_VAR": '{"key": "value"}'}):
        result = _load_json_env("TEST_VAR", {})
    assert result == {"key": "value"}


def test_load_json_env_invalid_json():
    with patch.dict(os.environ, {"TEST_VAR": "not json"}):
        result = _load_json_env("TEST_VAR", {"fallback": True})
    assert result == {"fallback": True}


def test_load_json_env_not_dict():
    with patch.dict(os.environ, {"TEST_VAR": '["list"]'}):
        result = _load_json_env("TEST_VAR", {"fallback": True})
    assert result == {"fallback": True}


# --- validate_config ---


def _make_valid_config():
    return {
        "profile": {},
        "keywords": {},
        "feeds": {"테스트": {"id": 234, "enabled": True}},
        "gemini": {"model": "gemini-flash-latest", "relevance_threshold": 3},
        "settings": {
            "state_file": "state.json",
            "users_file": "users.json",
            "base_url": "https://example.com",
            "rss_url_template": "https://example.com/{board_id}",
        },
    }


def test_validate_config_valid():
    validate_config(_make_valid_config())


def test_validate_config_missing_section():
    config = _make_valid_config()
    del config["feeds"]
    with pytest.raises(ValueError, match="feeds"):
        validate_config(config)


def test_validate_config_feed_missing_id():
    config = _make_valid_config()
    config["feeds"]["bad_feed"] = {"enabled": True}
    with pytest.raises(ValueError, match="bad_feed"):
        validate_config(config)


def test_validate_config_missing_gemini_model():
    config = _make_valid_config()
    del config["gemini"]["model"]
    with pytest.raises(ValueError, match="model"):
        validate_config(config)


def test_validate_config_missing_settings_field():
    config = _make_valid_config()
    del config["settings"]["base_url"]
    with pytest.raises(ValueError, match="base_url"):
        validate_config(config)
