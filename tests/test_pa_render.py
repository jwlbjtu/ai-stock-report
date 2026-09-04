from pa_render import render_pa, render_pa_index, write_pa_index


def _make_pa():
    return {
        "date": "2026-09-03",
        "base_currency": "HKD",
        "fx": {"USD": 7.8, "EUR": 8.5},
        "total": {"value": 1000000.0, "cost": 900000.0, "pnl": 100000.0, "pnl_pct": 11.11},
        "by_currency": {
            "HKD": {"value": 891000.0, "cost": 872000.0, "pnl": 19000.0, "pnl_pct": 2.18},
            "USD": {"value": 197000.0, "cost": 188000.0, "pnl": 9000.0, "pnl_pct": 4.79},
        },
        "positions": [
            {"symbol": "2899.HK", "name": "紫金矿业", "currency": "HKD", "quantity": 16000,
             "cost_price": 30.95, "close": 35.8, "change_pct": 1.2,
             "value": 572800.0, "cost": 495200.0, "pnl": 77600.0, "pnl_pct": 15.67,
             "value_base": 572800.0, "cost_base": 495200.0, "pnl_base": 77600.0,
             "price_vs_ma20": 3.2, "pct_from_52w_high": -8.1},
        ],
        "warnings": [],
    }


def test_render_pa_contains_key_elements():
    html = render_pa(_make_pa())
    assert "个人持仓复盘" in html
    assert "2899.HK" in html
    assert "紫金矿业" in html
    assert "总市值" in html
    assert "HK$" in html
    assert "分币种汇总" in html


def test_render_pa_escapes_html():
    pa = _make_pa()
    pa["positions"][0]["name"] = "<script>alert(1)</script>"
    html = render_pa(pa)
    assert "<script>" not in html


def test_render_pa_with_warnings():
    pa = _make_pa()
    pa["warnings"] = ["XXX: 数据不足，已跳过"]
    html = render_pa(pa)
    assert "数据不足" in html


def test_render_pa_index_and_write(tmp_path):
    assert "2026-09-03" in render_pa_index(["2026-09-03", "2026-09-02"])
    assert "暂无报告" in render_pa_index([])
    p = write_pa_index(str(tmp_path))
    assert (tmp_path / "index.html").exists()
    (tmp_path / "2026-09-03.html").write_text("x", encoding="utf-8")
    write_pa_index(str(tmp_path))
    assert "2026-09-03" in (tmp_path / "index.html").read_text(encoding="utf-8")
