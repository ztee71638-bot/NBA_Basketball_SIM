# NBA Basketball Simulator

A free-first NBA game and player-prop research simulator. The initial foundation uses public ESPN scoreboard data and public Polymarket Gamma market data, with a static site designed for GitHub Pages.

## Current status
The first foundation branch provides:
- NBA schedule/live scoreboard ingestion from ESPN's public site API.
- Read-only discovery of likely NBA markets from Polymarket's public Gamma API.
- A browser-based 10,000-trial Monte Carlo game simulator.
- A player-prop probability calculator using explicitly supplied projection and standard deviation.
- Automated data refresh and validation through GitHub Actions.

**Important:** initial game projections and player-prop inputs are editable assumptions, not verified player/team statistical projections. The app must not label them as model-backed picks until historical player logs, team ratings, minutes/lineup data, and backtests are integrated. Missing/injured/uncertain players and weak data should produce PASS.

## Run locally
```bash
python -m pip install -r requirements.txt
python scripts/refresh_data.py
python -m http.server 8000
```
Open http://localhost:8000.

## Data sources
- ESPN public NBA scoreboard endpoint (schedule, status, scores and teams).
- Polymarket public Gamma API (read-only market discovery).

These are public endpoints, not guaranteed service-level APIs. The refresh job validates response shape and retains source timestamps. No trading, order placement, wallet access, or private credentials are used.

## Next phases
1. Historical team/player game logs and player identity mapping.
2. Team pace, offensive/defensive ratings, rest and matchup features.
3. Player minutes/role projections, injuries and starting lineup status.
4. Correlated player/game Monte Carlo models and calibrated uncertainty.
5. Historical backtesting, probability calibration, and strict PASS thresholds.
6. Match/market linking and price-vs-model comparison.
7. Production monitoring, stale-data alerts, and deployment verification.
