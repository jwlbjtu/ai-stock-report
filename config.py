"""config.json 加载与 schema 校验。

用法:
    from config import load_config, enabled_symbols

    cfg = load_config()
    symbols = enabled_symbols(cfg)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
ENV_PATH = BASE_DIR / ".env"

_REQUIRED_TOP_KEYS = {
    "data",
    "sub_sectors",
    "benchmarks",
    "thresholds",
    "news",
    "llm",
    "report",
}

_REQUIRED_THRESHOLD_KEYS = {
    "split_guard_pct",
    "market_cap_coverage_min",
    "align_window_minutes",
    "news_window_hours",
    "shape_gap_threshold_pct",
    "shape_intraday_threshold_pct",
}


def load_config(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    """读取并校验 config.json，返回配置字典。

    同时加载 .env（幂等，文件不存在时静默跳过），供各模块通过 os.getenv 读取密钥。
    """
    load_dotenv(ENV_PATH)

    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    errors = _validate(raw)
    if errors:
        raise ValueError("config.json 校验失败:\n" + "\n".join(f"  - {e}" for e in errors))

    return raw


def enabled_symbols(config: Dict[str, Any]) -> List[str]:
    """返回所有 enabled=True 的 ticker 代码（去重、大写、按板块顺序）。"""
    symbols: List[str] = []
    for sector in config.get("sub_sectors", []):
        for t in sector.get("tickers", []):
            if t.get("enabled"):
                symbols.append(t["symbol"].strip().upper())
    return symbols


def _validate(cfg: Dict[str, Any]) -> List[str]:
    errors: List[str] = []

    if not isinstance(cfg, dict):
        return ["顶层必须是 JSON 对象"]

    missing = _REQUIRED_TOP_KEYS - set(cfg.keys())
    if missing:
        errors.append(f"缺少顶层键: {sorted(missing)}")

    # data
    data = cfg.get("data")
    if not isinstance(data, dict):
        errors.append("data 必须是对象")
    else:
        for k in ("period", "interval"):
            v = data.get(k)
            if not isinstance(v, str) or not v:
                errors.append(f"data.{k} 必须是非空字符串")

    # sub_sectors
    sectors = cfg.get("sub_sectors")
    if not isinstance(sectors, list) or not sectors:
        errors.append("sub_sectors 必须是非空数组")
    else:
        seen: set = set()
        for i, sector in enumerate(sectors):
            if not isinstance(sector, dict):
                errors.append(f"sub_sectors[{i}] 必须是对象")
                continue
            name = sector.get("name")
            if not isinstance(name, str) or not name:
                errors.append(f"sub_sectors[{i}].name 必须是非空字符串")
            tickers = sector.get("tickers")
            if not isinstance(tickers, list) or not tickers:
                errors.append(f"sub_sectors[{i}].tickers 必须是非空数组")
                continue
            for j, t in enumerate(tickers):
                prefix = f"sub_sectors[{i}].tickers[{j}]"
                if not isinstance(t, dict):
                    errors.append(f"{prefix} 必须是对象")
                    continue
                symbol = t.get("symbol")
                if not isinstance(symbol, str) or not symbol.strip():
                    errors.append(f"{prefix}.symbol 必须是非空字符串")
                    continue
                sym = symbol.strip().upper()
                if sym in seen:
                    errors.append(f"ticker 重复: {sym}")
                seen.add(sym)
                if not isinstance(t.get("enabled"), bool):
                    errors.append(f"{prefix}.enabled 必须是布尔值")

    # benchmarks
    benchmarks = cfg.get("benchmarks")
    if not isinstance(benchmarks, list):
        errors.append("benchmarks 必须是数组")
    else:
        for i, b in enumerate(benchmarks):
            if not isinstance(b, str) or not b.strip():
                errors.append(f"benchmarks[{i}] 必须是非空字符串")

    # thresholds
    thresholds = cfg.get("thresholds")
    if not isinstance(thresholds, dict):
        errors.append("thresholds 必须是对象")
    else:
        for k in _REQUIRED_THRESHOLD_KEYS:
            if k not in thresholds:
                errors.append(f"thresholds.{k} 缺失")
            elif not isinstance(thresholds[k], (int, float)):
                errors.append(f"thresholds.{k} 必须是数值")

    # news
    news = cfg.get("news")
    if not isinstance(news, dict):
        errors.append("news 必须是对象")
    else:
        if not isinstance(news.get("alpha_vantage_topics"), str) or not news.get("alpha_vantage_topics"):
            errors.append("news.alpha_vantage_topics 必须是非空字符串")
        if not isinstance(news.get("alpha_vantage_limit"), int):
            errors.append("news.alpha_vantage_limit 必须是整数")
        queries = news.get("google_news_queries")
        if not isinstance(queries, list) or not queries:
            errors.append("news.google_news_queries 必须是非空数组")

    # llm
    llm = cfg.get("llm")
    if not isinstance(llm, dict):
        errors.append("llm 必须是对象")
    else:
        for k in ("model", "base_url"):
            v = llm.get(k)
            if not isinstance(v, str) or not v:
                errors.append(f"llm.{k} 必须是非空字符串")
        if not isinstance(llm.get("temperature"), (int, float)):
            errors.append("llm.temperature 必须是数值")
        if not isinstance(llm.get("max_tokens"), int):
            errors.append("llm.max_tokens 必须是整数")

    # report
    report = cfg.get("report")
    if not isinstance(report, dict):
        errors.append("report 必须是对象")
    else:
        for k in ("output_dir", "base_url"):
            v = report.get(k)
            if not isinstance(v, str) or not v:
                errors.append(f"report.{k} 必须是非空字符串")

    return errors
