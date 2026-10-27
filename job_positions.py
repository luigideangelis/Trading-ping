"""JOB B — every 5 min: poll shortlist positions → signals → paper trades."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import fetch_positions
import notes
import paper_engine

ROOT = Path(__file__).parent
LOG = ROOT / "logs" / "job_positions.log"
ACTIVE = ROOT / "active_wallets.json"
SIGNALS = ROOT / "signals.json"
STATE_DIR = ROOT / "state"


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _key(p: dict) -> str:
    return f"{p['coin']}:{p['side']}"


def main() -> int:
    if not ACTIVE.exists():
        log("active_wallets.json missing — Job A hasn't run yet, skipping")
        return 0

    traders = json.loads(ACTIVE.read_text(encoding="utf-8")).get("top_traders", [])
    log(f"Polling {len(traders)} traders")
    STATE_DIR.mkdir(exist_ok=True)
    signals = json.loads(SIGNALS.read_text(encoding="utf-8")) if SIGNALS.exists() else []
    new_signals = []
    now = datetime.now(timezone.utc).isoformat()

    for t in traders:
        addr = t["address"]
        try:
            snap = fetch_positions.get_open_positions(addr)
        except Exception as e:
            log(f"  {addr[:10]}... fetch failed: {e}")
            continue

        state_file = STATE_DIR / f"{addr}.json"
        prev = json.loads(state_file.read_text(encoding="utf-8"))["positions"] if state_file.exists() else []
        prev_map = {_key(p): p for p in prev}
        curr_map = {_key(p): p for p in snap["positions"]}

        for k in curr_map.keys() - prev_map.keys():
            new_signals.append({"ts": now, "trader": addr, "type": "NEW", **curr_map[k]})
        for k in prev_map.keys() - curr_map.keys():
            new_signals.append({"ts": now, "trader": addr, "type": "CLOSED", **prev_map[k]})

        state_file.write_text(json.dumps(snap, indent=2), encoding="utf-8")
        log(f"  {addr[:10]}... {len(snap['positions'])} open positions")

    # Traders who fell off the shortlist are no longer polled, so their
    # positions would never get a CLOSED signal. Close them out now and drop
    # their snapshot (if they return later, everything they hold is NEW again).
    shortlist = {t["address"] for t in traders}
    for state_file in sorted(STATE_DIR.glob("*.json")):
        addr = state_file.stem
        if addr in shortlist:
            continue
        prev = json.loads(state_file.read_text(encoding="utf-8")).get("positions", [])
        for p in prev:
            new_signals.append({"ts": now, "trader": addr, "type": "CLOSED", "reason": "dropped_from_shortlist", **p})
        state_file.unlink()
        log(f"  {addr[:10]}... dropped from shortlist, closing {len(prev)} positions")

    if new_signals:
        signals.extend(new_signals)
        SIGNALS.write_text(json.dumps(signals, indent=2), encoding="utf-8")
    log(f"{len(new_signals)} new signals")

    try:
        result = paper_engine.apply_new_signals()
    except Exception as e:
        log(f"paper_engine failed: {e!r}")
        return 1

    start = result["starting_cash"]
    pnl_pct = (result["equity"] - start) / start * 100
    log(f"Paper: opened={len(result['opened'])} closed={len(result['closed'])} "
        f"skipped={len(result['skipped'])} equity=${result['equity']:,.2f} ({pnl_pct:+.2f}%)")

    if new_signals:
        lines = [f"{len(new_signals)} signals"]
        for s in new_signals:
            suffix = " — dropped from shortlist" if s.get("reason") == "dropped_from_shortlist" else ""
            lines.append(f"{s['type']} {s['side']} {s['coin']} x{s['leverage']} ({s['trader'][:10]}...){suffix}")
        lines.append(f"Portfolio equity: ${result['equity']:,.2f} ({pnl_pct:+.2f}%)")
        notes.append_entry("Position poll (Job B)", lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
