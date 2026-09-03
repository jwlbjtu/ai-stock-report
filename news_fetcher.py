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
_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


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


def parse_eastmoney_time(s: str) -> Optional[str]:
    """解析东方财富 'YYYY-MM-DD HH:MM:SS'（Asia/Shanghai）为 UTC ISO。"""
    if not s:
        return None
    try:
        naive = dt.datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    sh = pytz.timezone("Asia/Shanghai")
    return sh.localize(naive).astimezone(UTC).isoformat()


def normalize_eastmoney_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """把东方财富搜索结果条目规范化为统一结构。"""
    return {
        "title": item.get("title", ""),
        "summary": _strip_html(item.get("content", "")),
        "url": item.get("url", ""),
        "published_at": parse_eastmoney_time(item.get("date")),
        "source": item.get("mediaName", "东方财富"),
        "related_tickers": [],
        "sentiment": None,
    }


def _search_eastmoney(keyword: str, page_size: int, symbol: str) -> List[Dict[str, Any]]:
    """按关键词搜索东方财富资讯（JSONP），返回打上 symbol 标签的新闻列表。"""
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    param = json.dumps({
        "uid": "", "keyword": keyword, "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                                       "pageIndex": 1, "pageSize": page_size,
                                       "preTag": "", "postTag": ""}},
    })
    resp = requests.get(url, params={"cb": "cb", "param": param}, headers=_UA, timeout=15)
    resp.raise_for_status()
    text = resp.text
    start, end = text.find("("), text.rfind(")")
    if start == -1 or end == -1 or end <= start:
        log.warning("东方财富返回格式异常(疑似反爬): %s", text[:100])
        return []
    data = json.loads(text[start + 1:end])
    articles = (data.get("result") or {}).get("cmsArticleWebOld") or []
    out = []
    for a in articles:
        n = normalize_eastmoney_item(a)
        n["related_tickers"] = [symbol]
        out.append(n)
    return out


def fetch_eastmoney(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """抓取东方财富中文新闻：按 watchlist 中文名逐个搜索。"""
    chinese_names = config.get("chinese_names", {})
    em_cfg = (config.get("news", {}).get("eastmoney") or {})
    page_size = em_cfg.get("max_per_keyword", 5)
    items: List[Dict[str, Any]] = []
    for sym in enabled_symbols(config):
        kw = chinese_names.get(sym)
        if not kw:
            continue
        try:
            items.extend(_search_eastmoney(kw, page_size, sym))
        except Exception as e:  # noqa: BLE001
            log.warning("东方财富搜索失败(%s): %s", kw, e)
    return items


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------

def fetch_news(config: Dict[str, Any], use_cache: bool = True) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """抓取新闻：中文源东方财富 + 英文源 Alpha Vantage（兜底 Google News RSS）。

    返回 (news_list, source)。source 为以 '+' 连接的源名（如 'alpha_vantage+eastmoney'）或 'cache' / None。
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
    sources: List[str] = []

    # 中文源：东方财富（始终尝试，作为补充）
    if (config.get("news", {}).get("eastmoney") or {}).get("enabled", True):
        try:
            news.extend(fetch_eastmoney(config))
            sources.append("eastmoney")
        except Exception as e:  # noqa: BLE001
            log.warning("东方财富抓取失败: %s", e)

    # 英文主源：Alpha Vantage
    key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if key:
        try:
            news.extend(fetch_alpha_vantage(config, key))
            sources.append("alpha_vantage")
        except Exception as e:  # noqa: BLE001
            log.warning("Alpha Vantage 抓取失败: %s", e)

    # 英文兜底：Google News（仅当 Alpha Vantage 没拿到时）
    if "alpha_vantage" not in sources:
        try:
            news.extend(fetch_google_news(config))
            sources.append("google_news")
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

    return news, "+".join(sources)
