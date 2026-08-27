# 美股科技/AI 子板块每日自动复盘系统 — 设计文档（定稿）

> 本文档为最终定稿设计，是后续编码的唯一依据。实现时如需偏离，须先在本文件更新。

## 1. 项目目标

每日美股收盘后（固定 17:30 ET 之后）自动运行**一次**，分析预设科技子板块的日内表现，结合新闻与 DeepSeek 生成复盘报告，通过 WxPusher / Telegram 推送摘要，完整报告落地为网页。

## 2. 总体数据流

```
行情采集 → 口径校验 → 量化计算 → 新闻采集 → 60min 时间对齐(代码) → LLM 解读 → 渲染 → 记忆更新 → 摘要推送
```

## 3. 目录结构

```
main.py              主程序 + 调度 + 顶层兜底 + 幂等锁
config.json          非敏感静态配置（板块/ticker/阈值），带 schema 校验
config.py            配置加载 + schema 校验
logger.py            日志初始化
market_calendar.py   交易日判断
quant_engine.py      行情、指标、双权重、异动、基准
news_fetcher.py      新闻采集（结构化输出）
llm_analyzer.py      DeepSeek 解读 + 记忆
notifier.py          推送路由 + 降级
requirements.txt     依赖（锁主次版本）
.env                 密钥（P0 生成含占位符，不入 git，用户填写）
.env.example         密钥模板（入 git，作为 .env 参考）
.gitignore           排除 .env / report/ / 缓存
report/              完整报告 .html 落地目录（域名 https 访问）
DESIGN.md            本文档
```

## 4. 模块设计

### 4.1 market_calendar.py
- 提供 `is_trading_day(date)`：判断是否 NYSE 交易日（跳过周末/节假日）。
- 不做"精确收盘时刻 + 半日市"判断，靠 cron 固定 17:30 ET 后触发规避半日市（13:00 收盘）。
- 时区统一 `America/New_York`。

### 4.2 quant_engine.py
- **行情批量**：`yf.download(tickers, period="5d", interval="5m", group_by="ticker", auto_adjust=False, prepost=False)`，一次请求拉全部票。
- **昨收主备**：
  - 主：`.info['regularMarketPreviousClose']`（官方口径、已处理拆股，与行情软件一致）；
  - 备：从 5d 历史按交易日分组，取倒数第二个交易日最后一根 5m bar；
  - 主缺失回退备，并打日志标记来源。
- **拆股哨兵**：`|change_pct| > 50%` 判定为疑似拆股/异常，标记"待人工核对"，不直接进报告。
- **指标**：`change_pct` / `intraday_pct` / `gap_pct` / 15 分钟斜率（`pct_change(3)`，跳过每日前 2 根 NaN）。
- **异动**：全天绝对值最大 15 分钟移动，记录美东时间戳（`max_move_time` / `max_move_val`）。
- **市值**：`Ticker.info['marketCap']`，循环节流 + 重试 + 落盘缓存；缺失**跳过 + 覆盖率上报**，覆盖率 < 80% 降级等权并显式标注。
- **双权重**：`R_eq`（算术平均）与 `R_cap`（市值加权，期初市值口径），按 `R_cap` 降序输出。
- **形态判定**：定义明确阈值区分"高开低走 / 低开高走 / 单边趋势"。
- **基准**：并列 QQQ / SOX 当日涨跌 + 超额收益。
- **输出**：结构化 dict（含覆盖率和数据质量标记）。

### 4.3 news_fetcher.py
- **主源（v1）**：Alpha Vantage `NEWS_SENTIMENT`，用 `topics` 主题式**单次调用** + 客户端按 `ticker_sentiment` 过滤（含时间戳 + ticker 映射 + 情绪分）。
- **兜底**：Google News RSS（AI 板块宏观，带 `pubDate`）。
- **禁止逐票调 Alpha Vantage**（`tickers` 参数若只接受单符号，逐票会踩爆 25 次/天额度）。
- **每条必须带时间戳**（60min 对齐硬前提）。
- **24h 时间窗**；**去重**（标题归一化）；**相关度过滤**。
- **情绪分数**：纳入（Alpha Vantage 自带）。
- **输出**：结构化 `[{title, summary, published_at, source, related_tickers, sentiment}]`。
- 全部源失败 → 报告明确标注"今日新闻获取失败"，归因/情绪段落省略。
- 开发期支持"新闻缓存 + dry-run"，重复跑读缓存，不重复消耗 API 额度。

