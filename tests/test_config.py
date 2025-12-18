import os
from unittest import mock
from tele_home_supervisor import config


def test_settings_defaults():
    # Mock environment to be empty
    with mock.patch.dict(os.environ, {}, clear=True):
        settings = config._read_settings()
        assert settings.BOT_TOKEN is None
        assert settings.RATE_LIMIT_S == 1.0
        assert settings.QBT_HOST == "qbittorrent"
        assert settings.QBT_PORT == 8080


def test_settings_custom():
    env = {
        "BOT_TOKEN": "123:ABC",
        "ALLOWED_CHAT_IDS": "123, 456",
        "RATE_LIMIT_S": "2.5",
        "SHOW_WAN": "true",
        "QBT_PORT": "9090",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        settings = config._read_settings()
        assert settings.BOT_TOKEN == "123:ABC"
        assert settings.ALLOWED_CHAT_IDS == {123, 456}
        assert settings.RATE_LIMIT_S == 2.5
        assert settings.SHOW_WAN is True
        assert settings.QBT_PORT == 9090
