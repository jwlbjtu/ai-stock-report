"""报告渲染：LLM 结果 + 量化结果 → 移动端优先的静态 HTML。"""
from __future__ import annotations

import html as _html
from typing import Any, Dict, Optional

_CSS = """
:root { --fg:#111; --muted:#666; --line:#e5e5e5; --accent:#2563eb; }
* { box-sizing: border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif; color:var(--fg); line-height:1.6; font-size:16px; background:#fff; }
.wrap { max-width:760px; margin:0 auto; padding:20px 16px 48px; }
h1 { font-size:22px; margin:0 0 4px; }
.date { color:var(--muted); font-size:14px; margin-bottom:16px; }
h2 { font-size:18px; margin:28px 0 10px; border-left:4px solid var(--accent); padding-left:10px; }
.tag { font-size:13px; color:var(--muted); font-weight:normal; margin-left:8px; }
.prose { margin:8px 0; }
.bench { display:inline-block; margin:0 8px 8px 0; padding:4px 10px; background:#f3f4f6; border-radius:6px; font-size:14px; }
.table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; margin:12px 0; border:1px solid var(--line); border-radius:8px; }
table { border-collapse:collapse; width:100%; font-size:14px; min-width:540px; }
th,td { border-bottom:1px solid var(--line); padding:8px 12px; text-align:left; }
th { color:var(--muted); font-weight:600; background:#fafafa; }
tr:last-child td { border-bottom:none; }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
.pos { color:#16a34a; } .neg { color:#dc2626; }
.risk { background:#fef2f2; border-radius:8px; padding:12px 14px; margin-top:24px; }
.footer { color:var(--muted); font-size:12px; margin-top:32px; border-top:1px solid var(--line); padding-top:12px; }
"""


def _fmt_pct(x: Optional[float]) -> str:
    if x is None:
        return "N/A"
    return f"{x:+.2f}%"


def _colored_pct(x: Optional[float]) -> str:
    if x is None:
        return "N/A"
    cls = "pos" if x >= 0 else "neg"
    return f"<span class='{cls}'>{x:+.2f}%</span>"


def _esc(s: Any) -> str:
    return _html.escape(str(s or ""))


def render_html(llm_result: Dict[str, Any], quant_result: Dict[str, Any]) -> str:
    date = quant_result["date"]
    summary = (llm_result or {}).get("summary", "")
    core = (llm_result or {}).get("core_conclusion", "")
    continuity = (llm_result or {}).get("continuity", "")
    risk = (llm_result or {}).get("risk", "")
    disclaimer = (llm_result or {}).get("disclaimer", "本报告由系统自动生成，仅供信息参考，不构成投资建议。")
    llm_sectors = {s.get("name"): s for s in (llm_result or {}).get("sectors", [])}

    bench = quant_result.get("benchmarks", {})
    bench_html = "".join(
        f"<span class='bench'>{_esc(k)} {_fmt_pct(v)}</span>" for k, v in bench.items() if v is not None
    )

    sectors_html = []
    for s in quant_result.get("sectors", []):
        name = s["name"]
        ls = llm_sectors.get(name, {})
        w = "市值加权" if s.get("weight_used") == "cap" else "等权"
        head = f"{w} {_fmt_pct(s.get('r_cap'))} ｜ 等权 {_fmt_pct(s.get('r_eq'))}"

        rows = []
        for st in s.get("stocks", []):
            rows.append(
                "<tr>"
                f"<td>{_esc(st.get('symbol', ''))}</td>"
                f"<td class='num'>{_colored_pct(st.get('change_pct'))}</td>"
                f"<td class='num'>{_fmt_pct(st.get('intraday_pct'))}</td>"
                f"<td class='num'>{_fmt_pct(st.get('gap_pct'))}</td>"
                f"<td>{_esc(st.get('shape', ''))}</td>"
                f"<td>{_esc(st.get('max_move_time') or '')}</td>"
                "</tr>"
            )
        table = (
            "<div class='table-wrap'><table><thead><tr>"
            "<th>代码</th><th>涨跌幅</th><th>日内</th><th>跳空</th><th>形态</th><th>最大异动</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
        )

        sectors_html.append(
            f"<section><h2>{_esc(name)}<span class='tag'>{_esc(head)}</span></h2>"
            f"<p class='prose'><b>资金广度：</b>{_esc(ls.get('eq_vs_cap', ''))}</p>"
            f"<p class='prose'><b>关联解读：</b>{_esc(ls.get('attribution', ''))}</p>"
            f"<p class='prose'><b>形态点评：</b>{_esc(ls.get('shape_comment', ''))}</p>"
            f"{table}</section>"
        )

    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        f"<title>美股科技/AI 复盘 · {_esc(date)}</title>"
        f"<style>{_CSS}</style></head><body><div class='wrap'>"
        f"<h1>美股科技/AI 复盘 · {_esc(date)}</h1>"
        f"<div class='date'>由 AI 自动生成 · {_esc(date)}</div>"
        + (f"<p class='prose'>{_esc(summary)}</p>" if summary else "")
        + (f"<p class='prose'>{_esc(core)}</p>" if core else "")
        + (f"<h2>基准</h2><div>{bench_html}</div>" if bench_html else "")
        + "".join(sectors_html)
        + (f"<h2>连续性复盘</h2><p class='prose'>{_esc(continuity)}</p>" if continuity else "")
        + (f"<div class='risk'><b>⚠️ 风险提示：</b>{_esc(risk)}</div>" if risk else "")
        + f"<div class='footer'>{_esc(disclaimer)}</div>"
        + "</div></body></html>"
    )
