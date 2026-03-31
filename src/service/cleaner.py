from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from loguru import logger
from telegram.error import TelegramError

from config import TelegramSettings
from persistence.models import SentNotificationRow
from storage.notification_store import NotificationStore


async def _delete_rows(
    rows: list[SentNotificationRow],
    settings: TelegramSettings,
    store: NotificationStore,
) -> None:
    from service.notifier import _build_bot  # local import to avoid circular

    bot = _build_bot(settings)
    for row in rows:
        try:
            await bot.delete_message(
                chat_id=row.chat_id, message_id=row.telegram_message_id
            )
            logger.debug(f"Cleaner deleted Telegram message {row.telegram_message_id}")
        except TelegramError as e:
            logger.warning(
                f"Cleaner failed to delete Telegram message {row.telegram_message_id}: {e}"
            )
    await store.delete(rows)


async def run_cleaner(
    settings: TelegramSettings,
    store: NotificationStore,
    retention_seconds: int,
) -> None:
    logger.info(f"Starting notification cleaner (retention={retention_seconds}s)")
    while True:
        await asyncio.sleep(retention_seconds)
        cutoff = datetime.now() - timedelta(seconds=retention_seconds)
        rows = await store.load_older_than(cutoff)
        if rows:
            logger.info(f"Cleaner found {len(rows)} expired notification(s) to delete")
            await _delete_rows(rows, settings, store)
