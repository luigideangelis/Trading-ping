"""Thin wrappers around Hyperliquid's public /info endpoint."""
import sys

import requests

INFO_URL = "https://api.hyperliquid.xyz/info"


def _post(payload: dict):
    resp = requests.post(
        INFO_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def get_open_positions(address) -> dict:
    data = _post({"type": "clearinghouseState", "user": address})
    positions = []
    for entry in data.get("assetPositions", []):
        p = entry["position"]
        szi = float(p["szi"])
        if szi == 0:
            continue
        positions.append({
            "coin": p["coin"],
            "side": "LONG" if szi > 0 else "SHORT",
            "size": abs(szi),
            "entry_price": float(p["entryPx"]),
            "position_value_usd": float(p["positionValue"]),
            "leverage": p["leverage"]["value"],
            "unrealized_pnl": float(p["unrealizedPnl"]),
            "liquidation_price": float(p["liquidationPx"] or 0),
        })
    return {
        "account_value": float(data["marginSummary"]["accountValue"]),
        "positions": positions,
        "timestamp_ms": data["time"],
    }


def get_recent_fills(address, limit=50) -> list:
    """Optional helper — not used by the current jobs."""
    data = _post({"type": "userFills", "user": address})
    side_map = {"B": "BUY", "A": "SELL"}
    fills = []
    for f in data[:limit]:
        fills.append({
            "coin": f["coin"],
            "side": side_map.get(f["side"], f["side"]),
            "price": float(f["px"]),
            "size": float(f["sz"]),
            "time_ms": f["time"],
            "closed_pnl": float(f.get("closedPnl", 0) or 0),
            "dir": f.get("dir"),
        })
    return fills


if __name__ == "__main__":
    addr = sys.argv[1]
    res = get_open_positions(addr)
    print(f"account_value={res['account_value']:,.2f}")
    for p in res["positions"]:
        print(f"  {p['side']} {p['coin']} size={p['size']} entry={p['entry_price']} x{p['leverage']}")
