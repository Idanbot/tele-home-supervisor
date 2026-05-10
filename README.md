# 🤖 Tele-Home Supervisor

[![CI/CD](https://github.com/idanbot/tele-home-supervisor/actions/workflows/ci-cd.yml/badge.svg?branch=main)](https://github.com/idanbot/tele-home-supervisor/actions/workflows/ci-cd.yml)
[![Docker Image](https://img.shields.io/badge/docker-ghcr.io-blue?logo=docker)](https://github.com/idanbot/tele-home-supervisor/pkgs/container/tele-home-supervisor)
[![Python 3.14](https://img.shields.io/badge/python-3.14-yellow.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Tele-Home Supervisor** is a powerful, all-in-one Telegram bot designed to monitor and manage your home server (Raspberry Pi, Linux VPS, NAS) remotely. 

It unifies system monitoring, Docker management, torrenting, AI interaction, and media discovery into a single, secure chat interface.

---

## ✨ Key Features

### 🖥️ System & Network
*   **Real-time Monitoring**: Visual bars for CPU, RAM, and Disk usage (`/health`, `/diskusage`).
*   **Network Tools**: Ping, DNS lookup, Traceroute, and Speedtest (`/speedtest`).
*   **Wake-on-LAN**: Wake named managed devices and track power-up/status directly from the bot.
*   **Guest WiFi**: Generate QR codes for instant WiFi access (`/wifiqr`).
*   **Utilities**: Set async reminders (`/remind`), check uptime, and view top processes.
*   **Intel Briefing**: Daily 8 AM summary of weather, news, system health, and stoic wisdom.
*   **Alerts**: Threshold-based notifications with per-chat rules (`/alerts`).
*   **Audit Log**: Recent command/callback history (`/audit`).

### 🐳 Docker Management
*   **Interactive Control**: List and inspect containers directly from Telegram.
*   **Deep Inspection**: View logs, stats (CPU/Mem/Net/Block IO), and health status.
*   **Port Visibility**: See which ports your containers are exposing.

### 🎬 Media & Torrents
*   **Torrent Manager**: Full qBittorrent control (Add, Pause, Delete) with completion notifications.
*   **Discovery**: Search torrent providers (`/pbsearch`) or check trending movies/shows on TMDB.
*   **Gaming**: Check Linux/Steam Deck compatibility via ProtonDB (`/protondb`) and track free game giveaways (Epic, Steam, GOG).

### 🧠 Local AI Integration
*   **Ollama Support**: Chat with local LLMs (Llama 3, Mistral, etc.) directly in Telegram.
*   **Smart Splitting**: Automatically handles long responses by splitting them into multiple readable messages.
*   **Model Management**: List, pull, and switch models on the fly.

---

## 🚀 Quick Start (Docker Compose)

This is the recommended way to run the bot.

### 1. Get the Code
```bash
git clone https://github.com/idanbot/tele-home-supervisor.git
cd tele-home-supervisor
```

### 2. Configure Environment
Create a `.env` file with your secrets. **Do not commit this file.**

```bash
# Telegram (Required)
BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
ALLOWED_CHAT_IDS=12345678,87654321

# Docker (Required for permissions)
# Run `getent group docker | cut -d: -f3` to find your ID
DOCKER_GID=999

# Optional: Secure Auth (for critical commands)
# Generate a Base32 secret for Google Authenticator.
# You can generate one with: python -c "import pyotp; print(pyotp.random_base32())"
BOT_AUTH_TOTP_SECRET=<insert-base32-secret-here>

# Optional: External Services
OLLAMA_HOST=http://192.168.1.100:11434
QBT_HOST=qbittorrent
TMDB_API_KEY=your_tmdb_api_key

# Optional: Managed hosts/devices (recommended for /wol and /wolshutdown)
DEFAULT_MANAGED_HOST=gaming-pc
# REPLACE MAC AND TARGETS WITH YOUR DEVICE'S REAL DATA
MANAGED_HOSTS_JSON=[{"name":"gaming-pc","ping_host":"192.168.1.10","mac":"00:11:22:33:44:55","wol_broadcast_ip":"192.168.1.255","wol_port":9,"ssh_target":"myuser@192.168.1.10","ssh_port":22,"shutdown_command":"sudo systemctl poweroff","aliases":["pc","windows"]}]
```

### 3. Run
```bash
docker compose up -d
```

---

## ⚙️ Configuration Reference

### Core & Security
| Variable | Required | Description |
|:---|:---:|:---|
| `BOT_TOKEN` | ✅ | Your Telegram Bot API Token. |
| `ALLOWED_CHAT_IDS` | ✅ | Comma-separated list of user IDs allowed to interact with the bot. |
| `BOT_AUTH_TOTP_SECRET` | ❌ | Base32 secret for 2FA (`/auth`). Use if you want extra security for critical commands. |
| `DOCKER_GID` | ❌ | Group ID of the docker group on the host (enables `/docker` commands). |

### Integrations
| Variable | Description |
|:---|:---|
| `OLLAMA_HOST` | URL for Ollama API (e.g., `http://172.17.0.1:11434` for host access). |
| `OLLAMA_MODEL` | Default model to use (default: `llama2`). |
| `QBT_HOST` | qBittorrent hostname/IP. |
| `QBT_PORT` | qBittorrent WebUI port (default: `8080`). |
| `QBT_USER` | qBittorrent username. |
| `QBT_PASS` | qBittorrent password. |
| `TMDB_API_KEY` | API Key for Movie/TV metadata (The Movie Database). |

### Customization
| Variable | Default | Description |
|:---|:---:|:---|
| `RATE_LIMIT_S` | `1.0` | Minimum seconds between commands per user/command. |
| `ALERT_PING_LAN_TARGETS` | `` | Comma-separated LAN ping targets for `/alerts` reachability checks. |
| `ALERT_PING_WAN_TARGETS` | `` | Comma-separated WAN ping targets for `/alerts` reachability checks. |
| `DEFAULT_MANAGED_HOST` | `` | Default managed host/device name used by `/wol` and `/wolshutdown`. |
| `MANAGED_HOSTS_JSON` | `` | JSON array of managed host/device objects with `name`, `ping_host`, `mac`, WOL, and SSH shutdown fields. |
| `WATCH_PATHS` | `/` | Comma-separated paths to monitor for disk usage. |
| `SHOW_WAN` | `false` | Set to `true` to show public IP in `/health`. |
| `LOG_LEVEL` | `DEBUG` | logging verbosity. |
| `LOG_FORMAT` | `text` | set to `json` for structured logging. |

---

## 📚 Commands

### Info

| Command | Description |
| :--- | :--- |
| `/start` | show help |
| `/help` | this menu |
| `/whoami` | show chat and user info |
| `/auth &lt;code&gt;` | authorize sensitive commands for 7 days |
| `/check_auth` | check auth status and time remaining |
| `/auth_file` | show all authenticated user IDs and expiry from file |
| `/ban &lt;user_id&gt;` | owner-only persistent block for a user ID |
| `/unban &lt;user_id&gt;` | owner-only remove a user ID from persistent blocks |
| `/banlist` | owner-only view aggregated blocked user IDs |
| `/version` | bot version and build info |
| `/metrics` | command metrics summary |
| `/audit [n]` | show recent audit entries (or /audit clear) |
| `/debug [command]` | recent errors/debug info |

### System

| Command | Description |
| :--- | :--- |
| `/ip` | private LAN IP |
| `/health` | CPU/RAM/disk/load/uptime (and WAN if enabled) |
| `/uptime` | system uptime |
| `/temp` | CPU temperature (reads /host_thermal/temp) |
| `/top` | top CPU processes |
| `/diskusage` | visual disk usage bars |
| `/remind &lt;minutes&gt; &lt;msg&gt;` | set a reminder timer |
| `/cleanup` | delete all tracked media messages now |

### Docker

| Command | Description |
| :--- | :--- |
| `/docker` | list containers, status, ports |
| `/dinspect &lt;container&gt;` | inspect container (JSON, file if large) |
| `/dockerstats` | CPU/MEM per running container |
| `/dstatsrich` | detailed Docker stats (net/block IO) |
| `/dlogs &lt;container&gt; [page] [--since &lt;time&gt;] [--file]` | container logs (default sends file; use page for pagination) |
| `/dhealth &lt;container&gt;` | container health check |

### Network

| Command | Description |
| :--- | :--- |
| `/ping &lt;ip&gt; [count]` | ping an IP or hostname |
| `/ports` | listening ports (inside container) |
| `/dns &lt;name&gt;` | DNS lookup |
| `/traceroute &lt;host&gt; [max_hops]` | trace network route |
| `/speedtest [MB]` | quick download speed test |
| `/wifiqr &lt;ssid&gt; [password]` | generate WiFi QR code |
| `/wol [host|mac|ip]` | send Wake-on-LAN packet and watch for ping response |
| `/wolshutdown [host|ip]` | run configured remote shutdown and watch for ping failure |

### Torrents

| Command | Description |
| :--- | :--- |
| `/tadd &lt;torrent&gt; [save_path]` | add torrent (magnet/URL) |
| `/tstatus` | show torrent status |
| `/tstop &lt;torrent&gt;` | pause torrent(s) by name |
| `/tstart &lt;torrent&gt;` | resume torrent(s) by name |
| `/tdelete &lt;torrent&gt; yes` | delete torrent(s) and files |
| `/tclean yes` | remove torrents with missing files |
| `/subscribe [on|off|status]` | torrent completion notifications |
| `/pbtop [category]` | top Pirate Bay torrents (audio, video, apps, games, porn, other) |
| `/pbsearch &lt;query&gt;` | search Pirate Bay torrents |
| `/pbprovider [provider]` | show or set forced torrent provider |
| `/pbtoggle &lt;provider&gt;` | toggle torrent provider on/off |

### Notifications

| Command | Description |
| :--- | :--- |
| `/alerts` | alert rules and status |
| `/mute_gameoffers` | toggle Game Offers daily notifications (8 PM) |
| `/mute_hackernews` | toggle Hacker News daily digest (8 AM) |
| `/gameoffers` | show combined game offers (Epic/Steam/GOG/Humble) |
| `/epicgames` | check current Epic Games free games |
| `/hackernews [n]` | show top N Hacker News stories (default: 5) |
| `/steamfree [n]` | show current Steam free-to-keep games |
| `/gogfree` | show current GOG free games |
| `/humblefree` | show current Humble Bundle free games |
| `/intel_settings` | Intel Briefing module settings |
| `/intel_briefing` | fetch Intel Briefing on demand |

### Media

| Command | Description |
| :--- | :--- |
| `/movies` | TMDB trending movies |
| `/shows` | TMDB trending shows |
| `/incinema` | TMDB in cinemas now |
| `/tmdb &lt;query&gt;` | TMDB search (movies + shows) |
| `/protondb &lt;game&gt;` | ProtonDB Linux/Steam Deck compatibility |

### AI

| Command | Description |
| :--- | :--- |
| `/ask &lt;question&gt;` | ask a question, flags: --temp|-t 0.4 --top-k|-k 40 --top-p|-p 0.9 --num-predict|-n 640 |
| `/askreset` | reset custom AI generation parameters |
| `/ollamahost &lt;http://host:port&gt;` | set Ollama host target |
| `/ollamamodel &lt;model&gt;` | set Ollama model |
| `/ollamareset` | reset Ollama host/model overrides |
| `/ollamashow` | show current Ollama host/model |
| `/ollamalist` | list available Ollama models |
| `/ollamapull &lt;model&gt;` | download an Ollama model |
| `/ollamastatus` | show current Ollama download status |
| `/ollamacancel` | cancel current Ollama download |

---

## 🛠 Development

We use [`uv`](https://github.com/astral-sh/uv) for lightning-fast dependency management.

```bash
# 1. Install dependencies
uv sync --all-extras --dev

# 2. Run tests
uv run pytest

# 3. Start bot locally
export BOT_TOKEN="xyz"
export ALLOWED_CHAT_IDS="123"
uv run bot.py
```

## 📄 License

MIT © [Idan](https://github.com/idanbot)
