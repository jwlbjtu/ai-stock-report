# 美股科技/AI 子板块每日自动复盘系统

每天美股收盘后，自动抓取 **26 只科技/AI 股票 + QQQ/SOX 基准** 的行情与新闻，调用 **DeepSeek** 生成量化复盘，推送到 **微信（WxPusher）/ Telegram**，并生成 **移动端优先的网页报告**。

> 报告是**复盘**，不是荐股。系统内置「禁编数字 / 禁编新闻 / 禁因果断言 / 禁预测荐股」四道护栏，所有数字都来自真实行情数据，归因只做关联性描述。

---

## 功能特性

- **量化引擎**：市值加权 + 等权双口径板块涨跌幅，市值覆盖率不足自动降级等权；拆股/异常哨兵。
- **形态与异动**：自动标注「高开低走 / 低开高走 / 单边」，定位日内最大 15 分钟异动时刻。
- **量价与趋势**：相对量能（放量/缩量）、异动时刻量能配合、20/50 日均线位置、距 52 周高低点。
- **新闻归因**：Alpha Vantage `NEWS_SENTIMENT`（英文）+ 东方财富（中文）双源，Google News RSS 兜底；**60 分钟时间对齐在代码里完成**（只把异动时刻附近的新闻喂给模型）。
- **LLM 复盘**：DeepSeek-chat 生成结构化 JSON（资金广度 / 关联解读 / 形态点评 / 趋势位置 / 连续性复盘 / 风险提示），带**跨日记忆**（结合昨日结论看延续 vs 反转）。
- **推送降级链**：WxPusher → Telegram → 落盘，主通道失败自动切备，多收件人支持。
- **报告网页**：静态 HTML（内联 CSS，移动端优先），含**个股走势图 sparkline + 市场热力图**，自动生成历史报告列表 `index.html`。
- **个人持仓（PA）复盘**：独立的个人组合日报——实时行情 + 盈亏（折算港币）+ 走势（MA/52周）+ 集中度，与 AI 复盘完全隔离、互不影响。

---

## 工作流程

```
cron（17:35 ET，工作日）
  └─ main.py
       ├─ 交易日判断（休市则退出）
       ├─ 幂等锁（同日重复运行跳过）
       ├─ 量化计算   quant_engine.py（行情 + 双权重 + 异动/形态）
       ├─ 新闻抓取   news_fetcher.py（Alpha Vantage 主 + Google RSS 兜底）
       ├─ LLM 分析   llm_analyzer.py（DeepSeek + 60min 对齐 + 记忆）
       ├─ 报告渲染   render.py（HTML + index.html 列表）
       └─ 推送       notifier.py（摘要 + 链接，降级链）
```

---

## 目录结构

```
ai-stock-report/
├── main.py               # 主程序入口与调度
├── config.py             # 配置加载与 schema 校验
├── config.json           # 静态配置（板块/阈值/LLM/报告）
├── market_calendar.py    # 交易日与美东时区
├── quant_engine.py       # 量化计算引擎
├── news_fetcher.py       # 新闻抓取
├── llm_analyzer.py       # DeepSeek 归因与记忆
├── notifier.py           # 推送路由与降级
├── render.py             # HTML 渲染（报告 + 列表）
├── main_pa.py            # PA 持仓报告入口（独立）
├── pa_engine.py          # PA 持仓引擎（行情/盈亏/汇率/走势）
├── pa_render.py          # PA 报告渲染
├── pa_manage.py          # PA 调仓 CLI
├── pa_holdings.json      # PA 持仓配置（买入价+股数）
├── logger.py             # 日志
├── requirements.txt      # 依赖
├── .env.example          # 密钥模板
├── .env                  # 密钥（git 忽略，勿提交）
├── tests/                # 单元测试（pytest）
├── report/               # 生成的报告（git 忽略）
├── pa_report/            # PA 报告输出（git 忽略）
├── cache/                # 运行时缓存（git 忽略）
├── memory/               # 跨日记忆（git 忽略）
├── DESIGN.md             # 详细设计文档
├── DEPLOY.md             # 部署与运维手册（VPS 部署 + 更新）
└── README.md
```

---

## 环境要求

- **Python 3.11+**（开发环境为 3.13）
- 能访问外网（yfinance / Alpha Vantage / DeepSeek / WxPusher / Telegram）
- Linux VPS（用于定时运行与静态托管报告）

