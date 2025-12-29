import asyncio
import logging

from app.config import load_settings
from app.logger import setup_logging
from app.token_registry import BinanceTokenRegistry
from app.binance_futures import BinanceFuturesTrader
from app.bsc_ws_listener import BscAlchemyWsListener
from app.strategy import Strategy
from app.erc20_metadata import ERC20MetadataClient


def ws_to_http(ws_url: str) -> str:
    if ws_url.startswith("wss://"):
        return "https://" + ws_url[len("wss://"):]
    if ws_url.startswith("ws://"):
        return "http://" + ws_url[len("ws://"):]
    return ws_url


async def main() -> None:
    st = load_settings("config.yaml")
    setup_logging(st.log_level)
    log = logging.getLogger("main")

    registry = BinanceTokenRegistry(
        url=st.token_list_url,
        max_rpm=st.token_list_max_rpm,
        cache_ttl=st.token_list_cache_ttl,
    )

    trader = BinanceFuturesTrader(
        api_key=st.binance_api_key,
        api_secret=st.binance_api_secret,
        testnet=st.binance_testnet,
        recv_window=st.binance_recv_window,
    )

    listener = BscAlchemyWsListener(st.alchemy_ws_url, st.watch_address)

    rpc_http_url = ws_to_http(st.alchemy_ws_url)
    meta_client = ERC20MetadataClient(rpc_http_url=rpc_http_url, cache_ttl_sec=24 * 3600)

    strat = Strategy(
        token_registry=registry,
        trader=trader,
        meta_client=meta_client,
        trigger_value_usdt=st.trigger_value_usdt,
        short_notional_usdt=st.short_notional_usdt,
        leverage=st.leverage,
        margin_type=st.margin_type,
        trade_when_token_not_in_list=st.trade_when_token_not_in_list,
        take_profit_pct=st.take_profit_pct,
        stop_loss_pct=st.stop_loss_pct,
    )

    log.info("started. watching=%s", st.watch_address)

    async for evt in listener.listen():
        asyncio.create_task(strat.on_transfer_in(evt))


if __name__ == "__main__":
    asyncio.run(main())
