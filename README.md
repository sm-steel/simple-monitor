# simple-monitor

Lightweight TCP port monitoring service for remote hosts. Checks configured services on a regular interval and sends Telegram alerts when a service goes down, with repeat notifications, recovery messages, quiet windows, and automatic cleanup of old alerts.

**Features:**
- TCP reachability checks per host/service/port
- Telegram alerts on failure and recovery
- Configurable check intervals and failure thresholds (globally and per machine/service)
- Repeat notifications with configurable delay
- Quiet windows (no notifications during specified time ranges)
- Automatic deletion of old Telegram messages
- Hot config reload without restart
- State persistence in PostgreSQL

---

## Quick Start

### With Docker Compose (recommended)

1. Clone the repository:
   ```sh
   git clone https://github.com/your-username/simple-monitor.git
   cd simple-monitor
   ```

2. Copy the example config and fill in your values:
   ```sh
   cp config.example.yaml config.yaml
   ```

3. Edit `config.yaml` — at minimum set `telegram.token`, `telegram.chat_id`, and your machines/services.

4. Start:
   ```sh
   docker compose up -d
   ```

The database URL is pre-configured in `docker-compose.yml`. To use an external database, set the `DATABASE_URL` environment variable.

### Without Docker

Requirements: Python 3.12+, PostgreSQL, [uv](https://github.com/astral-sh/uv)

```sh
git clone https://github.com/your-username/simple-monitor.git
cd simple-monitor
uv sync
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/monitor \
  uv run src/main.py config.yaml
```

---

## Configuration

Configuration is a YAML file with two top-level keys: `settings` and `monitor`.

### `settings`

Global defaults and integrations.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `interval` | int | `60` | Check interval in seconds |
| `attempts` | int | `3` | Consecutive failures before alerting |
| `log_level` | string | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `notification_delay` | int | `300` | Seconds between repeat notifications for the same down service |
| `notification_retention` | int | `3600` | Seconds before sent Telegram messages are auto-deleted |
| `quiet_windows` | list[string] | `[]` | Time ranges during which no notifications are sent (see below) |
| `db_url` | string | — | PostgreSQL URL. Prefer `DATABASE_URL` env var |
| `telegram` | object | — | Telegram bot config (see below) |

#### `settings.telegram`

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `token` | string | yes | Bot token from @BotFather |
| `chat_id` | string | yes | Target chat or group ID |
| `proxy_url` | string | no | HTTP/HTTPS/SOCKS5 proxy URL |

#### Quiet windows

A list of `"HH:MM-HH:MM"` strings. Ranges that cross midnight are supported.

```yaml
quiet_windows:
  - "23:00-07:00"   # overnight (crosses midnight)
  - "12:00-13:00"   # lunch break
```

No alerts (including startup/shutdown messages) are sent while inside a quiet window.

---

### `monitor`

A list of machine entries to monitor.

#### Machine fields

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `name` | string | yes | Display name for the machine |
| `ip` | string | yes | IP address or hostname |
| `interval` | int | no | Override global `interval` for all services on this machine |
| `attempts` | int | no | Override global `attempts` for all services on this machine |
| `services` | list | yes | List of services to monitor (see below) |

#### Service fields

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `name` | string | yes | Display name for the service |
| `ports` | list[int] | yes | One or more TCP ports to check |
| `interval` | int | no | Override interval for this service (takes precedence over machine-level) |
| `attempts` | int | no | Override attempts for this service (takes precedence over machine-level) |

When `ports` contains multiple values, each port is monitored as a separate target named `"<service>:<port>"`.

Override precedence: **service > machine > global**.

---

### Full example

```yaml
settings:
  interval: 60
  attempts: 3
  log_level: INFO
  notification_delay: 300
  notification_retention: 3600
  quiet_windows:
    - "23:00-07:00"
    - "12:00-13:00"
  telegram:
    token: "123123:AAAAAAAAAAAAAAAA"
    chat_id: "-123"
    proxy_url: "http://host:3128"  # optional

monitor:
  - name: Web Server
    ip: 192.168.1.10
    interval: 30
    attempts: 2
    services:
      - name: nginx
        ports: [80, 443]
      - name: Postgres DB
        ports: [5432]
        interval: 60

  - name: Bastion
    ip: 192.168.1.11
    services:
      - name: SSH
        ports: [22]
      - name: Foo
        ports: [81]
        attempts: 1
```
