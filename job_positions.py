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

    # Traders who fell off the shortlist: keep polling them, but only to catch
    # the exits of positions we copied — no NEW signals are taken from them.
    # Their state file is narrowed to the positions we still hold copies of, so
    # if they return to the shortlist everything else they hold counts as NEW.
    shortlist = {t["address"] for t in traders}
    copies_by_trader = {}
    for pos in paper_engine.load_portfolio()["open_positions"].values():
        if pos["trader"] not in shortlist:
            copies_by_trader.setdefault(pos["trader"], []).append(pos)

    for addr, copies in copies_by_trader.items():
        try:
            snap = fetch_positions.get_open_positions(addr)
        except Exception as e:
            log(f"  {addr[:10]}... (dropped) fetch failed: {e}")
            continue
        state_file = STATE_DIR / f"{addr}.json"
        prev = json.loads(state_file.read_text(encoding="utf-8"))["positions"] if state_file.exists() else []
        prev_map = {_key(p): p for p in prev}
        curr_map = {_key(p): p for p in snap["positions"]}
        still_held = []
        for c in copies:
            k = _key(c)
            if k in curr_map:
                still_held.append(curr_map[k])
            else:
                p = prev_map.get(k, {"coin": c["coin"], "side": c["side"], "leverage": c["leverage"]})
                new_signals.append({"ts": now, "trader": addr, "type": "CLOSED", "reason": "dropped_trader_exit", **p})
        if still_held:
            state_file.write_text(json.dumps({**snap, "positions": still_held}, indent=2), encoding="utf-8")
        elif state_file.exists():
            state_file.unlink()
        log(f"  {addr[:10]}... (dropped) {len(copies) - len(still_held)} copied positions exited, "
            f"{len(still_held)} still held")

    # Snapshots of dropped traders we no longer hold anything from.
    for state_file in STATE_DIR.glob("*.json"):
        if state_file.stem not in shortlist and state_file.stem not in copies_by_trader:
            state_file.unlink()

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
            suffix = " — trader no longer on shortlist" if s.get("reason") == "dropped_trader_exit" else ""
            lines.append(f"{s['type']} {s['side']} {s['coin']} x{s['leverage']} ({s['trader'][:10]}...){suffix}")
        lines.append(f"Portfolio equity: ${result['equity']:,.2f} ({pnl_pct:+.2f}%)")
        notes.append_entry("Position poll (Job B)", lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
