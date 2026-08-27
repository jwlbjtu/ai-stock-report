from llm_analyzer import (
    align_news_to_move,
    build_aligned_news,
    build_user_prompt,
    get_yesterday_summary,
    load_summaries,
    parse_json_response,
    save_summary,
)


def test_parse_json_response_plain():
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_json_response_with_fence():
    assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_response_with_extra_text():
    assert parse_json_response('结果如下：{"a": 1} 谢谢') == {"a": 1}


def test_align_news_to_move():
    move = "2026-08-27T14:00:00+00:00"
    news = [
        {"published_at": "2026-08-27T14:30:00+00:00"},  # 30min 内
        {"published_at": "2026-08-27T15:30:00+00:00"},  # 90min 外
        {"published_at": None},
    ]
    out = align_news_to_move(move, news, 60)
    assert len(out) == 1
    assert out[0]["published_at"] == "2026-08-27T14:30:00+00:00"


def test_build_aligned_news_picks_largest_move():
    quant = {
        "sectors": [
            {
                "name": "S1",
                "stocks": [
                    {"symbol": "A", "max_move_time_iso": "2026-08-27T14:00:00+00:00", "max_move_val": -2.0},
                    {"symbol": "B", "max_move_time_iso": "2026-08-27T10:00:00+00:00", "max_move_val": 1.0},
                ],
            }
        ]
    }
    news = [{"published_at": "2026-08-27T14:30:00+00:00", "title": "x"}]
    aligned = build_aligned_news(quant, news, 60)
    assert aligned["S1"][0]["title"] == "x"


def test_memory_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    save_summary("2026-08-26", "总结A", path=p)
    save_summary("2026-08-27", "总结B", path=p)
    assert load_summaries(path=p) == {"2026-08-26": "总结A", "2026-08-27": "总结B"}


def test_get_yesterday_summary(tmp_path):
    p = tmp_path / "s.json"
    save_summary("2026-08-26", "昨日总结", path=p)
    assert get_yesterday_summary("2026-08-27", path=p) == "昨日总结"


def test_build_user_prompt_includes_context():
    quant = {"date": "2026-08-27", "sectors": [], "benchmarks": {}, "warnings": []}
    prompt = build_user_prompt(quant, [], {}, "昨日总结")
    assert "2026-08-27" in prompt
    assert "昨日总结" in prompt
    assert "新闻获取失败" in prompt


def test_build_user_prompt_with_news():
    quant = {"date": "2026-08-27", "sectors": [], "benchmarks": {}, "warnings": []}
    news = [{
        "title": "AI rally",
        "summary": "x" * 200,
        "published_at": "2026-08-27T14:00:00+00:00",
        "source": "Reuters",
        "matched_tickers": ["NVDA"],
        "sentiment": 0.2,
    }]
    prompt = build_user_prompt(quant, news, {}, None)
    assert "AI rally" in prompt
    assert "NVDA" in prompt
