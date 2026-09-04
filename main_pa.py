"""PA 持仓报告入口与调度。与 AI 复盘（main.py）完全独立，互不影响。

运行方式（cron，每天美东 17:40 触发）：
    CRON_TZ=America/New_York
    40 17 * * 1-5 cd /path/to/ai-stock-report && .venv/bin/python main_pa.py >> logs/cron_pa.log 2>&1
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from logger import get_logger, setup_logging
from market_calendar import is_trading_day, now_et
from notifier import parse_recipients, send_pa_notification, send_telegram
from pa_engine import load_holdings, run_pa
from pa_render import render_pa, write_pa_index

log = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"


def _lock_path() -> Path:
    return CACHE_DIR / "pa_last_run.txt"


def try_acquire_lock(path: Optional[Path] = None) -> bool:
    lock = path or _lock_path()
    today = now_et().date().isoformat()
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists() and lock.read_text(encoding="utf-8").strip() == today:
        return False
    lock.write_text(today, encoding="utf-8")
    return True


def release_lock(path: Optional[Path] = None) -> None:
    (path or _lock_path()).unlink(missing_ok=True)


def save_report(html: str, date_str: str, output_dir: str, base_url: str) -> str:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{date_str}.html").write_text(html, encoding="utf-8")
    return f"{base_url.rstrip('/')}/{date_str}.html"


def send_failure_alert(error: str) -> None:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_ids = parse_recipients(os.getenv("TELEGRAM_CHAT_IDS"))
    if bot_token and chat_ids:
        try:
            send_telegram(bot_token, chat_ids, f"⚠️ PA 持仓复盘执行失败：{error}")
        except Exception:  # noqa: BLE001
            log.exception("失败告警发送也失败")


def main() -> None:
    setup_logging()
    log.info("===== PA 持仓复盘开始 =====")

    if not is_trading_day():
        log.info("今日美股休市，退出")
        sys.exit(0)

    if not try_acquire_lock():
        log.info("今日已运行过，跳过（幂等）")
        sys.exit(0)

    try:
        holdings = load_holdings()
        report_cfg = holdings.get("report", {})
        output_dir = report_cfg.get("output_dir", "pa_report")
        base_url = report_cfg.get("base_url", "https://reports.buildbodys.com/pa")

        pa_result = run_pa(holdings)
        log.info("PA 计算完成，%d 个持仓", len(pa_result["positions"]))

        html = render_pa(pa_result)
        report_url = save_report(html, pa_result["date"], output_dir, base_url)
        log.info("PA 报告已生成：%s", report_url)

        write_pa_index(output_dir)
        log.info("PA 报告列表 index.html 已更新")

        send_result = send_pa_notification(pa_result, report_url)
        log.info("PA 推送结果：%s", send_result)
    except Exception as e:  # noqa: BLE001
        log.exception("PA 执行失败")
        release_lock()
        send_failure_alert(str(e))
        sys.exit(1)

    log.info("===== PA 持仓复盘完成 =====")


if __name__ == "__main__":
    main()
