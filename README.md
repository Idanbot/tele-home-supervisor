# 🤖 Tele-Home Supervisor

[![CI/CD](https://github.com/idanbot/tele-home-supervisor/actions/workflows/ci-cd.yml/badge.svg?branch=main)](https://github.com/idanbot/tele-home-supervisor/actions/workflows/ci-cd.yml)
[![Docker Image](https://img.shields.io/badge/docker-ghcr.io-blue?logo=docker)](https://github.com/idanbot/tele-home-supervisor/pkgs/container/tele-home-supervisor)
[![Python 3.13](https://img.shields.io/badge/python-3.13-yellow.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Tele-Home Supervisor** is a powerful, all-in-one Telegram bot designed to monitor and manage your home server (Raspberry Pi, Linux VPS, NAS) remotely. 

It unifies system monitoring, Docker management, torrenting, AI interaction, and media discovery into a single, secure chat interface.

---

## ✨ Key Features

### 🖥️ System & Network
*   **Real-time Monitoring**: Visual bars for CPU, RAM, and Disk usage (`/health`, `/diskusage`).
*   **Network Tools**: Ping, DNS lookup, Traceroute, and Speedtest (`/speedtest`).
*   **Guest WiFi**: Generate QR codes for instant WiFi access (`/wifiqr`).
*   **Utilities**: Set async reminders (`/remind`), check uptime, and view top processes.
*   **Alerts**: Threshold-based notifications with per-chat rules (`/alerts`).
*   **Audit Log**: Recent command/callback history (`/audit`).

### 🐳 Docker Management
*   **Interactive Control**: Start, stop, and restart containers with inline buttons.
*   **Deep Inspection**: View logs, stats (CPU/Mem/Net/Block IO), and health status.
*   **Port Visibility**: See which ports your containers are exposing.

### 🎬 Media & Torrents
*   **Torrent Manager**: Full qBittorrent control (Add, Pause, Delete) with completion notifications.
*   **Discovery**: Search The Pirate Bay (`/pbsearch`) or check trending movies/shows on TMDB.
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
# Generate a Base32 secret for Google Authenticator
BOT_AUTH_TOTP_SECRET=JBSWY3DPEHPK3PXP

# Optional: External Services
OLLAMA_HOST=http://192.168.1.100:11434
QBT_HOST=qbittorrent
TMDB_API_KEY=your_tmdb_api_key
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
| `RATE_LIMIT_S` | `1.0` | Minimum seconds between commands (flood protection). |
| `ALERT_PING_LAN_TARGETS` | `` | Comma-separated LAN ping targets for `/alerts` reachability checks. |
| `ALERT_PING_WAN_TARGETS` | `` | Comma-separated WAN ping targets for `/alerts` reachability checks. |
| `WATCH_PATHS` | `/` | Comma-separated paths to monitor for disk usage. |
| `SHOW_WAN` | `false` | Set to `true` to show public IP in `/health`. |
| `LOG_LEVEL` | `DEBUG` | logging verbosity. |

---

## 📚 Command Reference

### 🛠 System
*   `/health` - Comprehensive system dashboard (CPU, RAM, Disk, Load).
*   `/diskusage` - Visual bar charts of disk space.
*   `/remind <min> <msg>` - Set a timer to ping you later.
*   `/wifiqr <ssid> [pass]` - Generate WiFi login QR code.
*   `/ip` - Show LAN and WAN IP addresses.
*   `/top` - Show top resource-consuming processes.

### 🔔 Alerts & Audit
*   `/alerts` - Manage alert rules and status.
*   `/audit [n]` - Show recent audit entries (or `/audit clear`).

### 🐳 Docker
*   `/docker` - Interactive container list (Start/Stop/Restart).
*   `/dlogs <name>` - Fetch container logs (as file or text).
*   `/dstatsrich` - Detailed container metrics (I/O, PIDs).
*   `/dinspect <name>` - View raw container configuration.

### 📥 Torrents
*   `/tstatus` - Real-time download progress with control buttons.
*   `/tadd <magnet>` - Remote download starter.
*   `/pbsearch <query>` - Search The Pirate Bay.
*   `/subscribe` - Get notified when downloads finish.

### 🤖 AI (Ollama)
*   `/ask <prompt>` - Query your local LLM.
*   `/ollamapull <model>` - Download new models to your server.
*   `/ollamastatus` - Track model download progress.

### 🎮 Media & Games
*   `/protondb <game>` - Check Linux gaming compatibility.
*   `/movies` / `/shows` - See what's trending.
*   `/epicgames` - Check this week's free games.

---

## 🛠 Development

We use [`uv`](https://github.com/astral-sh/uv) for lightning-fast dependency management.

```bash
# 1. Install dependencies
uv sync

# 2. Run tests
uv run pytest

# 3. Start bot locally
export BOT_TOKEN="xyz"
export ALLOWED_CHAT_IDS="123"
uv run bot.py
```

## 📄 License

MIT © [Idan](https://github.com/idanbot)
