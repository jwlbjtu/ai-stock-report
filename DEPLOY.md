# 部署与运维手册

本文是项目在 VPS 上的**完整部署 + 日常更新**参考。适用于从零部署、也适用于日常维护。

---

## 0. 架构概览（三个环境）

```
开发（本地/沙盒） ──git push──▶ GitHub（唯一真源） ──git pull──▶ VPS（生产）
```

- **开发环境**：写代码、跑测试，改动通过 `git push` 上到 GitHub。
- **GitHub**：代码与配置的唯一权威副本（`.env` 等密钥**不在**这里）。
- **VPS**：实际运行 cron 的地方，通过 `git pull` 保持与 GitHub 同步。

**核心原则：GitHub 是唯一真源，VPS 的更新就是一句 `git pull`。**

---

## 1. 首次部署

### 1.1 前置条件

- 一台 VPS（Ubuntu/Debian），能访问外网；
- 一个域名（本文以 `reports.buildbodys.com` 为例）；
- 域名 A 记录指向 VPS 公网 IP。

### 1.2 克隆代码到 /var/www

```bash
cd /var/www
git clone https://github.com/jwlbjtu/ai-stock-report.git
```

> 仓库默认私有，clone 需要认证。二选一：
> - **公开仓库**（最简单）：GitHub 仓库 Settings → Danger Zone → Change visibility → public（代码里无密钥，公开安全）。
> - **保持私有**：用 Personal Access Token，`git clone https://<TOKEN>@github.com/jwlbjtu/ai-stock-report.git`。

### 1.3 复制 .env（⚠️ 关键，别漏）

`.env` 在 `.gitignore` 里，不在 GitHub 上，必须手动提供：

```bash
cp /旧项目路径/.env /var/www/ai-stock-report/.env
```

验证键名都在（不显示值）：

```bash
cd /var/www/ai-stock-report && grep -oE '^[A-Z_]+' .env
```

### 1.4 创建虚拟环境 + 装依赖

```bash
cd /var/www/ai-stock-report
sudo apt install -y python3-venv          # 若缺 venv 模块
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 1.5 配置 nginx

创建站点配置：

```bash
sudo nano /etc/nginx/sites-available/reports
```

内容：

```nginx
# HTTP：强制跳转 HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name reports.buildbodys.com;
    return 301 https://$host$request_uri;
}

# HTTPS：服务报告目录
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name reports.buildbodys.com;

    root /var/www/ai-stock-report/report;
    index index.html;

    ssl_certificate /etc/letsencrypt/live/reports.buildbodys.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/reports.buildbodys.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    location / {
        try_files $uri $uri/ =404;
    }

    # PA 持仓报告（子路径 /pa/）
    location /pa/ {
        alias /var/www/ai-stock-report/pa_report/;
        index index.html;
    }
}
```

启用 + 测试 + 重载：

```bash
sudo ln -s /etc/nginx/sites-available/reports /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 1.6 签发 HTTPS 证书（Let's Encrypt）

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d reports.buildbodys.com
```

> 注意：certbot 若把证书配置写进了 `default` 站点而不是 `reports`，需要手动把 1.5 的配置（含证书行）放到 `reports` 文件里，并清理 `default`。

### 1.7 目录权限

`/var/www` 本就在 nginx 可访问的位置，一般无需额外 chmod。若遇到 `Permission denied`：

```bash
sudo chmod -R o+rX /var/www/ai-stock-report/report
```

### 1.8 验证

```bash
python3 scripts/generate_sample.py    # 生成样例报告
curl -I https://reports.buildbodys.com/   # 应返回 200
```

---

## 2. 定时任务（cron）

```bash
crontab -e
```

```cron
CRON_TZ=America/New_York
35 17 * * 1-5 cd /var/www/ai-stock-report && .venv/bin/python main.py >> logs/cron.log 2>&1
40 17 * * 1-5 cd /var/www/ai-stock-report && .venv/bin/python main_pa.py >> logs/cron_pa.log 2>&1
```

- `CRON_TZ`：按美东时区解释时间；
- `35 17 * * 1-5`：每个工作日 17:35（收盘后），节假日由 `is_trading_day()` 兜底；
- 用 `.venv/bin/python` 的**完整路径**，避免依赖系统 Python；
- `logs/` 目录需提前创建：`mkdir -p /var/www/ai-stock-report/logs`。
- **两条 cron 相互独立**：`main.py`（AI 复盘）与 `main_pa.py`（PA 持仓）各自独立进程、独立日志，一条失败不影响另一条。

---

## 3. 日常更新

### 3.1 手动更新（推荐起步）

```bash
cd /var/www/ai-stock-report && bash scripts/update.sh
```

`update.sh` 会依次执行 `git pull` → 重装依赖 → 跑测试。

### 3.2 自动更新（可选）

在报告运行前 5 分钟自动 pull：

```cron
CRON_TZ=America/New_York
30 17 * * 1-5 cd /var/www/ai-stock-report && git pull >> logs/update.log 2>&1
35 17 * * 1-5 cd /var/www/ai-stock-report && .venv/bin/python main.py >> logs/cron.log 2>&1
```

> 自动更新省心，但会即时拉取最新代码（包括可能的 bug）。建议先手动，跑顺了再开自动。

### 3.3 版本回滚

```bash
cd /var/www/ai-stock-report
git checkout v1.0.0          # 回滚到某个 tag
git checkout main            # 回到最新
```

---

## 4. 更新注意事项

| 事项 | 说明 |
|---|---|
| `.env`（密钥） | 在 `.gitignore`，`git pull` 永不覆盖 ✅ |
| `cache/` `memory/` `report/` | 都在 `.gitignore`，pull 不覆盖 VPS 已生成数据 ✅ |
| `config.json` | **被 git 跟踪**。若在 VPS 手动改过它，pull 可能冲突。建议配置变更统一走 GitHub |
| `pa_holdings.json` | **被 git 跟踪**（PA 持仓清单）。调仓用 `python3 pa_manage.py`，或改了后 commit 推送 |
| `pa_report/` | 在 `.gitignore`，pull 不覆盖 VPS 已生成数据 ✅ |
| 新增依赖 | `update.sh` 会自动重装 |
| nginx / cron | 只有项目路径或端口变化时才需改动 |

---

## 5. 常见问题

| 问题 | 原因 / 解决 |
|---|---|
| 访问显示 `Welcome to nginx` | nginx 还在用默认站点，检查 `sites-enabled` 里你的站点是否启用、`server_name` 是否匹配 |
| 返回 404 | 报告目录空（无 index.html），跑 `python3 scripts/generate_sample.py` 或等 `main.py` 生成 |
| 日志 `Permission denied` | nginx 读不到文件：确认项目不在 `/root` 下、`report/` 有 `o+rX` 权限 |
| `git pull` 认证失败 | 仓库私有：设为公开，或用 PAT / `git config --global credential.helper store` 缓存 token |
| cron 没跑 | 检查 python 路径（用 `.venv/bin/python` 完整路径）、`logs/` 目录是否存在、`crontab -l` 是否生效 |
| 时区不对 | 老版 cron 不支持 `CRON_TZ`，可 `sudo timedatectl set-timezone America/New_York` |
