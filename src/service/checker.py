import asyncio

from loguru import logger

from config import ServiceTarget

CONNECT_TIMEOUT = 5  # seconds


async def check_service(target: ServiceTarget) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(target.ip, target.port),
            timeout=CONNECT_TIMEOUT,
        )
        writer.close()
        await writer.wait_closed()
        logger.debug(f"[{target.name}] {target.ip}:{target.port} is UP")
        return True
    except (OSError, asyncio.TimeoutError) as e:
        logger.debug(f"[{target.name}] {target.ip}:{target.port} is DOWN — {e}")
        return False
