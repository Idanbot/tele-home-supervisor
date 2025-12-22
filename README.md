# tele-home-supervisor

[![CI/CD](https://github.com/idanbot/tele-home-supervisor/actions/workflows/ci-cd.yml/badge.svg?branch=main)](https://github.com/idanbot/tele-home-supervisor/actions/workflows/ci-cd.yml)

A Telegram bot for monitoring a Raspberry Pi (or any Linux host) and managing Docker containers, qBittorrent, and AI queries remotely.

## Features

| Category | Capabilities |
|----------|-------------|
| **System** | CPU/RAM/disk usage, temperature, uptime, top processes, LAN/WAN IP |
| **Docker** | List containers, stats, logs, health checks, listening ports |
| **Network** | Ping, DNS lookup, traceroute, speed test |
| **Torrents** | Add/pause/resume/delete torrents, completion notifications |
| **Free Games** | Epic Games, Steam, GOG, Humble Bundle giveaway tracking |
| **News** | Hacker News top stories with daily digest |
| **AI** | Query local LLMs via Ollama with customizable parameters |

### Interactive Features

- **Inline Keyboards**: `/docker` and `/tstatus` display interactive buttons for quick actions
- **Command Autocomplete**: All commands appear in Telegram's autocomplete menu
- **Smart Suggestions**: Commands requiring names show suggestions when called without arguments

## Quick Start

### Prerequisites

- Docker and Docker Compose
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Your Telegram chat ID
- (Optional) [Ollama](https://ollama.com/) for AI features

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
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3
DOCKER_GID=your_docker_gid
EOF

# Create the external network
docker network create bit-net

# Start the bot
docker compose up -d
```

The included Watchtower service auto-updates the bot when new images are pushed.

Note: the container runs as a non-root user. Set `DOCKER_GID` to your host's
docker group id (e.g. `getent group docker | cut -d: -f3`) so Docker commands
work inside the container.

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
| `/docker [page]` | List containers with interactive buttons (optional page) |
| `/dinspect <container>` | Docker inspect (JSON, sent as file if large) |
| `/dockerstats` | CPU/memory per container |
| `/dstatsrich` | Detailed stats with network/block IO |
| `/dlogs <container> [page] [--since <time>] [--file]` | Container logs (default sends file; pagination is 50 lines) |
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
| `/pbtop [category]` | Pirate Bay top 10 (optional category or top mode) |
| `/pbsearch <query>` | Pirate Bay search (top 10 by seeds) |

Categories for `/pbtop`: audio, music, flac, video, hdmovies, hdtv, 4kmovies,
4ktv, apps, games, porn, ebook, other, top, top48h.

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

### Media
| Command | Description |
|---------|-------------|
| `/imdb <query>` | IMDB lookup (storyline, rating, cast) |
| `/imdbmovies` | IMDB trending movies |
| `/imdbshows` | IMDB trending shows |

### AI
| Command | Description |
|---------|-------------|
| `/ask <question>` | Ask a question via Ollama (supports flags like `--temp`, `--num-predict`) |
| `/askreset` | Reset custom AI generation parameters |

### Info
| Command | Description |
|---------|-------------|
| `/auth <code>` | Authorize sensitive commands for 15 minutes |
| `/help` | Show all commands |
| `/debug [command]` | Show recent errors/debug info |
| `/metrics` | Command metrics summary |
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
| `LOG_LEVEL` | `DEBUG` | Logging level (e.g. DEBUG, INFO, WARNING) |
| `SHOW_WAN` | `false` | Include WAN IP in `/health` |
| `WATCH_PATHS` | `/,/srv/media` | Paths for disk usage reporting |
| `QBT_HOST` | `qbittorrent` | qBittorrent hostname |
| `QBT_PORT` | `8080` | qBittorrent WebUI port |
| `QBT_USER` | `admin` | qBittorrent username |
| `QBT_PASS` | `adminadmin` | qBittorrent password |
| `QBT_TIMEOUT_S` | `8` | qBittorrent API timeout in seconds |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `llama2` | Default model for AI queries |
| `BOT_AUTH_TOTP_SECRET` | (none) | Base32 TOTP seed for `/auth` (Google Authenticator) |
| `TPB_BASE_URL` | `https://thepiratebay.org` | Pirate Bay HTML base URL (mirror override) |
| `TPB_API_BASE_URL` | `https://apibay.org` | Pirate Bay API base URL (fallback) |
| `TPB_API_BASE_URLS` | (none) | Comma-separated Pirate Bay API mirrors (tried in order) |
| `TPB_USER_AGENT` | `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36` | Pirate Bay User-Agent override |
| `TPB_COOKIE` | (none) | Pirate Bay Cookie header override (e.g. clearance tokens) |
| `TPB_REFERER` | (none) | Pirate Bay Referer header override |
| `IMDB_BASE_URL` | `https://www.imdb.com` | IMDB base URL (mirror override) |
| `MEDIA_USER_AGENT` | `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36` | User-Agent for IMDB requests |
| `IMDB_COOKIE` | (none) | IMDB Cookie header override (e.g. clearance tokens) |
| `IMDB_REFERER` | (none) | IMDB Referer header override |

### TOTP Auth Setup

Set `BOT_AUTH_TOTP_SECRET` to a Base32 secret and add it to Google Authenticator
(manual entry). Example generator:

```bash
python - <<'PY'
import base64
import secrets

print(base64.b32encode(secrets.token_bytes(20)).decode("utf-8").strip("="))
PY
```

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

This project uses [`uv`](https://github.com/astral-sh/uv) for dependency management.

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies and setup environment
uv sync

# Install pre-commit hooks
uv run pre-commit install

# Run locally
export BOT_TOKEN=...
export ALLOWED_CHAT_IDS=...
uv run bot.py
```

### Formatting & Linting

The project uses [`Ruff`](https://github.com/astral-sh/ruff) for fast linting and formatting (replaces Black, Flake8, Isort).

```bash
uv run ruff check .   # Lint
uv run ruff format .  # Format
```

### Testing

Run the test suite with pytest:

```bash
uv run pytest tests/ -v           # Verbose test output
uv run pytest tests/ --cov=tele_home_supervisor  # With coverage
```

### Security Scanning

Use Bandit for security analysis:

```bash
uv run bandit -r tele_home_supervisor
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
├── config.py         # Settings and environment variables
├── state.py          # Runtime state, caches, subscriptions
├── runtime.py        # Bot runtime initialization
├── background.py     # Background tasks (torrent polling, schedulers)
├── scheduled.py      # Fetchers for Epic, Steam, GOG, Humble, HN
├── services.py       # Business logic layer
├── ai_service.py     # Ollama integration
├── torrent.py        # qBittorrent API wrapper
├── view.py           # Message formatting utilities
├── logger.py         # Logging configuration
├── utils.py          # System/Docker/network utilities
└── handlers/
    ├── dispatch.py      # Rate-limiting dispatcher
    ├── callbacks.py     # Inline keyboard handlers
    ├── ai.py            # AI command handlers
    ├── meta.py          # /start, /help, /whoami, /version
    ├── system.py        # Host monitoring commands
    ├── docker.py        # Docker commands
    ├── network.py       # Network commands
    ├── torrents.py      # Torrent commands
    ├── notifications.py # Free games and news commands
    └── common.py        # Shared handler utilities
```

## CI/CD

The GitHub Actions pipeline ([`.github/workflows/ci-cd.yml`](.github/workflows/ci-cd.yml)):

1. **Quality**: Ruff linting & formatting check, Bandit security scan, Trivy filesystem scan.
2. **Test**: Pytest unit tests.
3. **Container Validation**: Docker Compose validation and Dockerfile linting with Hadolint.
4. **Build & Push**: Multi-arch Docker images (amd64, arm64) pushed to GHCR.
5. **Security**: Image signing with Cosign and SBOM generation with Syft.
6. **Notify**: Telegram notifications on failure with log snippets.

## Best Practices

### Code Quality
- All code passes Ruff linting and formatting checks
- Comprehensive docstrings for public APIs
- Type hints throughout the codebase for better IDE support
- 100% test coverage for critical paths

### Security
- No hard-coded secrets (uses environment variables)
- Input validation and sanitization
- Rate limiting on all commands
- Authorization checks on all handlers
- Regular security scans with Bandit and Trivy

### Architecture
- Clear separation of concerns (handlers, services, utilities)
- Async/await throughout for non-blocking I/O
- Proper error handling with logging
- Stateful caching with TTL for performance
- Background tasks for scheduled operations

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No Docker data | Verify `/var/run/docker.sock` is mounted |
| No torrent data | Check `QBT_*` environment variables and network connectivity |
| No AI response | Verify `OLLAMA_HOST` is reachable and model is pulled (`ollama pull llama2`) |
| Permission denied | Ensure the bot container can access the Docker socket |

## License

MIT