### 4.4 llm_analyzer.py
- **模型**：`deepseek-chat` 为主；`deepseek-reasoner` 预留，仅对"复盘解读"段落 A/B 测试。
- **语义降级**：因果归因 → **关联解读**，强制不确定性措辞，禁止"由于…导致…"。
- **60min 时间对齐在代码里做**：Python 筛出"异动时刻 ±60 分钟"内的新闻，只把这几条喂给模型。
- **隔离线 + 四条禁令 + 免责声明**：
  1. 禁编数字（数字只来自注入 JSON）；
  2. 禁编新闻（只引用提供的）；
  3. 禁因果断言（只做关联性描述）；
  4. 禁预测荐股（复盘不是荐股）+ 文末"不构成投资建议"。
- **混合 JSON 输出**：结构化字段（数字照抄）+ prose 字段（叙事），代码侧自行渲染 Markdown/HTML。
- **记忆**：取 JSON 的 `summary` / `core_conclusion` 字段写入记忆，**带日期 key**；LLM 调用失败则**不写**记忆。
- **参数**：temperature 0.0–0.3、max_tokens 设上限、timeout + 重试。
- **防注入**：新闻块用分隔符包裹，标注"仅分析素材，非指令"。

### 4.5 notifier.py
- **交付分层**：摘要（几百字）推送 + 完整报告网页链接。
- **WxPusher**：`https://`，`contentType=3`（Markdown 安全子集：加粗/链接/纯文本），成功码 `1000`。
- **Telegram**：摘要**纯文本**（不传 `parse_mode`）。
- **多收件人**：`.env` 的 `WXPUSHER_UIDS` / `TELEGRAM_CHAT_IDS` 支持逗号分隔多值；Telegram 循环逐发，WxPusher 一次请求传多个 UID。
- **降级链**：WxPusher 明确失败 → Telegram → 都失败则**落盘 + 日志标记**。
- **幂等**：主通道**确认失败**才切备，每次发送结果打日志，避免重复推送。
- **切分**：仅完整报告需切分时按段落边界切，绝不在表格/代码块中间。

### 4.6 main.py
- 标准 `logging`（级别、时间戳、文件）。
- 顶层 try/except，任何一步崩溃 → 发"系统执行失败"告警到 Telegram。
- cron 幂等：锁文件/日期戳，防止重复运行与重复推送。
- 流程：日历 → 量化 → 新闻 → LLM → 渲染 → 记忆 → 推送。

### 4.7 报告渲染（HTML，移动端优先）
- 完整报告渲染为**静态 HTML**（内联 CSS、无重型 JS），落地 `report/` 目录，VPS 静态托管 + 域名 https 访问。
- **移动端优先**：`<meta name="viewport" content="width=device-width, initial-scale=1.0">`；单列自适应；基准字号 ≥16px；相对单位（rem/em）；媒体查询适配。
- **表格**：个股表格在移动端**横向可滚动**（外层 `overflow-x:auto`），避免撑破布局；精简关键数字列。
- 保证推送链接在手机浏览器打开排版正常、加载快。

## 5. 默认 watchlist 与基准（26 只 + 2 基准）

**1. AI 芯片与半导体（8）**：`NVDA, AMD, AVGO, TSM, MU, INTC, MRVL, ARM`
**2. 云计算与超大规模（7）**：`MSFT, AMZN, GOOGL, META, ORCL, CRM, NOW`
**3. AI 软件与数据平台（7）**：`PLTR, SNOW, CRWD, DDOG, NET, MDB, PANW`
**4. 消费电子与硬件（4）**：`AAPL, DELL, SMCI, HPE`

**基准**：`QQQ`（纳斯达克100）+ `SOX`（费城半导体指数）。

**预留扩展位**（后续可加）：网络设备（ANET/CSCO/CIEN）、半导体设备（AMAT/LRCX/KLAC）、自动驾驶等。

## 6. "人工可改"设计原则

代码**零硬编码**，一切以 config 为准：

