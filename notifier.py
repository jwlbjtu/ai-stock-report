"""消息推送路由与降级熔断。

主通道 WxPusher(Markdown) → 备用 Telegram(纯文本) → 都失败落盘。支持多收件人。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from market_calendar import now_et

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "report"
PA_REPORT_DIR = BASE_DIR / "pa_report"

WXPUSHER_URL = "https://wxpusher.zjiecode.com/api/send/message"

_CUR_SYMBOL = {"HKD": "HK$", "USD": "US$", "EUR": "€", "GBP": "£", "CNY": "¥", "JPY": "¥"}


# ---------------------------------------------------------------------------
# 纯函数（可单测）
# ---------------------------------------------------------------------------

def parse_recipients(raw: Optional[str]) -> List[str]:
    """把逗号分隔字符串解析为去空白的列表。"""
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _fmt_pct(x: Optional[float]) -> str:
    if x is None:
        return "N/A"
    return f"{x:+.2f}%"


def _fmt_num(x: Optional[float], sign: bool = False) -> str:
    if x is None:
        return "N/A"
    s = f"{x:,.2f}"
    if sign and x > 0:
        s = "+" + s
    return s


def build_digest(
    quant_result: Dict[str, Any],
    llm_result: Optional[Dict[str, Any]],
    report_url: Optional[str] = None,
) -> str:
    """构建推送摘要（纯文本 + emoji，对 WxPusher Markdown 与 Telegram 纯文本均安全）。"""
    lines = [f"📊 美股科技/AI 复盘 · {quant_result['date']}", ""]

    summary = (llm_result or {}).get("summary")
    if summary:
        lines.append(str(summary))
        lines.append("")

    # 领涨/领跌（跨板块）
    pairs = []
    for s in quant_result.get("sectors", []):
        for st in s.get("stocks", []):
            c = st.get("change_pct")
            if c is not None:
                pairs.append((st.get("symbol", ""), c))
    if pairs:
        pairs.sort(key=lambda x: x[1])
        lines.append(f"领涨 {pairs[-1][0]} {_fmt_pct(pairs[-1][1])} ｜ 领跌 {pairs[0][0]} {_fmt_pct(pairs[0][1])}")
        lines.append("")

    for s in quant_result.get("sectors", []):
        w = "市值加权" if s.get("weight_used") == "cap" else "等权"
        lines.append(f"▪️ {s['name']}: {w} {_fmt_pct(s.get('r_cap'))} ｜ 等权 {_fmt_pct(s.get('r_eq'))}")

    bench = quant_result.get("benchmarks", {})
    if bench:
        parts = [f"{k} {_fmt_pct(v)}" for k, v in bench.items() if v is not None]
        if parts:
            lines.append("")
            lines.append("基准: " + " ｜ ".join(parts))

    if report_url:
        lines.append("")
        lines.append(f"完整报告: {report_url}")

    return "\n".join(lines)


def split_text(text: str, limit: int = 4000) -> List[str]:
    """按段落边界切分长文本，单段超长时硬切。"""
    if len(text) <= limit:
        return [text]
    chunks: List[str] = []
    current = ""
    for para in text.split("\n"):
        if len(current) + len(para) + 1 > limit:
            if current:
                chunks.append(current)
            current = para
            while len(current) > limit:
                chunks.append(current[:limit])
                current = current[limit:]
        else:
            current = current + "\n" + para if current else para
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# 网络 I/O
# ---------------------------------------------------------------------------

def send_wxpusher(app_token: str, uids: List[str], content: str) -> Tuple[bool, Dict[str, Any]]:
    """WxPusher 发送（Markdown，contentType=3）。返回 (是否成功, 响应)。"""
    payload = {
        "appToken": app_token,
        "content": content,
        "contentType": 3,
        "uids": uids,
    }
    resp = requests.post(WXPUSHER_URL, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("code") == 1000, data


def send_telegram(bot_token: str, chat_ids: List[str], text: str) -> Tuple[bool, List[str]]:
    """Telegram 发送（纯文本，逐 chat_id 循环）。返回 (是否全部成功, 错误列表)。"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    all_ok = True
    errors: List[str] = []
    for cid in chat_ids:
        try:
            resp = requests.post(url, json={"chat_id": cid, "text": text}, timeout=15)
            data = resp.json()
            if not data.get("ok"):
                all_ok = False
                errors.append(f"{cid}: {data.get('description', data)}")
                log.warning("Telegram 发送失败 %s: %s", cid, data)
            else:
                log.info("Telegram 发送成功: %s", cid)
        except Exception as e:  # noqa: BLE001
            all_ok = False
            errors.append(f"{cid}: {e}")
            log.warning("Telegram 发送异常 %s: %s", cid, e)
    return all_ok, errors


