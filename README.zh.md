# ticker-digest

[English](README.md)

这是一个给**美股和加密投资者**用的事件驱动提醒引擎。

**适用场景。** 有一类投资者不是天天盯盘，而是等事件发生了再动：财报出来、单日大涨大跌、持仓浮亏穿过止损线、某个自己关注的博主发了观点。他们要的不是每天一份行情汇总，而是「有事才响、没事安静」。这个仓库就是做这件事：把自选股、持仓、关注的观点账号统一成一套信号，事件触发时才推送一条带来源的简短日报，其它标的只给一句「N 个标的无事」。

**给谁用。** 自己维护自选和持仓的个人投资者；要在产品里做提醒推送、想先把「推什么、不推什么、为什么不推」这套规则跑通的产品和内容同学；想接自己数据源的开发者。

**它给你什么。** 有事的那天，每种切片一份简短的 Markdown 日报：一句总览，然后每个有事的标的一行——判断、为什么、盯什么、来源和数据日期。没事的那天一个文件都不写，只在审计文件里留一条「为什么没推」。只依赖 PyYAML 和 requests，自带的离线样例几秒跑完，数据全部合成。

**范围和边界。** 实时触发只覆盖美股和加密；港股、日韩等市场只走财报和催化剂日历。不是行情看板，不接券商下单，不给买卖建议。默认演示完全离线，价格、日历、持仓、观点账号都是合成数据。

## 效果预览

在合成样例上跑两天：一个安静的日子，一个有事的日子。安静那天命令只打印一行，不写文件。有事那天写出一份 Markdown 日报：一句总览（net read），有事的标的每个一行（判断、为什么、盯什么、来源和数据日期），其余折成一句「+5 more quiet」。

![日报：安静日只有一行，有事日写出一份带来源的日报](docs/preview/digest.png)

想知道某条为什么推了或没推，`explain` 把每个标的的每条规则都列出来：有没有触发、策略拿它怎么办，是保留、被上限截掉、被去重压掉，还是没过阈值。

![explain：每个候选的阈值检查和策略决定](docs/preview/explain.png)

同一批候选还可以按账号切（`--slice person`，按 `## @handle` 分组）或按持仓簿切（`--slice book`，按 `## core` / `## crypto` 分组）；下面的「快速开始」把三种都跑一遍。

## 和普通行情日报不一样的五点

券商和行情 App 的「日报」是聚合：每天一份、每个标的一段、有没有事都发。结果是两种失败：滞后（等你看到，量化早就拉过一波）和过密（用户直接静音）。这个引擎在五个地方反着做：

1. **无事不推，有注意力预算。** 只有过了阈值、通过频控和去重、通过输出契约的内容才会出现；每个标的每天最多 2 条，每份最多 3 个标的，其余归入一句「+N more quiet」。没推的那天，审计文件里写清「为什么没推」。
2. **一套信号，多种切片。** 同一批候选按标的切成自选日报、按持仓簿切成持仓日报、按账号切成观点日报，不为每种日报各写一套抓取。
3. **只在恶化时重推。** 同一件事 7 天内不重复；强度比上次高出一档且过了最小间隔才再推。变好永远不是重推的理由。
4. **有仓位就按仓位排。** 风险线（浮盈亏穿越、集中度）优先于纯价格，其后按「权重 × 波动」排；没仓位才按事件优先级。
5. **发送前硬闸，大模型只润色。** 每行必须带来源、数据日期、链接；禁止买卖措辞和技术指标黑话；LLM 改写后用同一套契约复检，不过就回退模板。

## 快速开始

需要 Python 3.9+，依赖 `PyYAML` 和 `requests`（`anthropic` 可选）。全部命令离线运行，数据来自 `data/` 下的合成样例。

```bash
pip install -e .                                   # 或 pip install pyyaml requests
python -m unittest discover -s tests               # 测试

# 一个安静的两天：第一天推一条风险线，第二天没有新东西 -> 不写文件
python -m digest run --date 2026-09-02
python -m digest run --date 2026-09-03            # "No new events for 2026-09-03 (ticker slice); no digest written."

# 一个有事的日子，同一批候选切成三份日报
python -m digest run --date 2026-09-12                    # 自选日报（按标的）
python -m digest run --date 2026-09-12 --slice person     # 观点日报（按人/账号）
python -m digest run --date 2026-09-12 --slice book       # 持仓日报（按持仓簿）

python -m digest run --date 2026-09-12                    # 同日再跑：已推的被去重，被上限挤掉的补发（含 [calendar-only] 标的）
python -m digest explain --date 2026-09-12                # 列出每个候选：阈值检查 + 策略决定，不碰状态
python -m digest reset-state
```

