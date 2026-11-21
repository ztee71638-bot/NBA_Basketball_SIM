# NBA simulator data sources

## ESPN public endpoints — primary free source

The first implementation uses:
- Scoreboard: `site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard`
- Team rosters: `site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster`
- League injury report: `site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries`
- Player game logs: `site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{athlete_id}/gamelog?season={year}`

The scoreboard feed has been exercised successfully by the initial scheduled data refresh. The player roster and game-log collector has parser tests. The collector prioritizes the active 2026–27 roster (`season=2027`) and retrieves five seasons of game logs by default (2027 through 2023); `NBA_HISTORY_SEASONS` can override the comma-separated season-ending years. The collector queries each configured season's team rosters, but ESPN's public roster endpoint may return only the current roster even when an older season is requested. To avoid silently omitting historical logs when roster history is incomplete, the collector queries every configured game-log season for every indexed player. This improves multi-season coverage for players in the indexed roster, but does not guarantee coverage of players who are no longer present on any returned roster. Missing logs are retained as missing, not filled with zeros. The refresh refuses to replace the last good archive if any configured season falls below the minimum game-log coverage threshold.

ESPN endpoints are public but undocumented and unofficial. They can change, omit older seasons, or throttle requests. The collector uses timeouts, a request delay, retries for transient errors, a 120-minute workflow limit, and a minimum-record guard; permanent client errors are not retried, and failed player requests are recorded as empty season logs rather than fabricated values.

## Team history

The team-history collector uses ESPN's public daily scoreboard feed to collect completed regular-season games for the active season, then groups the results by ESPN team ID. The team schedule endpoint returned empty/inconsistent results during validation, so the daily scoreboard is the verified source path. The collector requests five season-ending years by default (2027 through 2023; configurable with `NBA_TEAM_HISTORY_SEASONS`) and keeps completed games only. Because a full five-year boxscore crawl would create thousands of additional requests, detailed pace/efficiency enrichment is limited to the two newest seasons; older seasons supply score-level historical context. The scheduled job has a 60-minute limit and the quality audit reports missing team/season coverage rather than treating an incomplete feed as complete. A separate per-game summary request enriches team rows with estimated possessions, pace, offensive rating and defensive rating when the ESPN boxscore exposes FGA, FTA, offensive rebounds and turnovers. Estimated possessions use FGA - OREB + TO + 0.44*FTA. These are boxscore-derived estimates, not official NBA tracking values. The experimental efficiency model is backtested on the same holdout games as the last-10 baseline and remains out of the live default unless it improves.

## Starting lineups\n\nThe frequent refresh checks ESPN game summaries near tipoff. It displays a lineup only when the summary explicitly marks five starters for each team. If either side is incomplete, the record remains `not_available`; no starters are inferred from roster order or depth charts. The lineup snapshot is timestamped and the browser hides stale snapshots.\n\n## Rest, travel and arenas\n\nThe team-history collector calculates rest days, back-to-back flags, games in the prior three/five days, consecutive road-trip games and straight-line arena-to-arena travel miles. Arena coordinates are stored in `data/arenas.json`; the source coordinate reference is a public ArcGIS NBA arenas point dataset, with current arena names/locations maintained in the project. Travel miles are great-circle distances, not flight paths, actual routing, time-zone changes or verified team itineraries. These features are currently experimental inputs for the walk-forward efficiency model and are not applied to the live score estimate unless validation supports them.\n\n## Injuries

The collector flattens ESPN's league-wide injury report into player-level records, including athlete ID (resolved from profile links when needed), team, status, injury type, date, expected return date and comments. ESPN's report is secondary reporting and can contain stale or incomplete entries; it must not replace official team/league status reports. The prop interface blocks calculations for players ESPN lists as Out, Doubtful, Questionable or Day-To-Day when a matching player ID is available.

## NBA Stats / nba_api — secondary candidate

The open-source `nba_api` client wraps the NBA.com Stats endpoints and exposes player game logs, team/player statistics, box scores and play-by-play. It requires no API key, but the underlying NBA endpoints are not a documented public service and can return 403s or become unavailable. It should be evaluated as a fallback, not assumed to be reliable. Reference: https://github.com/swar/nba_api

## Polymarket Gamma — public read-only market source

Base URL: `https://gamma-api.polymarket.com`

The current collector queries active events in Polymarket's NBA series (`series_id=10345`) and flattens their nested markets. It supplements those with paginated active markets carrying the NBA tag (`tag_id=745`), retaining only markets associated with the active game events; this second path is needed because some player props are exposed on the flat markets endpoint rather than the event's nested list. It retains active, non-closed markets and excludes events whose scheduled end time has passed. This captures game moneylines, spreads, totals and player props. Outcome prices, 24-hour volume and liquidity are stored for display. Player/event identity matching and model-vs-price edge calculations are still separate validation steps.

Gamma is used only for market/event discovery and metadata. The simulator does not connect to wallets, create orders, or trade.

## Reproducible prediction ledger

The team-history workflow writes `data/backtest_predictions.json` from the chronological walk-forward run. Each record stores the game date and ID, season, versioned production-baseline and experimental-model projections, the observed final score, and compact pregame-only team/league inputs. It is an audit trail of historical out-of-sample predictions, not a live odds feed. The ledger is generated from historical archives, and future features must not be added to historical records unless their historical pregame availability can be established.

## Data quality rules

- Store source name and refresh timestamp with each snapshot.
- Keep ESPN player IDs as stable source identifiers; do not merge players by display name alone.
- Preserve missing values as null/empty; never convert missing statistics to zero.
- Keep historical logs separate from model projections.
- Record the season and game ID for every player game log.
- Require a minimum data coverage threshold before a player can receive a prop projection.
- Exclude or PASS players with unknown minutes, questionable status, stale roster data or insufficient game history.
- Backtests must use only information that was available before each historical game.


## Archive quality audit

`scripts/audit_data_quality.py` checks the team archive for 30-team coverage, season/team game counts, malformed and duplicate rows, paired opponent/score consistency, and timestamp freshness. When the player archive is present it also checks player ID uniqueness, declared record counts, missing game logs, and freshness. The report is written to `data/data_quality.json` by the team-history workflow. This is a data integrity report, not a predictive performance score.
