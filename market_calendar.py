"""交易日与美东时区判断。"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import pandas_market_calendars as mcal
import pytz

EASTERN = pytz.timezone("America/New_York")
_NYSE = mcal.get_calendar("NYSE")


def now_et() -> dt.datetime:
    """当前美东时间（tz-aware）。"""
    return dt.datetime.now(pytz.utc).astimezone(EASTERN)


def is_trading_day(date: Optional[dt.date] = None) -> bool:
    """判断给定日期（默认今天，按美东）是否 NYSE 交易日。

    仅判断"是否交易日"，不判断"是否已收盘"；收盘由 cron 调度到 17:30 ET 之后保证。
    """
    if date is None:
        date = now_et().date()
    schedule = _NYSE.schedule(start_date=date, end_date=date)
    return not schedule.empty


def previous_trading_day(date: Optional[dt.date] = None) -> dt.date:
    """返回给定日期（默认今天，按美东）之前最近一个交易日。"""
    if date is None:
        date = now_et().date()
    start = date - dt.timedelta(days=14)
    valid = _NYSE.valid_days(start_date=start, end_date=date - dt.timedelta(days=1))
    if len(valid) == 0:
        raise ValueError(f"在 {start} 到 {date} 之间未找到交易日")
    return valid[-1].date()
