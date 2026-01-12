from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict
import yaml


@dataclass(frozen=True)
class Settings:
    # RPC provider endpoints (single provider only)
    rpc_provider: str
    rpc_ws_url: str
    rpc_http_url: str

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

    # Backward compatibility:
    # - legacy config uses `alchemy.ws_url` and `alchemy.watch_address`
    # - new config uses `rpc.{provider, api_key, ws_url, http_url, watch_address}`
    if "rpc" in raw and "alchemy" in raw:
        raise ValueError(
            "Config error: please keep ONLY ONE of `rpc` (new) or `alchemy` (legacy) section."
        )

    rpc_raw = raw.get("rpc") or {}
    legacy_raw = raw.get("alchemy") or {}

    provider = str(rpc_raw.get("provider") or "alchemy").strip().lower() if "rpc" in raw else "alchemy"

    # Enforce: single endpoint only
    # - provider=alchemy/infura => must provide `api_key` (or legacy full ws_url for alchemy) and URLs are auto-built
    # - provider=custom         => must provide both ws_url + http_url
    if provider not in {"alchemy", "infura", "custom"}:
        raise ValueError("rpc.provider must be one of: alchemy / infura / custom")

    if provider == "alchemy":
        # legacy config may provide full ws url already
        api_key = str(rpc_raw.get("api_key") or "").strip()
        ws_url = str(rpc_raw.get("ws_url") or legacy_raw.get("ws_url") or "").strip()
        http_url = str(rpc_raw.get("http_url") or "").strip()

        if not ws_url and not api_key:
            raise ValueError("Alchemy config missing: set rpc.api_key OR alchemy.ws_url")

        if http_url:
            # Avoid mixed endpoints: alchemy provider uses derived http+ws pair only.
            raise ValueError(
                "provider=alchemy does not allow rpc.http_url override. "
                "Remove rpc.http_url (or use provider=custom)."
            )

        if not ws_url:
            ws_url = f"wss://bnb-mainnet.g.alchemy.com/v2/{api_key}"

        # Basic sanity check to prevent accidental mixed endpoints.
        if "infura.io" in ws_url:
            raise ValueError("provider=alchemy but ws_url looks like Infura. Please fix config.")

        # Alchemy BNB endpoints share the same path prefix; use the same key.
        key = ws_url.rsplit("/", 1)[-1]
        http_url = f"https://bnb-mainnet.g.alchemy.com/v2/{key}"

    elif provider == "infura":
        api_key = str(rpc_raw.get("api_key") or "").strip()
        ws_url = str(rpc_raw.get("ws_url") or "").strip()
        http_url = str(rpc_raw.get("http_url") or "").strip()

        if ws_url or http_url:
            raise ValueError(
                "provider=infura does not allow rpc.ws_url/http_url override. "
                "Remove them (or use provider=custom)."
            )
        if not api_key:
            raise ValueError("Infura config missing: set rpc.api_key")

        # Infura endpoints are fixed; only api_key varies.

        ws_url = f"wss://bsc-mainnet.infura.io/ws/v3/{api_key}"
        http_url = f"https://bsc-mainnet.infura.io/v3/{api_key}"

    else:  # custom
        ws_url = str(rpc_raw.get("ws_url") or "").strip()
        http_url = str(rpc_raw.get("http_url") or "").strip()
        if not ws_url or not http_url:
            raise ValueError("provider=custom requires BOTH rpc.ws_url and rpc.http_url")

    watch_address = str(
        (rpc_raw.get("watch_address") if "rpc" in raw else legacy_raw.get("watch_address"))
    ).strip()
    if not watch_address:
        raise ValueError("watch_address is required")

    return Settings(
        rpc_provider=provider,
        rpc_ws_url=ws_url,
        rpc_http_url=http_url,
        watch_address=watch_address,

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