第二天的输出只有一行 stdout，没有文件。有事那天写出的就是上面预览里的那份日报；想要精确格式的可以展开看原文。

<details>
<summary>2026-09-12 自选日报的 Markdown 原文（模板模式）</summary>

```
# Watchlist digest - 2026-09-12

Net read: 3 of 8 tickers have something real for 2026-09-12; NVDA leads (risk line: unrealized P&L crossed +20%); 5 quiet.

- **NVDA** · risk line: unrealized P&L crossed +20% · Unrealized P&L crossed +20%: now +20.5% vs avg cost 100.00; New 52-week high: close 120.48 vs prior high 119.00 · watch: position size against the plan it was opened with · (source: fixture, 2026-09-11, link n/a)
- **AAPL** · material move: size, volume and a reason all line up · Closed +6.2% at 232.15 (previous close 218.60) on 3.2x typical volume; reason: @ledger_owl note (2026-09-11); ... · watch: whether volume stays elevated next session and whether the reason is confirmed · (source: fixture, 2026-09-11, link n/a)
- **MSFT** · earnings in 5 days · Earnings scheduled for 2026-09-17 (5 days away); @ledger_owl: Earnings preview ... · watch: the reported numbers and any change in guidance on the day · (source: fixture, 2026-09-12, link n/a) (source: fixture, 2026-09-11, link n/a)

+5 more quiet: TSLA, AMD, BTC-USD, 0700.HK, 7203.T

positions last updated 23 days ago — reconnect or re-enter

---
Not investment advice. Automated summary of market data; verify before acting.
```

</details>

观点日报按账号分组（`## @ledger_owl` 下面是它提到的标的），持仓日报按持仓簿分组（`## core`、`## crypto`），三者来自同一批候选。`run` 写 `out/digest-<date>[-<slice>].md`（同日重复运行加 `-2`、`-3` 后缀）并记录状态；`--date` 是运行日期，每个标的取该日期及之前最近一根日线，所以周六运行摘要的是周五收盘，引用的也是周五的日期。`--now YYYY-MM-DDTHH:MM` 可以固定时钟（去重间隔按它算），演示和测试用。

在线模式 `--source stooq` 从 stooq.com 拉免费日线（无需 key）；stooq 没有财报接口，日历仍读 `data/earnings_calendar.csv`（引用为 `local-calendar`），观点读 `data/voices.csv`（引用为 `local-notes`）。任何网络或载荷问题都降级为「该标的无数据」并打警告（`-v` 可见），不抛异常；stooq 偶尔对脚本返回浏览器验证页，适配器识别并如实报告，不做绕过。

设置 `ANTHROPIC_API_KEY` 并安装 `anthropic`（`pip install -e ".[llm]"`）后自动启用 LLM 润色（模型 `claude-sonnet-5`），`--no-llm` 强制模板模式。改写结果用同一套契约复检，API 出错或违约都回退模板。

## 它怎么工作

```
data/ 日线 · 财报日历 · 观点 note · 持仓          watchlist.yaml 自选 · 持仓簿 · 阈值 · 策略
            │                                            │
            ▼                                            ▼
1 信号   digest/signals.py     每个标的跑每条规则，触没触发都产出候选（带 why、指纹、强度）
2 切片   digest/slices.py      按标的 / 账号 / 持仓簿分组，决定「安静」的全集
3 排序   digest/policy.py      风险线 → 权重×波动 → 事件优先级；频控、去重、升级判断
4 渲染   digest/render.py      一句 net read + 每标的一行；digest/contract.py 硬闸复检
5 投递   run / propose+publish  写 out/digest-<date>[-slice].md；人审路径先出提案再勾选
6 审计   digest/audit.py       state/audit/<date>.json：每个候选的决定、去重命中、why_no_push
```

`run` 走完 1 到 6；`explain` 只走 1 到 3 并打印每个候选的阈值检查和策略决定，不碰状态。

## 设计取舍

