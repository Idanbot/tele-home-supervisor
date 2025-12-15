# tele-home-supervisor

Telegram bot for monitoring a Raspberry Pi (or any Linux host) and managing Docker + qBittorrent from chat.

- Runs as a Docker container (multi-arch: `linux/amd64` and `linux/arm64`).
- Uses the Docker socket to inspect containers and fetch logs.
- Uses qBittorrent WebUI API for torrent operations.
- Built with `python-telegram-bot`.

## Features

**Host monitoring**
- LAN/WAN IP (WAN optional), CPU/RAM/load, uptime, disk usage for configured paths
- CPU temperature (supports `/host_thermal/temp` mount)
- Top CPU processes

**Docker**
- List containers + ports
- Per-container stats
- Detailed stats (net/block IO)
- Container logs and health status

**Networking**
- Ping
- DNS lookup
- Traceroute/tracepath
- Quick download speed test (no files are written)
- List listening ports inside the container

**qBittorrent**
- Add magnet/URL
- Status (includes downloaded/total size)
- Pause/resume by name substring
- Delete torrents + files (confirmation required)
- Optional torrent completion notifications (`/subscribe`)

## Commands

/start - Show help  
/help - Show this menu  
/whoami - Show chat and user info  
/version - Show bot version and build info  
/ip - Show private LAN IP  
/health - Show CPU/RAM/disk/load/uptime (and WAN if enabled)  
/uptime - Show system uptime  
/temp - Show CPU temperature (reads /host_thermal/temp)  
/top - Show top CPU processes  
/docker - List containers, status, ports  
/dockerstats - Show CPU/MEM per running container  
/dstatsrich - Show detailed Docker stats (net/block IO)  
/dlogs - Show recent logs from a container  
/dhealth - Show container health check  
/ping - Ping an IP or hostname  
/ports - Show listening ports (inside container)  
/dns - DNS lookup  
/traceroute - Trace network route  
/speedtest - Quick download speed test  
/tadd - Add torrent (magnet/URL)  
/tstatus - Show torrent status  
/tstop - Pause torrent(s) by name  
/tstart - Resume torrent(s) by name  
/tdelete - Delete torrent(s) and files  
/subscribe - Torrent completion notifications  

Note: Telegram does not support argument autocomplete while typing. For commands that require a container/torrent name, the bot replies with up to 5 suggestions when you send the command without arguments.

## Quick Start (Docker Compose)

1. Create a `.env` file (or export env vars in your shell):

   ```bash
   BOT_TOKEN=123456:abc...
   ALLOWED_CHAT_IDS=11111111,22222222
   QBT_HOST=qbittorrent
   QBT_PORT=8080
   QBT_USER=admin
   QBT_PASS=adminadmin
   ```

2. Ensure your Docker network exists (this repo expects an external network named `bit-net`):

   ```bash
   docker network create bit-net
   ```

3. Start the bot:

   ```bash
   docker compose up -d
   ```

The provided `docker-compose.yml` also includes Watchtower to auto-update the bot container.

## Configuration

Environment variables used by the bot:

- `BOT_TOKEN` (required): Telegram bot token.
- `ALLOWED_CHAT_IDS` (required): Comma-separated chat IDs that can use the bot.
- `RATE_LIMIT_S` (optional, default `1.0`): Global command rate limit.
- `SHOW_WAN` (optional, default `false`): If true, `/ip` and `/health` include WAN IP.
- `WATCH_PATHS` (optional, default `/,/srv/media`): Comma-separated paths for disk usage in `/health`.

qBittorrent:
- `QBT_HOST` (default `qbittorrent`)
- `QBT_PORT` (default `8080`)
- `QBT_USER` (default `admin`)
- `QBT_PASS` (default `adminadmin`)

Build metadata (set automatically by CI):
- `TELE_HOME_SUPERVISOR_BUILD_VERSION`: Shown in `/version` as a timestamped build tag.

## Volumes and Host Access

The bot needs access to:

- Docker socket for Docker commands:
  - `/var/run/docker.sock:/var/run/docker.sock`
- Optional media mount for disk usage reporting:
  - `/srv/media:/srv/media:ro`
- Optional thermal mount for CPU temp:
  - `/sys/class/thermal/thermal_zone0:/host_thermal:ro`

## Architecture

High-level flow:

- `tele_home_supervisor/main.py` builds the Telegram application and registers commands.
- `tele_home_supervisor/commands.py` is the single source of truth for command wiring and help text (grouped).
- `tele_home_supervisor/handlers/*` contain command handlers, split by domain:
  - `handlers/meta.py`: `/start`, `/help`, `/whoami`, `/version`
  - `handlers/system.py`: host health, ping, temp, top
  - `handlers/docker.py`: docker list/stats/logs/health/ports
  - `handlers/network.py`: dns/traceroute/speedtest
  - `handlers/torrents.py`: torrent operations + subscribe
  - `handlers/dispatch.py`: applies a global rate limit wrapper before calling the real handler
- `tele_home_supervisor/state.py` stores runtime state in `Application.bot_data`:
  - in-memory caches for container/torrent names (used for suggestions)
  - subscription state for torrent completion notifications
  - background task handles
- `tele_home_supervisor/background.py` runs background jobs (currently torrent completion polling).
- `tele_home_supervisor/services.py` provides synchronous “business” helpers used from handlers via `asyncio.to_thread`.
- `tele_home_supervisor/utils.py` implements system/Docker/network helpers and formatting.
- `tele_home_supervisor/torrent.py` wraps `qbittorrent-api` interactions.

### Suggestions and caching

For commands requiring a container/torrent name, the bot keeps an in-memory cache:

- Containers: refreshed on `/docker` and lazily refreshed when needed.
- Torrents: refreshed on `/tstatus` and lazily refreshed when needed.

If a cache is empty (e.g., Docker socket unavailable, qBittorrent not reachable), suggestions will not appear.

### Background notifications

`/subscribe` toggles torrent completion notifications for your chat. The bot polls qBittorrent periodically and sends a message when a torrent transitions to “complete”.

Subscription state is currently in-memory (resets on container restart). If you want persistence, add a small storage backend (json/sqlite/redis) and load into `BotState` on startup.

## CI/CD and DevOps

### GitHub Actions pipeline

Workflow: `.github/workflows/build-and-push.yml`

- **Lint**: runs pylint (fatal errors only) on every push to `main` and on version tags.
- **Build (scan)**: builds an `amd64` image and loads it for scanning.
- **Security scan**: runs Trivy against the built image.
- **Build & push**: builds and pushes multi-arch images (`linux/amd64` + `linux/arm64`) to GHCR.
- **Build version tag**: CI injects a timestamped `BUILD_VERSION` into the Docker image (exposed in `/version`).

### Deployment model

Recommended: run on the Raspberry Pi with Docker Compose plus Watchtower.

- The bot image is pulled from GHCR.
- Watchtower periodically checks for updates and restarts the bot container.

## Development

Local run (non-Docker) requires Python 3.11+ and dependencies:

```bash
pip install -r requirements.txt
export BOT_TOKEN=...
export ALLOWED_CHAT_IDS=...
python bot.py
```

For Docker builds:

```bash
docker build -t tele-home-supervisor .
```

## Troubleshooting

- **No Docker data**: verify `/var/run/docker.sock` is mounted and `DOCKER_HOST=unix:///var/run/docker.sock` is set.
- **No torrent data**: verify `QBT_HOST/QBT_PORT/QBT_USER/QBT_PASS` and container networking.
- **Suggestions not shown**: send the command without args (e.g. `/dlogs`) and ensure the cache is non-empty.

