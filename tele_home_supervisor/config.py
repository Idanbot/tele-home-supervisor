"""Central configuration for tele_home_supervisor."""

from __future__ import annotations

import json
import logging
import os
from typing import Set, List

from .models.managed_host import ManagedHost
from .models.settings import Settings

logger = logging.getLogger(__name__)


def _split_ints(s: str) -> Set[int]:
    """Parse comma-separated string into a set of integers.

    Args:
        s: Comma-separated string of integers (e.g., "123,456,789")

    Returns:
        Set of parsed integers. Invalid entries are silently skipped.

    Example:
        >>> _split_ints("123,456,invalid,789")
        {123, 456, 789}
    """
    out = set()
    for part in (s or "").split(","):
        p = part.strip()
        if p.isdigit():
            out.add(int(p))
    return out


def _read_optional_int(name: str) -> int | None:
    value = (os.environ.get(name) or "").strip()
    if not value:
        return None
    return int(value) if value.isdigit() else None


def _split_paths(s: str) -> List[str]:
    """Parse comma-separated string into a list of filesystem paths.

    Args:
        s: Comma-separated string of paths. Defaults to "/,/srv/media" if empty.

    Returns:
        List of non-empty path strings.

    Example:
        >>> _split_paths("/home,/var/log")
        ['/home', '/var/log']
    """
    return [p.strip() for p in (s or "/,/srv/media").split(",") if p.strip()]


def _split_csv(s: str) -> List[str]:
    """Parse comma-separated string into a list of values."""
    return [p.strip() for p in (s or "").split(",") if p.strip()]


def _strip_outer_quotes(value: str) -> str:
    text = (value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1].strip()
    return text


def _read_optional_float(name: str, default: float) -> float:
    value = (os.environ.get(name) or "").strip()
    if not value:
        return default
    try:
        return float(value)
    except Exception:
        return default


