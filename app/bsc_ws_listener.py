from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import websockets

from .utils import norm_addr, pad_topic_address

log = logging.getLogger("bsc_ws_listener")

TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


@dataclass
class ERC20TransferIn:
    token_contract: str
    from_addr: str
    to_addr: str
    amount_raw: int
    tx_hash: str
    block_number: int


class BscWsListener:
    """BSC WebSocket listener (Alchemy/Infura/custom).

    Uses standard JSON-RPC over WebSocket (eth_subscribe logs).
    """

    def __init__(self, ws_url: str, watch_address: str) -> None:
        self.ws_url = ws_url
        self.watch_address = norm_addr(watch_address)
        self.watch_topic = pad_topic_address(self.watch_address)

    async def listen(self) -> AsyncIterator[ERC20TransferIn]:
        backoff = 0.2
        while True:
            try:
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20, max_queue=1024) as ws:
                    backoff = 0.2
                    sub_id = await self._subscribe_logs(ws)
                    log.info("subscribed: %s", sub_id)

                    async for msg in ws:
                        evt = self._parse_message(msg)
                        if evt:
                            yield evt

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("ws disconnected: %s", e, exc_info=True)
                await asyncio.sleep(min(backoff, 3.0))
                backoff = min(backoff * 2, 3.0)

    async def _subscribe_logs(self, ws) -> str:
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": [
                "logs",
                {
                    "topics": [
                        TRANSFER_TOPIC0,
                        None,
                        self.watch_topic,
                    ]
                },
            ],
        }
        await ws.send(json.dumps(req))
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        data = json.loads(raw)
        if "result" not in data:
            raise RuntimeError(f"subscribe failed: {data}")
        return data["result"]

    def _parse_message(self, msg: str) -> Optional[ERC20TransferIn]:
        try:
            data = json.loads(msg)
            params = data.get("params", {})
            result = params.get("result")
            if not result:
                return None

            topics = result.get("topics", [])
            if len(topics) < 3:
                return None

            token_contract = norm_addr(result["address"])
            from_addr = "0x" + topics[1][-40:]
            to_addr = "0x" + topics[2][-40:]
            from_addr = norm_addr(from_addr)
            to_addr = norm_addr(to_addr)

            if to_addr != self.watch_address:
                return None

            amount_raw = int(result.get("data", "0x0"), 16)
            tx_hash = result.get("transactionHash")
            block_number = int(result.get("blockNumber", "0x0"), 16)

            return ERC20TransferIn(
                token_contract=token_contract,
                from_addr=from_addr,
                to_addr=to_addr,
                amount_raw=amount_raw,
                tx_hash=tx_hash,
                block_number=block_number,
            )
        except Exception:
            return None


# Backward-compatible alias (old name referenced in README / older code)
BscAlchemyWsListener = BscWsListener
