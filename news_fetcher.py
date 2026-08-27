"""新闻舆情抓取：Alpha Vantage NEWS_SENTIMENT 主源 + Google News RSS 兜底。

每条新闻统一为结构化 dict：title / summary / url / published_at(UTC ISO) /
source / related_tickers / sentiment / matched_tickers。
"""
from __future__ import annotations

import datetime as dt
import html
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import feedparser
import pytz
import requests

from config import enabled_symbols
from market_calendar import now_et

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"
UTC = pytz.utc


# ---------------------------------------------------------------------------
# 纯函数（离线可单测）
# ---------------------------------------------------------------------------

def _strip_html(text: Optional[str]) -> str:
    """去除 HTML 标签并反转义实体。"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_av_time(s: str) -> dt.datetime:
    """解析 Alpha Vantage time_published（'YYYYMMDDTHHMM' 或含秒）为 tz-aware UTC。"""
    s = s.strip()
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            return dt.datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError(f"无法解析 Alpha Vantage 时间: {s}")


def normalize_av_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """把 Alpha Vantage feed 条目规范化为统一结构。"""
    ts_raw = item.get("time_published")
    published = parse_av_time(ts_raw).isoformat() if ts_raw else None
    tickers = [t.get("ticker") for t in item.get("ticker_sentiment", []) if t.get("ticker")]
    return {
        "title": item.get("title", ""),
        "summary": item.get("summary", ""),
        "url": item.get("url", ""),
        "published_at": published,
        "source": item.get("source", "Alpha Vantage"),
        "related_tickers": tickers,
        "sentiment": item.get("overall_sentiment_score"),
    }


def normalize_google_item(entry: Any) -> Dict[str, Any]:
    """把 Google News RSS 条目规范化为统一结构。"""
    published = None
    pp = getattr(entry, "published_parsed", None)
    if pp:
        published = dt.datetime(*pp[:6], tzinfo=UTC).isoformat()
    source = getattr(entry, "source", {})
    source_name = source.get("title", "Google News") if isinstance(source, dict) else "Google News"
    return {
        "title": getattr(entry, "title", ""),
        "summary": _strip_html(getattr(entry, "summary", "")),
        "url": getattr(entry, "link", ""),
        "published_at": published,
        "source": source_name,
        "related_tickers": [],
        "sentiment": None,
    }


def _title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def dedup(news: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按归一化标题去重（忽略大小写/标点）。"""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for n in news:
        k = _title_key(n.get("title", ""))
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(n)
    return out


def _to_dt(s: Optional[str]) -> Optional[dt.datetime]:
    if not s:
        return None
    return dt.datetime.fromisoformat(s)


def filter_window(news: List[Dict[str, Any]], hours: int) -> List[Dict[str, Any]]:
    """只保留最近 hours 小时内的新闻（无时间戳的保留，交由下游判断）。"""
    now = dt.datetime.now(UTC)
    cutoff = now - dt.timedelta(hours=hours)
    out = []
    for n in news:
        ts = _to_dt(n.get("published_at"))
        if ts is None or ts >= cutoff:
            out.append(n)
    return out


def enrich_relevance(news: List[Dict[str, Any]], symbols: List[str]) -> List[Dict[str, Any]]:
    """为每条新闻标注命中的 watchlist ticker（related_tickers 交集 + 标题/摘要关键词）。"""
    sym_set = set(symbols)
    for n in news:
        matched = set(n.get("related_tickers", [])) & sym_set
        text = (n.get("title", "") + " " + n.get("summary", "")).upper()
        for s in sym_set:
            if s in text:
                matched.add(s)
        n["matched_tickers"] = sorted(matched)
    return news


# ---------------------------------------------------------------------------
# 网络 I/O
# ---------------------------------------------------------------------------

def fetch_alpha_vantage(config: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    """调用 Alpha Vantage NEWS_SENTIMENT（topics 单次调用）。"""
    params = {
        "function": "NEWS_SENTIMENT",
        "topics": config["news"]["alpha_vantage_topics"],
        "limit": config["news"]["alpha_vantage_limit"],
        "apikey": key,
    }
    resp = requests.get("https://www.alphavantage.co/query", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "feed" not in data:
        log.warning("Alpha Vantage 返回异常(可能限流/额度不足): %s", list(data.keys()))
        return []
    return [normalize_av_item(it) for it in data["feed"]]


def fetch_google_news(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """抓取 Google News RSS（多个查询词）。"""
    items: List[Dict[str, Any]] = []
    for q in config["news"]["google_news_queries"]:
        url = f"https://news.google.com/rss/search?q={quote(q)}&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        for entry in feed.entries:
            items.append(normalize_google_item(entry))
    return items


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------

def fetch_news(config: Dict[str, Any], use_cache: bool = True) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """抓取新闻（主源 Alpha Vantage，兜底 Google News RSS）。

    返回 (news_list, source)。source 为 'alpha_vantage' / 'google_news' / 'cache' / None。
    全部源失败返回 ([], None)。
    """
    symbols = enabled_symbols(config)
    hours = config["thresholds"].get("news_window_hours")

    today = now_et().date().isoformat()
    cache_file = CACHE_DIR / f"news_{today}.json"

    if use_cache and cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8")), "cache"
        except Exception:  # noqa: BLE001
            pass

    news: List[Dict[str, Any]] = []
    source: Optional[str] = None

    key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if key:
        try:
            news = fetch_alpha_vantage(config, key)
            source = "alpha_vantage"
        except Exception as e:  # noqa: BLE001
            log.warning("Alpha Vantage 抓取失败: %s", e)

    if not news:
        try:
            news = fetch_google_news(config)
            source = "google_news"
        except Exception as e:  # noqa: BLE001
            log.warning("Google News 抓取失败: %s", e)

    if not news:
        log.warning("所有新闻源均失败")
        return [], None

    news = filter_window(news, hours)
    news = dedup(news)
    news = enrich_relevance(news, symbols)
    news.sort(key=lambda n: n.get("published_at") or "", reverse=True)

    if use_cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(news, ensure_ascii=False), encoding="utf-8")

    return news, source
