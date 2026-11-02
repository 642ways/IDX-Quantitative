"""Every tunable number in the app. These are starting points, not tuned results."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # Trading costs and market rules
    buy_fee: float = 0.0015
    sell_fee: float = 0.0025
    lot: int = 100
    # Universe filters
    min_value_idr: float = 5e9
    min_history_days: int = 504
    suspension_window: int = 10  # A zero-volume day this recent means the stock may not be buyable
    # Factor engine
    factor_top_pct: float = 0.20
    max_fundamental_age_days: int = 548
    # Stat arb
    pair_pvalue: float = 0.05
    pair_hl_min: float = 3
    pair_hl_max: float = 30
    pair_lookback: int = 504
    z_window: int = 60
    z_active: float = -2.0
    z_watch: float = -1.0
    z_exit: float = -0.5
    z_stop: float = -3.5
    # Long-term play
    long_entry_band: float = 0.02
    long_target_cap: float = 0.35
    long_stop: float = 0.25  # Chosen over 0.15 from a 2017-2025 test, see the design doc
    long_days: int = 365
    # Short-term play
    short_entry_band: float = 0.01
    short_target_atr: float = 3.0
    short_stop_atr: float = 1.5
    short_days: int = 14
    # Pair play
    pair_entry_band: float = 0.015
    pair_time_mult: int = 2
    # Monte Carlo
    mc_paths: int = 10000
    mc_block_days: int = 5
    mc_lookback: int = 756
    mc_min_history: int = 252
    mc_chart_paths: int = 60
    mc_chart_points: int = 60
    mc_calibration_paths: int = 500
    mc_calibration_step: int = 63
    # Market regime
    regime_min_history: int = 504
    regime_refit_days: int = 63
    regime_threshold: float = 0.5
    # Pick filters
    min_up_long: float = 0.10
    min_up_other: float = 0.03
    min_stop_price: int = 50
    max_rows: int = 15
    # Data counts as final from this hour, Jakarta time
    final_hour_wib: int = 17
    # Keep retrying until this hour if Yahoo hasn't published the day's data yet
    retry_until_hour_wib: int = 20
    # A refresh missing more than this share of stocks counts as failed
    max_failed_share: float = 0.30
    # Days before the slow backtest is recomputed
    backtest_max_age_days: int = 30


CONFIG = Config()
