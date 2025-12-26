from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import aiohttp
from eth_utils import to_checksum_address

log = logging.getLogger("erc20_metadata")

DECIMALS_CALLDATA = "0x313ce567"
SYMBOL_CALLDATA = "0x95d89b41"


@dataclass
class TokenMeta:
    symbol: str
    decimals: int
    ts: float


class ERC20MetadataClient:
    def __init__(self, rpc_http_url: str, cache_ttl_sec: int = 24 * 3600) -> None:
        self.rpc_http_url = rpc_http_url
        self.cache_ttl_sec = cache_ttl_sec

        self._cache: Dict[str, TokenMeta] = {}
        self._inflight: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _now() -> float:
        return time.monotonic()

    def _cache_get(self, contract: str) -> Optional[TokenMeta]:
        key = contract.lower()
        meta = self._cache.get(key)
        if not meta:
            return None
        if self._now() - meta.ts > self.cache_ttl_sec:
            self._cache.pop(key, None)
            return None
        return meta

    def _cache_set(self, contract: str, symbol: str, decimals: int) -> TokenMeta:
        meta = TokenMeta(symbol=symbol.upper(), decimals=int(decimals), ts=self._now())
        self._cache[contract.lower()] = meta
        return meta

    async def get_symbol_decimals(self, token_contract: str, timeout_sec: float = 1.0) -> Optional[Tuple[str, int]]:
        token_contract = to_checksum_address(token_contract)
        cached = self._cache_get(token_contract)
        if cached:
            return cached.symbol, cached.decimals

        key = token_contract.lower()
        async with self._lock:
            cached2 = self._cache_get(token_contract)
            if cached2:
                return cached2.symbol, cached2.decimals

            fut = self._inflight.get(key)
            if fut is None:
                loop = asyncio.get_running_loop()
                fut = loop.create_future()
                self._inflight[key] = fut
                do_fetch = True
            else:
                do_fetch = False

        if not do_fetch:
            try:
                return await asyncio.wait_for(fut, timeout=timeout_sec)
            except Exception:
                return None

        try:
            # 并发请求 symbol/decimals，降低首次延迟
            symbol_res, decimals_res = await asyncio.gather(
                self._eth_call_symbol(token_contract, timeout_sec=timeout_sec),
                self._eth_call_decimals(token_contract, timeout_sec=timeout_sec),
                return_exceptions=True,
            )

            symbol = None if isinstance(symbol_res, Exception) else symbol_res
            decimals = None if isinstance(decimals_res, Exception) else decimals_res

            if not symbol or decimals is None:
                raise RuntimeError("metadata incomplete")

            meta = self._cache_set(token_contract, symbol, decimals)

            async with self._lock:
                f = self._inflight.pop(key, None)
                if f and not f.done():
                    f.set_result((meta.symbol, meta.decimals))
            return meta.symbol, meta.decimals

        except Exception as e:
            log.info("metadata fetch failed token=%s err=%s", token_contract, e)
            async with self._lock:
                f = self._inflight.pop(key, None)
                if f and not f.done():
                    f.set_result(None)
            return None

    async def _rpc(self, method: str, params: list, timeout_sec: float) -> dict:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        timeout = aiohttp.ClientTimeout(total=timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self.rpc_http_url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
                if "error" in data:
                    raise RuntimeError(data["error"])
                return data

    async def _eth_call(self, to_addr: str, data: str, timeout_sec: float) -> str:
        res = await self._rpc(
            "eth_call",
            [{"to": to_checksum_address(to_addr), "data": data}, "latest"],
            timeout_sec=timeout_sec,
        )
        return res.get("result", "0x")

    async def _eth_call_decimals(self, token_contract: str, timeout_sec: float) -> Optional[int]:
        raw = await self._eth_call(token_contract, DECIMALS_CALLDATA, timeout_sec=timeout_sec)
        if not raw or raw == "0x":
            return None
        try:
            return int(raw, 16)
        except Exception:
            return None

    async def _eth_call_symbol(self, token_contract: str, timeout_sec: float) -> Optional[str]:
        raw = await self._eth_call(token_contract, SYMBOL_CALLDATA, timeout_sec=timeout_sec)
        if not raw or raw == "0x":
            return None

        h = raw[2:]
        try:
            b = bytes.fromhex(h)
        except Exception:
            return None

        if len(b) == 32:
            s = b.rstrip(b"\x00").decode("utf-8", errors="ignore").strip()
            return s or None

        if len(b) >= 96:
            try:
                strlen = int.from_bytes(b[32:64], "big")
                sbytes = b[64:64 + strlen]
                s = sbytes.decode("utf-8", errors="ignore").strip()
                return s or None
            except Exception:
                return None

        return None
