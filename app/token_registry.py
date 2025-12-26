from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

import aiohttp

from .utils import RateLimiter

log = logging.getLogger("token_registry")


class BinanceTokenRegistry:
    def __init__(self, url: str, max_rpm: int, cache_ttl: int) -> None:
        self._url = url
        self._limiter = RateLimiter(max_calls=max_rpm, period=60.0)
        self._cache_ttl = cache_ttl

        self._lock = asyncio.Lock()
        self._last_fetch = 0.0
        self._cached: Dict[str, Dict[str, Any]] = {}

    async def _fetch(self) -> Dict[str, Dict[str, Any]]:
        await self._limiter.acquire()
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(self._url) as resp:
                resp.raise_for_status()
                data = await resp.json()

        tokens = data.get("data") or data.get("Data") or data
        out: Dict[str, Dict[str, Any]] = {}
        if isinstance(tokens, list):
            for t in tokens:
                sym = (t.get("symbol") or t.get("tokenSymbol") or "").upper()
                if not sym:
                    continue
                out[sym] = t
        elif isinstance(tokens, dict):
            lst = tokens.get("list") or tokens.get("tokens") or []
            if isinstance(lst, list):
                for t in lst:
                    sym = (t.get("symbol") or t.get("tokenSymbol") or "").upper()
                    if sym:
                        out[sym] = t

        return out

    async def refresh_if_needed(self) -> None:
        now = time.monotonic()
        if now - self._last_fetch < self._cache_ttl and self._cached:
            return

        async with self._lock:
            now2 = time.monotonic()
            if now2 - self._last_fetch < self._cache_ttl and self._cached:
                return
            try:
                self._cached = await self._fetch()
                self._last_fetch = time.monotonic()
                log.debug("token list refreshed: %d tokens", len(self._cached))
            except Exception as e:
                log.warning("token list refresh failed: %s", e, exc_info=True)

    async def get_token_info(self, symbol_upper: str) -> Optional[Dict[str, Any]]:
        await self.refresh_if_needed()
        return self._cached.get(symbol_upper.upper())

    @staticmethod
    def extract_price_usdt(token_info: Dict[str, Any]) -> Optional[float]:
        for k in ["price", "lastPrice", "usdtPrice", "priceUsd", "priceUSDT"]:
            v = token_info.get(k)
            if v is None:
                continue
            try:
                return float(v)
            except Exception:
                continue
        return None
