"""生成示例报告 + index.html（真实渲染代码 + 模拟数据），用于预览报告样式。

用法（在项目根目录执行）：
    python3 scripts/generate_sample.py
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config
from quant_engine import classify_shape, compute_cap_weight, compute_equal_weight
from render import render_html, write_index


def make_quant(cfg, date_str, rng):
    sectors = []
    for sec in cfg["sub_sectors"]:
        stocks = []
        changes = []
        caps = []
        for t in sec["tickers"]:
            sym = t["symbol"]
            change = round(rng.uniform(-4.5, 5.5), 2)
            gap = round(rng.uniform(-2.2, 2.2), 2)
            intraday = round(change - gap, 2)
            shape = classify_shape(
                gap, intraday,
                cfg["thresholds"]["shape_gap_threshold_pct"],
                cfg["thresholds"]["shape_intraday_threshold_pct"],
            )
            hh = rng.randint(9, 15)
            mm = rng.choice([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])
            stocks.append({
                "symbol": sym,
                "open": round(rng.uniform(40, 500), 2),
                "close": round(rng.uniform(40, 500), 2),
                "change_pct": change,
                "intraday_pct": intraday,
                "gap_pct": gap,
                "max_move_time": f"{hh:02d}:{mm:02d} ET",
                "max_move_time_iso": f"{date_str}T{hh:02d}:{mm:02d}:00-04:00",
                "max_move_val": round(rng.uniform(-3, 3), 2),
                "shape": shape,
                "split_guard": False,
            })
            changes.append(change)
            caps.append(rng.uniform(30e9, 3000e9))
        stocks.sort(key=lambda x: x["change_pct"], reverse=True)
        r_eq = compute_equal_weight(changes)
        r_cap, coverage, _, _ = compute_cap_weight(changes, caps)
        sectors.append({
            "name": sec["name"], "r_eq": r_eq, "r_cap": r_cap,
            "weight_used": "cap", "cap_coverage": round(coverage, 2), "stocks": stocks,
        })
    sectors.sort(key=lambda s: (s["r_cap"] is None, -(s["r_cap"] or 0)))
    return {
        "date": date_str,
        "sectors": sectors,
        "benchmarks": {"QQQ": round(rng.uniform(-1, 2), 2), "SOX": round(rng.uniform(-1.5, 3), 2)},
        "warnings": [],
    }


def make_llm(quant):
    sec_prose = []
    for s in quant["sectors"]:
        top = s["stocks"][0]
        bottom = s["stocks"][-1]
        verdict = "权重龙头贡献更大，资金偏抱团" if s["r_cap"] > s["r_eq"] else "中小盘更活跃，资金偏扩散"
        sec_prose.append({
            "name": s["name"],
            "eq_vs_cap": f"市值加权 {s['r_cap']}% 与等权 {s['r_eq']}% 存在差异，{verdict}。",
            "attribution": f"领涨股 {top['symbol']} 日内最大异动出现在 {top['max_move_time']}，或与科技/AI 相关消息有关联（仅为关联性解读，非因果归因）。",
            "shape_comment": f"{top['symbol']} 呈 {top['shape']}，{bottom['symbol']} 呈 {bottom['shape']}，板块内部分化。",
        })
    up = quant["benchmarks"]["QQQ"] > 0
    return {
        "summary": f"科技/AI 板块今日整体{'上涨' if up else '回调'}，芯片板块领涨，资金向龙头集中。",
        "core_conclusion": "今日美股科技/AI 板块延续近期趋势，芯片与半导体表现最强，云计算温和上行，软件与消费电子分化。整体情绪偏积极，但需关注龙头短期涨幅过大的回调风险。",
        "sectors": sec_prose,
        "continuity": "延续近期 AI 硬件主线，资金偏好未发生明显切换。",
        "risk": "警惕龙头短期涨幅过大后的回调，以及消息面情绪反转。",
        "disclaimer": "本报告由系统自动生成，仅供信息参考，不构成投资建议。",
    }


def main():
    rng = random.Random(20260827)
    cfg = load_config()
    out = Path("report")
    out.mkdir(exist_ok=True)
    for d in ["2026-08-25", "2026-08-26", "2026-08-27"]:
        q = make_quant(cfg, d, rng)
        l = make_llm(q)
        (out / f"{d}.html").write_text(render_html(l, q), encoding="utf-8")
        print(f"已生成 report/{d}.html")
    print("已生成", write_index("report"))


if __name__ == "__main__":
    main()
