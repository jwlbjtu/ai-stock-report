from notifier import build_digest, parse_recipients, split_text


def test_parse_recipients():
    assert parse_recipients("a,b , c") == ["a", "b", "c"]
    assert parse_recipients("") == []
    assert parse_recipients(None) == []
    assert parse_recipients("single") == ["single"]


def test_build_digest():
    quant = {
        "date": "2026-08-27",
        "sectors": [
            {
                "name": "AI 芯片",
                "r_cap": 2.0,
                "r_eq": 1.5,
                "weight_used": "cap",
                "stocks": [
                    {"symbol": "NVDA", "change_pct": 3.2},
                    {"symbol": "AMD", "change_pct": -0.5},
                ],
            }
        ],
        "benchmarks": {"QQQ": 0.8, "SOX": 1.2},
    }
    llm = {"summary": "今日科技股普涨"}
    d = build_digest(quant, llm, "https://example.com/r.html")
    assert "2026-08-27" in d
    assert "AI 芯片" in d
    assert "+2.00%" in d
    assert "NVDA" in d
    assert "AMD" in d
    assert "今日科技股普涨" in d
    assert "https://example.com/r.html" in d


def test_build_digest_without_llm_and_url():
    quant = {"date": "2026-08-27", "sectors": [], "benchmarks": {}}
    d = build_digest(quant, None, None)
    assert "2026-08-27" in d
    assert "完整报告" not in d


def test_split_text_short():
    assert split_text("hello", 100) == ["hello"]


def test_split_text_long():
    text = "\n".join(["para" + str(i) for i in range(100)])
    chunks = split_text(text, 50)
    assert len(chunks) > 1
    assert all(len(c) <= 50 for c in chunks)
    # 拼接回去内容一致（按 \n 重建）
    assert "\n".join(chunks) == text
