from render import render_html


def test_render_html_contains_data():
    llm = {
        "summary": "今日科技股普涨",
        "core_conclusion": "整体强势",
        "continuity": "延续",
        "risk": "注意回调",
        "disclaimer": "不构成投资建议",
        "sectors": [
            {"name": "AI 芯片", "eq_vs_cap": "龙头抱团", "attribution": "或与芯片消息相关", "shape_comment": "单边上涨"}
        ],
    }
    quant = {
        "date": "2026-08-27",
        "sectors": [
            {
                "name": "AI 芯片",
                "r_cap": 2.0,
                "r_eq": 1.5,
                "weight_used": "cap",
                "stocks": [
                    {"symbol": "NVDA", "change_pct": 3.2, "intraday_pct": 1.0, "gap_pct": 2.0,
                     "shape": "单边上涨", "max_move_time": "10:00 ET"}
                ],
            }
        ],
        "benchmarks": {"QQQ": 0.8},
    }
    html = render_html(llm, quant)
    assert "2026-08-27" in html
    assert "AI 芯片" in html
    assert "NVDA" in html
    assert "+3.20%" in html
    assert "龙头抱团" in html
    assert "不构成投资建议" in html
    assert "viewport" in html  # 移动端
    assert "overflow-x:auto" in html  # 表格横向滚动


def test_render_html_escapes_special_chars():
    llm = {"summary": "含 <script> 标签", "sectors": []}
    quant = {"date": "2026-08-27", "sectors": [], "benchmarks": {}}
    html = render_html(llm, quant)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
