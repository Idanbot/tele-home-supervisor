import os
import json
from unittest import mock
from tele_home_supervisor import config


def test_settings_defaults():
    # Mock environment to be empty
    with mock.patch.dict(os.environ, {}, clear=True):
        settings = config._read_settings()
        assert settings.BOT_TOKEN is None
        assert settings.OWNER_ID is None
        assert settings.BLOCKED_IDS == set()
        assert settings.RATE_LIMIT_S == 1.0
        assert settings.QBT_HOST == "qbittorrent"
        assert settings.QBT_PORT == 8080
        assert settings.QBT_TIMEOUT_S == 8.0
        assert settings.WOL_TARGET_IP == ""
        assert settings.WOL_TARGET_MAC == ""
        assert settings.WOL_PORT == 9
        assert settings.WOL_HELPER_IMAGE == ""
        assert settings.WOL_SSH_TARGET == ""
        assert settings.WOL_SSH_PORT == 22
        assert settings.WOL_SSH_PASSWORD == ""
        assert settings.WOL_SHUTDOWN_REMOTE_CMD == ""
        assert settings.WOL_VERIFY_TIMEOUT_S == 180.0
        assert settings.WOL_VERIFY_INTERVAL_S == 5.0
        assert settings.DEFAULT_MANAGED_HOST == ""
        assert settings.MANAGED_HOSTS == []


def test_settings_custom():
    managed_hosts = [
        {
            "name": "gaming-pc",
            "ping_host": "192.168.1.10",
            "mac": "aa:bb:cc:dd:ee:ff",
            "wol_broadcast_ip": "192.168.1.255",
            "wol_port": 7,
            "ssh_target": "pc-user@192.168.1.10",
            "ssh_port": 2222,
            "ssh_password": "topsecret",
            "ssh_password_env": "PC1_SSH_PASSWORD",
            "shutdown_command": "sudo poweroff",
            "aliases": ["pc", "gaming"],
        }
    ]
    env = {
        "BOT_TOKEN": "123:ABC",
        "OWNER_ID": "999",
        "ALLOWED_CHAT_IDS": "123, 456",
        "BLOCKED_IDS": "111, 222",
        "RATE_LIMIT_S": "2.5",
        "SHOW_WAN": "true",
        "QBT_PORT": "9090",
        "QBT_TIMEOUT_S": "12.5",
        "MANAGED_HOSTS_JSON": json.dumps(managed_hosts),
        "DEFAULT_MANAGED_HOST": "gaming-pc",
        "WOL_VERIFY_TIMEOUT_S": "90",
        "WOL_VERIFY_INTERVAL_S": "2",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        settings = config._read_settings()
        assert settings.BOT_TOKEN == "123:ABC"
        assert settings.OWNER_ID == 999
        assert settings.ALLOWED_CHAT_IDS == {123, 456}
        assert settings.BLOCKED_IDS == {111, 222}
        assert settings.RATE_LIMIT_S == 2.5
        assert settings.SHOW_WAN is True
        assert settings.QBT_PORT == 9090
        assert settings.QBT_TIMEOUT_S == 12.5
        assert settings.DEFAULT_MANAGED_HOST == "gaming-pc"
        assert len(settings.MANAGED_HOSTS) == 1
        host = settings.MANAGED_HOSTS[0]
        assert host.name == "gaming-pc"
        assert host.ping_host == "192.168.1.10"
        assert host.mac == "aa:bb:cc:dd:ee:ff"
        assert host.wol_broadcast_ip == "192.168.1.255"
        assert host.wol_port == 7
        assert host.ssh_target == "pc-user@192.168.1.10"
        assert host.ssh_port == 2222
        assert host.ssh_password == "topsecret"
        assert host.ssh_password_env == "PC1_SSH_PASSWORD"
        assert host.shutdown_command == "sudo poweroff"
        assert host.aliases == ("pc", "gaming")
        assert settings.WOL_VERIFY_TIMEOUT_S == 90.0
        assert settings.WOL_VERIFY_INTERVAL_S == 2.0


def test_settings_custom_with_quoted_managed_hosts_json():
    managed_hosts = [
        {
            "name": "pc1",
            "ping_host": "192.0.2.29",
            "mac": "aa:bb:cc:dd:ee:29",
            "wol_broadcast_ip": "192.0.2.255",
            "wol_port": 9,
            "ssh_target": "user@192.0.2.29",
            "ssh_port": 22,
            "ssh_password": "secret123",
            "ssh_password_env": "PC1_SSH_PASSWORD",
            "shutdown_command": "sudo systemctl poweroff",
            "aliases": ["pc", "windows"],
        }
    ]
    env = {
        "MANAGED_HOSTS_JSON": "'" + json.dumps(managed_hosts) + "'",
        "DEFAULT_MANAGED_HOST": "pc1",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        settings = config._read_settings()
        assert settings.DEFAULT_MANAGED_HOST == "pc1"
        assert len(settings.MANAGED_HOSTS) == 1
        host = settings.MANAGED_HOSTS[0]
        assert host.name == "pc1"
        assert host.ping_host == "192.0.2.29"
        assert host.mac == "aa:bb:cc:dd:ee:29"
        assert host.ssh_password == "secret123"
        assert host.ssh_password_env == "PC1_SSH_PASSWORD"
        assert host.aliases == ("pc", "windows")


def test_settings_legacy_wol_populates_default_managed_host():
    env = {
        "WOL_TARGET_IP": "192.168.1.10",
        "WOL_TARGET_MAC": "aa:bb:cc:dd:ee:ff",
        "WOL_BROADCAST_IP": "192.168.1.255",
        "WOL_PORT": "9",
        "WOL_HELPER_IMAGE": "ghcr.io/example/wol-helper:latest",
        "WOL_SSH_TARGET": "pc-user@192.168.1.10",
        "WOL_SSH_PORT": "22",
        "WOL_SSH_PASSWORD": "hunter2",
        "WOL_SHUTDOWN_REMOTE_CMD": "sudo poweroff",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        settings = config._read_settings()
        assert settings.DEFAULT_MANAGED_HOST == "default"
        assert len(settings.MANAGED_HOSTS) == 1
        host = settings.MANAGED_HOSTS[0]
        assert host.name == "default"
        assert host.ping_host == "192.168.1.10"
        assert host.mac == "aa:bb:cc:dd:ee:ff"
        assert settings.WOL_HELPER_IMAGE == "ghcr.io/example/wol-helper:latest"
        assert settings.WOL_SSH_PASSWORD == "hunter2"
        assert host.ssh_password_env == "WOL_SSH_PASSWORD"
