from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Optional

import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class TimeWindow:
    start: time
    end: time


@dataclass
class TelegramSettings:
    token: str
    chat_id: str
    proxy_url: Optional[str] = None


@dataclass
class GlobalSettings:
    interval: int = 60
    attempts: int = 3
    log_level: str = "INFO"
    notification_delay: int = 300  # seconds between repeat notifications
    notification_retention: int = (
        3600  # seconds before old notifications are auto-deleted
    )
    quiet_windows: list[TimeWindow] = field(default_factory=list)
    telegram: Optional[TelegramSettings] = None
    db_url: Optional[str] = None  # overridden by DATABASE_URL env var


@dataclass
class ServiceConfig:
    name: str
    ports: list[int]
    interval: Optional[int] = None
    attempts: Optional[int] = None


@dataclass
class MachineConfig:
    name: str
    ip: str
    interval: Optional[int] = None
    attempts: Optional[int] = None
    services: list[ServiceConfig] = field(default_factory=list)


@dataclass
class ServiceTarget:
    """Resolved, flat monitoring target for a single (machine, service, port) combination."""

    ip: str
    port: int
    name: str
    machine_name: str
    interval: Optional[int] = (
        None  # pre-resolved: service > machine; None falls back to global
    )
    attempts: Optional[int] = (
        None  # pre-resolved: service > machine; None falls back to global
    )


@dataclass
class AppConfig:
    settings: GlobalSettings
    machines: list[MachineConfig]


def expand_targets(config: AppConfig) -> list[ServiceTarget]:
    """Flatten machines/services/ports into individual ServiceTargets with resolved overrides."""
    targets: list[ServiceTarget] = []
    for machine in config.machines:
        for service in machine.services:
            resolved_interval = (
                service.interval if service.interval is not None else machine.interval
            )
            resolved_attempts = (
                service.attempts if service.attempts is not None else machine.attempts
            )
            for port in service.ports:
                name = (
                    f"{service.name}:{port}" if len(service.ports) > 1 else service.name
                )
                targets.append(
                    ServiceTarget(
                        ip=machine.ip,
                        port=port,
                        name=name,
                        machine_name=machine.name,
                        interval=resolved_interval,
                        attempts=resolved_attempts,
                    )
                )
    return targets


@dataclass
class AppContext:
    """Runtime context bundling the parsed config with its pre-expanded service targets and DB access."""

    config: AppConfig
    targets: list[ServiceTarget]
    db: Optional[async_sessionmaker[AsyncSession]] = field(default=None)


def load_context(path: str) -> AppContext:
    config = load_config(path)
    return AppContext(config=config, targets=expand_targets(config))


def _parse_time_window(raw: str) -> TimeWindow:
    parts = raw.strip().split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid time window format '{raw}', expected 'HH:MM-HH:MM'")
    start = time.fromisoformat(parts[0].strip())
    end = time.fromisoformat(parts[1].strip())
    return TimeWindow(start=start, end=end)


def _parse_global_settings(raw: dict) -> GlobalSettings:
    telegram: Optional[TelegramSettings] = None
    if tg := raw.get("telegram"):
        token = tg.get("token")
        chat_id = tg.get("chat_id")
        if not token or not chat_id:
            raise ValueError("telegram config requires both 'token' and 'chat_id'")
        proxy_url = tg.get("proxy_url")
        telegram = TelegramSettings(
            token=str(token),
            chat_id=str(chat_id),
            proxy_url=str(proxy_url) if proxy_url else None,
        )

    quiet_windows: list[TimeWindow] = []
    for window_str in raw.get("quiet_windows", []):
        quiet_windows.append(_parse_time_window(window_str))

    return GlobalSettings(
        interval=int(raw.get("interval", 60)),
        attempts=int(raw.get("attempts", 3)),
        log_level=str(raw.get("log_level", "INFO")).upper(),
        notification_delay=int(raw.get("notification_delay", 300)),
        notification_retention=int(raw.get("notification_retention", 3600)),
        quiet_windows=quiet_windows,
        telegram=telegram,
        db_url=str(raw["db_url"]) if raw.get("db_url") else None,
    )


def _parse_service_config(raw: dict) -> ServiceConfig:
    name = raw.get("name")
    ports = raw.get("ports")
    if not name:
        raise ValueError(f"Service entry missing 'name': {raw}")
    if not ports or not isinstance(ports, list):
        raise ValueError(
            f"Service entry missing or invalid 'ports' (must be a list): {raw}"
        )
    if not all(isinstance(p, int) and p > 0 for p in ports):
        raise ValueError(f"All ports must be positive integers: {raw}")
    return ServiceConfig(
        name=str(name),
        ports=[int(p) for p in ports],
        interval=int(raw["interval"]) if "interval" in raw else None,
        attempts=int(raw["attempts"]) if "attempts" in raw else None,
    )


def _parse_machine_config(raw: dict) -> MachineConfig:
    name = raw.get("name")
    ip = raw.get("ip")
    if not name:
        raise ValueError(f"Machine entry missing 'name': {raw}")
    if not ip:
        raise ValueError(f"Machine entry missing 'ip': {raw}")

    raw_services = raw.get("services", [])
    if not isinstance(raw_services, list):
        raise ValueError(f"'services' for machine '{name}' must be a list")

    services = [_parse_service_config(svc) for svc in raw_services]
    if not services:
        raise ValueError(f"Machine '{name}' has no services defined")

    return MachineConfig(
        name=str(name),
        ip=str(ip),
        interval=int(raw["interval"]) if "interval" in raw else None,
        attempts=int(raw["attempts"]) if "attempts" in raw else None,
        services=services,
    )


def load_config(path: str) -> AppConfig:
    with open(path, "r") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError("Config file must be a YAML mapping")

    raw_settings = data.get("settings", {})
    if not isinstance(raw_settings, dict):
        raise ValueError("'settings' must be a YAML mapping")

    settings = _parse_global_settings(raw_settings)

    raw_monitor = data.get("monitor", [])
    if not isinstance(raw_monitor, list):
        raise ValueError("'monitor' must be a YAML list")
    if not raw_monitor:
        raise ValueError("No machines defined under 'monitor'")

    machines = [_parse_machine_config(entry) for entry in raw_monitor]

    return AppConfig(settings=settings, machines=machines)
