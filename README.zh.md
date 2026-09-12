# ticker-digest

事件驱动的**自选股每日摘要**代理。给它一份自选列表（可选持仓），它会检测值得通知的事件、执行频控与去重、校验带引用的输出契约，并渲染 Markdown 摘要（可选 LLM 润色）。默认演示完全离线，使用内置的合成数据。

> 非投资建议。样例数据为合成数据，工具只报告规则触发的价格、成交量与日历事实。

## 设计要点

- **无事件，不推送**：只有规则触发且通过策略层，才会写出摘要；安静的一天只输出一行提示。
- **频控**：每个 ticker 每天最多 `max_signals_per_ticker` 条（当日多次运行累计），每份摘要最多 `max_tickers_per_digest` 个 ticker；超限时按规则优先级取舍，被 ticker 上限挤掉的信号会在下次运行补发。
- **去重**：每条信号有一个 *fingerprint* 定义“同一条信号”的含义（日涨跌按数据日期，52 周新高按 ticker，财报按事件日期），已推送的指纹存于 `state/sent.json`，`dedupe_days` 内不再重复。
- **输出契约**：每条 bullet 必须以 `(source: <名称>, YYYY-MM-DD)` 结尾；禁止目标价、买/卖/应该、保证等措辞；必须带免责声明。LLM 改写用同一个校验器复检，不合规即回退模板。
- **持仓感知**：浮盈亏穿越 `±pnl_pct`（穿越而非水平，只触发一次）、单一持仓占比超过 `concentration_pct`。
- **可插拔数据源**：实现“某 ticker 的日线”和“事件日历”两个方法即可。

## 快速开始

```bash
pip install -e .
python -m digest run --date 2026-09-12 --source fixture   # 写出 out/digest-2026-09-12.md
python -m digest run --date 2026-09-12 --source fixture   # 第二次运行触发去重
python -m digest explain --date 2026-09-12 --source fixture   # 列出每个候选及保留/丢弃原因
python -m digest reset-state
python -m unittest discover -s tests
```

在线模式 `--source stooq` 从 stooq.com 拉取免费日线（无需 key），网络失败时优雅降级。设置 `ANTHROPIC_API_KEY` 并安装 `anthropic` 后自动启用 LLM 润色（模型 `claude-sonnet-5`），`--no-llm` 可强制模板模式。

配置项、扩展数据源与规则的方法见英文 `README.md`。