def _save_fallback(content: str, out_dir: Path = REPORT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"fallback_{now_et().strftime('%Y%m%d_%H%M%S')}.txt"
    out.write_text(content, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------

def build_pa_digest(pa_result: Dict[str, Any], report_url: Optional[str] = None) -> str:
    """构建 PA 持仓推送摘要（纯文本 + emoji）。"""
    base = pa_result.get("base_currency", "HKD")
    base_sym = _CUR_SYMBOL.get(base, base + " ")
    total = pa_result.get("total", {})
    lines = [f"💼 个人持仓复盘 · {pa_result['date']}", ""]
    lines.append(f"总市值（折{base}）: {base_sym}{_fmt_num(total.get('value'))}")
    lines.append(f"浮动盈亏: {base_sym}{_fmt_num(total.get('pnl'), sign=True)} （{_fmt_pct(total.get('pnl_pct'))}）")

    pairs = [
        (p.get("symbol", ""), p.get("pnl_pct"))
        for p in pa_result.get("positions", [])
        if p.get("pnl_pct") is not None
    ]
    if pairs:
        pairs.sort(key=lambda x: x[1])
        lines.append("")
        lines.append(f"领涨 {pairs[-1][0]} {_fmt_pct(pairs[-1][1])} ｜ 领跌 {pairs[0][0]} {_fmt_pct(pairs[0][1])}")

    if report_url:
        lines.append("")
        lines.append(f"完整报告: {report_url}")
    return "\n".join(lines)


def send_pa_notification(pa_result: Dict[str, Any], report_url: Optional[str] = None) -> Dict[str, Any]:
    """发送 PA 持仓摘要。"""
    return _dispatch(build_pa_digest(pa_result, report_url), fallback_dir=PA_REPORT_DIR)


def _dispatch(text: str, fallback_dir: Path = REPORT_DIR) -> Dict[str, Any]:
    """发送文本：WxPusher 主通道 → Telegram 备用 → 落盘。返回发送结果。"""
    app_token = os.getenv("WXPUSHER_APP_TOKEN")
    uids = parse_recipients(os.getenv("WXPUSHER_UIDS"))
    if app_token and uids:
        try:
            ok, data = send_wxpusher(app_token, uids, text)
            if ok:
                log.info("WxPusher 发送成功")
                return {"channel": "wxpusher", "success": True}
            log.warning("WxPusher 发送失败(code!=1000): %s", data)
        except Exception as e:  # noqa: BLE001
            log.warning("WxPusher 发送异常: %s", e)
    else:
        log.warning("WxPusher 未配置(appToken/uids 缺失)")

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_ids = parse_recipients(os.getenv("TELEGRAM_CHAT_IDS"))
    if bot_token and chat_ids:
        try:
            all_ok, errors = send_telegram(bot_token, chat_ids, text)
            if all_ok:
                log.info("Telegram 发送成功")
                return {"channel": "telegram", "success": True}
            log.warning("Telegram 部分/全部失败: %s", errors)
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram 发送异常: %s", e)
    else:
        log.warning("Telegram 未配置(bot token/chat_id 缺失)")

    out = _save_fallback(text, fallback_dir)
    log.error("所有通道发送失败，已落盘: %s", out)
    return {"channel": "file", "success": False, "file": str(out)}


def send_notification(
    quant_result: Dict[str, Any],
    llm_result: Optional[Dict[str, Any]],
    report_url: Optional[str] = None,
) -> Dict[str, Any]:
    """发送 AI 复盘摘要，WxPusher 主通道 → Telegram 备用 → 落盘。"""
    return _dispatch(build_digest(quant_result, llm_result, report_url))