这个仓库是我把在前一家公司做「自选和持仓日报」时想清楚的东西，从零重写成通用版。下面是几条关键取舍和它们的来历。

**为什么是「一套信号，多种切片」。** 信号层只产出候选，每条带阈值检查和指纹；同一批候选可以按标的、按持仓、按人切成三种日报。这是我最想保留的抽象：日报的种类会变，信号的定义不会，所以抓取和规则只写一遍。

**排序为什么这样。** 有仓位就按权重乘波动排，风险线优先于纯价格；没仓位就按事件优先级。新鲜度靠指纹去重，同一件事 7 天内不重复，只在恶化时重推。这条规则来自原型某一天的投递日志：当时每 15 分钟跑一次、完全没有去重，同一小时内出现了几乎一样的提醒，那天一共 16 次推送对 3 次静默。「同主题只在恶化时重推，且不早于最小间隔」就是这一天换来的。

**渲染为什么这样。** 先一句 net read，再每个标的一行：判断、为什么、盯什么、来源。不写买卖、目标价、技术指标黑话；每条必须带来源和数据日期；LLM 只做润色，改写后用同一套契约复检，不过就回退模板。这几条都是踩过坑换来的：原型上线时输出不稳定、满屏工具旁白、按维度拆段导致同一标的重复出现，最后靠「发送前硬闸」而不是靠提示词解决。

**为什么不做全市场实时。** 实时触发只做美股和加密，其他市场只走财报和催化剂日历，原因不是技术，是实时行情数据源太贵。哪天接上了某市场的行情源，把它改成 `realtime` 即可，规则一行不用动。

**持仓时效。** 三种持仓接入（手填、截图、连券商）里前两种是静态快照，要在合适节点提醒用户「这条用的是 14 天前的仓位」。

**日报是基本盘，单推才是卖点。** 在一个相关产品三个月的投放数据里，digest 类聚合页在所有承接方式中转化垫底；这说明用户真正愿意为之打开通知的是「有事时的那一条」，而不是每天的汇总。这也是整个仓库以「无事不推」为第一原则的原因。

## 信号与阈值

信号层对每个标的跑每条规则，**无论触没触发都产出候选**（带一行 `why`），`explain` 和审计文件因此能展示没触发的阈值检查。每条 `Signal` 是信号矩阵里的一格：一定有 `subject`（标的），可选 `voice`（账号/人）和 `book`（持仓簿）；再加 `fingerprint`（去重身份）、`severity`（升级去重用的强度）、`judgment` / `watch`（渲染用的判断和盯什么）、`link`（引用链接，没有就是 `link n/a`）。

| 规则 | 触发条件 | 指纹 | 强度 (severity) |
|---|---|---|---|
| `daily_move` | \|涨跌\| ≥ `move_k` × 该标的近 `typical_window` 个交易日的典型（中位数）单日波动，**且**成交量 ≥ `volume_multiple` × 近 `volume_window` 日均量；历史不足 `typical_window` 时退回绝对阈值 `move_pct` | 标的 + 数据日期 | \|涨跌 %\| |
| `volume_spike` | 成交量 ≥ `volume_multiple` × 均量；同一根 K 线上 `daily_move` 已触发时并入它，不单独推 | 标的 + 数据日期 | 倍数 |
| `week52_high` / `week52_low` | 收盘突破近 `week52_window` 个交易日的区间 | 标的 | 超出区间的 % |
| `earnings_soon` / `catalyst_soon` | 日历里的财报 / 催化剂在 `earnings_days` 天内；日历行 `kind` 不是 `earnings` 的都算催化剂 | 标的 + 事件日期 | 固定为零（日历事件不会「恶化」，每个事件推一次） |
| `pnl_cross` | 浮盈亏**穿越** ±`pnl_pct`（穿越而非水平，只触发一次）；带 `book` | 标的 + 方向 | \|浮盈亏 %\| |
| `concentration` | 单一持仓占其持仓簿价值超过 `concentration_pct`；只有一个持仓的簿不评估；带 `book` | 标的 + 簿 | 占比 % |
| `voice_take` | `data/voices.csv` 里某账号关于自选标的的 note 不超过 `note_days` 天；带 `voice` 和 `link` | 标的 + 账号 + 日期 | 零 |

