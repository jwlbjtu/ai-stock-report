"""量化计算引擎：行情抓取、指标、双权重汇总、异动与形态判定。

纯计算函数与网络 I/O 分离，前者可离线单测。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from config import enabled_symbols
from market_calendar import EASTERN, now_et

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"


# ---------------------------------------------------------------------------
# 纯计算函数（离线可单测）
# ---------------------------------------------------------------------------

def classify_shape(gap_pct: float, intraday_pct: float, gap_thr: float, intra_thr: float) -> str:
    """根据跳空与日内涨跌标注形态。"""
    if gap_pct > gap_thr and intraday_pct < -intra_thr:
        return "高开低走"
    if gap_pct < -gap_thr and intraday_pct > intra_thr:
        return "低开高走"
    if abs(gap_pct) <= gap_thr and abs(intraday_pct) > intra_thr:
        return "单边上涨" if intraday_pct > 0 else "单边下跌"
    return "震荡"


def _fmt_time_et(ts) -> Optional[str]:
    """把时间戳格式化为 'HH:MM ET' 展示字符串。"""
    if ts is None or pd.isna(ts):
        return None
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize(EASTERN)
    return ts.astimezone(EASTERN).strftime("%H:%M ET")


def compute_metrics(
    today_bars: pd.DataFrame,
    prev_close: Optional[float],
    thresholds: Dict[str, float],
) -> Optional[Dict[str, Any]]:
    """从当日 5m bar（需含 Open/Close 列，时间升序）计算单票指标。"""
    if today_bars is None or today_bars.empty:
        return None
    if prev_close is None or prev_close <= 0:
        return None

    open_ = float(today_bars["Open"].iloc[0])
    close_ = float(today_bars["Close"].iloc[-1])

    change_pct = (close_ - prev_close) / prev_close * 100
    intraday_pct = (close_ - open_) / open_ * 100
    gap_pct = (open_ - prev_close) / prev_close * 100

    # 15 分钟滚动涨跌幅 = 5m Close 的 pct_change(3)
    moves = today_bars["Close"].pct_change(3) * 100
    valid = moves.dropna()
    if valid.empty:
        max_move_time = None
        max_move_val = None
    else:
        idx = valid.abs().idxmax()
        max_move_time = _fmt_time_et(idx)
        max_move_val = float(valid.loc[idx])

    return {
        "open": round(open_, 2),
        "close": round(close_, 2),
        "change_pct": round(change_pct, 2),
        "intraday_pct": round(intraday_pct, 2),
        "gap_pct": round(gap_pct, 2),
        "max_move_time": max_move_time,
        "max_move_val": None if max_move_val is None else round(max_move_val, 2),
        "shape": classify_shape(
            gap_pct,
            intraday_pct,
            thresholds["shape_gap_threshold_pct"],
            thresholds["shape_intraday_threshold_pct"],
        ),
        "split_guard": abs(change_pct) > thresholds["split_guard_pct"],
    }


def compute_equal_weight(changes: List[Optional[float]]) -> Optional[float]:
    """算术平均涨幅 R_eq（忽略 None）。"""
    vals = [c for c in changes if c is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def compute_cap_weight(
    changes: List[Optional[float]],
    caps: List[Optional[float]],
) -> Tuple[Optional[float], float, int, int]:
    """市值加权涨幅 R_cap。返回 (R_cap, coverage, covered, total)。

    caps 中 None 或 <=0 的标的跳过；coverage = 有市值标的数 / 总标的数。
    """
    total = len(changes)
    covered = 0
    weighted_sum = 0.0
    total_cap = 0.0
    for chg, cap in zip(changes, caps):
        if chg is None or cap is None or cap <= 0:
            continue
        weighted_sum += cap * chg
        total_cap += cap
        covered += 1
    if total_cap <= 0:
        return None, 0.0, 0, total
    r_cap = weighted_sum / total_cap
    coverage = covered / total if total else 0.0
    return round(r_cap, 2), round(coverage, 4), covered, total


def parse_download(
    df: pd.DataFrame,
    symbol: str,
) -> Tuple[Optional[pd.DataFrame], Optional[float]]:
    """从批量 download 结果提取 symbol 的当日 bar 与备选昨收。

    返回 (today_bars, backup_prev_close)。df 为 group_by='ticker' 的 MultiIndex 结果。
    """
    if df is None or df.empty or not isinstance(df.columns, pd.MultiIndex):
        return None, None
    if symbol not in df.columns.get_level_values(0):
        return None, None

    sub = df[symbol].dropna(how="all")
    if sub.empty:
        return None, None

    dates = sorted(set(sub.index.date))
    today = dates[-1]
    today_bars = sub[sub.index.date == today]

    backup_prev_close = None
    if len(dates) >= 2:
        y_bars = sub[sub.index.date == dates[-2]]
        if not y_bars.empty and "Close" in y_bars:
            backup_prev_close = float(y_bars["Close"].iloc[-1])

    return today_bars, backup_prev_close


# ---------------------------------------------------------------------------
# 网络 I/O
# ---------------------------------------------------------------------------

def fetch_market_data(symbols: List[str], period: str, interval: str) -> pd.DataFrame:
    """批量抓取 5m 行情，返回 group_by='ticker' 的 DataFrame。"""
    log.info("抓取行情: %d 个标的, period=%s interval=%s", len(symbols), period, interval)
    df = yf.download(
        tickers=symbols,
        period=period,
        interval=interval,
        group_by="ticker",
        auto_adjust=False,
        prepost=False,
        progress=False,
        threads=True,
    )
    if df.empty:
        log.warning("行情抓取返回空数据")
    return df


def fetch_quote_info(
    symbols: List[str],
    sleep: float = 0.5,
    retries: int = 2,
) -> Dict[str, Dict[str, Optional[float]]]:
    """逐票拉取 .info，提取 marketCap 与 regularMarketPreviousClose。

    带节流 + 重试。返回 {symbol: {"market_cap": ..., "previous_close": ...}}。
    """
    result: Dict[str, Dict[str, Optional[float]]] = {}
    for i, sym in enumerate(symbols):
        cap = None
        prev = None
        for attempt in range(retries + 1):
            try:
                info = yf.Ticker(sym).info
                cap = info.get("marketCap")
                prev = info.get("regularMarketPreviousClose")
                if cap is not None or prev is not None:
                    break
            except Exception as e:  # noqa: BLE001
                log.warning("拉取 %s .info 失败(第%d次): %s", sym, attempt + 1, e)
            time.sleep(sleep * (attempt + 1))
        result[sym] = {"market_cap": cap, "previous_close": prev}
        if (i + 1) < len(symbols):
            time.sleep(sleep)
    return result


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------

def run_quant(config: Dict[str, Any], fetch_quotes: bool = True) -> Dict[str, Any]:
    """执行量化计算，返回结构化结果 dict（sectors 按 R_cap 降序）。"""
    thresholds = config["thresholds"]
    symbols = enabled_symbols(config)
    benchmarks = config.get("benchmarks", [])
    all_syms = symbols + benchmarks

    df = fetch_market_data(all_syms, config["data"]["period"], config["data"]["interval"])

    today = now_et().date().isoformat()
    cache_file = CACHE_DIR / f"quote_info_{today}.json"

    info_map: Dict[str, Dict[str, Optional[float]]] = {}
    if fetch_quotes:
        if cache_file.exists():
            try:
                info_map = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                info_map = {}
        if not info_map:
            info_map = fetch_quote_info(all_syms)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(info_map), encoding="utf-8")

    warnings: List[str] = []
    sectors: List[Dict[str, Any]] = []

    for sector in config["sub_sectors"]:
        stock_rows: List[Dict[str, Any]] = []
        changes: List[Optional[float]] = []
        caps: List[Optional[float]] = []

        for t in sector["tickers"]:
            sym = t["symbol"].strip().upper()
            if not t.get("enabled"):
                continue

            today_bars, backup_prev = parse_download(df, sym)
            info = info_map.get(sym, {})
            prev_close = info.get("previous_close")
            if prev_close is None:
                prev_close = backup_prev

            m = compute_metrics(today_bars, prev_close, thresholds)
            if m is None:
                warnings.append(f"{sym}: 数据不足，已跳过")
                changes.append(None)
                caps.append(None)
                continue

            m["symbol"] = sym
            if m["split_guard"]:
                warnings.append(f"{sym}: 疑似拆股/异常(涨跌幅 {m['change_pct']}%)，待人工核对")
            stock_rows.append(m)
            changes.append(m["change_pct"])
            caps.append(info.get("market_cap"))

        stock_rows.sort(key=lambda x: x.get("change_pct", -1e9), reverse=True)

        r_eq = compute_equal_weight(changes)
        r_cap, coverage, covered, total = compute_cap_weight(changes, caps)

        weight_used = "cap"
        if coverage < thresholds["market_cap_coverage_min"]:
            weight_used = "eq"
            warnings.append(f"{sector['name']}: 市值覆盖率不足({covered}/{total})，改用等权")

        sectors.append({
            "name": sector["name"],
            "r_eq": r_eq,
            "r_cap": r_cap,
            "weight_used": weight_used,
            "cap_coverage": coverage,
            "stocks": stock_rows,
        })

    sectors.sort(key=lambda s: (s["r_cap"] is None, -(s["r_cap"] or 0)))

    bench: Dict[str, Optional[float]] = {}
    for b in benchmarks:
        today_bars, backup_prev = parse_download(df, b)
        info = info_map.get(b, {})
        prev = info.get("previous_close")
        if prev is None:
            prev = backup_prev
        if today_bars is not None and not today_bars.empty and prev:
            bench[b] = round((float(today_bars["Close"].iloc[-1]) - prev) / prev * 100, 2)
        else:
            bench[b] = None
            warnings.append(f"基准 {b}: 数据不足")

    return {
        "date": today,
        "sectors": sectors,
        "benchmarks": bench,
        "warnings": warnings,
    }
