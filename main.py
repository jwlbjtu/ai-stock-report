"""主程序入口与调度逻辑。

运行方式（cron，每天美东 17:35 触发，见 DESIGN.md 第 11 节）：
    CRON_TZ=America/New_York
    35 17 * * 1-5 cd /path/to/ai-stock-report && python3 main.py >> logs/cron.log 2>&1
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from config import enabled_symbols, load_config
from llm_analyzer import analyze
from logger import get_logger, setup_logging
from market_calendar import is_trading_day, now_et
from news_fetcher import fetch_news
from notifier import parse_recipients, send_notification, send_telegram
from quant_engine import run_quant
from render import render_html

log = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"


def _lock_path() -> Path:
    return CACHE_DIR / "last_run.txt"


def try_acquire_lock(path: Optional[Path] = None) -> bool:
    """尝试获取今日运行锁。已运行过返回 False，否则写入今日日期并返回 True。"""
    lock = path or _lock_path()
    today = now_et().date().isoformat()
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists() and lock.read_text(encoding="utf-8").strip() == today:
        return False
    lock.write_text(today, encoding="utf-8")
    return True


def release_lock(path: Optional[Path] = None) -> None:
    (path or _lock_path()).unlink(missing_ok=True)


def save_report(html: str, date_str: str, output_dir, base_url: str) -> str:
    """写报告 HTML 到 output_dir，返回访问 URL。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{date_str}.html").write_text(html, encoding="utf-8")
    return f"{base_url.rstrip('/')}/{date_str}.html"


def send_failure_alert(error: str) -> None:
    """顶层失败时发告警（不依赖主通道成功，走 Telegram）。"""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_ids = parse_recipients(os.getenv("TELEGRAM_CHAT_IDS"))
    if bot_token and chat_ids:
        try:
            send_telegram(bot_token, chat_ids, f"⚠️ 每日复盘执行失败：{error}")
        except Exception:  # noqa: BLE001
            log.exception("失败告警发送也失败")


def main() -> None:
    setup_logging()
    log.info("===== 每日复盘开始 =====")

    if not is_trading_day():
        log.info("今日美股休市，退出")
        sys.exit(0)

    if not try_acquire_lock():
        log.info("今日已运行过，跳过（幂等）")
        sys.exit(0)

    try:
        config = load_config()
        log.info("配置加载成功，enabled 股票 %d 只", len(enabled_symbols(config)))

        quant_result = run_quant(config)
        log.info("量化计算完成，%d 个板块", len(quant_result["sectors"]))

        news, news_source = fetch_news(config)
        log.info("新闻抓取完成：来源=%s，条数=%d", news_source, len(news))

        llm_result = analyze(config, quant_result, news)
        log.info("LLM 分析完成")

        html = render_html(llm_result, quant_result)
        report_url = save_report(
            html,
            quant_result["date"],
            config["report"]["output_dir"],
            config["report"]["base_url"],
        )
        log.info("报告已生成：%s", report_url)

        send_result = send_notification(quant_result, llm_result, report_url)
        log.info("推送结果：%s", send_result)
    except Exception as e:  # noqa: BLE001
        log.exception("执行失败")
        release_lock()
        send_failure_alert(str(e))
        sys.exit(1)

    log.info("===== 每日复盘完成 =====")


if __name__ == "__main__":
    main()
