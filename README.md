# BSC -> Binance Futures Short Bot (alpha)

监听 BSC 指定地址的 ERC20 `Transfer` 转入事件（基于 Alchemy BSC WebSocket），
当转入价值超过阈值时，在 Binance USDT-M 合约市场开空（MARKET SELL）。

## 目录
- main.py: 入口
- app/bsc_ws_listener.py: WS 订阅 logs，提取 Transfer(to=watch_address)
- app/erc20_metadata.py: 通过 JSON-RPC eth_call 获取 symbol/decimals（缓存+并发去重）
- app/token_registry.py: 币安 token list 接口（限速<=2次/分钟 + 缓存）
- app/binance_futures.py: python-binance 下单/查询（exchangeInfo 缓存）
- app/strategy.py: 核心策略

## Start
- 你必须拥有alchemy的账号。并获取APIKEY并开通BSC主链操作权限。（https://www.alchemy.com/）
- 你必须会注册并使用Binance API。
- 你必须有简单的项目部署经验。
- 你必须拥有一台稳定的可访问境外网站的服务器/本地主机。注意，必须要稳定的网络。
- 一切配置均在config.yaml文件中。

## 安装
```bash
pip install -r requirements.txt
```

# 编辑 config.yaml
```

## 运行
```bash
python main.py
```

## 注意
- 仅监听 ERC20 Transfer（不含原生 BNB 转账）
- 默认下单带 positionSide="SHORT"（Hedge Mode）。若你账户是 One-way Mode，需要在 `app/binance_futures.py` 中删除该字段。
- 建议先用 testnet 或小号测试。

## 安全提醒
- 使用本开源代码即代表您了解并熟悉有关脚本的部署/调试。
- 使用本开源代码即代表您自行承担一切风险与损失。

- 盈亏同源，祝各位好运。

## alpha闲聊群 https://t.me/bn_alpha_chat
## alpha监控群 https://t.me/bn_alpha_monitor

## 感谢老板赞助！收款地址bsc：0x69a6ad2f4ab24b8b3fe3ac1bd3e4c0ba947e4949
