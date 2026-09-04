import json

from pa_engine import compute_position_metrics, load_holdings, summarize


def test_compute_position_metrics():
    m = compute_position_metrics(close=110.0, prev_close=100.0, quantity=10, cost_price=90.0)
    assert m["close"] == 110.0
    assert m["value"] == 1100.0
    assert m["cost"] == 900.0
    assert m["pnl"] == 200.0
    assert m["pnl_pct"] == round(200 / 900 * 100, 2)
    assert m["change_pct"] == 10.0


def test_compute_position_metrics_with_trend():
    m = compute_position_metrics(110.0, 100.0, 10, 90.0, {"ma20": 105.0, "price_vs_ma20": 4.76})
    assert m["ma20"] == 105.0
    assert m["price_vs_ma20"] == 4.76


def test_compute_position_metrics_no_prev_close():
    m = compute_position_metrics(110.0, None, 10, 90.0)
    assert m["change_pct"] is None


def test_summarize():
    positions = [
        {"currency": "HKD", "value": 1000.0, "cost": 900.0, "pnl": 100.0,
         "value_base": 1000.0, "cost_base": 900.0, "pnl_base": 100.0},
        {"currency": "USD", "value": 500.0, "cost": 400.0, "pnl": 100.0,
         "value_base": 3900.0, "cost_base": 3120.0, "pnl_base": 780.0},
    ]
    by_ccy, total = summarize(positions, "HKD", {"USD": 7.8})
    assert by_ccy["HKD"]["value"] == 1000.0
    assert by_ccy["USD"]["value"] == 500.0
    assert by_ccy["USD"]["pnl_pct"] == 25.0
    assert total["value"] == 4900.0
    assert total["cost"] == 4020.0
    assert total["pnl"] == 880.0
    assert total["pnl_pct"] == round(880 / 4020 * 100, 2)


def test_load_holdings(tmp_path):
    f = tmp_path / "h.json"
    f.write_text(json.dumps({
        "base_currency": "USD",
        "positions": [{"symbol": "AAPL", "currency": "USD", "quantity": 1, "cost_price": 100.0}],
    }), encoding="utf-8")
    data = load_holdings(f)
    assert data["base_currency"] == "USD"
    assert len(data["positions"]) == 1
    assert data["positions"][0]["symbol"] == "AAPL"
