"""JOB C — read state files and post a PnL summary to Slack (read-only)."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import paper_engine

ROOT = Path(__file__).parent


def _read(name: str, default):
    path = ROOT / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _age(ts: str, now: datetime) -> str:
    mins = int((now - _parse_ts(ts)).total_seconds() // 60)
    if mins < 60:
        return f"{mins}m ago"
    hours, mins = divmod(mins, 60)
    if hours < 24:
        return f"{hours}h {mins}m ago"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h ago"


def _usd(x: float) -> str:
    return f"{x:+,.2f}"


def build_message() -> str:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    portfolio = _read("portfolio.json", None) or paper_engine.load_portfolio()
    trades = _read("paper_trades.json", [])
    signals = _read("signals.json", [])
    active = _read("active_wallets.json", {})
    start = portfolio["starting_cash"]

    try:
        marks = paper_engine.get_mark_prices()
        current = paper_engine.compute_equity(portfolio, marks)
    except Exception:
        marks = {}
        hist = portfolio.get("equity_history", [])
        current = hist[-1]["equity"] if hist else portfolio["cash"]

    older = [h for h in portfolio.get("equity_history", []) if _parse_ts(h["ts"]) <= cutoff]
    yesterday = older[-1]["equity"] if older else start
    pnl_24h = current - yesterday
    pnl_all = current - start

    trades_24h = [t for t in trades if _parse_ts(t["closed_at"]) >= cutoff]
    realized_24h = sum(t["pnl"] for t in trades_24h)
    sigs_24h = [s for s in signals if _parse_ts(s["ts"]) >= cutoff]
    n_new = sum(1 for s in sigs_24h if s["type"] == "NEW")
    n_closed = sum(1 for s in sigs_24h if s["type"] == "CLOSED")
    open_pos = list(portfolio.get("open_positions", {}).values())

    lines = [
        f"*📈 Copytrade daily report — {now:%Y-%m-%d %H:%M} UTC*",
        "",
        f"*Portfolio:* `${current:,.2f}`  (yesterday: `${yesterday:,.2f}`)",
        f"*24h PnL:* `{_usd(pnl_24h)}` USD  (`{pnl_24h / yesterday * 100:+.2f}%`)",
        f"*All-time:* `{_usd(pnl_all)}` USD  (`{pnl_all / start * 100:+.2f}%`)  — start `${start:,.0f}`",
        "",
        "*Last 24h activity:*",
        f"• Signals: {n_new} NEW, {n_closed} CLOSED",
        f"• Closed paper trades: {len(trades_24h)}  (realized PnL: `{_usd(realized_24h)}` USD)",
        f"• Open positions: {len(open_pos)}",
        "",
        "*Last activity:*",
    ]
    if signals:
        s = signals[-1]
        lines.append(f"• Last signal: {_age(s['ts'], now)} — {s['type']} {s['side']} {s['coin']} ({s['trader'][:10]}...)")
    else:
        lines.append("• Last signal: none yet")
    if trades:
        t = trades[-1]
        lines.append(f"• Last paper trade closed: {_age(t['closed_at'], now)} — {t['side']} {t['coin']} PnL `{_usd(t['pnl'])}` USD")
    else:
        lines.append("• Last paper trade closed: none yet")

    lines += ["", f"*Following:* {len(active.get('top_traders', []))} traders"]

    if open_pos:
        lines += ["", "*Open positions:*"]
        for p in open_pos[:10]:
            lines.append(f"• {p['side']} {p['coin']}  size=`{p['size']:.4f}`  entry=`${p['entry_price']:,.4f}`  x{p['leverage']}")
        if len(open_pos) > 10:
            lines.append(f"…and {len(open_pos) - 10} more")
    return "\n".join(lines)


def main() -> int:
    msg = build_message()
    if os.environ.get("DRY_RUN") == "1":
        print(msg)
        return 0
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        print("ERROR: SLACK_WEBHOOK_URL is not set", file=sys.stderr)
        return 1
    resp = requests.post(url, json={"text": msg}, timeout=20)
    resp.raise_for_status()
    print("Report posted to Slack")
    return 0


if __name__ == "__main__":
    sys.exit(main())