**价格类信号的成色。** 触发只是门槛；`daily_move` 只有在「波动、成交量、可归因的原因」三者同时成立时才标为 `material`（优先级更高，判断写 *material move*），否则是 `unattributed`（判断写 *no attributable reason found*，盯的是「有没有原因浮出来」）。原因按顺序找：`reason_days` 内的账号 note → `reason_days` 内的日历事件 → 板块代理（`sectors` 里同板块的另一标的同方向也触发了自己的阈值）。

样例数据每个标的有 300 个交易日（远超 `typical_window`），由 `scripts/make_sample_data.py` 用固定种子生成并自检：最后一根 K 线被设计成 AAPL 放量大涨且当天有虚构账号 note（→ material）、NVDA 创新高且浮盈穿越、持仓簿 `core` 集中度超限、AMD/MSFT/0700.HK 财报在即、BTC-USD 有一个催化剂。改了规则后重新生成会直接断言场景没漂移。

## 切片与排序

`--slice` 决定同一批候选怎么分组、怎么排、什么算「安静」：

| 切片 | 分组键 | 包含哪些信号 | 「+N more quiet」的全集 |
|---|---|---|---|
| `ticker`（默认，自选日报） | 标的 | 全部 | `tickers` |
| `person`（观点日报） | `voice` | 只有带 `voice` 的（账号 note） | `voices.csv` 里出现过的账号 |
| `book`（持仓日报） | `book` | 持仓信号带自己的簿；价格/日历信号加入每一个持有该标的的簿 | 所有持仓标的 |

排序分两层。**组内的行**：`book` 切片是仓位感知的，先排有风险线（`pnl_cross`、`concentration`）的标的，再按 `权重 × |波动|`（权重 = 该标的占簿价值的份额，波动 = 最近一根 K 线的涨跌），最后按事件优先级；其它切片按事件优先级（`pnl_cross` / material 波动 > 波动 > 新高新低 / 财报 / 催化剂 > 成交量 / 观点 > 集中度）。**组之间**按各自最强的一行排，再按组内总权重，同分按名字。频控也按切片计：`max_signals_per_ticker` 是「每个分组键每天」（观点日报里就是每个账号每天），`max_tickers_per_digest` 是「每份最多几个分组」（持仓日报里就是几个簿）。

三份日报是三次独立投递，`state/sent.json` 按切片分命名空间：观点日报里推过的 note，不会让自选日报把它当成「已推」。

**持仓时效。** `positions.updated_at` 是持仓快照的日期。当一份日报用到了持仓（`book` 切片，或任何切片里推出了带 `book` 的信号）且快照比 `positions_stale_days` 更旧，页脚追加一行 `positions last updated N days ago — reconnect or re-enter`。手填和截图导入的持仓都是静态快照，这行就是给它们的。

## 渲染契约（写什么、不写什么）

模板固定为：标题 → 一句 **net read**（几个标的有事、谁领头、几个安静）→ **每个标的一行**（`**标的** · 判断 · 为什么 · watch: 盯什么 · 来源`，同一标的的几条信号折进同一行，事实用分号连接，引用一个不少）→ 最多 `max_lines_per_digest` 行 → `+N more quiet: …` → 可选的持仓时效页脚 → 免责声明。`person` 和 `book` 切片在行前加 `## 分组` 标题；日历档市场的标的名字后带 `[calendar-only]`。

`digest/contract.py` 在写出前硬闸每一份输出，模板输出和 LLM 改写用**同一个校验器**：

- **写什么**：每个 bullet 以一个或多个 `(source: <名称>, YYYY-MM-DD, <URL 或 link n/a>)` 结尾——来源、数据日期、链接三者都要有；链接要么是数据里真实带着的 URL，要么就是字面量 `link n/a`，模板把信号的链接集合交给校验器，改写里出现任何不在集合内的 URL 一律判为伪造。免责声明一字不差。
- **不写什么**：买卖 / 应该 / 目标价 / 保证之类的建议措辞（`FORBIDDEN_PHRASES`），以及技术分析黑话（`TA_JARGON`：RSI、MACD、金叉死叉、布林、斐波那契、支撑压力、突破、超买超卖、头肩、均线、K 线形态、背离、趋势线……），整词匹配，所以 buyback、resell、average 这类不会误伤。
- **LLM 只做润色**：系统提示要求保留 net read、每标的一行、引用和免责声明原样，不加事实、数字、链接和观点；返回后仍要过契约，任何违约、API 错误、非正常 stop reason 都回退模板。

