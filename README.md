# NBA Basketball Simulator

A free-first NBA game and player-prop research simulator. The first foundation uses ESPN public NBA endpoints and Polymarket's public Gamma API, with a static site designed for GitHub Pages.

## Current foundation
- NBA schedule/live scoreboard ingestion for a rolling three-day window.
- Read-only discovery of active NBA game markets and nested player props from Polymarket's NBA series.
- Selected game and player panels show likely matching Polymarket markets and available outcome prices.
- Live ESPN injury report snapshot with player/team/status details.
- Browser-based 10,000-trial Monte Carlo game calculator.
- Player-prop probability calculator with manual assumptions or a recent-game historical baseline when player logs are available.
- Searchable player roster and historical game-log interface.
- Current-season team game history and recent form (points for/against, wins, last-10 averages) built from ESPN daily scoreboards to seed game projections.
- Separate nightly player-history refresh and frequent game/market refresh workflows.
- Automated tests for feed parsing, market filtering, and player-log normalization.

**Important model limitation:** the game and prop calculators are currently assumption-driven calculators, not validated predictive models. Historical player logs and recent team form are descriptive baselines only. Player projections, minutes/role, injury impact, confirmed lineups, opponent adjustments, correlation, backtesting and calibration must be implemented and validated before the app labels any selection as a model-backed edge. Players listed as Out, Doubtful, Questionable or Day-To-Day are blocked by the prop calculator with a PASS warning when ESPN injury data is available. Missing, stale or uncertain inputs must result in PASS.

## Run locally
```bash
python -m pip install -r requirements.txt
python scripts/refresh_data.py
python scripts/refresh_player_history.py
python -m http.server 8000
```
Open http://localhost:8000.

## Automated data collection
- `Refresh NBA data`: every 15 minutes; schedule, read-only market snapshot and ESPN injury report.
- `Refresh NBA player history`: nightly; team rosters plus player game logs for seasons 2027 and 2026.
- `Refresh NBA team history`: nightly; current-season game histories and recent-form summaries for all 30 teams, using ESPN daily scoreboard results.
- Player history requests are rate-limited and retried. If fewer than 100 player records are retrieved, the job refuses to overwrite the existing archive.
- No API secrets, Polymarket trading permissions, wallet access or paid subscription are required for the current public feeds.

## Data source caveats
ESPN's public endpoints are undocumented/unofficial and may change or rate-limit requests. Polymarket Gamma is read-only public market metadata; it is not a trading API. See [DATA_SOURCES.md](docs/DATA_SOURCES.md).

## Next development phases
1. Verify full roster/game-log coverage and player identity mapping against real season records.
2. Extend team game logs with pace, possessions, offensive/defensive ratings, rest and matchup features.
3. Add minutes/role projections, confirmed starting lineups and automated injury/status-change monitoring.
4. Build correlated player/game Monte Carlo models and calibrated uncertainty.
5. Backtest against historical results with strict no-leakage and PASS thresholds.
6. Validate Polymarket event/player identity matching and compare calibrated model probabilities with market prices.
7. Add freshness monitoring, stale-data alerts, regression tests and production deployment verification.
