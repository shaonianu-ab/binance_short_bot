from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, Optional, Tuple

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from decimal import Decimal, ROUND_DOWN, getcontext


log = logging.getLogger("binance_futures")
getcontext().prec = 28


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

    def _futures_algo_order(self, **params):
        """
        Binance USD-M Futures: New Algo Order endpoint
        POST /fapi/v1/algoOrder (signed)

        python-binance 目前多数版本还没封装该接口，所以用底层 _request_futures_api 直调。
        """
        return self.client._request_futures_api("post", "algoOrder", True, data=params)


    def _get_tick_size(self, symbol: str) -> Optional[float]:
        """
        读取 PRICE_FILTER tickSize，用于触发价舍入。
        """
        self._refresh_exchange_info_if_needed()
        assert self._exchange_info is not None
        for s in self._exchange_info.get("symbols", []):
            if s.get("symbol") != symbol:
                continue
            for f in s.get("filters", []):
                if f.get("filterType") == "PRICE_FILTER":
                    try:
                        return float(f.get("tickSize"))
                    except Exception:
                        return None
        return None

    @staticmethod
    def _round_to_tick_str(price: float, tick: float) -> str:
        """
        按 tickSize 向下截断，并输出符合精度的十进制字符串，避免 float 尾差导致 -1111。
        """
        if not tick or tick <= 0:
            # 兜底：转成普通字符串
            return format(Decimal(str(price)), "f")

        p = Decimal(str(price))
        t = Decimal(str(tick))

        # 向下取整到 tick 的整数倍
        multiple = (p / t).to_integral_value(rounding=ROUND_DOWN)
        rounded = multiple * t

        # 按 tick 的小数位 quantize（例如 tick=0.001 => 保留 3 位）
        rounded = rounded.quantize(t, rounding=ROUND_DOWN)

        # 转成非科学计数法字符串
        return format(rounded, "f")


    def place_tp_sl_for_short(
        self,
        symbol: str,
        entry_price: float,
        take_profit_pct: float,
        stop_loss_pct: float,
    ) -> Dict[str, Any]:
        """
        做空后的止盈/止损（可选）：
        - take_profit_pct = 0 => 不挂止盈
        - stop_loss_pct  = 0 => 不挂止损

        采用：
        - TAKE_PROFIT_MARKET + closePosition=True （买入平空）
        - STOP_MARKET        + closePosition=True （买入止损）
        """
        results: Dict[str, Any] = {"tp": None, "sl": None}

        try:
            if entry_price <= 0:
                return results

            tp = float(take_profit_pct or 0.0)
            sl = float(stop_loss_pct or 0.0)
            if tp <= 0 and sl <= 0:
                return results

            tick = self._get_tick_size(symbol)

            # 做空：
            # TP 触发价：entry * (1 - tp)
            # SL 触发价：entry * (1 + sl)
            tp_price = entry_price * (1.0 - tp) if tp > 0 else None
            sl_price = entry_price * (1.0 + sl) if sl > 0 else None

            tp_trigger = self._round_to_tick_str(tp_price, tick) if (tp_price and tick) else (str(tp_price) if tp_price else None)
            sl_trigger = self._round_to_tick_str(sl_price, tick) if (sl_price and tick) else (str(sl_price) if sl_price else None)

            # 注意：合约触发单通常要设置 workingType（MARK_PRICE/CONTRACT_PRICE）
            # 这里用 MARK_PRICE 更稳
            if tp_price and tp_price > 0:
                results["tp"] = self._futures_algo_order(
                    algoType="CONDITIONAL",
                    symbol=symbol,
                    side="BUY",
                    type="TAKE_PROFIT_MARKET",
                    triggerPrice=tp_trigger,
                    closePosition="true",
                    workingType="MARK_PRICE",
                    positionSide="SHORT",   # One-way 模式删掉这一行
                    recvWindow=self.recv_window,
                )

            if sl_price and sl_price > 0:
                results["sl"] = self._futures_algo_order(
                    algoType="CONDITIONAL",
                    symbol=symbol,
                    side="BUY",
                    type="STOP_MARKET",
                    triggerPrice=sl_trigger,
                    closePosition="true",
                    workingType="MARK_PRICE",
                    positionSide="SHORT",   # One-way 模式删掉这一行
                    recvWindow=self.recv_window,
                )

            return results

        except (BinanceRequestException, BinanceAPIException) as e:
            log.error("place_tp_sl_for_short failed: %s", e, exc_info=True)
            return results
        except Exception as e:
            log.error("place_tp_sl_for_short error: %s", e, exc_info=True)
            return results