## 投递、去重与审批

**投递。** `run` 是自动路径：评估 → 策略 → 渲染 → 写 `out/` → 记录状态 → 写审计。没有存活的候选就只打印一行、不写文件。渲染出的 Markdown 就是投递物；接 IM / 邮件把 `out/` 的文件发出去即可，仓库不带任何真实 webhook。

**去重（升级感知）。** 每条信号的指纹定义了「同一件事」，状态里记的是指纹 → {推送时刻， 强度， 分组}。两道闸：

1. **身份去重**：同一指纹在 `dedupe_days` 内不再推——除非**恶化**：强度比上次高出至少 `escalation_pp`，且距上次至少 `min_interval_minutes`。变好永远不是重推的理由。
2. **同主题突发闸**：指纹去掉细节部分就是主题（`标的:规则`）。同一主题在 `escalation_window_hours` 内推过（哪怕细节不同，比如盘中重跑换了日期），同样只在恶化且过了最小间隔时才重推。

被 `max_tickers_per_digest` 挤掉的信号下次运行补发，被当日预算挤掉的等第二天；`explain` 的 DECISION 列和审计里的 `dedupe_hits` 会写清每一次 `dedupe: …` 和 `escalation: …` 的数字。

**审批。** 自动路径之外有一条人审路径：

```bash
python -m digest propose --date 2026-09-12              # 写 out/proposals/2026-09-12.md：所有过阈值的候选 + 策略会怎么处理它
# 编辑该文件，把要发的行从 "- [ ]" 改成 "- [x]"
python -m digest publish --date 2026-09-12 --approved            # 只渲染被勾选的项；默认 --dry：不写文件、不动状态
python -m digest publish --date 2026-09-12 --approved --send     # 真正投递
python -m digest publish --date 2026-09-12                       # 不带 --approved：按策略结果，同样默认 dry
```

提案只列过了阈值的候选（没过阈值没什么可批），但包括被上限或去重压掉的项：勾选就是人工覆盖。没有提案文件时 `publish --approved` 报错退出。

## 多市场分级

`watchlist.yaml` 的 `markets` 把市场分成 `realtime` 和 `calendar` 两档；市场由代码后缀推断（`.HK` → HK，`.T`/`.JP` → JP，`.KS`/`.KQ`/`.KR` → KR，`-USD` → CRYPTO，其它 → US），没列出的市场默认 `realtime`。`realtime` 跑全部规则；`calendar` **不拉日线**，只跑 `earnings_soon` / `catalyst_soon`，渲染时名字后带 `[calendar-only]`。

这个分档是数据源成本的取舍，不是能力限制：美股和加密有免费日线，其它交易所的日线/实时源要付费。哪天接上了某市场的行情源，把它改成 `realtime` 即可，规则一行不用动。

## 审计

每次 `run` / `propose` / `publish`（含 dry）都往 `state/audit/<date>.json` 追加一条记录（`explain` 不写）：运行时刻、命令、切片、数据源、生效的 `thresholds` / `policy` / `markets`、持仓快照日期、每个候选的决定（`fired`、`kept`、`decision`、`why`、`severity`、`grade`、指纹、引用来源与日期）、按类别的计数、`dedupe_hits`、投递的指纹、输出路径，以及 **`why_no_push`**——没投递时的一句话解释：没有候选过阈值 / 过阈值的都被压掉了（按 dedupe、cap 分类计数）/ dry run / 提案里没勾选。想知道「今天为什么没推」，看这个文件而不是翻日志。

## 配置项

