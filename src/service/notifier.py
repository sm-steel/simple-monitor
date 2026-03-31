from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from telegram.error import TelegramError
from telegram.ext import ApplicationBuilder

from config import GlobalSettings, ServiceTarget, TelegramSettings
from storage.notification_store import NotificationStore
from storage.state_store import ServiceState, is_quiet_time

# Sentinel target used to track startup/shutdown notifications in the store
_SYSTEM_TARGET = ServiceTarget(
    ip="",
    port=0,
    name="monitor",
    machine_name="__system__",
)


@dataclass
class NotificationMessage:
    ip: str
    port: int
    name: str
    machine_name: str
    down_since: datetime


@dataclass
class RecoveryMessage:
    ip: str
    port: int
    name: str
    machine_name: str
    down_since: Optional[datetime]


def build_message(state: ServiceState, target: ServiceTarget) -> NotificationMessage:
    return NotificationMessage(
        ip=target.ip,
        port=target.port,
        name=target.name,
        machine_name=target.machine_name,
        down_since=state.first_failure_at or datetime.now(),
    )


def build_recovery_message(
    down_since: Optional[datetime], target: ServiceTarget
) -> RecoveryMessage:
    return RecoveryMessage(
        ip=target.ip,
        port=target.port,
        name=target.name,
        machine_name=target.machine_name,
        down_since=down_since,
    )


def _format_alert(msg: NotificationMessage) -> str:
    down_since_str = msg.down_since.strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"🔴 Service DOWN\n"
        f"Machine: {msg.machine_name}\n"
        f"Service: {msg.name}\n"
        f"Address: {msg.ip}:{msg.port}\n"
        f"Down since: {down_since_str}"
    )


def _format_recovery(msg: RecoveryMessage) -> str:
    if msg.down_since:
        down_since_str = msg.down_since.strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"✅ Service UP\n"
            f"Machine: {msg.machine_name}\n"
            f"Service: {msg.name}\n"
            f"Address: {msg.ip}:{msg.port}\n"
            f"Was down since: {down_since_str}"
        )
    return (
        f"✅ Service UP\n"
        f"Machine: {msg.machine_name}\n"
        f"Service: {msg.name}\n"
        f"Address: {msg.ip}:{msg.port}"
    )


def _build_bot(settings: TelegramSettings):
    builder = ApplicationBuilder().token(settings.token)
    if settings.proxy_url:
        builder = builder.proxy(settings.proxy_url).get_updates_proxy(
            settings.proxy_url
        )
    return builder.build().bot


async def send_notification(
    msg: NotificationMessage, settings: TelegramSettings
) -> Optional[int]:
    """Send a service-down alert and return the Telegram message_id, or None on failure."""
    try:
        bot = _build_bot(settings)
        result = await bot.send_message(
            chat_id=settings.chat_id, text=_format_alert(msg)
        )
        logger.debug(f"Telegram notification sent for {msg.machine_name}/{msg.name}")
        return result.message_id
    except TelegramError as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return None


async def send_recovery_notification(
    msg: RecoveryMessage, settings: TelegramSettings
) -> None:
    """Send a service-recovery alert."""
    try:
        bot = _build_bot(settings)
        await bot.send_message(chat_id=settings.chat_id, text=_format_recovery(msg))
        logger.debug(f"Recovery notification sent for {msg.machine_name}/{msg.name}")
    except TelegramError as e:
        logger.error(f"Failed to send recovery notification: {e}")


async def delete_notifications(
    target: ServiceTarget,
    settings: TelegramSettings,
    store: NotificationStore,
) -> None:
    """Delete all stored Telegram alert messages for a target and remove them from the store."""
    rows = await store.load(target)
    if not rows:
        return

    bot = _build_bot(settings)
    for row in rows:
        try:
            await bot.delete_message(
                chat_id=row.chat_id, message_id=row.telegram_message_id
            )
            logger.debug(
                f"Deleted Telegram message {row.telegram_message_id} for {target.machine_name}/{target.name}"
            )
        except TelegramError as e:
            logger.warning(
                f"Failed to delete Telegram message {row.telegram_message_id}: {e}"
            )
    await store.delete(rows)


async def notify_startup(
    settings: TelegramSettings,
    global_settings: GlobalSettings,
    store: NotificationStore,
) -> None:
    await _send_system_text(
        "✅ simple-monitor started", settings, global_settings, store
    )


async def notify_shutdown(
    settings: TelegramSettings,
    global_settings: GlobalSettings,
    store: NotificationStore,
) -> None:
    await _send_system_text(
        "🛑 simple-monitor stopped", settings, global_settings, store
    )


async def _send_system_text(
    text: str,
    settings: TelegramSettings,
    global_settings: GlobalSettings,
    store: NotificationStore,
) -> None:
    if is_quiet_time(global_settings.quiet_windows):
        logger.debug(f"Skipping system notification (quiet window): {text!r}")
        return

    rows = await store.load(_SYSTEM_TARGET)
    if rows:
        last_sent = max(r.sent_at for r in rows)
        if last_sent.tzinfo is None:
            last_sent = last_sent.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last_sent).total_seconds()
        if elapsed < global_settings.notification_delay:
            logger.debug(f"Skipping system notification (delay not elapsed): {text!r}")
            return

    try:
        bot = _build_bot(settings)
        result = await bot.send_message(chat_id=settings.chat_id, text=text)
        logger.debug(f"Telegram system notification sent: {text!r}")
        await store.save(_SYSTEM_TARGET, result.message_id, settings.chat_id)
    except TelegramError as e:
        logger.error(f"Failed to send system notification: {e}")
