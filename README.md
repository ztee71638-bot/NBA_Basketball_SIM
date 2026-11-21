# NBA Basketball Simulator

A free-first NBA game and player-prop research simulator. The first foundation uses ESPN public NBA endpoints and Polymarket's public Gamma API, with a static site designed for GitHub Pages.

**Live site:** https://ztee71638-bot.github.io/NBA_Basketball_SIM/

## Current foundation
- NBA schedule/live scoreboard ingestion for a rolling three-day window.
- Read-only discovery of active NBA game markets and nested player props from Polymarket's NBA series.
- Selected game and player panels show likely matching Polymarket markets and available outcome prices.
- Live ESPN injury report snapshot with player/team/status details.
- Browser-based 100,000-trial Monte Carlo game simulator with recency-weighted, opponent-informed scoring estimates, small-sample shrinkage, team-specific scoring variance and a modest shared pace shock.
- Player-prop probability calculator with manual assumptions or recent-game baselines; matched Polymarket player props can prefill the stat and line for simulation.
- Searchable player roster and historical game-log interface.
- Current-season team game history and recent form (points for/against, wins, last-10 averages) built from ESPN daily scoreboards to seed game projections.
- A chronological walk-forward backtest (`python scripts/backtest_model.py`) that reports score MAE, winner accuracy and Brier score against a simple last-10 baseline, using only games before each test game.
- Separate nightly player-history refresh and frequent game/market refresh workflows.
- Automated tests for feed parsing, market filtering, and player-log normalization.

**Important model limitation:** the game simulator now uses a recency-weighted, opponent-informed team scoring model with sample-size shrinkage and correlated score noise, but it is not yet a validated predictive model. The walk-forward backtest is a measurement tool, not proof of predictive edge; review its sample size and compare results across multiple seasons. Advanced pace/possessions, offensive/defensive efficiency, player-level availability and minutes/role impact, confirmed lineups, travel/rest effects and probability calibration remain incomplete. Injury flags are displayed as context but are not converted into unsupported point adjustments. Player-prop estimates remain historical baselines, not validated projections. Missing, stale or uncertain inputs must result in PASS. Players listed as Out, Doubtful, Questionable or Day-To-Day are blocked with a PASS warning when ESPN injury data is available; the prop calculator also passes on fewer than five stat observations or unstable/limited minutes roles. Polymarket comparisons are raw historical-baseline differences, not validated edges. Missing, stale or uncertain inputs must result in PASS.

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
1. Extend historical coverage across multiple seasons and retain immutable daily snapshots for reproducible backtests.
2. Add pace, possessions, offensive/defensive ratings, rest and travel features from a reliable free data source.
3. Add minutes/role projections, confirmed starting lineups and verified injury/status-change monitoring.
4. Build player-level impact and game-script-aware correlated player/game Monte Carlo models.
5. Calibrate probabilities on out-of-sample seasons and add strict sample-size, freshness and PASS thresholds.
6. Validate Polymarket event/player identity matching and compare calibrated model probabilities with market prices.
7. Add automated monitoring, model drift alerts, regression tests and production deployment verification.
