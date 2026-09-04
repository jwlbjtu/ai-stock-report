"""PA 持仓报告渲染：移动端优先静态 HTML。"""
from __future__ import annotations

import html as _html
from pathlib import Path
from typing import Any, Dict, List, Optional

_CURRENCY_SYMBOL = {"HKD": "HK$", "USD": "US$", "EUR": "€", "GBP": "£", "CNY": "¥", "JPY": "¥"}

_CSS = """
:root { --fg:#111; --muted:#666; --line:#e5e5e5; --accent:#2563eb; }
* { box-sizing: border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif; color:var(--fg); line-height:1.6; font-size:16px; background:#fff; }
.wrap { max-width:760px; margin:0 auto; padding:20px 16px 48px; }
h1 { font-size:22px; margin:0 0 4px; }
.date { color:var(--muted); font-size:14px; margin-bottom:16px; }
h2 { font-size:18px; margin:26px 0 10px; border-left:4px solid var(--accent); padding-left:10px; }
.tag { font-size:13px; color:var(--muted); font-weight:normal; margin-left:8px; }
.table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; margin:12px 0; border:1px solid var(--line); border-radius:8px; }
table { border-collapse:collapse; width:100%; font-size:14px; min-width:720px; }
th,td { border-bottom:1px solid var(--line); padding:8px 10px; text-align:left; }
th { color:var(--muted); font-weight:600; background:#fafafa; }
tr:last-child td { border-bottom:none; }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
.pos { color:#16a34a; } .neg { color:#dc2626; }
.sym { font-weight:600; } .nm { font-size:12px; color:var(--muted); }
.total-card { background:#f8fafc; border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin:12px 0; }
.total-card .big { font-size:24px; font-weight:700; }
.note { background:#f0f7ff; border:1px solid #bfdbfe; border-radius:8px; padding:10px 14px; margin:14px 0; font-size:13px; color:#1e40af; }
.footer { color:var(--muted); font-size:12px; margin-top:32px; border-top:1px solid var(--line); padding-top:12px; }
"""


def _cur(ccy: str) -> str:
    return _CURRENCY_SYMBOL.get(ccy, ccy + " ")


def _esc(s: Any) -> str:
    return _html.escape(str(s or ""))


def _fmt_num(x: Optional[float], sign: bool = False) -> str:
    if x is None:
        return "—"
    s = f"{x:,.2f}"
    if sign and x > 0:
        s = "+" + s
    return s


