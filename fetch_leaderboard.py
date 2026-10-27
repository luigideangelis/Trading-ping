"""Fetch the public Hyperliquid leaderboard and snapshot it to data/."""
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
DATA_DIR = Path(__file__).parent / "data"


def fetch() -> dict:
    resp = requests.get(
        LEADERBOARD_URL,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def save_snapshot(payload) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = DATA_DIR / f"leaderboard_{today}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


if __name__ == "__main__":
    data = fetch()
    p = save_snapshot(data)
    print(f"Saved {len(data.get('leaderboardRows', []))} rows to {p}")
