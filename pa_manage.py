"""PA 持仓管理 CLI：增删改持仓，方便调仓。

用法:
    python pa_manage.py list
    python pa_manage.py add <symbol> <quantity> <cost_price> <currency> [name]
    python pa_manage.py update <symbol> [--quantity N] [--cost-price P] [--name 名]
    python pa_manage.py remove <symbol>

symbol 用 yfinance 代码（港股 4 位加 .HK，德国股加 .DE，美股直接写）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent
PA_HOLDINGS_PATH = BASE_DIR / "pa_holdings.json"


def _load() -> Dict[str, Any]:
    if not PA_HOLDINGS_PATH.exists():
        return {"base_currency": "HKD", "positions": []}
    return json.loads(PA_HOLDINGS_PATH.read_text(encoding="utf-8"))


def _save(data: Dict[str, Any]) -> None:
    PA_HOLDINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _find(positions: List[Dict[str, Any]], symbol: str) -> Dict[str, Any] | None:
    sym = symbol.strip().upper()
    for p in positions:
        if p["symbol"].strip().upper() == sym:
            return p
    return None


def cmd_list(args: argparse.Namespace) -> None:
    data = _load()
    base = data.get("base_currency", "HKD")
    print(f"基准币种: {base} ｜ 持仓数: {len(data.get('positions', []))}")
    for p in data.get("positions", []):
        print(f"  {p['symbol']:<10} {p.get('name', ''):<12} {p['currency']:<4} "
              f"数量={p['quantity']:g}  成本价={p['cost_price']:.4f}")


def cmd_add(args: argparse.Namespace) -> None:
    data = _load()
    sym = args.symbol.strip().upper()
    if _find(data.get("positions", []), sym):
        print(f"已存在 {sym}，用 update 修改")
        return
    data.setdefault("positions", []).append({
        "symbol": sym,
        "name": (args.name or "").strip() or sym,
        "currency": args.currency.strip().upper(),
        "quantity": args.quantity,
        "cost_price": args.cost_price,
    })
    _save(data)
    print(f"已添加 {sym}（{args.quantity:g} 股 @ {args.cost_price:.4f} {args.currency.upper()}）")


def cmd_update(args: argparse.Namespace) -> None:
    data = _load()
    p = _find(data.get("positions", []), args.symbol)
    if p is None:
        print(f"未找到 {args.symbol}，用 add 添加")
        return
    if args.quantity is not None:
        p["quantity"] = args.quantity
    if args.cost_price is not None:
        p["cost_price"] = args.cost_price
    if args.name:
        p["name"] = args.name.strip()
    _save(data)
    print(f"已更新 {p['symbol']}（数量={p['quantity']:g} 成本价={p['cost_price']:.4f}）")


def cmd_remove(args: argparse.Namespace) -> None:
    data = _load()
    before = len(data.get("positions", []))
    data["positions"] = [p for p in data.get("positions", []) if p["symbol"].strip().upper() != args.symbol.strip().upper()]
    if len(data["positions"]) == before:
        print(f"未找到 {args.symbol}")
        return
    _save(data)
    print(f"已删除 {args.symbol.strip().upper()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="PA 持仓管理")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出当前持仓")

    p_add = sub.add_parser("add", help="新增持仓")
    p_add.add_argument("symbol")
    p_add.add_argument("quantity", type=float)
    p_add.add_argument("cost_price", type=float)
    p_add.add_argument("currency")
    p_add.add_argument("name", nargs="?", default="")

    p_upd = sub.add_parser("update", help="更新持仓")
    p_upd.add_argument("symbol")
    p_upd.add_argument("--quantity", type=float, default=None)
    p_upd.add_argument("--cost-price", type=float, default=None)
    p_upd.add_argument("--name", default="")

    p_rm = sub.add_parser("remove", help="删除持仓")
    p_rm.add_argument("symbol")

    args = parser.parse_args()
    if args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "add":
        cmd_add(args)
    elif args.cmd == "update":
        cmd_update(args)
    elif args.cmd == "remove":
        cmd_remove(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
