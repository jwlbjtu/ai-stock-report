import datetime as dt

import pandas as pd

from quant_engine import (
    classify_shape,
    compute_cap_weight,
    compute_equal_weight,
    compute_metrics,
    compute_trend,
    parse_download,
)

ET = "America/New_York"
THR = {
    "split_guard_pct": 50.0,
    "shape_gap_threshold_pct": 0.5,
    "shape_intraday_threshold_pct": 0.5,
}


def _make_df() -> pd.DataFrame:
    """构造两日 5m 合成数据：前一日收 103，今日开 105 收 102（高开低走）。"""
    times = [
        dt.datetime(2026, 7, 23, 9, 30), dt.datetime(2026, 7, 23, 9, 35),
        dt.datetime(2026, 7, 23, 9, 40), dt.datetime(2026, 7, 23, 9, 45),
        dt.datetime(2026, 7, 24, 9, 30), dt.datetime(2026, 7, 24, 9, 35),
        dt.datetime(2026, 7, 24, 9, 40), dt.datetime(2026, 7, 24, 9, 45),
    ]
    idx = pd.DatetimeIndex(times, tz=ET)
    cols = pd.MultiIndex.from_product(
        [["AAPL"], ["Open", "High", "Low", "Close", "Adj Close", "Volume"]]
    )
    df = pd.DataFrame(index=idx, columns=cols, dtype=float)
    close = [100.0, 101.0, 102.0, 103.0, 105.0, 104.0, 103.0, 102.0]
    open_ = [99.5, 100.5, 101.5, 102.5, 105.0, 104.5, 103.5, 102.5]
    df[("AAPL", "Close")] = close
    df[("AAPL", "Open")] = open_
    df[("AAPL", "High")] = [c + 1 for c in close]
    df[("AAPL", "Low")] = [o - 1 for o in open_]
    df[("AAPL", "Adj Close")] = close
    df[("AAPL", "Volume")] = 1000
    return df


def test_parse_download_extracts_today_and_backup_prev_close():
    today, backup = parse_download(_make_df(), "AAPL")
    assert backup == 103.0
    assert len(today) == 4
    assert today["Open"].iloc[0] == 105.0
    assert today["Close"].iloc[-1] == 102.0


def test_parse_download_missing_symbol():
    today, backup = parse_download(_make_df(), "ZZZZ")
    assert today is None and backup is None


def test_compute_metrics_gaokaizou():
    today, backup = parse_download(_make_df(), "AAPL")
    m = compute_metrics(today, backup, THR)
    assert m is not None
    assert m["change_pct"] == round((102.0 - 103.0) / 103.0 * 100, 2)
    assert m["intraday_pct"] == round((102.0 - 105.0) / 105.0 * 100, 2)
    assert m["gap_pct"] == round((105.0 - 103.0) / 103.0 * 100, 2)
    assert m["shape"] == "高开低走"
    assert m["max_move_val"] == round((102.0 - 105.0) / 105.0 * 100, 2)
    assert m["max_move_time"] == "09:45 ET"
    assert m["max_move_time_iso"].startswith("2026-07-24T09:45")
    assert m["split_guard"] is False


def test_compute_metrics_returns_none_for_missing_data():
    assert compute_metrics(pd.DataFrame(), 100.0, THR) is None
    assert compute_metrics(None, 100.0, THR) is None
    today, _ = parse_download(_make_df(), "AAPL")
    assert compute_metrics(today, None, THR) is None


def test_classify_shape():
    assert classify_shape(1.0, -1.0, 0.5, 0.5) == "高开低走"
    assert classify_shape(-1.0, 1.0, 0.5, 0.5) == "低开高走"
    assert classify_shape(0.1, 1.0, 0.5, 0.5) == "单边上涨"
    assert classify_shape(0.1, -1.0, 0.5, 0.5) == "单边下跌"
    assert classify_shape(0.1, 0.1, 0.5, 0.5) == "震荡"


def test_equal_weight():
    assert compute_equal_weight([1.0, 2.0, 3.0]) == 2.0
    assert compute_equal_weight([1.0, None, 3.0]) == 2.0
    assert compute_equal_weight([None, None]) is None


def test_cap_weight():
    r, cov, covered, total = compute_cap_weight([1.0, 2.0, 3.0], [100.0, 200.0, None])
    assert r == round((1.0 * 100 + 2.0 * 200) / 300.0, 2)
    assert covered == 2
    assert total == 3
    assert cov == round(2 / 3, 4)


def test_cap_weight_all_missing():
    r, cov, covered, total = compute_cap_weight([1.0, 2.0], [None, None])
    assert r is None
    assert cov == 0.0
    assert covered == 0


def _make_daily() -> pd.DataFrame:
    n = 60
    dates = pd.date_range("2026-01-01", periods=n, freq="B", tz=ET)
    close = [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {
            "Open": [c - 0.5 for c in close],
            "High": [c + 1 for c in close],
            "Low": [c - 1 for c in close],
            "Close": close,
            "Volume": [1000] * n,
        },
        index=dates,
    )


def test_compute_trend():
    daily = _make_daily()
    t = compute_trend(daily)
    closes = daily["Close"]
    last = float(closes.iloc[-1])
    assert t["ma20"] == round(closes.iloc[-20:].mean(), 2)
    assert t["ma50"] == round(closes.iloc[-50:].mean(), 2)
    assert t["rel_volume"] == 1.0
    hi = float(daily["High"].max())
    assert t["pct_from_52w_high"] == round((last - hi) / hi * 100, 2)
    assert t["price_vs_ma20"] == round((last - t["ma20"]) / t["ma20"] * 100, 2)


def test_compute_trend_short_data():
    daily = pd.DataFrame({
        "Close": [1.0, 2.0, 3.0], "High": [1.0, 2.0, 3.0],
        "Low": [1.0, 2.0, 3.0], "Volume": [10, 10, 10],
    })
    t = compute_trend(daily)
    assert "ma20" not in t
    assert "ma50" not in t
    assert "rel_volume" not in t


def test_compute_metrics_new_fields():
    today, backup = parse_download(_make_df(), "AAPL")
    m = compute_metrics(today, backup, THR)
    assert m["intraday_closes"] == [105.0, 104.0, 103.0, 102.0]
    assert m["max_move_volume_ratio"] == 1.0
