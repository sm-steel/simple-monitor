from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import ServiceTarget
from persistence.models import SentNotificationRow, ServiceStateRow


async def load_service_state_row(
    session: AsyncSession, target: ServiceTarget
) -> Optional[ServiceStateRow]:
    return await session.scalar(
        select(ServiceStateRow).where(
            ServiceStateRow.machine_name == target.machine_name,
            ServiceStateRow.service_name == target.name,
            ServiceStateRow.port == target.port,
        )
    )


async def upsert_service_state(
    session: AsyncSession,
    target: ServiceTarget,
    consecutive_failures: int,
    first_failure_at: Optional[datetime],
    last_notified_at: Optional[datetime],
) -> None:
    row = await load_service_state_row(session, target)
    if row is None:
        row = ServiceStateRow(
            machine_name=target.machine_name,
            service_name=target.name,
            port=target.port,
        )
        session.add(row)
    row.consecutive_failures = consecutive_failures
    row.first_failure_at = first_failure_at
    row.last_notified_at = last_notified_at
    await session.commit()


async def save_notification(
    session: AsyncSession,
    target: ServiceTarget,
    message_id: int,
    chat_id: str,
) -> None:
    session.add(
        SentNotificationRow(
            machine_name=target.machine_name,
            service_name=target.name,
            port=target.port,
            telegram_message_id=message_id,
            chat_id=chat_id,
        )
    )
    await session.commit()


async def load_notifications(
    session: AsyncSession, target: ServiceTarget
) -> list[SentNotificationRow]:
    return list(
        (
            await session.scalars(
                select(SentNotificationRow).where(
                    SentNotificationRow.machine_name == target.machine_name,
                    SentNotificationRow.service_name == target.name,
                    SentNotificationRow.port == target.port,
                )
            )
        ).all()
    )


async def load_old_notifications(
    session: AsyncSession, older_than: datetime
) -> list[SentNotificationRow]:
    return list(
        (
            await session.scalars(
                select(SentNotificationRow).where(
                    SentNotificationRow.sent_at < older_than
                )
            )
        ).all()
    )


async def delete_notification_rows(
    session: AsyncSession, rows: list[SentNotificationRow]
) -> None:
    for row in rows:
        await session.delete(row)
    await session.commit()