```yaml
tickers: [AAPL, NVDA, TSLA, MSFT, AMD, BTC-USD, 0700.HK, 7203.T]

markets: {US: realtime, CRYPTO: realtime, HK: calendar, JP: calendar, KR: calendar}

positions:                    # 可选；示例为合成持仓
  updated_at: 2026-08-20      # 快照日期，可选；超过 policy.positions_stale_days 触发页脚提醒
  NVDA: {qty: 40, avg_cost: 100.0, book: core}   # book 可选，默认 "default"
  TSLA: {qty: 10, avg_cost: 300.0, book: core}
  BTC-USD: {qty: 0.05, avg_cost: 50000.0, book: crypto}

sectors:                      # 可选；板块代理归因用
  semis: [NVDA, AMD]
  megacap: [AAPL, MSFT]

thresholds:                   # 全部可选；下面是默认值
  move_k: 2.0                 # 波动触发倍数（× 典型单日波动）
  typical_window: 30          # 典型波动的交易日数
  move_pct: 5.0               # 历史不足时的绝对阈值
  volume_multiple: 2.0        # 成交量倍数（波动触发也要求它）
  volume_window: 20
  week52_window: 252
  earnings_days: 7            # 财报 / 催化剂提前天数
  pnl_pct: 20.0
  concentration_pct: 40.0
  note_days: 2                # 账号 note 的有效天数
  reason_days: 2              # note / 日历事件算作「原因」的天数

policy:                       # 全部可选；下面是默认值
  max_signals_per_ticker: 2   # 每个分组键每天
  max_tickers_per_digest: 3   # 每份最多几个分组
  max_lines_per_digest: 8     # 渲染行数上限
  dedupe_days: 7
  escalation_pp: 1.5          # 重推所需的最小恶化幅度
  min_interval_minutes: 55    # 重推所需的最小间隔
  escalation_window_hours: 1  # 同主题突发闸窗口
  positions_stale_days: 14
```

未知键（包括顶层）会抛 `ConfigError`，拼错不会静默关闭某条规则。`data/earnings_calendar.csv` 是 `ticker,date[,kind,note]`，`data/voices.csv` 是 `date,voice,ticker,headline,link`（`link` 留空或写 `link n/a` 都表示没有链接）。CLI 全局参数：`--config`、`--state`（默认 `state/sent.json`）、`--audit`（默认 `state/audit`）、`-v`；子命令参数：`--date`、`--now`、`--slice`、`--source`、`--data`、`--out`；`run` / `publish` 另有 `--no-llm`，`publish` 另有 `--approved`、`--dry`（默认）/ `--send`。

## 扩展

- **加数据源**：继承 `digest.sources.base.DataSource`，实现 `daily_bars(ticker, end)`（最旧在前、不晚于 `end`）和 `earnings_calendar()`，可选实现 `notes()`；失败返回空列表而不是抛异常；在 `digest/cli.py` 的 `build_source()` 注册。
- **加规则**：在 `digest/signals.py` 写一个对触发和未触发都返回 `Signal` 的函数，选好 `priority`、定义 `fingerprint` 的身份含义、给 `severity` 一个「越大越糟」的量，从 `evaluate()` 调用；`headline` 里不要带引用（渲染器会加），也不要出现契约禁止的词，否则渲染会拒绝。
- **改样例场景**：改了规则后运行 `scripts/make_sample_data.py`，它会重新生成数据并断言演示场景没有漂移。

## 边界

- **市场。** 实时触发只覆盖美股和加密。其它市场在接上行情源之前只走财报和催化剂日历；接上之后规则本身不用改。
- **交易。** 不连券商、不下单、不做持仓核算。持仓是引擎读取的输入，引擎从不回写。
- **建议。** 不给买卖结论、不给目标价、不解读技术指标。这类措辞在写出来之前就被输出契约拦掉，模板和 LLM 改写走的是同一套检查。
- **回测。** 它只判断今天什么值得说，不回答「按过去某条提醒操作能不能赚钱」。
- **投递。** 交付物是 `out/` 下的一个 Markdown 文件。发到聊天工具、邮箱还是机器人由你接；仓库不带 webhook，也不存任何凭据。
- **界面。** 输出是 Markdown、JSON 状态和审计文件，没有网页，也没有通知中心。
- **写分析。** LLM 只润色措辞，不新增事实、数字和链接；改写一旦新增就作废，回退模板。

## 目录

```
digest/            config, markets, signals, slices, policy, contract, render, llm, proposals, audit, cli
digest/sources/    base（接口 + CSV 解析）, fixture（离线）, stooq（在线）
data/              合成样例：sample/*.csv 日线、earnings_calendar.csv、voices.csv（虚构账号）
scripts/           确定性的样例数据生成器（自带场景断言）
tests/             unittest 套件
out/               运行产物：digest-*.md、proposals/<date>.md（已 gitignore）
state/             sent.json（按切片分命名空间）、audit/<date>.json（已 gitignore）
```

## License

MIT — see `LICENSE`.
