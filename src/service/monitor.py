from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from loguru import logger

from config import AppContext, ServiceTarget, load_context
from logging_setup import setup_logging
from service.checker import check_service
from service.notifier import (
    build_message,
    build_recovery_message,
    send_notification,
    send_recovery_notification,
)
from storage.notification_store import NotificationStore
from storage.state_store import (
    StateStore,
    mark_notified,
    should_alert,
    should_notify,
    update_state,
)

_CONFIG_POLL_INTERVAL = 2.0  # seconds


@dataclass
class Stores:
    state: StateStore
    notifications: NotificationStore


async def monitor_service(
    target: ServiceTarget, ctx: AppContext, stores: Stores
) -> None:
    settings = ctx.config.settings
    interval = target.interval if target.interval is not None else settings.interval
    state = await stores.state.get_or_load(target)
    logger.info(
        f"[{target.machine_name}/{target.name}] Starting monitor for {target.ip}:{target.port} (interval={interval}s)"
    )

    while True:
        is_up = await check_service(target)
        was_down = state.consecutive_failures > 0
        down_since = state.first_failure_at
        state = update_state(state, is_up)
        await stores.state.save(target, state)

        if is_up:
            logger.info(
                f"[{target.machine_name}/{target.name}] {target.ip}:{target.port} is UP"
            )
            if was_down and settings.telegram:
                await send_recovery_notification(
                    build_recovery_message(down_since, target), settings.telegram
                )
        else:
            logger.warning(
                f"[{target.machine_name}/{target.name}] {target.ip}:{target.port} is DOWN "
                f"(consecutive failures: {state.consecutive_failures})"
            )
            if (
                should_alert(state, target, settings)
                and should_notify(state, settings)
                and settings.telegram is not None
            ):
                msg = build_message(state, target)
                message_id = await send_notification(msg, settings.telegram)
                if message_id is not None:
                    await stores.notifications.save(
                        target, message_id, settings.telegram.chat_id
                    )
                state = mark_notified(state)
                await stores.state.save(target, state)

        await asyncio.sleep(interval)


async def _wait_for_config_change(path: str) -> None:
    """Resolves as soon as the file's mtime differs from when we started watching."""
    mtime = os.path.getmtime(path)
    while True:
        await asyncio.sleep(_CONFIG_POLL_INTERVAL)
        try:
            if os.path.getmtime(path) != mtime:
                return
        except OSError:
            pass


async def _cancel_all(tasks: list[asyncio.Task]) -> None:
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def run_all(config_path: str, ctx: AppContext, stores: Stores) -> AppContext:
    """Run all service monitors, restarting them whenever the config file changes.
    Returns the last successfully loaded AppContext (useful for shutdown notifications)."""
    while True:
        logger.info(f"Spawning {len(ctx.targets)} monitor task(s)")
        monitor_tasks = [
            asyncio.create_task(monitor_service(target, ctx, stores))
            for target in ctx.targets
        ]
        watcher_task = asyncio.create_task(_wait_for_config_change(config_path))

        done, pending = await asyncio.wait(
            [watcher_task, *monitor_tasks],
            return_when=asyncio.FIRST_COMPLETED,
        )
        await _cancel_all(list(pending))

        if watcher_task not in done:
            watcher_task.cancel()
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc
            return ctx

        # Config file changed
        logger.info(f"Config file '{config_path}' changed, reloading...")
        try:
            reloaded = load_context(config_path)
            ctx = AppContext(
                config=reloaded.config, targets=reloaded.targets, db=ctx.db
            )
            setup_logging(ctx.config.settings.log_level)
            logger.info(
                f"Config reloaded — {len(ctx.targets)} service(s), "
                f"log_level={ctx.config.settings.log_level}"
            )
        except (ValueError, OSError) as e:
            logger.error(
                f"Failed to reload config, keeping previous configuration: {e}"
            )