def _fmt_pct(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return f"{x:+.2f}%"


def _cls(x: Optional[float]) -> str:
    return "pos" if (x or 0) >= 0 else "neg"


def _trend_cell(st: Dict[str, Any]) -> str:
    parts = []
    pv20 = st.get("price_vs_ma20")
    if pv20 is not None:
        parts.append(f"20日{'上' if pv20 >= 0 else '下'}{abs(pv20):.1f}%")
    ph = st.get("pct_from_52w_high")
    if ph is not None:
        parts.append(f"距高{ph:.1f}%")
    return _esc(" · ".join(parts)) if parts else "—"


def render_pa(pa: Dict[str, Any]) -> str:
    date = pa["date"]
    base = pa.get("base_currency", "HKD")
    base_sym = _cur(base)
    total = pa.get("total", {})
    fx = pa.get("fx", {})
    warnings = pa.get("warnings", [])

    # 总览卡片
    total_card = (
        "<div class='total-card'>"
        f"<div>总市值（折{_esc(base)}）</div>"
        f"<div class='big {_cls(total.get('pnl'))}'>{base_sym}{_fmt_num(total.get('value'))}</div>"
        f"<div>总成本 {base_sym}{_fmt_num(total.get('cost'))} ｜ "
        f"浮动盈亏 <span class='{_cls(total.get('pnl'))}'>{base_sym}{_fmt_num(total.get('pnl'), sign=True)} "
        f"（{_fmt_pct(total.get('pnl_pct'))}）</span></div>"
        "</div>"
    )

    # 分币种汇总
    ccys = pa.get("by_currency", {})
    summary_rows = "".join(
        "<tr>"
        f"<td><b>{_esc(ccy)}</b></td>"
        f"<td class='num'>{_cur(ccy)}{_fmt_num(c.get('cost'))}</td>"
        f"<td class='num'>{_cur(ccy)}{_fmt_num(c.get('value'))}</td>"
        f"<td class='num {_cls(c.get('pnl'))}'>{_cur(ccy)}{_fmt_num(c.get('pnl'), sign=True)}</td>"
        f"<td class='num {_cls(c.get('pnl'))}'>{_fmt_pct(c.get('pnl_pct'))}</td>"
        "</tr>"
        for ccy, c in ccys.items()
    )
    summary_table = (
        "<div class='table-wrap'><table><thead><tr>"
        "<th>币种</th><th>成本</th><th>市值</th><th>浮动盈亏</th><th>盈亏%</th>"
        "</tr></thead><tbody>" + summary_rows + "</tbody></table></div>"
    )

    # 明细（按币种分组，币种内按本币市值降序）
    order = ["HKD", "USD", "EUR", "GBP", "CNY", "JPY"]
    pos_by_ccy: Dict[str, List[Dict[str, Any]]] = {}
    for p in pa.get("positions", []):
        pos_by_ccy.setdefault(p["currency"], []).append(p)

    detail_blocks = []
    for ccy in order:
        rows = sorted(pos_by_ccy.get(ccy, []), key=lambda x: -x.get("value", 0))
        if not rows:
            continue
        tot_val = sum(r["value"] for r in rows)
        trs = []
        for r in rows:
            w = r["value"] / tot_val * 100 if tot_val else 0.0
            sym_cell = f"<div class='sym'>{_esc(r['symbol'])}</div><div class='nm'>{_esc(r.get('name',''))}</div>"
            trs.append(
                "<tr>"
                f"<td>{sym_cell}</td>"
                f"<td class='num'>{r['quantity']:g}</td>"
                f"<td class='num'>{_fmt_num(r['cost_price'])}</td>"
                f"<td class='num'>{_fmt_num(r['close'])}</td>"
                f"<td class='num {_cls(r.get('change_pct'))}'>{_fmt_pct(r.get('change_pct'))}</td>"
                f"<td class='num'>{_cur(ccy)}{_fmt_num(r['value'])}</td>"
                f"<td class='num {_cls(r.get('pnl'))}'>{_cur(ccy)}{_fmt_num(r['pnl'], sign=True)}</td>"
                f"<td class='num {_cls(r.get('pnl'))}'>{_fmt_pct(r.get('pnl_pct'))}</td>"
                f"<td class='num'>{w:.1f}%</td>"
                f"<td>{_trend_cell(r)}</td>"
                "</tr>"
            )
        detail_blocks.append(
            f"<h2>{_esc(ccy)}<span class='tag'>市值 {_cur(ccy)}{_fmt_num(tot_val)}</span></h2>"
            "<div class='table-wrap'><table><thead><tr>"
            "<th>代码</th><th>数量</th><th>成本价</th><th>现价</th><th>今日</th><th>市值</th><th>盈亏</th><th>盈亏%</th><th>权重</th><th>趋势</th>"
            "</tr></thead><tbody>" + "".join(trs) + "</tbody></table></div>"
        )

    fx_note = ""
    if fx:
        parts = [f"{_esc(k)}→{_esc(base)} {v:.4f}" for k, v in sorted(fx.items())]
        fx_note = f"<div class='note'>汇率（用于折算港币）：{'; '.join(parts)}</div>"

    warn_html = ""
    if warnings:
        warn_html = "<div class='note'>⚠️ " + _esc("；".join(warnings)) + "</div>"

    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        f"<title>PA 持仓复盘 · {_esc(date)}</title>"
        f"<style>{_CSS}</style></head><body><div class='wrap'>"
        f"<h1>个人持仓复盘 · {_esc(date)}</h1>"
        f"<div class='date'>由系统自动生成 · 基准币种 {_esc(base)}</div>"
        + total_card
        + (f"<h2>分币种汇总</h2>{summary_table}" if summary_rows else "")
        + fx_note
        + warn_html
        + "".join(detail_blocks)
        + "<div class='footer'>本报告由系统自动生成，仅供信息参考，不构成投资建议。现价取自最近收盘，可能有延迟。</div>"
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


def render_pa_index(dates: List[str]) -> str:
    if not dates:
        items = "<li>暂无报告</li>"
    else:
        items = "".join(f"<li><a href='{_esc(d)}.html'>💼 {_esc(d)}</a></li>" for d in dates)
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        "<title>PA 持仓复盘列表</title>"
        f"<style>{_INDEX_CSS}</style></head><body><div class='wrap'>"
        "<h1>💼 个人持仓复盘列表</h1>"
        f"<ul>{items}</ul>"
        "</div></body></html>"
    )


def write_pa_index(output_dir: str) -> str:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    dates = sorted((f.stem for f in out.glob("*.html") if f.stem != "index"), reverse=True)
    path = out / "index.html"
    path.write_text(render_pa_index(dates), encoding="utf-8")
    return str(path)
