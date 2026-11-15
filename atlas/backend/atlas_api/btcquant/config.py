"""Protocol constants for the btcquant system. One place, because the protocol (atlas/btcquant/PROTOCOL.md, version 1.3) fixes them in advance: changing a value here is an amendment, not an edit.

Research and paper only. Nothing in this package places a real order, holds a key, uses leverage or sells short.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

PROTOCOL_VERSION = "1.3"

# --- data (protocol section 1) ---
PROVIDER = "coinbase"                         # Binance (BTC/USDT) is blocked from this environment; Coinbase BTC-USD is the alternative provider
PRODUCT = "BTC-USD"
DAY = 86400
HOUR = 3600
WARMUP_START = datetime(2019, 1, 1, tzinfo=timezone.utc)     # candles from here (indicator warm-up, never traded)
EVAL_START = date(2020, 1, 1)                                  # evaluation starts here
MAX_DAILY_MOVE = 0.40                                          # a close-to-close move beyond this is flagged for review (not fatal)
DAYS_PER_YEAR = 365                                            # Bitcoin trades every day

# --- execution and costs (section 3) ---
FEE = 0.0010                                  # of notional, per side
SLIPPAGE = 0.0005                             # against the trade, per side
COST_SENSITIVITY = ((0.0005, 0.0002), (0.0010, 0.0005), (0.0020, 0.0010), (0.0030, 0.0015))   # (fee, slippage)

# --- accounts and risk (section 4) ---
START_EQUITY_STRATEGY = 10_000.0
START_EQUITY_PORTFOLIO = 100_000.0
RISK_PER_TRADE = 0.01                         # of equity, planned loss at the protective stop
MAX_EXPOSURE = 1.0                            # unleveraged spot: at most 100% of equity in Bitcoin
ATR_N = 14
STOP_ATR_MULT = 3.0                           # default protective stop: entry-decision close minus 3 x ATR(14)
CIRCUIT_BREAKER = 0.15                        # equity 15% below its running peak: close everything at the next open and halt
BREAKER_COOL_OFF_DAYS = 30                    # research accounts (backtests, shadow accounts of challengers) resume this many days after a trip; the main portfolio waits for a human (protocol v1.1)
REBALANCE_BAND = 0.10                         # weight-mode strategies rebalance only when the target moves by more than this

# --- periods (section 2): (name, first day, last day or None for "latest complete candle") ---
PERIODS = {
    "TRAIN": (date(2020, 1, 1), date(2022, 12, 31)),
    "VALIDATION": (date(2023, 1, 1), date(2024, 12, 31)),
    "TEST": (date(2025, 1, 1), None),
}

# --- paths (artifacts live outside the python package so they can be committed and read) ---
ROOT = Path(__file__).resolve().parents[3] / "btcquant"
DATA_DIR = ROOT / "data"
STATE_DIR = ROOT / "state"
REPORT_DIR = ROOT / "reports"
REGISTRY_DIR = ROOT / "registry"
