"""报告渲染：LLM 结果 + 量化结果 → 移动端优先的静态 HTML。"""
from __future__ import annotations

import html as _html
from pathlib import Path
from typing import Any, Dict, List, Optional

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
table { border-collapse:collapse; width:100%; font-size:14px; min-width:640px; }
th,td { border-bottom:1px solid var(--line); padding:8px 12px; text-align:left; }
th { color:var(--muted); font-weight:600; background:#fafafa; }
tr:last-child td { border-bottom:none; }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
.pos { color:#16a34a; } .neg { color:#dc2626; }
.risk { background:#fef2f2; border-radius:8px; padding:12px 14px; margin-top:24px; }
.footer { color:var(--muted); font-size:12px; margin-top:32px; border-top:1px solid var(--line); padding-top:12px; }
.heatmap { display:grid; grid-template-columns:repeat(auto-fill, minmax(86px,1fr)); gap:6px; margin:12px 0; }
.tile { border-radius:8px; padding:8px 6px; text-align:center; }
.t-sym { font-weight:600; font-size:13px; }
.t-pct { font-size:12px; }
.spark { width:70px; height:24px; vertical-align:middle; }
.spark-cell { width:74px; }
.sym { font-weight:600; }
.trend { font-size:11px; color:var(--muted); white-space:nowrap; }
.muted { font-size:12px; color:var(--muted); }
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


def _sparkline(closes: Optional[List[float]], up: bool) -> str:
    if not closes or len(closes) < 2:
        return ""
    mn, mx = min(closes), max(closes)
    if mx == mn:
        pts = ["0,15", "100,15"]
    else:
        n = len(closes)
        pts = [
            f"{i / (n - 1) * 100:.1f},{30 - (v - mn) / (mx - mn) * 30:.1f}"
            for i, v in enumerate(closes)
        ]
    color = "#16a34a" if up else "#dc2626"
    return (
        f"<svg class='spark' viewBox='0 0 100 30' preserveAspectRatio='none'>"
        f"<polyline fill='none' stroke='{color}' stroke-width='1.5' points='{' '.join(pts)}'/></svg>"
    )


def _heat_style(change: Optional[float]) -> str:
    if change is None:
        return "background:#e5e5e5;color:#666;"
    mag = min(abs(change) / 5.0, 1.0)
    if change >= 0:
        bg = f"rgba(22,163,74,{0.15 + 0.7 * mag:.3f})"
        fg = "#fff" if mag > 0.4 else "#14532d"
    else:
        bg = f"rgba(220,38,38,{0.15 + 0.7 * mag:.3f})"
        fg = "#fff" if mag > 0.4 else "#7f1d1d"
    return f"background:{bg};color:{fg};"


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

    all_stocks = []
    for s in quant_result.get("sectors", []):
        all_stocks.extend(s.get("stocks", []))
    all_stocks.sort(key=lambda x: x.get("change_pct") if x.get("change_pct") is not None else -1e9, reverse=True)
    heatmap_html = "".join(
        f"<div class='tile' style='{_heat_style(st.get('change_pct'))}'>"
        f"<div class='t-sym'>{_esc(st.get('symbol', ''))}</div>"
        f"<div class='t-pct'>{_fmt_pct(st.get('change_pct'))}</div></div>"
        for st in all_stocks
    )

    sectors_html = []
    for s in quant_result.get("sectors", []):
        name = s["name"]
        ls = llm_sectors.get(name, {})
        w = "市值加权" if s.get("weight_used") == "cap" else "等权"
        head = f"{w} {_fmt_pct(s.get('r_cap'))} ｜ 等权 {_fmt_pct(s.get('r_eq'))}"

        rows = []
        for st in s.get("stocks", []):
            chg = st.get("change_pct")
            spark = _sparkline(st.get("intraday_closes"), chg is not None and chg >= 0)

            rv = st.get("rel_volume")
            vol_cell = "—" if rv is None else f"{rv:.2f}x"

            move_cell = _esc(st.get("max_move_time") or "")
            mvr = st.get("max_move_volume_ratio")
            if mvr is not None and mvr >= 1.5:
                move_cell += f" <span class='muted'>放量{mvr:.1f}x</span>"

            trend_parts = []
            pv20 = st.get("price_vs_ma20")
            if pv20 is not None:
                trend_parts.append(f"20日{'上' if pv20 >= 0 else '下'}{abs(pv20):.1f}%")
            ph = st.get("pct_from_52w_high")
            if ph is not None:
                trend_parts.append(f"距高{ph:.1f}%")
            sym_cell = f"<div class='sym'>{_esc(st.get('symbol', ''))}</div>"
            if trend_parts:
                sym_cell += f"<div class='trend'>{_esc(' · '.join(trend_parts))}</div>"

            rows.append(
                "<tr>"
                f"<td>{sym_cell}</td>"
                f"<td class='spark-cell'>{spark}</td>"
                f"<td class='num'>{_colored_pct(chg)}</td>"
                f"<td class='num'>{_fmt_pct(st.get('intraday_pct'))}</td>"
                f"<td class='num'>{_fmt_pct(st.get('gap_pct'))}</td>"
                f"<td>{_esc(st.get('shape', ''))}</td>"
                f"<td class='num'>{vol_cell}</td>"
                f"<td>{move_cell}</td>"
                "</tr>"
            )
        table = (
            "<div class='table-wrap'><table><thead><tr>"
            "<th>代码</th><th>走势</th><th>涨跌幅</th><th>日内</th><th>跳空</th><th>形态</th><th>量能</th><th>最大异动</th>"
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
        + (f"<h2>市场全景</h2><div class='heatmap'>{heatmap_html}</div>" if heatmap_html else "")
        + (f"<h2>基准</h2><div>{bench_html}</div>" if bench_html else "")
        + "".join(sectors_html)
        + (f"<h2>连续性复盘</h2><p class='prose'>{_esc(continuity)}</p>" if continuity else "")
        + (f"<div class='risk'><b>⚠️ 风险提示：</b>{_esc(risk)}</div>" if risk else "")
        + f"<div class='footer'>{_esc(disclaimer)}</div>"
        + "</div></body></html>"
    )


_INDEX_CSS = """
* { box-sizing: border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif; color:#111; line-height:1.6; font-size:16px; background:#fff; }
.wrap { max-width:760px; margin:0 auto; padding:24px 16px 48px; }
h1 { font-size:20px; margin:0 0 16px; }
ul { list-style:none; padding:0; margin:0; }
li { margin:0 0 8px; }
a { display:block; padding:12px 14px; background:#f8fafc; border:1px solid #e5e5e5; border-radius:8px; color:#2563eb; text-decoration:none; }
a:hover { background:#eff6ff; }
"""


def render_index(dates: List[str]) -> str:
    """生成报告列表 HTML（日期倒序）。dates 为 'YYYY-MM-DD' 字符串列表。"""
    if not dates:
        items = "<li>暂无报告</li>"
    else:
        items = "".join(f"<li><a href='{_esc(d)}.html'>📄 {_esc(d)}</a></li>" for d in dates)
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        "<title>美股科技/AI 复盘报告列表</title>"
        f"<style>{_INDEX_CSS}</style></head><body><div class='wrap'>"
        "<h1>📊 美股科技/AI 复盘报告列表</h1>"
        f"<ul>{items}</ul>"
        "</div></body></html>"
    )


def write_index(output_dir: str) -> str:
    """扫描 output_dir 下的 *.html（不含 index 自身），写 index.html。返回路径。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    dates = sorted((f.stem for f in out.glob("*.html") if f.stem != "index"), reverse=True)
    path = out / "index.html"
    path.write_text(render_index(dates), encoding="utf-8")
    return str(path)