def _normalize_aliases(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return tuple(_split_csv(raw))
    if isinstance(raw, list):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return ()


def _read_managed_hosts_json(raw: str) -> list[ManagedHost]:
    payload = _strip_outer_quotes(raw)
    if not payload:
        return []
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        logger.warning("Invalid MANAGED_HOSTS_JSON: %s", exc)
        return []
    if not isinstance(data, list):
        logger.warning("MANAGED_HOSTS_JSON must be a JSON array of host objects.")
        return []

    hosts: list[ManagedHost] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        ping_host = str(
            item.get("ping_host") or item.get("host") or item.get("ip") or ""
        ).strip()
        mac = str(item.get("mac") or "").strip()
        wol_broadcast_ip = str(
            item.get("wol_broadcast_ip") or item.get("broadcast_ip") or ""
        ).strip()
        try:
            wol_port = int(item.get("wol_port", item.get("port", 9)) or 9)
        except Exception:
            wol_port = 9
        ssh_target = str(
            item.get("ssh_target") or item.get("shutdown_ssh_target") or ""
        ).strip()
        try:
            ssh_port = int(
                item.get("ssh_port", item.get("shutdown_ssh_port", 22)) or 22
            )
        except Exception:
            ssh_port = 22
        shutdown_command = str(
            item.get("shutdown_command")
            or item.get("wol_shutdown_remote_cmd")
            or item.get("command")
            or ""
        ).strip()
        ssh_password = str(
            item.get("ssh_password") or item.get("password") or ""
        ).strip()
        ssh_password_env = str(
            item.get("ssh_password_env") or item.get("password_env") or ""
        ).strip()
        aliases = _normalize_aliases(item.get("aliases"))
        hosts.append(
            ManagedHost(
                name=name,
                ping_host=ping_host,
                mac=mac,
                wol_broadcast_ip=wol_broadcast_ip,
                wol_port=wol_port,
                ssh_target=ssh_target,
                ssh_port=ssh_port,
                shutdown_command=shutdown_command,
                ssh_password=ssh_password,
                ssh_password_env=ssh_password_env,
                aliases=aliases,
            )
        )
    return hosts


def _legacy_wol_host() -> ManagedHost | None:
    wol_target_ip = (os.environ.get("WOL_TARGET_IP") or "").strip()
    wol_target_mac = (os.environ.get("WOL_TARGET_MAC") or "").strip()
    wol_broadcast_ip = (os.environ.get("WOL_BROADCAST_IP") or "").strip()
    wol_ssh_target = (os.environ.get("WOL_SSH_TARGET") or "").strip()
    wol_ssh_password = (os.environ.get("WOL_SSH_PASSWORD") or "").strip()
    wol_shutdown_remote_cmd = (os.environ.get("WOL_SHUTDOWN_REMOTE_CMD") or "").strip()
    try:
        wol_port = int((os.environ.get("WOL_PORT") or "9").strip() or "9")
    except Exception:
        wol_port = 9
    try:
        wol_ssh_port = int((os.environ.get("WOL_SSH_PORT") or "22").strip() or "22")
    except Exception:
        wol_ssh_port = 22
    if not any(
        [
            wol_target_ip,
            wol_target_mac,
            wol_broadcast_ip,
            wol_ssh_target,
            wol_ssh_password,
            wol_shutdown_remote_cmd,
        ]
    ):
        return None
    return ManagedHost(
        name="default",
        ping_host=wol_target_ip,
        mac=wol_target_mac,
        wol_broadcast_ip=wol_broadcast_ip,
        wol_port=wol_port,
        ssh_target=wol_ssh_target,
        ssh_port=wol_ssh_port,
        shutdown_command=wol_shutdown_remote_cmd,
        ssh_password_env="WOL_SSH_PASSWORD" if wol_ssh_password else "",
    )


def _read_settings() -> Settings:
    """Read all configuration from environment variables.

    Returns:
        Settings object with all configuration values.

    Note:
        Invalid numeric values fall back to sensible defaults.
        Boolean values accept: 1/true/yes (case-insensitive) as True.
    """
    token = os.environ.get("BOT_TOKEN") or None
    owner_id = _read_optional_int("OWNER_ID")
    allowed = _split_ints(os.environ.get("ALLOWED_CHAT_IDS", ""))
    blocked = _split_ints(os.environ.get("BLOCKED_IDS", ""))
    try:
        rate_limit = float(os.environ.get("RATE_LIMIT_S", "1.0") or "1.0")
    except Exception:
        rate_limit = 1.0
    show_wan = os.environ.get("SHOW_WAN", "false").lower() in {"1", "true", "yes"}
    watch_paths = _split_paths(os.environ.get("WATCH_PATHS", "/,/srv/media"))

    # qBittorrent
    qbt_host = os.environ.get("QBT_HOST") or "qbittorrent"
    qbt_port_raw = (os.environ.get("QBT_PORT") or "8080").strip()
    try:
        qbt_port = int(qbt_port_raw) if qbt_port_raw else 8080
    except Exception:
        qbt_port = 8080
    qbt_user = os.environ.get("QBT_USER") or "admin"
    qbt_pass = os.environ.get("QBT_PASS") or "adminadmin"
    try:
        qbt_timeout = float(os.environ.get("QBT_TIMEOUT_S", "8") or "8")
    except Exception:
        qbt_timeout = 8.0

    # Ollama
    ollama_host = os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
    ollama_model = os.environ.get("OLLAMA_MODEL") or "llama2"
    bot_auth_totp_secret = os.environ.get("BOT_AUTH_TOTP_SECRET") or None
    try:
        bot_auth_ttl_hours = float(os.environ.get("BOT_AUTH_TTL_HOURS", "168") or "168")
    except Exception:
        bot_auth_ttl_hours = 168.0
    try:
        bot_auto_delete_media_hours = float(
            os.environ.get("BOT_AUTO_DELETE_MEDIA_HOURS", "24") or "24"
        )
    except Exception:
        bot_auto_delete_media_hours = 24.0
    alert_ping_lan = _split_csv(os.environ.get("ALERT_PING_LAN_TARGETS", ""))
    alert_ping_wan = _split_csv(os.environ.get("ALERT_PING_WAN_TARGETS", ""))
    wol_helper_image = (os.environ.get("WOL_HELPER_IMAGE") or "").strip()
    managed_hosts = _read_managed_hosts_json(os.environ.get("MANAGED_HOSTS_JSON", ""))
    legacy_host = _legacy_wol_host()
    if legacy_host is not None and not any(
        host.name == legacy_host.name for host in managed_hosts
    ):
        managed_hosts.append(legacy_host)
    default_managed_host = (os.environ.get("DEFAULT_MANAGED_HOST") or "").strip()
    if not default_managed_host and len(managed_hosts) == 1:
        default_managed_host = managed_hosts[0].name
    wol_verify_timeout_s = _read_optional_float("WOL_VERIFY_TIMEOUT_S", 180.0)
    wol_verify_interval_s = _read_optional_float("WOL_VERIFY_INTERVAL_S", 5.0)

    # TMDB
    tmdb_api_key = os.environ.get("TMDB_API_KEY", "")
    tmdb_base_url = os.environ.get(
        "TMDB_BASE_URL", "https://api.themoviedb.org/3"
    ).rstrip("/")
    tmdb_user_agent = os.environ.get(
        "TMDB_USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )

    # PirateBay / TPB
    tpb_base_url = os.environ.get("TPB_BASE_URL", "https://thepiratebay.org").rstrip(
        "/"
    )
    tpb_api_base_url = os.environ.get("TPB_API_BASE_URL", "https://apibay.org").rstrip(
        "/"
    )
    tpb_api_base_urls = _split_csv(os.environ.get("TPB_API_BASE_URLS", ""))
    tpb_user_agent = os.environ.get(
        "TPB_USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    tpb_cookie = os.environ.get("TPB_COOKIE", "")
    tpb_referer = os.environ.get("TPB_REFERER", "")

    return Settings(
        BOT_TOKEN=token,
        OWNER_ID=owner_id,
        ALLOWED_CHAT_IDS=allowed,
        BLOCKED_IDS=blocked,
        RATE_LIMIT_S=rate_limit,
        SHOW_WAN=show_wan,
        WATCH_PATHS=watch_paths,
        QBT_HOST=qbt_host,
        QBT_PORT=qbt_port,
        QBT_USER=qbt_user,
        QBT_PASS=qbt_pass,
        QBT_TIMEOUT_S=qbt_timeout,
        OLLAMA_HOST=ollama_host,
        OLLAMA_MODEL=ollama_model,
        BOT_AUTH_TOTP_SECRET=bot_auth_totp_secret,
        BOT_AUTH_TTL_HOURS=bot_auth_ttl_hours,
        BOT_AUTO_DELETE_MEDIA_HOURS=bot_auto_delete_media_hours,
        ALERT_PING_LAN_TARGETS=alert_ping_lan,
        ALERT_PING_WAN_TARGETS=alert_ping_wan,
        WOL_TARGET_IP=legacy_host.ping_host if legacy_host is not None else "",
        WOL_TARGET_MAC=legacy_host.mac if legacy_host is not None else "",
        WOL_BROADCAST_IP=legacy_host.wol_broadcast_ip
        if legacy_host is not None
        else "",
        WOL_PORT=legacy_host.wol_port if legacy_host is not None else 9,
        WOL_HELPER_IMAGE=wol_helper_image,
        WOL_SSH_TARGET=legacy_host.ssh_target if legacy_host is not None else "",
        WOL_SSH_PORT=legacy_host.ssh_port if legacy_host is not None else 22,
        WOL_SSH_PASSWORD=(os.environ.get("WOL_SSH_PASSWORD") or "").strip(),
        WOL_SHUTDOWN_REMOTE_CMD=legacy_host.shutdown_command
        if legacy_host is not None
        else "",
        WOL_VERIFY_TIMEOUT_S=wol_verify_timeout_s,
        WOL_VERIFY_INTERVAL_S=wol_verify_interval_s,
        DEFAULT_MANAGED_HOST=default_managed_host,
        MANAGED_HOSTS=managed_hosts,
        TMDB_API_KEY=tmdb_api_key,
        TMDB_BASE_URL=tmdb_base_url,
        TMDB_USER_AGENT=tmdb_user_agent,
        TPB_BASE_URL=tpb_base_url,
        TPB_API_BASE_URL=tpb_api_base_url,
        TPB_API_BASE_URLS=tpb_api_base_urls,
        TPB_USER_AGENT=tpb_user_agent,
        TPB_COOKIE=tpb_cookie,
        TPB_REFERER=tpb_referer,
    )


settings = _read_settings()


def validate_settings() -> None:
    """Validate critical configuration and log warnings for issues.

    This function checks BOT_TOKEN and ALLOWED_CHAT_IDS, logging appropriate
    error/warning messages if they are not configured correctly.
    """
    if settings.BOT_TOKEN is None:
        logger.error("BOT_TOKEN environment variable is not set")
    if not settings.ALLOWED_CHAT_IDS:
        logger.warning(
            "ALLOWED_CHAT_IDS is empty; guarded commands will be unauthorized."
        )
    if settings.BOT_AUTH_TOTP_SECRET is None:
        logger.warning("BOT_AUTH_TOTP_SECRET is not set; /auth will be unavailable.")
    if settings.DEFAULT_MANAGED_HOST and not any(
        host.matches(settings.DEFAULT_MANAGED_HOST) for host in settings.MANAGED_HOSTS
    ):
        logger.warning(
            "DEFAULT_MANAGED_HOST=%s does not match any configured MANAGED_HOSTS entry.",
            settings.DEFAULT_MANAGED_HOST,
        )


def get_managed_host(name_or_alias: str) -> ManagedHost | None:
    """Return a configured managed host by name or alias."""
    needle = (name_or_alias or "").strip()
    if not needle:
        return None
    for host in settings.MANAGED_HOSTS:
        if host.matches(needle):
            return host
    return None


def default_managed_host() -> ManagedHost | None:
    """Return the configured default managed host, if any."""
    if settings.DEFAULT_MANAGED_HOST:
        host = get_managed_host(settings.DEFAULT_MANAGED_HOST)
        if host is not None:
            return host
    if len(settings.MANAGED_HOSTS) == 1:
        return settings.MANAGED_HOSTS[0]
    return None


# Exported constants
TOKEN: str | None = settings.BOT_TOKEN
OWNER_ID: int | None = settings.OWNER_ID
ALLOWED: set[int] = settings.ALLOWED_CHAT_IDS
BLOCKED_IDS: set[int] = settings.BLOCKED_IDS
RATE_LIMIT_S: float = settings.RATE_LIMIT_S
SHOW_WAN: bool = settings.SHOW_WAN
WATCH_PATHS: list[str] = settings.WATCH_PATHS
OLLAMA_HOST: str = settings.OLLAMA_HOST
OLLAMA_MODEL: str = settings.OLLAMA_MODEL
QBT_TIMEOUT_S: float = settings.QBT_TIMEOUT_S
BOT_AUTH_TOTP_SECRET: str | None = settings.BOT_AUTH_TOTP_SECRET
BOT_AUTH_TTL_HOURS: float = settings.BOT_AUTH_TTL_HOURS
BOT_AUTO_DELETE_MEDIA_HOURS: float = settings.BOT_AUTO_DELETE_MEDIA_HOURS
ALERT_PING_LAN_TARGETS: list[str] = settings.ALERT_PING_LAN_TARGETS
ALERT_PING_WAN_TARGETS: list[str] = settings.ALERT_PING_WAN_TARGETS
WOL_TARGET_IP: str = settings.WOL_TARGET_IP
WOL_TARGET_MAC: str = settings.WOL_TARGET_MAC
WOL_BROADCAST_IP: str = settings.WOL_BROADCAST_IP
WOL_PORT: int = settings.WOL_PORT
WOL_HELPER_IMAGE: str = settings.WOL_HELPER_IMAGE
WOL_SSH_TARGET: str = settings.WOL_SSH_TARGET
WOL_SSH_PORT: int = settings.WOL_SSH_PORT
WOL_SSH_PASSWORD: str = settings.WOL_SSH_PASSWORD
WOL_SHUTDOWN_REMOTE_CMD: str = settings.WOL_SHUTDOWN_REMOTE_CMD
WOL_VERIFY_TIMEOUT_S: float = settings.WOL_VERIFY_TIMEOUT_S
WOL_VERIFY_INTERVAL_S: float = settings.WOL_VERIFY_INTERVAL_S
DEFAULT_MANAGED_HOST: str = settings.DEFAULT_MANAGED_HOST
MANAGED_HOSTS: list[ManagedHost] = settings.MANAGED_HOSTS

validate_settings()
