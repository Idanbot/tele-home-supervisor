# tele-home-supervisor

[![Build & Publish](https://github.com/idanbot/tele-home-supervisor/actions/workflows/build-and-push.yml/badge.svg?branch=main)](https://github.com/idanbot/tele-home-supervisor/actions/workflows/build-and-push.yml)

A Telegram bot for monitoring a Raspberry Pi (or any Linux host) and managing Docker containers and qBittorrent remotely.

## Features

| Category | Capabilities |
|----------|-------------|
| **System** | CPU/RAM/disk usage, temperature, uptime, top processes, LAN/WAN IP |
| **Docker** | List containers, stats, logs, health checks, listening ports |
| **Network** | Ping, DNS lookup, traceroute, speed test |
| **Torrents** | Add/pause/resume/delete torrents, completion notifications |
| **Free Games** | Epic Games, Steam, GOG, Humble Bundle giveaway tracking |
| **News** | Hacker News top stories with daily digest |

### Interactive Features

- **Inline Keyboards**: `/docker` and `/tstatus` display interactive buttons for quick actions
- **Command Autocomplete**: All commands appear in Telegram's autocomplete menu
- **Smart Suggestions**: Commands requiring names show suggestions when called without arguments

## Quick Start

### Prerequisites

- Docker and Docker Compose
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Your Telegram chat ID

### Installation

```bash
git clone https://github.com/idanbot/tele-home-supervisor.git
cd tele-home-supervisor

# Create environment file
cat > .env << EOF
BOT_TOKEN=your_bot_token_here
ALLOWED_CHAT_IDS=your_chat_id_here
QBT_HOST=qbittorrent
QBT_PORT=8080
QBT_USER=admin
QBT_PASS=adminadmin
EOF

# Create the external network
docker network create bit-net

# Start the bot
docker compose up -d
```

The included Watchtower service auto-updates the bot when new images are pushed.

## Commands

### System
| Command | Description |
|---------|-------------|
| `/health` | CPU, RAM, disk, load, uptime |
| `/ip` | Private LAN and public WAN IP |
| `/temp` | CPU temperature |
| `/top` | Top CPU-consuming processes |
| `/uptime` | System uptime |

### Docker
| Command | Description |
|---------|-------------|
| `/docker` | List containers with interactive buttons |
| `/dockerstats` | CPU/memory per container |
| `/dstatsrich` | Detailed stats with network/block IO |
| `/dlogs <container> [lines]` | Container logs (use negative for head) |
| `/dhealth <container>` | Health check status |
| `/ports` | Listening ports inside the bot container |

### Network
| Command | Description |
|---------|-------------|
| `/ping <host> [count]` | Ping a host |
| `/dns <name>` | DNS lookup |
| `/traceroute <host>` | Trace network route |
| `/speedtest [MB]` | Download speed test |

### Torrents
| Command | Description |
|---------|-------------|
| `/tstatus` | List torrents with interactive buttons |
| `/tadd <magnet/url> [path]` | Add a torrent |
| `/tstop <name>` | Pause torrent(s) |
| `/tstart <name>` | Resume torrent(s) |
| `/tdelete <name> yes` | Delete torrent(s) and files |
| `/subscribe [on/off]` | Toggle completion notifications |

### Free Games & News
| Command | Description |
|---------|-------------|
| `/epicgames` | Current Epic Games freebies |
| `/steamfree [n]` | Steam free-to-keep games |
| `/gogfree` | GOG free games |
| `/humblefree` | Humble Bundle free games |
| `/hackernews [n]` | Top Hacker News stories |
| `/mute_epicgames` | Toggle daily Epic digest (8 PM) |
| `/mute_hackernews` | Toggle daily HN digest (8 AM) |

### Info
| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/whoami` | Chat and user info |
| `/version` | Bot version and build info |

## Configuration

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram bot token |
| `ALLOWED_CHAT_IDS` | Comma-separated authorized chat IDs |

### Optional Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_S` | `1.0` | Command rate limit in seconds |
| `SHOW_WAN` | `false` | Include WAN IP in `/health` |
| `WATCH_PATHS` | `/,/srv/media` | Paths for disk usage reporting |
| `QBT_HOST` | `qbittorrent` | qBittorrent hostname |
| `QBT_PORT` | `8080` | qBittorrent WebUI port |
| `QBT_USER` | `admin` | qBittorrent username |
| `QBT_PASS` | `adminadmin` | qBittorrent password |

### Volume Mounts

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock  # Required for Docker commands
  - /sys/class/thermal/thermal_zone0:/host_thermal:ro  # Optional: CPU temp
  - /srv/media:/srv/media:ro  # Optional: disk usage monitoring
  - ./bot_data:/app/data  # Persistent state (mute preferences)
```

## Development

### Local Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Run locally
export BOT_TOKEN=...
export ALLOWED_CHAT_IDS=...
python bot.py
```

### Pre-commit Hooks

The project uses Black (formatting) and Bandit (security) hooks that mirror CI checks:

```bash
pre-commit run --all-files
```

### Building the Docker Image

```bash
docker build -t tele-home-supervisor .
```

## Project Structure

```
tele_home_supervisor/
├── main.py           # Application entry point, command registration
├── commands.py       # Command registry (single source of truth)
├── state.py          # Runtime state, caches, subscriptions
├── background.py     # Background tasks (torrent polling, schedulers)
├── scheduled.py      # Fetchers for Epic, Steam, GOG, Humble, HN
├── services.py       # Business logic layer
├── utils.py          # System/Docker/network utilities
├── torrent.py        # qBittorrent API wrapper
└── handlers/
    ├── dispatch.py      # Rate-limiting dispatcher
    ├── callbacks.py     # Inline keyboard handlers
    ├── meta.py          # /start, /help, /whoami, /version
    ├── system.py        # Host monitoring commands
    ├── docker.py        # Docker commands
    ├── network.py       # Network commands
    ├── torrents.py      # Torrent commands
    └── notifications.py # Free games and news commands
```

## CI/CD

The GitHub Actions pipeline (`.github/workflows/build-and-push.yml`):

1. **Lint**: Black formatting, Pylint errors, Bandit security scan, pip-audit
2. **Build**: Multi-arch images (amd64 + arm64)
3. **Scan**: Trivy vulnerability scanning
4. **Push**: Images pushed to `ghcr.io/idanbot/tele-home-supervisor`
5. **Notify**: Telegram notifications on build status

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No Docker data | Verify `/var/run/docker.sock` is mounted |
| No torrent data | Check `QBT_*` environment variables and network connectivity |
| No suggestions | Run the base command (e.g., `/docker`) to populate the cache |
| Permission denied | Ensure the bot container can access the Docker socket |

## License

MIT