---

## 快速开始

### 1. 安装依赖

```bash
cd ai-stock-report
pip install -r requirements.txt
```

### 2. 配置 `.env`

复制模板并填入真实密钥：

```bash
cp .env.example .env
vim .env
```

| 键 | 说明 | 获取方式 |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 大模型（付费，需预充值） | platform.deepseek.com |
| `ALPHA_VANTAGE_API_KEY` | 新闻源（免费 25 次/天） | alphavantage.co |
| `WXPUSHER_APP_TOKEN` | 微信推送应用 token | wxpusher.zjiecode.com |
| `WXPUSHER_UIDS` | 收件人 UID，多个用英文逗号分隔 | WxPusher 控制台 |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | @BotFather |
| `TELEGRAM_CHAT_IDS` | 收件人 chat_id，多个用英文逗号分隔 | @userinfobot |

> ⚠️ `.env` 已在 `.gitignore` 中，**切勿提交**。密钥只存在于服务器本地。

### 3. 配置 `config.json`（按需）

- `sub_sectors`：板块与成分股，`enabled` 控制是否启用。
- `thresholds`：拆股哨兵、市值覆盖率下限、对齐窗口、新闻窗口、形态阈值。
- `llm.model`：默认 `deepseek-chat`。
- `chinese_names`：中文名映射（用于东方财富中文新闻搜索），可自行增删改。
- `report.base_url`：报告访问根地址（占位符，见下方「报告网页访问」）。

### 4. 手动运行一次

```bash
python3 main.py
```

运行日志会输出到控制台；成功后会生成 `report/YYYY-MM-DD.html` 并推送摘要。

---

## 定时任务（cron）

系统设计为 **每个交易日美东 17:35** 运行一次（收盘后，规避早收盘半日市）。

> 📘 完整的 VPS 部署（nginx + HTTPS + venv）与日常更新策略见 [DEPLOY.md](DEPLOY.md)。

### 1. 编辑 crontab

```bash
crontab -e
```

### 2. 添加下面这行

```cron
CRON_TZ=America/New_York
35 17 * * 1-5 cd /path/to/ai-stock-report && /usr/bin/python3 main.py >> logs/cron.log 2>&1
```

> 把 `/path/to/ai-stock-report` 换成你的实际项目路径；`/usr/bin/python3` 换成 `which python3` 的结果（尤其用了 venv 时）。

### 3. 字段含义

| 字段 | 值 | 含义 |
|---|---|---|
| `CRON_TZ` | `America/New_York` | 让 cron 按美东时区解释时间 |
| `35 17` | 17:35 | 每天 17:35 触发 |
| `* * 1-5` | 周一～周五 | 仅工作日触发（节假日由 `is_trading_day()` 再兜底） |
| `>> logs/cron.log 2>&1` | 日志重定向 | 标准输出 + 错误都追加到日志文件 |

### 4. 验证与排查

```bash
crontab -l                          # 查看已配置的定时任务
tail -f logs/cron.log               # 实时看日志
grep "每日复盘完成" logs/cron.log    # 确认最近一次成功
```

**常见问题**：

- **cron 没跑**：检查 python 路径（`which python3`）、项目路径是否正确、`logs/` 目录是否存在（`mkdir -p logs`）。
- **时区不对**：老版本 cron 不支持 `CRON_TZ`，可改用 `0 21 * * 1-5`（把服务器时区设成 UTC 后按 21:35 UTC ≈ 17:35 ET）或直接 `sudo timedatectl set-timezone America/New_York`。
- **重复推送**：系统有幂等锁（`cache/last_run.txt`），同日重复触发会被跳过；运行失败会自动释放锁以便手动重试。

---

## 推送通道说明

- **摘要推送**：几百字（板块涨跌 + 领涨领跌 + 基准 + 报告链接），发送到 WxPusher（微信）与 Telegram。
- **降级链**：WxPusher 明确失败（`code != 1000`）→ 自动切 Telegram → 都失败则把摘要落盘到 `report/fallback_*.txt` 并记日志。
- **多收件人**：`WXPUSHER_UIDS` / `TELEGRAM_CHAT_IDS` 用英文逗号分隔；WxPusher 一次发多个 UID，Telegram 逐个 chat_id 发送。
- **失败告警**：整个流程失败时，会额外给 Telegram 发一条 `⚠️ 每日复盘执行失败` 告警。

