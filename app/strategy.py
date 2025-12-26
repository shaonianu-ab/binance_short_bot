from __future__ import annotations

import asyncio
import logging

from .token_registry import BinanceTokenRegistry
from .binance_futures import BinanceFuturesTrader
from .bsc_ws_listener import ERC20TransferIn
from .erc20_metadata import ERC20MetadataClient

log = logging.getLogger("strategy")


class Strategy:
    def __init__(
        self,
        token_registry: BinanceTokenRegistry,
        trader: BinanceFuturesTrader,
        meta_client: ERC20MetadataClient,
        *,
        trigger_value_usdt: float,
        short_notional_usdt: float,
        leverage: int,
        margin_type: str,
        trade_when_token_not_in_list: bool,
    ) -> None:
        self.registry = token_registry
        self.trader = trader
        self.meta = meta_client

        self.trigger_value_usdt = trigger_value_usdt
        self.short_notional_usdt = short_notional_usdt
        self.leverage = leverage
        self.margin_type = margin_type
        self.trade_when_token_not_in_list = trade_when_token_not_in_list

        self._seen_txs = set()
        self._seen_lock = asyncio.Lock()

    async def _dedup_tx(self, tx_hash: str) -> bool:
        async with self._seen_lock:
            if tx_hash in self._seen_txs:
                return False
            self._seen_txs.add(tx_hash)
            if len(self._seen_txs) > 50000:
                self._seen_txs.clear()
            return True

    async def on_transfer_in(self, evt: ERC20TransferIn) -> None:
        try:
            if evt.tx_hash and not await self._dedup_tx(evt.tx_hash):
                return

            sd = await self.meta.get_symbol_decimals(evt.token_contract, timeout_sec=1.0)
            if not sd:
                log.info("metadata unavailable, skip safely. token=%s tx=%s", evt.token_contract, evt.tx_hash)
                return

            symbol, decimals = sd
            if decimals < 0 or decimals > 36:
                log.info("weird decimals=%s, skip. symbol=%s token=%s", decimals, symbol, evt.token_contract)
                return

            amount = evt.amount_raw / (10 ** decimals)

            info = await self.registry.get_token_info(symbol)
            in_list = info is not None
            price = self.registry.extract_price_usdt(info) if info else None

            futures_symbol = f"{symbol}USDT"
            if price is None:
                if self.trader.futures_symbol_exists(futures_symbol):
                    price = self.trader.get_mark_price(futures_symbol)

            if price is None:
                log.info("price unavailable, skip. symbol=%s in_list=%s tx=%s", symbol, in_list, evt.tx_hash)
                return

            value_usdt = amount * price

            log.info(
                "IN: symbol=%s amount=%.8f price=%.6f value=%.2f token=%s tx=%s",
                symbol, amount, price, value_usdt, evt.token_contract, evt.tx_hash
            )

            if (not in_list) and (not self.trade_when_token_not_in_list):
                return

            if value_usdt < self.trigger_value_usdt:
                return

            if not self.trader.futures_symbol_exists(futures_symbol):
                log.info("triggered but no futures market: %s tx=%s", futures_symbol, evt.tx_hash)
                return

            order = self.trader.open_short_market(
                symbol=futures_symbol,
                notional_usdt=self.short_notional_usdt,
                leverage=self.leverage,
                margin_type=self.margin_type,
            )

            if order:
                log.warning("SHORT OPENED: %s orderId=%s tx=%s", futures_symbol, order.get("orderId"), evt.tx_hash)
            else:
                log.error("SHORT FAILED: %s tx=%s", futures_symbol, evt.tx_hash)

        except Exception as e:
            log.error("on_transfer_in crashed: %s", e, exc_info=True)
