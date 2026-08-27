import datetime as dt

from market_calendar import is_trading_day, previous_trading_day


def test_weekend_is_not_trading_day():
    sat = dt.date(2026, 7, 25)
    assert sat.weekday() == 5
    assert is_trading_day(sat) is False

    sun = dt.date(2026, 7, 26)
    assert sun.weekday() == 6
    assert is_trading_day(sun) is False


def test_weekday_is_trading_day():
    fri = dt.date(2026, 7, 24)
    assert fri.weekday() == 4
    assert is_trading_day(fri) is True


def test_holiday_is_not_trading_day():
    xmas = dt.date(2025, 12, 25)  # 周四，圣诞
    assert is_trading_day(xmas) is False


def test_previous_trading_day_skips_weekend():
    mon = dt.date(2026, 7, 27)
    assert mon.weekday() == 0
    assert previous_trading_day(mon) == dt.date(2026, 7, 24)
