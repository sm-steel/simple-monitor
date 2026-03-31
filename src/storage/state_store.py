from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import GlobalSettings, ServiceTarget, TimeWindow
from persistence import queries


@dataclass
class ServiceState:
    consecutive_failures: int = 0
    first_failure_at: Optional[datetime] = None
    last_notified_at: Optional[datetime] = None


def update_state(state: ServiceState, is_up: bool) -> ServiceState:
    if is_up:
        return ServiceState()
    now = datetime.now(timezone.utc)
    return ServiceState(
        consecutive_failures=state.consecutive_failures + 1,
        first_failure_at=state.first_failure_at or now,
        last_notified_at=state.last_notified_at,
    )


def mark_notified(state: ServiceState) -> ServiceState:
    return ServiceState(
        consecutive_failures=state.consecutive_failures,
        first_failure_at=state.first_failure_at,
        last_notified_at=datetime.now(timezone.utc),
    )


def effective_attempts(target: ServiceTarget, settings: GlobalSettings) -> int:
    return target.attempts if target.attempts is not None else settings.attempts


def should_alert(
    state: ServiceState, target: ServiceTarget, settings: GlobalSettings
) -> bool:
    return state.consecutive_failures >= effective_attempts(target, settings)


def _in_window(now: time, window: TimeWindow) -> bool:
    if window.start <= window.end:
        return window.start <= now <= window.end
    return now >= window.start or now <= window.end


def is_quiet_time(windows: list[TimeWindow]) -> bool:
    now = datetime.now(timezone.utc).time()
    return any(_in_window(now, w) for w in windows)


def should_notify(state: ServiceState, settings: GlobalSettings) -> bool:
    if is_quiet_time(settings.quiet_windows):
        return False
    if state.last_notified_at is None:
        return True
    elapsed = (datetime.now(timezone.utc) - state.last_notified_at).total_seconds()
    return elapsed >= settings.notification_delay


def _state_key(target: ServiceTarget) -> str:
    return f"{target.machine_name}/{target.name}/{target.port}"


@dataclass
class StateStore:
    db: async_sessionmaker[AsyncSession]
    _states: dict[str, ServiceState] = field(default_factory=dict)

    async def get_or_load(self, target: ServiceTarget) -> ServiceState:
        key = _state_key(target)
        if key in self._states:
            return self._states[key]
        async with self.db() as session:
            row = await queries.load_service_state_row(session, target)
        if row is None:
            state = ServiceState()
        else:
            state = ServiceState(
                consecutive_failures=row.consecutive_failures,
                first_failure_at=row.first_failure_at,
                last_notified_at=row.last_notified_at,
            )
        self._states[key] = state
        return state

    async def save(self, target: ServiceTarget, state: ServiceState) -> None:
        self._states[_state_key(target)] = state
        async with self.db() as session:
            await queries.upsert_service_state(
                session,
                target,
                state.consecutive_failures,
                state.first_failure_at,
                state.last_notified_at,
            )
