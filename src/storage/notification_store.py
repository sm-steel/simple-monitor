from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import ServiceTarget
from persistence import queries
from persistence.models import SentNotificationRow


@dataclass
class NotificationStore:
    db: async_sessionmaker[AsyncSession]

    async def save(self, target: ServiceTarget, message_id: int, chat_id: str) -> None:
        async with self.db() as session:
            await queries.save_notification(session, target, message_id, chat_id)

    async def load(self, target: ServiceTarget) -> list[SentNotificationRow]:
        async with self.db() as session:
            return await queries.load_notifications(session, target)

    async def load_older_than(self, cutoff: datetime) -> list[SentNotificationRow]:
        async with self.db() as session:
            return await queries.load_old_notifications(session, cutoff)

    async def delete(self, rows: list[SentNotificationRow]) -> None:
        async with self.db() as session:
            await queries.delete_notification_rows(session, rows)
