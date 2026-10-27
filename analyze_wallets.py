"""Filter + score leaderboard rows and write the top-5 shortlist."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
OUTPUT = ROOT / "active_wallets.json"
TOP_N = 5

FILTERS = {
    "min_account_value": 100_000,
    "min_30d_volume": 5_000_000,
    "min_30d_pnl": 50_000,
    "day_pnl_positive": True,
    "week_pnl_positive": True,
    "max_day_to_month_pnl_ratio": 0.8,
    "max_abs_day_roi": 5.0,
}


def load_leaderboard() -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = DATA_DIR / f"leaderboard_{today}.json"
    if not path.exists():
        candidates = sorted(DATA_DIR.glob("leaderboard_*.json"))
        if not candidates:
            raise FileNotFoundError("No leaderboard snapshot in data/")
        path = candidates[-1]
    return json.loads(path.read_text(encoding="utf-8"))


def _stats(windows: dict, name: str) -> tuple:
    w = windows.get(name) or {}
    return (
        float(w.get("pnl", 0) or 0),
        float(w.get("roi", 0) or 0),
        float(w.get("vlm", 0) or 0),
    )


def score_trader(row):
    windows = dict(row.get("windowPerformances", []))
    account_value = float(row.get("accountValue", 0) or 0)
    day_pnl, day_roi, _ = _stats(windows, "day")
    week_pnl, week_roi, week_volume = _stats(windows, "week")
    month_pnl, month_roi, month_volume = _stats(windows, "month")

    if account_value < FILTERS["min_account_value"]:
        return None
    if month_volume < FILTERS["min_30d_volume"]:
        return None
    if month_pnl < FILTERS["min_30d_pnl"]:
        return None
    if day_pnl <= 0 or week_pnl <= 0:
        return None
    if day_pnl >= FILTERS["max_day_to_month_pnl_ratio"] * month_pnl:
        return None
    if abs(day_roi) > FILTERS["max_abs_day_roi"]:
        return None
    if week_volume <= 0:
        return None

    month_edge_bps = (month_pnl / month_volume) * 10000
    week_edge_bps = (week_pnl / week_volume) * 10000
    score = month_edge_bps * 2.0 + week_edge_bps * 1.0 + math.log10(max(month_pnl, 1))

    return {
        "address": row["ethAddress"],
        "account_value": account_value,
        "day_pnl": day_pnl,
        "day_roi": day_roi,
        "week_pnl": week_pnl,
        "week_roi": week_roi,
        "month_pnl": month_pnl,
        "month_roi": month_roi,
        "month_volume": month_volume,
        "month_edge_bps": month_edge_bps,
        "week_edge_bps": week_edge_bps,
        "score": score,
    }


def main() -> dict:
    payload = load_leaderboard()
    rows = payload.get("leaderboardRows", [])
    scored = [s for s in (score_trader(r) for r in rows) if s]
    scored.sort(key=lambda s: s["score"], reverse=True)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": FILTERS,
        "leaderboard_count": len(rows),
        "qualified_count": len(scored),
        "top_traders": scored[:TOP_N],
    }
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    res = main()
    print(f"{res['leaderboard_count']} rows, {res['qualified_count']} qualified")
    for i, t in enumerate(res["top_traders"], 1):
        print(f"#{i} {t['address']} acc=${t['account_value']:,.0f} "
              f"month=${t['month_pnl']:,.0f} edge={t['month_edge_bps']:.0f}bps score={t['score']:.1f}")
