# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) informally.

## [Unreleased]

## [2026-04-20]

### Added
- **GW Brief** tab: single weekly view with captain/VC, XI, bench, transfer idea, chip note, risks + Markdown export.
- **Captaincy EV** view: EV + variance bands and risk-adjusted ranking mode.
- **Minutes model v2**: start probability + minutes-if-starts → expected minutes used in projections.
- **Transfer planning upgrades**: horizon blank/DGW context, FT rollover/hits estimate, improved transfer impact summaries.
- **Rivals/mini‑league intelligence**: captain swing matrix, rival upgrade watchlist, target mode v2 “best single move vs rival”.
- **Backtesting workflow**: save projection snapshots and evaluate vs actual GW points (MAE/correlation + biggest misses).
- **Data health** sidebar diagnostics panel (API fetch telemetry + dataset sizes).

### Changed
- Projection weighting improved with bootstrap team strength scaling (handles both bucketed and rating-style strengths).
- Team views now support **Next GW vs Current GW** display selection; fallbacks added when next‑GW picks are unavailable.
- `.gitignore` updated to ignore local projection snapshot files.

### Fixed
- Target Mode: fall back to current GW picks when next-GW picks return 404 for rival entries.
- Projection edge cases: cache versioning to prevent stale “all zero” projections after logic changes.

