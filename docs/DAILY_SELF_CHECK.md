## Daily live prediction and results ledger

`scripts/daily_self_check.py` runs hourly through GitHub Actions. It checks the
previous, current and next UTC scoreboard dates, saves a pregame prediction
once per ESPN game ID, and later attaches the ESPN final score only after the
event is marked completed. Existing predictions are immutable and result
reconciliation is idempotent.

The committed `data/daily_predictions.json` file stores each game's original
prediction, model version, final result, winner correctness, score errors and
Brier score, plus daily and cumulative summaries. Games without a valid
pregame prediction or verified final score are not included in accuracy.
This live ledger is separate from the historical walk-forward backtest.
