# FPL Elite Dashboard

A Streamlit dashboard for Fantasy Premier League managers who want a data-driven edge. The app syncs with the official FPL API and provides decision-support tooling around captaincy, transfers, EO/template risk, chips, fixtures, and rivals.

## Key features

- **GW Brief**: a weekly “one page” view (captain/VC, optimized XI + bench order, transfer idea, chip note, risks) with Markdown export.
- **Lineup**: projection-based XI optimizer + bench order (with on-demand “why benched?” explanation).
- **Captaincy**: EV + variance bands and a risk-adjusted (“safer”) ranking mode, with reason breakdown.
- **Transfers**:
  - Transfer Optimizer (drop candidates + replacements)
  - Multi‑GW Transfer Planner (FT rollover + hits estimate + horizon blank/DGW context)
  - Transfer Impact Simulator (before/after XI and readable transfer summary tables)
- **Risk / EO**: template threats + differentials, plus ownership-based “shield vs attack” framing.
- **Rivals & Mini‑League**:
  - squad comparison (shield/sword/danger)
  - captaincy swing matrix
  - rival upgrade watchlist
  - target-mode “best move vs rival”
- **Chips**: chip usage tracking from manager history.
- **Backtesting**: save a projection snapshot pre-deadline and compare vs actual GW points later (MAE/correlation + biggest misses).

## Running locally

### Prereqs
- Python **3.10+** recommended

### Setup
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### Start the app
```bash
python -m streamlit run app.py
```

If you need a specific port:
```bash
python -m streamlit run app.py --server.port 8506
```

## Usage notes

- **Manager ID**: enter your FPL entry ID in the sidebar to sync your squad.
- **Team view (Next GW vs Current GW)**:
  - Most “My Team” screens use **Team view = Next GW** by default.
  - The FPL API can return **404** for next‑GW picks (especially for other managers). The app falls back to current GW where needed.
- **Local files**:
  - `.local_settings.json` stores profiles/settings locally.
  - `.projection_snapshots.json` stores your saved backtesting snapshots locally.
  - Both are ignored by git by default (see `.gitignore`).

## Data source

This app uses the official FPL API endpoints:
- `bootstrap-static` for players/teams/events
- `fixtures` for fixtures
- manager endpoints for picks/history

## Troubleshooting

- **“Could not sync squad”**: verify Manager ID and try switching **Team view** to **Current GW**.
- **Port already in use**: run Streamlit with a different port: `--server.port 8510`.
