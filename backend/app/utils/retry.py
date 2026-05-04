import asyncio
from typing import Callable, TypeVar
from app.logging_setup import get_logger

log = get_logger(__name__)
T = TypeVar("T")

async def retry_async(
    fn: Callable[..., T],
    *args,
    retries: int = 3,
    delay: float = 0.1,
    backoff: float = 2.0,
    **kwargs
) -> T:
    attempt = 0
    while True:
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            attempt += 1
            log.warning("retry.attempt", attempt=attempt, error=str(e))

            if attempt >= retries:
                log.error("retry.failed", error=str(e))
                raise

            await asyncio.sleep(delay)
            delay *= backoff