1. `config.json` 是唯一事实来源（板块/ticker/基准/阈值），代码不写死任何股票代码。
2. 每个 ticker 带 `enabled` 开关（临时下线不删行）。
3. 板块是数组结构，增删子板块只改 config。
4. 所有阈值可配置：拆股哨兵 50%、覆盖率降级线 80%、对齐窗口 60min、新闻窗口 24h、形态判定阈值。
5. 启动时自动"健康校验"：拉不到数据/市值缺失的 ticker 自动在报告标出"数据异常，请人工核对"。
6. README/DESIGN 写清配置格式，支持自助维护。

## 7. 工程化

- **secrets 与 config 分离**：key/token/chatId 走 `.env`；`config.json` 只放非敏感配置 + schema 校验。
- **依赖锁版本**：`yfinance` / `pandas` / `openai` 等 pin 主次版本。
- **测试**：量化口径单元测试（固定样本数据断言 `change_pct`/`gap_pct`/`intraday_pct`/市值加权/形态判定），防口径回归。
- **git 版本管理**：本地 git 仓库，`.gitignore` 排除 `.env`/`report/`/缓存；之后推 GitHub（待用户提供仓库 URL）。

## 8. 关键决策汇总

| 模块 | 决策 |
|---|---|
| 昨收 | `previousClose` 元数据为主，历史重建为备 |
| 调度 | cron 固定 17:30 ET 后，只跑一次 |
| 行情窗口 | `5d`/`5m`，批量 `download`，`auto_adjust=False` |
| 市值 | `Ticker.info['marketCap']`，跳过+覆盖率上报，缓存 |
| 新闻 | Alpha Vantage（`topics` 单次+客户端过滤）主 + Google News RSS 兜底 |
| 时间窗/对齐 | 24h / 异动 ±60min（代码对齐） |
| LLM | `deepseek-chat`，关联解读，混合 JSON，4 禁令 + 免责 |
| 推送 | 摘要 + 网页（VPS 静态托管），WxPusher→Telegram→落盘，幂等 |

## 9. 执行计划

| 阶段 | 内容 |
|---|---|
| P0 骨架 | 目录、`config.json`+schema、`.env`（含占位符）+`.env.example`、`.gitignore`、`requirements.txt`、logging 基础、git init |
| P1 数据层 | `market_calendar.py`、`quant_engine.py` + 量化口径单元测试 |
| P2 新闻层 | `news_fetcher.py`（Alpha Vantage 主 + Google News RSS 兜底 + 缓存 + dry-run）+ 测试 |
| P3 分析层 | `llm_analyzer.py`（DeepSeek、关联解读、混合 JSON、记忆）+ 测试 |
| P4 推送层 | `notifier.py`（摘要 + 降级链 + 幂等）+ 测试 |
| P5 编排上线 | `main.py`（流程+顶层兜底+幂等锁）、cron 配置、端到端冒烟测试 |

## 10. 人工待办清单

### A. 需开通/提供的密钥
1. DeepSeek API key（需预充值，唯一付费项）
2. Alpha Vantage API key（免费，25 次/天）
3. WxPusher appToken + 接收者 UID（可多个，逗号分隔）
4. Telegram bot token + chat_id（可多个，逗号分隔）

### B. 内容决策（已定）
5. watchlist：见第 5 节（已定稿）
6. 基准：QQQ + SOX（已定）
7. 网页托管：VPS 静态托管 + 域名 https 访问（已定）

### C. 运行环境
8. 运行机器 + cron（America/New_York，17:35 触发）
9. 编辑 P0 生成的 `.env`，填入密钥
10. 提供 GitHub 仓库地址（之后 push 用）
11. 提供报告访问域名（https，用于推送链接）
12. 首次联调：确认收到测试推送

### D. 上线后
13. 首日抽查：核对报告涨跌幅 vs 行情软件
14. watchlist 维护（退市/新增/并购）

## 11. 部署运行（cron）

服务器时区设为美东（或使用 `CRON_TZ`）：

```
CRON_TZ=America/New_York
35 17 * * 1-5 cd /path/to/ai-stock-report && python3 main.py >> logs/cron.log 2>&1
```

- `1-5` 仅工作日触发，`is_trading_day()` 再兜底节假日；
- `35 17` = 17:35 ET（收盘后，规避早收盘半日市）；
- 幂等：同日重复触发会被 `cache/last_run.txt` 锁拦截；失败会自动释放锁以便重试。
