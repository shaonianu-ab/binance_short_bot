from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from eth_utils import to_checksum_address


def norm_addr(a: str) -> str:
    return to_checksum_address(a)


def pad_topic_address(addr: str) -> str:
    addr = addr.lower().replace("0x", "")
    return "0x" + ("0" * 24) + addr


@dataclass
class RateLimiter:
    max_calls: int
    period: float

    _tokens: float = 0
    _last: float = 0
    _lock: asyncio.Lock = asyncio.Lock()

    def __post_init__(self) -> None:
        self._tokens = float(self.max_calls)
        self._last = time.monotonic()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._last = now

            self._tokens = min(self.max_calls, self._tokens + elapsed * (self.max_calls / self.period))

            if self._tokens >= 1:
                self._tokens -= 1
                return

            need = (1 - self._tokens) * (self.period / self.max_calls)
        await asyncio.sleep(max(need, 0.0))
        await self.acquire()
