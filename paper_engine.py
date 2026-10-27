"""Mock execution engine: turns signals into paper positions/trades."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).parent
PORTFOLIO = ROOT / "portfolio.json"
TRADES = ROOT / "paper_trades.json"
SIGNALS = ROOT / "signals.json"
INFO_URL = "https://api.hyperliquid.xyz/info"

STARTING_CASH = 10_000.0
POSITION_PCT = 0.05    # 5% of cash per signal
SLIPPAGE_BPS = 5
MAX_LEVERAGE = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_mark_prices() -> dict:
    resp = requests.post(
        INFO_URL,
        json={"type": "allMids"},
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    return {coin: float(px) for coin, px in resp.json().items()}


def load_portfolio() -> dict:
    return _read_json(PORTFOLIO, {
        "cash": STARTING_CASH,
        "starting_cash": STARTING_CASH,
        "open_positions": {},
        "equity_history": [],
        "last_processed_signal_index": -1,
    })


def save_portfolio(portfolio: dict) -> None:
    _write_json(PORTFOLIO, portfolio)


def position_key(trader, coin, side) -> str:
    return f"{trader}:{coin}:{side}"


def apply_slippage(mid: float, side: str) -> float:
    factor = SLIPPAGE_BPS / 10000
    return mid * (1 + factor) if side == "LONG" else mid * (1 - factor)


def _opposite(side: str) -> str:
    return "SHORT" if side == "LONG" else "LONG"


def open_position(portfolio, signal, mark):
    key = position_key(signal["trader"], signal["coin"], signal["side"])
    if key in portfolio["open_positions"]:
        return None
    leverage = max(1, min(int(signal.get("leverage", 1) or 1), MAX_LEVERAGE))
    cash = portfolio["cash"]
    notional = cash * POSITION_PCT * leverage
    margin = notional / leverage
    if margin > cash or margin <= 0:
        return None
    fill_price = apply_slippage(mark, signal["side"])
    size = notional / fill_price
    pos = {
        "trader": signal["trader"],
        "coin": signal["coin"],
        "side": signal["side"],
        "size": size,
        "entry_price": fill_price,
        "leverage": leverage,
        "notional": notional,
        "margin": margin,
        "opened_at": _now_iso(),
        "signal_ts": signal.get("ts"),
    }
    portfolio["open_positions"][key] = pos
    portfolio["cash"] = cash - margin
    return pos


def close_position(portfolio, signal, mark):
    key = position_key(signal["trader"], signal["coin"], signal["side"])
    pos = portfolio["open_positions"].pop(key, None)
    if pos is None:
        return None
    exit_price = apply_slippage(mark, _opposite(pos["side"]))
    if pos["side"] == "LONG":
        pnl = (exit_price - pos["entry_price"]) * pos["size"]
    else:
        pnl = (pos["entry_price"] - exit_price) * pos["size"]
    portfolio["cash"] += pos["margin"] + pnl
    trade = dict(pos)
    trade.update({
        "exit_price": exit_price,
        "closed_at": _now_iso(),
        "pnl": pnl,
        "pnl_pct": pnl / pos["margin"] * 100 if pos["margin"] else 0.0,
    })
    trades = _read_json(TRADES, [])
    trades.append(trade)
    _write_json(TRADES, trades)
    return trade


def unrealized_pnl(pos, mark) -> float:
    if mark is None:
        return 0.0
    if pos["side"] == "LONG":
        return (mark - pos["entry_price"]) * pos["size"]
    return (pos["entry_price"] - mark) * pos["size"]


def compute_equity(portfolio, marks) -> float:
    equity = portfolio["cash"]
    for pos in portfolio["open_positions"].values():
        equity += pos["margin"] + unrealized_pnl(pos, marks.get(pos["coin"]))
    return equity


def apply_new_signals() -> dict:
    """Process unseen signals, snapshot equity, save. Returns a summary dict."""
    portfolio = load_portfolio()
    signals = _read_json(SIGNALS, [])
    start = portfolio.get("last_processed_signal_index", -1) + 1
    new_signals = signals[start:]
    marks = get_mark_prices()

    opened, closed, skipped = [], [], []
    for sig in new_signals:
        mark = marks.get(sig["coin"])
        if mark is None:
            skipped.append(sig)
            continue
        if sig["type"] == "NEW":
            res = open_position(portfolio, sig, mark)
            (opened if res else skipped).append(res or sig)
        elif sig["type"] == "CLOSED":
            res = close_position(portfolio, sig, mark)
            (closed if res else skipped).append(res or sig)

    portfolio["last_processed_signal_index"] = len(signals) - 1
    equity = compute_equity(portfolio, marks)
    portfolio["equity_history"].append({
        "ts": _now_iso(),
        "equity": equity,
        "cash": portfolio["cash"],
    })
    save_portfolio(portfolio)
    return {
        "opened": opened,
        "closed": closed,
        "skipped": skipped,
        "equity": equity,
        "cash": portfolio["cash"],
        "starting_cash": portfolio["starting_cash"],
    }


def summary() -> None:
    portfolio = load_portfolio()
    try:
        marks = get_mark_prices()
    except Exception as e:
        print(f"(mark prices unavailable: {e})")
        marks = {}
    equity = compute_equity(portfolio, marks)
    start = portfolio["starting_cash"]
    print(f"Cash:     ${portfolio['cash']:,.2f}")
    print(f"Equity:   ${equity:,.2f}  ({(equity - start) / start * 100:+.2f}% vs ${start:,.0f})")
    print(f"Open positions: {len(portfolio['open_positions'])}")
    for pos in portfolio["open_positions"].values():
        upnl = unrealized_pnl(pos, marks.get(pos["coin"]))
        print(f"  {pos['side']:5} {pos['coin']:8} size={pos['size']:.4f} "
              f"entry=${pos['entry_price']:,.4f} x{pos['leverage']} uPnL={upnl:+.2f}  ({pos['trader'][:10]}...)")
    trades = _read_json(TRADES, [])
    realized = sum(t["pnl"] for t in trades)
    print(f"Closed trades: {len(trades)}  realized PnL: {realized:+.2f}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "summary":
        summary()
    else:
        print("usage: python paper_engine.py summary")
