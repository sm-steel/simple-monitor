import asyncio
import os
import signal
import sys

from loguru import logger

from config import load_context
from logging_setup import setup_logging
from persistence.database import init_db, make_engine, make_session_factory
from service.cleaner import run_cleaner
from service.monitor import Stores, run_all
from service.notifier import notify_shutdown, notify_startup
from storage.notification_store import NotificationStore
from storage.state_store import StateStore


def _install_signal_handlers(
    loop: asyncio.AbstractEventLoop, task: asyncio.Task
) -> None:
    def _handle_signal(sig: signal.Signals) -> None:
        logger.info(f"Received {sig.name}, shutting down...")
        task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)


async def _run(config_path: str) -> None:
    ctx = load_context(config_path)
    setup_logging(ctx.config.settings.log_level)
    logger.info(
        f"Configuration loaded from '{config_path}' — {len(ctx.targets)} service(s)"
    )

    db_url = os.getenv("DATABASE_URL") or ctx.config.settings.db_url
    if not db_url:
        raise ValueError(
            "Database URL not configured. Set DATABASE_URL env var or settings.db_url in config."
        )
    engine = make_engine(db_url)
    await init_db(engine)
    session_factory = make_session_factory(engine)
    logger.info("Database initialized")

    stores = Stores(
        state=StateStore(db=session_factory),
        notifications=NotificationStore(db=session_factory),
    )

    if ctx.config.settings.telegram:
        await notify_startup(
            ctx.config.settings.telegram, ctx.config.settings, stores.notifications
        )
        asyncio.create_task(
            run_cleaner(
                ctx.config.settings.telegram,
                stores.notifications,
                ctx.config.settings.notification_retention,
            )
        )

    loop = asyncio.get_running_loop()
    main_task = asyncio.current_task()
    assert main_task is not None
    _install_signal_handlers(loop, main_task)

    try:
        ctx = await run_all(config_path, ctx, stores)
    except asyncio.CancelledError:
        pass
    finally:
        if ctx.config.settings.telegram:
            await notify_shutdown(
                ctx.config.settings.telegram, ctx.config.settings, stores.notifications
            )
        await engine.dispose()
        logger.info("simple-monitor stopped")


def main() -> None:
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    try:
        asyncio.run(_run(config_path))
    except KeyboardInterrupt:
        pass
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"Startup error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
