"""JOB A — once a day: leaderboard → shortlist → NOTES.md."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import analyze_wallets
import fetch_leaderboard
import fetch_positions
import notes

ROOT = Path(__file__).parent
LOG = ROOT / "logs" / "job_daily.log"
ACTIVE = ROOT / "active_wallets.json"


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    try:
        prior = []
        if ACTIVE.exists():
            prior = [t["address"] for t in json.loads(ACTIVE.read_text(encoding="utf-8")).get("top_traders", [])]

        log("Fetching leaderboard…")
        payload = fetch_leaderboard.fetch()
        path = fetch_leaderboard.save_snapshot(payload)
        log(f"Saved snapshot {path.name}")

        result = analyze_wallets.main()
        top = result["top_traders"]
        log(f"Leaderboard: {result['leaderboard_count']} rows, {result['qualified_count']} qualified")
        log(f"Shortlist updated: {len(top)} traders")

        snapshots = {}
        for t in top:
            addr = t["address"]
            try:
                snapshots[addr] = fetch_positions.get_open_positions(addr)["positions"]
            except Exception as e:
                log(f"Position snapshot failed for {addr}: {e}")

        new_addrs = [t["address"] for t in top]
        lines = [f"Leaderboard: {result['leaderboard_count']} traders fetched, {len(top)} shortlisted"]
        if not prior:
            lines.append("First shortlist (no prior run)")
        else:
            added = [a for a in new_addrs if a not in prior]
            removed = [a for a in prior if a not in new_addrs]
            lines.append(f"Shortlist change: +{len(added)} new, -{len(removed)} dropped")
            lines += [f"  +{a}" for a in added]
            lines += [f"  -{a}" for a in removed]
        for i, t in enumerate(top, 1):
            lines.append(f"#{i} {t['address'][:10]}... acc=${t['account_value']:,.0f} "
                         f"month=${t['month_pnl']:,.0f} edge={t['month_edge_bps']:.0f}bps")
        lines.append("Current positions across the shortlist:")
        for t in top:
            addr = t["address"]
            if addr not in snapshots:
                lines.append(f"  {addr[:10]}... (snapshot unavailable)")
            elif not snapshots[addr]:
                lines.append(f"  {addr[:10]}... no open positions")
            else:
                desc = ", ".join(f"{p['side']} {p['coin']} x{p['leverage']}" for p in snapshots[addr])
                lines.append(f"  {addr[:10]}... {len(snapshots[addr])} positions: {desc}")

        notes.append_entry("Daily refresh (Job A)", lines)
        log("NOTES.md updated")
        return 0
    except Exception as e:
        log(f"FAILED: {e!r}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
