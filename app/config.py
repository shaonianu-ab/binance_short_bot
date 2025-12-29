from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict
import yaml


@dataclass(frozen=True)
class Settings:
    alchemy_ws_url: str
    watch_address: str

    binance_api_key: str
    binance_api_secret: str
    binance_testnet: bool
    binance_recv_window: int

    trigger_value_usdt: float
    short_notional_usdt: float
    leverage: int
    margin_type: str
    trade_when_token_not_in_list: bool
    take_profit_pct: float
    stop_loss_pct: float


    token_list_url: str
    token_list_max_rpm: int
    token_list_cache_ttl: int

    log_level: str


def load_settings(path: str) -> Settings:
    with open(path, "r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f)

    return Settings(
        alchemy_ws_url=raw["alchemy"]["ws_url"],
        watch_address=raw["alchemy"]["watch_address"],

        binance_api_key=raw["binance"]["api_key"],
        binance_api_secret=raw["binance"]["api_secret"],
        binance_testnet=bool(raw["binance"].get("testnet", False)),
        binance_recv_window=int(raw["binance"].get("recv_window", 5000)),

        trigger_value_usdt=float(raw["risk"]["trigger_value_usdt"]),
        short_notional_usdt=float(raw["risk"]["short_notional_usdt"]),
        leverage=int(raw["risk"]["leverage"]),
        margin_type=str(raw["risk"]["margin_type"]).upper(),
        trade_when_token_not_in_list=bool(raw["risk"].get("trade_when_token_not_in_list", False)),
        take_profit_pct=float(raw["risk"].get("take_profit_pct", 0.0)),
        stop_loss_pct=float(raw["risk"].get("stop_loss_pct", 0.0)),


        token_list_url=raw["binance_token_list"]["url"],
        token_list_max_rpm=int(raw["binance_token_list"].get("max_requests_per_minute", 2)),
        token_list_cache_ttl=int(raw["binance_token_list"].get("cache_ttl_seconds", 45)),

        log_level=str(raw["runtime"].get("log_level", "INFO")),
    )
