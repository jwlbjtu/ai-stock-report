"""PA 持仓引擎：实时行情 + 盈亏 + 走势 + 汇率折算。

纯计算函数与网络 I/O 分离，前者可离线单测。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yfinance as yf

from market_calendar import now_et
from quant_engine import compute_trend, parse_daily

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
PA_HOLDINGS_PATH = BASE_DIR / "pa_holdings.json"

# 需要折算的币种（基准币种之外）。汇率抓不到时仅影响折算，不影响本币盈亏。
_FX_CURRENCIES = ("USD", "EUR", "GBP", "CNY", "JPY")


def load_holdings(path: Path = PA_HOLDINGS_PATH) -> Dict[str, Any]:
    """读取持仓配置（base_currency + positions）。"""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data.get("positions"), list):
        raise ValueError("pa_holdings.json 缺少 positions 数组")
    return data


# ---------------------------------------------------------------------------
# 纯计算函数（离线可单测）
# ---------------------------------------------------------------------------

def compute_position_metrics(
    close: float,
    prev_close: Optional[float],
    quantity: float,
    cost_price: float,
    trend: Optional[Dict[str, Optional[float]]] = None,
) -> Dict[str, Any]:
    """从现价/昨收/数量/成本价/趋势 计算单持仓指标（本币）。"""
    value = close * quantity
    cost = cost_price * quantity
    pnl = value - cost
    change_pct = (close - prev_close) / prev_close * 100 if prev_close else None
    m: Dict[str, Any] = {
        "close": round(close, 4),
        "change_pct": None if change_pct is None else round(change_pct, 2),
        "value": round(value, 2),
        "cost": round(cost, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl / cost * 100, 2) if cost else None,
    }
    if trend:
        m.update(trend)
    return m


def summarize(
    positions: List[Dict[str, Any]],
    base_currency: str,
    fx: Dict[str, float],
) -> tuple[Dict[str, Dict[str, Optional[float]]], Dict[str, Optional[float]]]:
    """汇总：按币种 + 折算基准币种的总值/总成本/总盈亏。"""
    by_currency: Dict[str, Dict[str, float]] = {}
    for p in positions:
        c = by_currency.setdefault(p["currency"], {"value": 0.0, "cost": 0.0, "pnl": 0.0})
        c["value"] += p["value"]
        c["cost"] += p["cost"]
        c["pnl"] += p["pnl"]

    out_ccy: Dict[str, Dict[str, Optional[float]]] = {}
    for ccy, c in by_currency.items():
        out_ccy[ccy] = {
            "value": round(c["value"], 2),
            "cost": round(c["cost"], 2),
            "pnl": round(c["pnl"], 2),
            "pnl_pct": round(c["pnl"] / c["cost"] * 100, 2) if c["cost"] else None,
        }

    total_value = round(sum(p["value_base"] for p in positions if p["value_base"] is not None), 2)
    total_cost = round(sum(p["cost_base"] for p in positions if p["cost_base"] is not None), 2)
    total_pnl = round(sum(p["pnl_base"] for p in positions if p["pnl_base"] is not None), 2)
    total = {
        "value": total_value,
        "cost": total_cost,
        "pnl": total_pnl,
        "pnl_pct": round(total_pnl / total_cost * 100, 2) if total_cost else None,
    }
    return out_ccy, total


# ---------------------------------------------------------------------------
# 网络 I/O
# ---------------------------------------------------------------------------

def fetch_daily_batch(tickers: List[str], period: str = "1y") -> pd.DataFrame:
    """批量抓取日线（用于现价/昨收/趋势）。"""
    log.info("PA 抓取日线: %d 个标的", len(tickers))
    df = yf.download(
        tickers=tickers,
        period=period,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        prepost=False,
        progress=False,
        threads=True,
    )
    return df


def fetch_fx_rates(base_currency: str) -> Dict[str, float]:
    """抓取各币种 → 基准币种的汇率。失败时返回空 dict（由调用方降级）。"""
    pairs = [f"{ccy}{base_currency}=X" for ccy in _FX_CURRENCIES if ccy != base_currency]
    if not pairs:
        return {}
    try:
        df = yf.download(
            tickers=pairs,
            period="5d",
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("汇率抓取失败: %s", e)
        return {}

    rates: Dict[str, float] = {}
    for ccy in _FX_CURRENCIES:
        if ccy == base_currency:
            continue
        daily = parse_daily(df, f"{ccy}{base_currency}=X")
        if daily is not None and "Close" in daily:
            c = daily["Close"].dropna()
            if not c.empty:
                rates[ccy] = float(c.iloc[-1])
    return rates


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------

def run_pa(holdings: Dict[str, Any]) -> Dict[str, Any]:
    """执行 PA 持仓计算，返回结构化结果。"""
    base = holdings.get("base_currency", "HKD")
    positions = holdings["positions"]

    # 按币种分组抓日线（不同市场分开，避免混合市场批量下载的坑）
    groups: Dict[str, List[str]] = {}
    for p in positions:
        groups.setdefault(p["currency"], []).append(p["symbol"])

    daily_dfs: Dict[str, pd.DataFrame] = {}
    for ccy, tickers in groups.items():
        try:
            daily_dfs[ccy] = fetch_daily_batch(tickers)
        except Exception as e:  # noqa: BLE001
            log.warning("PA 抓取 %s 日线失败: %s", ccy, e)
            daily_dfs[ccy] = pd.DataFrame()

    fx = fetch_fx_rates(base)
    warnings: List[str] = []

    result_positions: List[Dict[str, Any]] = []
    for p in positions:
        sym = p["symbol"]
        ccy = p["currency"]
        daily = parse_daily(daily_dfs.get(ccy), sym)

        close = None
        prev_close = None
        trend: Dict[str, Optional[float]] = {}
        if daily is not None and "Close" in daily:
            c = daily["Close"].dropna()
            if not c.empty:
                close = float(c.iloc[-1])
                if len(c) >= 2:
                    prev_close = float(c.iloc[-2])
                trend = compute_trend(daily)

        if close is None:
            warnings.append(f"{sym}: 数据不足，已跳过")
            continue

        m = compute_position_metrics(close, prev_close, p["quantity"], p["cost_price"], trend)
        m["symbol"] = sym
        m["name"] = p.get("name", sym)
        m["currency"] = ccy
        m["quantity"] = p["quantity"]
        m["cost_price"] = p["cost_price"]

        rate = 1.0 if ccy == base else fx.get(ccy)
        if rate is None:
            warnings.append(f"{sym}: 缺少 {ccy}→{base} 汇率，已跳过折算")
            m["value_base"] = None
            m["cost_base"] = None
            m["pnl_base"] = None
        else:
            m["value_base"] = round(m["value"] * rate, 2)
            m["cost_base"] = round(m["cost"] * rate, 2)
            m["pnl_base"] = round(m["pnl"] * rate, 2)
        result_positions.append(m)

    result_positions.sort(key=lambda x: (x["pnl_base"] is None, -(x["pnl_base"] or 0)))
    by_currency, total = summarize(result_positions, base, fx)

    return {
        "date": now_et().date().isoformat(),
        "base_currency": base,
        "fx": {k: round(v, 4) for k, v in fx.items()},
        "positions": result_positions,
        "by_currency": by_currency,
        "total": total,
        "warnings": warnings,
    }