---

## 报告网页访问（域名 + HTTPS）

报告是静态 HTML，需要一个 Web 服务器把它暴露到域名上。步骤：

1. **DNS**：给子域名加 A 记录指向 VPS 公网 IP，如 `reports` → `1.2.3.4`。
2. **nginx**：把 `report/` 目录作为静态站点：

   ```nginx
   server {
       listen 80;
       server_name reports.yourdomain.com;
       root /path/to/ai-stock-report/report;
       index index.html;
       location / { try_files $uri $uri/ =404; }
   }
   ```

3. **HTTPS**：`sudo certbot --nginx -d reports.yourdomain.com`（Let's Encrypt 免费证书，自动续期）。
4. **改 `config.json`**：把 `report.base_url` 改成实际地址，使 `base_url + "/" + 日期.html` 正好等于可访问路径。用上面的子域名 + root 直指 `report/` 时：

   ```json
   "base_url": "https://reports.yourdomain.com"
   ```

5. **权限**：`sudo chmod -R o+rX /path/to/ai-stock-report/report`，并放行 80/443 端口。

之后每天 cron 跑完，HTML 自动落到 `report/`，nginx 实时读文件，**无需每天重启**。根路径 `reports.yourdomain.com/` 会自动显示历史报告列表（`index.html`）。

---

## PA 持仓复盘（个人组合）

除了 AI 子板块复盘，系统还能生成一份**个人持仓（PA）日报**，两者完全独立、互不影响：

- **独立入口** `main_pa.py`，独立 cron，独立日志 `logs/cron_pa.log`，独立输出 `pa_report/`；一份失败不影响另一份。
- **数据**：`pa_holdings.json` 只存**买入价 + 股数**（唯一信任的输入），现价/市值/盈亏全部实时抓取。
- **总盈亏折算港币**（`base_currency: "HKD"`，汇率实时抓取）。
- **走势分析**：今日涨跌 + MA20/50 + 距 52 周高低点（确定性规则，无 LLM）。
- **推送**：复用同一微信/Telegram 通道，摘要标题带 `💼 个人持仓复盘`。

### 调仓（更新仓位）

用命令行工具增删改持仓，无需手改 JSON：

```bash
python3 pa_manage.py list                          # 查看当前持仓
python3 pa_manage.py add AAPL 10 180.5 USD 苹果     # 新增：代码 数量 成本价 币种 [名称]
python3 pa_manage.py update AAPL --quantity 20      # 改数量（或 --cost-price / --name）
python3 pa_manage.py remove AAPL                    # 删除
```

- 港股代码用 4 位加 `.HK`（`17`→`0017.HK`），德国股加 `.DE`（`RHM.DE`），美股直接写。
- 改完下次 cron 自动生效。

### 运行与定时

```bash
python3 main_pa.py
```

报告落在 `pa_report/`，访问 `https://reports.buildbodys.com/pa/`。定时任务（与 AI 复盘独立，互不影响）：

```cron
CRON_TZ=America/New_York
40 17 * * 1-5 cd /var/www/ai-stock-report && .venv/bin/python main_pa.py >> logs/cron_pa.log 2>&1
```

---

## 测试

```bash
python3 -m pytest -q
```

测试覆盖：交易日历、量化计算、新闻解析、LLM 时间对齐与记忆、推送摘要/切分、HTML 渲染等纯逻辑（不含网络 I/O）。

---

## 常见问题（FAQ）

- **为什么涨跌幅和行情软件对不上？** 检查是否在收盘后运行（17:35 ET 后），盘中运行会拿到未收盘数据；另外拆股/除权会被哨兵标记为「待人工核对」。
- **Alpha Vantage 报错？** 免费额度 25 次/天，系统单次调用 + 客户端过滤，正常一天只消耗 1 次；额度用完会自动降级 Google News RSS。
- **某只票数据缺失？** 会在日志/报告的 warnings 里标注「数据不足，已跳过」，市值缺失则该票不参与市值加权。
- **想增删股票？** 改 `config.json` 的 `sub_sectors`，把 `enabled` 设为 `false` 即可停用（无需删除）。
