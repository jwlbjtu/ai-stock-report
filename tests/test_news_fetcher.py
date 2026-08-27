import datetime as dt

import feedparser
import pytz

from news_fetcher import (
    _strip_html,
    dedup,
    enrich_relevance,
    filter_window,
    normalize_av_item,
    normalize_google_item,
    parse_av_time,
)

UTC = pytz.utc


def test_strip_html():
    assert _strip_html("<p>Hello &amp; world</p>") == "Hello & world"
    assert _strip_html("  <b>Tech</b> &amp; <i>AI</i>  ") == "Tech & AI"
    assert _strip_html("") == ""


def test_parse_av_time_with_seconds():
    assert parse_av_time("20260827T140000") == dt.datetime(2026, 8, 27, 14, 0, 0, tzinfo=UTC)


def test_parse_av_time_without_seconds():
    assert parse_av_time("20260827T1400") == dt.datetime(2026, 8, 27, 14, 0, 0, tzinfo=UTC)


def test_normalize_av_item():
    item = {
        "title": "NVDA rally",
        "summary": "Chip stocks up",
        "url": "http://example.com/1",
        "time_published": "20260827T140000",
        "source": "Reuters",
        "overall_sentiment_score": 0.25,
        "ticker_sentiment": [
            {"ticker": "NVDA", "relevance_score": "0.9", "ticker_sentiment_score": "0.3"}
        ],
    }
    n = normalize_av_item(item)
    assert n["title"] == "NVDA rally"
    assert n["published_at"] == "2026-08-27T14:00:00+00:00"
    assert n["related_tickers"] == ["NVDA"]
    assert n["sentiment"] == 0.25
    assert n["source"] == "Reuters"


def test_normalize_google_item():
    rss = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test</title>
<item><title>AI stocks surge</title><link>http://example.com/1</link>
<description>&lt;p&gt;Tech &amp;amp; AI &lt;b&gt;rally&lt;/b&gt;&lt;/p&gt;</description>
<pubDate>Wed, 27 Aug 2026 14:00:00 GMT</pubDate></item>
</channel></rss>"""
    entry = feedparser.parse(rss).entries[0]
    n = normalize_google_item(entry)
    assert n["title"] == "AI stocks surge"
    assert "<" not in n["summary"] and "&amp;" not in n["summary"]
    assert n["published_at"] is not None
    assert n["related_tickers"] == []
    assert n["sentiment"] is None


def test_dedup():
    news = [
        {"title": "AI stocks surge!"},
        {"title": "ai stocks surge"},
        {"title": "different news"},
    ]
    out = dedup(news)
    assert len(out) == 2


def test_filter_window():
    now = dt.datetime.now(UTC)
    recent = (now - dt.timedelta(hours=1)).isoformat()
    old = (now - dt.timedelta(hours=48)).isoformat()
    news = [
        {"published_at": recent},
        {"published_at": old},
        {"published_at": None},
    ]
    out = filter_window(news, 24)
    assert len(out) == 2  # recent + None 保留，old 剔除


def test_enrich_relevance():
    news = [
        {"title": "Nvidia", "summary": "", "related_tickers": ["NVDA"]},
        {"title": "AAPL beats estimates", "summary": "", "related_tickers": []},
        {"title": "unrelated", "summary": "", "related_tickers": ["TSLA"]},
    ]
    out = enrich_relevance(news, ["NVDA", "AAPL"])
    assert out[0]["matched_tickers"] == ["NVDA"]
    assert out[1]["matched_tickers"] == ["AAPL"]
    assert out[2]["matched_tickers"] == []
