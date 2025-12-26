from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, Optional, Tuple

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

log = logging.getLogger("binance_futures")


class BinanceFuturesTrader:
    def __init__(self, api_key: str, api_secret: str, testnet: bool, recv_window: int) -> None:
        self.client = Client(api_key, api_secret, testnet=testnet)
        self.client.FUTURES_URL = self.client.FUTURES_TESTNET_URL if testnet else self.client.FUTURES_URL
        self.recv_window = recv_window

        self._exchange_info: Optional[Dict[str, Any]] = None
        self._exchange_info_ts = 0.0
        self._exchange_info_ttl = 600.0

    def _refresh_exchange_info_if_needed(self) -> None:
        now = time.monotonic()
        if self._exchange_info and (now - self._exchange_info_ts) < self._exchange_info_ttl:
            return
        self._exchange_info = self.client.futures_exchange_info()
        self._exchange_info_ts = time.monotonic()

    def futures_symbol_exists(self, symbol: str) -> bool:
        try:
            self._refresh_exchange_info_if_needed()
            assert self._exchange_info is not None
            for s in self._exchange_info.get("symbols", []):
                if s.get("symbol") == symbol and s.get("status") == "TRADING":
                    return True
            return False
        except Exception as e:
            log.warning("futures_symbol_exists error: %s", e, exc_info=True)
            return False

    def _get_filters(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        self._refresh_exchange_info_if_needed()
        assert self._exchange_info is not None
        for s in self._exchange_info.get("symbols", []):
            if s.get("symbol") != symbol:
                continue
            step = None
            min_qty = None
            for f in s.get("filters", []):
                if f.get("filterType") == "LOT_SIZE":
                    try:
                        step = float(f.get("stepSize"))
                        min_qty = float(f.get("minQty"))
                    except Exception:
                        pass
            return step, min_qty
        return None, None

    def get_mark_price(self, symbol: str) -> Optional[float]:
        try:
            mp = self.client.futures_mark_price(symbol=symbol)
            return float(mp["markPrice"])
        except Exception as e:
            log.warning("get_mark_price error: %s", e, exc_info=True)
            return None

    @staticmethod
    def _round_step(qty: float, step: float) -> float:
        if step <= 0:
            return qty
        return math.floor(qty / step) * step

    def open_short_market(self, symbol: str, notional_usdt: float, leverage: int, margin_type: str) -> Optional[Dict[str, Any]]:
        try:
            price = self.get_mark_price(symbol)
            if not price or price <= 0:
                log.warning("mark price unavailable, skip trade: %s", symbol)
                return None

            step, min_qty = self._get_filters(symbol)
            qty = notional_usdt / price

            if step:
                qty = self._round_step(qty, step)

            if min_qty and qty < min_qty:
                log.warning("qty < minQty, skip. symbol=%s qty=%s min=%s", symbol, qty, min_qty)
                return None

            try:
                self.client.futures_change_margin_type(symbol=symbol, marginType=margin_type, recvWindow=self.recv_window)
            except BinanceAPIException as e:
                log.info("change_margin_type: %s", getattr(e, "message", str(e)))
            except Exception as e:
                log.info("change_margin_type err: %s", e)

            try:
                self.client.futures_change_leverage(symbol=symbol, leverage=leverage, recvWindow=self.recv_window)
            except Exception as e:
                log.info("change_leverage err: %s", e)

            order = self.client.futures_create_order(
                symbol=symbol,
                side="SELL",
                type="MARKET",
                quantity=qty,
                positionSide="SHORT",
                recvWindow=self.recv_window,
            )
            return order

        except (BinanceRequestException, BinanceAPIException) as e:
            log.error("binance order failed: %s", e, exc_info=True)
            return None
        except Exception as e:
            log.error("open_short_market error: %s", e, exc_info=True)
            return None
