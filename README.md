# Copytrade with Claude

Paper copy-trading on Hyperliquid. Every day the system picks the 5 most
profitable and consistent traders from the public leaderboard (edge-weighted
scoring), polls their open positions every 5 minutes, and mirrors any new or
closed position into a $10,000 paper portfolio. A summary is posted to Slack
every 30 minutes.

- `job_daily.py` — refresh the shortlist (`active_wallets.json`)
- `job_positions.py` — diff positions → `signals.json` → paper trades
- `daily_report.py` — Slack report

Runs on GitHub Actions, triggered by cron-job.org. See `CLAUDE.md` for the
full design, setup steps and decision log; `NOTES.md` for the activity log.

**Paper only.** No real money is traded.
