# NBA simulator data sources

## ESPN public endpoints — primary free source

The first implementation uses:
- Scoreboard: `site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard`
- Team rosters: `site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster`
- League injury report: `site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries`
- Player game logs: `site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{athlete_id}/gamelog?season={year}`

The scoreboard feed has been exercised successfully by the initial scheduled data refresh. The player roster and game-log collector has parser tests, but full historical coverage still needs to be confirmed by a real scheduled run after the branch is merged.

ESPN endpoints are public but undocumented and unofficial. They can change, omit older seasons, or throttle requests. The collector uses timeouts, a request delay, retries, and a minimum-record guard; failed player requests are recorded as empty season logs rather than fabricated values.

## Team history

The team-history collector uses ESPN's public daily scoreboard feed to collect completed regular-season games for the active season, then groups the results by ESPN team ID. The team schedule endpoint returned empty/inconsistent results during validation, so the daily scoreboard is the verified source path. Current-season game history includes points for/against, wins and last-10 form; prior-season slots remain empty until a reliable historical endpoint is validated. These are team box-score aggregates, not pace or possession metrics. They are a free baseline for seeding game score assumptions, not a substitute for a full efficiency model.

## Injuries

The collector flattens ESPN's league-wide injury report into player-level records, including athlete ID (resolved from profile links when needed), team, status, injury type, date, expected return date and comments. ESPN's report is secondary reporting and can contain stale or incomplete entries; it must not replace official team/league status reports. The prop interface blocks calculations for players ESPN lists as Out, Doubtful, Questionable or Day-To-Day when a matching player ID is available.

## NBA Stats / nba_api — secondary candidate

The open-source `nba_api` client wraps the NBA.com Stats endpoints and exposes player game logs, team/player statistics, box scores and play-by-play. It requires no API key, but the underlying NBA endpoints are not a documented public service and can return 403s or become unavailable. It should be evaluated as a fallback, not assumed to be reliable. Reference: https://github.com/swar/nba_api

## Polymarket Gamma — public read-only market source

Base URL: `https://gamma-api.polymarket.com`

The current collector queries active events in Polymarket's NBA series (`series_id=10345`) and flattens each event's nested markets. It retains active, non-closed markets and filters out records whose end time is more than four hours old. This captures game moneylines, spreads, totals and any player-prop markets attached to those events. Outcome prices, 24-hour volume and liquidity are stored for display. Player/event identity matching and model-vs-price edge calculations are still separate validation steps.

Gamma is used only for market/event discovery and metadata. The simulator does not connect to wallets, create orders, or trade.

## Data quality rules

- Store source name and refresh timestamp with each snapshot.
- Keep ESPN player IDs as stable source identifiers; do not merge players by display name alone.
- Preserve missing values as null/empty; never convert missing statistics to zero.
- Keep historical logs separate from model projections.
- Record the season and game ID for every player game log.
- Require a minimum data coverage threshold before a player can receive a prop projection.
- Exclude or PASS players with unknown minutes, questionable status, stale roster data or insufficient game history.
- Backtests must use only information that was available before each historical game.
