# NBA Basketball Simulator

A free-first NBA game and player-prop research simulator. The first foundation uses ESPN public NBA endpoints and Polymarket's public Gamma API, with a static site designed for GitHub Pages.

**Live site:** https://ztee71638-bot.github.io/NBA_Basketball_SIM/

## Current foundation
- NBA schedule/live scoreboard ingestion for a rolling three-day window.
- Read-only discovery of active NBA game markets and nested player props from Polymarket's NBA series.
- Selected game and player panels show likely matching Polymarket markets and available outcome prices.
- Live ESPN injury report snapshot with player/team/status details.
- Browser-based 100,000-trial Monte Carlo game simulator with a conservative last-10 baseline, prior-season context, team-specific scoring variance and correlated score variation.
- Experimental opponent-adjusted and pace/efficiency models are evaluated separately against the baseline and are not promoted unless they improve out-of-sample results.
- Player-prop probability calculator with manual assumptions or recent-game baselines; matched Polymarket player props can prefill the stat and line for simulation.
- Searchable player roster and historical game-log interface.
- Two-season team game histories from completed ESPN regular-season scoreboard results; upcoming 0-0 placeholders are excluded.
- Boxscore enrichment estimates possessions, pace, offensive rating and defensive rating from field-goal attempts, offensive rebounds, turnovers and free-throw attempts when ESPN exposes complete team statistics.
- Rest days, back-to-back flags, recent schedule density, road-trip streaks and straight-line arena travel estimates are collected as experimental context.
- Immutable daily snapshots preserve game-level model inputs (including pace, efficiency, rest and travel) for reproducible backtests.
- A chronological walk-forward backtest (`python scripts/backtest_model.py`) that reports score MAE, winner accuracy, Brier score and calibration error against a simple last-10 baseline, using only games before each test game. Daily metrics are published to the simulator so experimental changes can be compared against the baseline.
- Two-season player game logs retain minutes, shooting attempts, turnovers, offensive rebounds and plus/minus when available; player baselines blend recent per-minute production with minutes trends.
- ESPN-confirmed starting lineups are checked near tipoff and displayed only when five starters per team are explicitly flagged; no guessed starters or unvalidated player-impact penalties are used.
- Separate nightly player-history refresh and frequent game/market/lineup refresh workflows.
- Automated tests for feed parsing, market filtering, and player-log normalization.

**Important model limitation:** the game simulator now uses a recency-weighted, opponent-informed team scoring model with sample-size shrinkage and correlated score noise, but it is not yet a validated predictive model. The walk-forward backtest is a measurement tool, not proof of predictive edge; review its sample size and compare results across multiple seasons. Pace/possessions, efficiency, rest and straight-line travel are collected as experimental features where source coverage permits; their scoring and winner metrics are measured on identical holdout games before promotion. Travel distances are estimates between arena coordinates, not actual flight itineraries. Minutes-trend adjustments are descriptive player baselines, not official expected minutes. Confirmed lineup flags are displayed only when ESPN explicitly supplies five starters per side. Player on/off impact, schedule rest/travel, and full multi-season probability calibration remain incomplete. Injury flags are displayed as context but are not converted into unsupported point adjustments. Player-prop estimates remain historical baselines, not validated projections. Missing, stale or uncertain inputs must result in PASS. Players listed as Out, Doubtful, Questionable or Day-To-Day are blocked with a PASS warning when ESPN injury data is available; the prop calculator also passes on fewer than five stat observations or unstable/limited minutes roles. Polymarket comparisons are raw historical-baseline differences, not validated edges. Missing, stale or uncertain inputs must result in PASS.

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
1. Validate coverage and data quality of the new two-season team and player archives after the next successful refresh.
2. Extend historical seasons and immutable snapshots without overwriting prior daily inputs.
3. Add travel/rest and player on/off impact only from verified, time-aligned sources.
4. Expand out-of-sample calibration across more seasons and monitor model drift.
5. Validate Polymarket event/player identity matching and compare calibrated model probabilities with market prices.
6. Add automated data freshness/coverage alerts and keep strict PASS thresholds.
