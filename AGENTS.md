# AGENTS.md — 项目持久记忆

## 项目
美股科技/AI 子板块每日自动复盘系统。每日美股收盘后（17:30 ET 后）跑一次：抓行情 → 量化计算 → 抓新闻 → DeepSeek 解读 → 摘要推送（WxPusher/Telegram）+ 完整报告网页。

## 权威设计文档
完整定稿设计见 `DESIGN.md`，是编码的唯一依据。改动前先更新 DESIGN.md。

## 关键决策（速记）
- **昨收**：`.info['regularMarketPreviousClose']` 为主，5d 历史按交易日重建为备；`auto_adjust=False` + 拆股哨兵(±50%)。
- **行情**：`yf.download(tickers, period="5d", interval="5m", group_by="ticker", auto_adjust=False, prepost=False)` 批量一次请求。
- **市值**：`Ticker.info['marketCap']`，缺失跳过+覆盖率上报，<80% 降级等权；循环节流+重试+落盘缓存。
- **新闻**：Alpha Vantage `NEWS_SENTIMENT`（`topics` 单次调用 + 客户端按 `ticker_sentiment` 过滤）为主，Google News RSS 兜底；禁止逐票调 Alpha Vantage（25次/天额度）。每条必须带时间戳，24h 窗口，去重。
- **LLM**：`deepseek-chat` 为主；关联解读（非因果归因）；60min 时间对齐在代码里做；混合 JSON 输出（结构化字段+prose 字段，代码自行渲染）；4 禁令（禁编数字/禁编新闻/禁因果断言/禁预测荐股）+ 免责声明；记忆带日期 key，LLM 失败不写记忆。
- **推送**：摘要+网页链接（VPS 静态托管 + 域名 https）；WxPusher(https, contentType=3, code==1000)→Telegram(纯文本)→落盘；幂等。
- **报告 HTML**：静态 HTML（内联 CSS），移动端优先（viewport、单列、字号≥16px、表格横向滚动）。
- **工程化**：logging 标准、顶层 try/except 失败告警、cron 幂等锁、secrets 走 `.env`（P0 生成含占位符、git 忽略）、依赖锁主次版本、量化口径单元测试。
- **版本管理**：本地 git 仓库（`.gitignore` 排除 `.env`/`report/`/缓存），之后推 GitHub（等用户给 repo URL）。

## 默认 watchlist（26 只 + 基准 QQQ/SOX）
- AI 芯片与半导体：NVDA, AMD, AVGO, TSM, MU, INTC, MRVL, ARM
- 云计算与超大规模：MSFT, AMZN, GOOGL, META, ORCL, CRM, NOW
- AI 软件与数据平台：PLTR, SNOW, CRWD, DDOG, NET, MDB, PANW
- 消费电子与硬件：AAPL, DELL, SMCI, HPE

## 代码原则
- 零硬编码 ticker/阈值，一切以 `config.json` 为准；每个 ticker 带 `enabled` 开关。
- 阈值全部可配：拆股 50%、覆盖率 80%、对齐 60min、新闻 24h、形态阈值。
- 启动时健康校验：拉不到数据/市值的 ticker 自动标"数据异常"。

## 人工待办（实现前需用户提供）
DeepSeek key（付费）、Alpha Vantage key（免费）、WxPusher appToken+UID、Telegram bot token+chat_id、运行机器+cron、GitHub 仓库地址（push 用）、报告访问域名（https）。
