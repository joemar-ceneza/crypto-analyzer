"""
Central configuration for the crypto_analyzer project.

All settings, constants, and tunable parameters live here.
Nothing in this file should be hardcoded anywhere else in the codebase.
"""

import os

# ======================================================
# BASE PATHS (absolute — Task Scheduler safe)
# ======================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "automation.log")
SCREENSHOT_DIR = os.path.join(LOG_DIR, "screenshots")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATABASE_FILE = os.path.join(BASE_DIR, "output", "market_data.db")
REPORT_DIR = os.path.join(OUTPUT_DIR, "reports")

# ======================================================
# EXCHANGE / DATA COLLECTION
# ======================================================
EXCHANGE_ID = "binance"          # any CCXT-supported exchange id
DEFAULT_SYMBOL = "ETH/USDT"      # default market — dashboard can switch dynamically
QUOTE_CURRENCY = "USDT"          # used to build the dynamic symbol list
SYMBOL_CHOICES = [               # quick-pick symbols shown in the dashboard
    "ETH/USDT",
    "BTC/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "DOGE/USDT",
    "LINK/USDT",
]
TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]
DEFAULT_TIMEFRAME = "1h"
CANDLE_FETCH_LIMIT = 1000        # max candles per API request
HISTORY_CANDLES = 1500           # candles to keep warm per symbol/timeframe
REQUEST_TIMEOUT_MS = 30000       # CCXT request timeout

# Retry policy for all network calls
RETRY_ATTEMPTS = 3
RETRY_DELAY = 2                  # seconds between retries

# ======================================================
# VOLUME PROFILE
# ======================================================
VOLUME_PROFILE_BINS = 100        # number of price buckets in the histogram
VALUE_AREA_PCT = 0.70            # value area covers 70% of traded volume
HVN_THRESHOLD = 1.5              # bin volume > 1.5x mean volume => High Volume Node
LVN_THRESHOLD = 0.5              # bin volume < 0.5x mean volume => Low Volume Node
VOLUME_PROFILE_LOOKBACK = 500    # candles used to build the profile

# ======================================================
# SUPPORT / RESISTANCE
# ======================================================
SWING_LOOKBACK = 5               # bars on each side to confirm a swing point
SR_CLUSTER_PCT = 0.005           # cluster levels within 0.5% of each other
MAX_SR_LEVELS = 6                # max support + max resistance levels reported
FIB_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]

# ======================================================
# INDICATOR SETTINGS
# ======================================================
EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 200
SMA_PERIOD = 50
ADX_PERIOD = 14
ADX_TREND_THRESHOLD = 25         # ADX above this = trending market

RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

STOCH_RSI_PERIOD = 14
STOCH_RSI_SMOOTH_K = 3
STOCH_RSI_SMOOTH_D = 3

ATR_PERIOD = 14
BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2.0

# ======================================================
# VWAP
# ======================================================
VWAP_SESSION_FREQ = "D"          # session VWAP resets on this boundary (D = daily)
# Anchored VWAP starts from a chosen bar. "auto" anchors to the extreme
# (lowest low / highest high) of the lookback window, which is where traders
# usually anchor. The dashboard can override with an explicit date.
VWAP_ANCHOR_MODE = "auto"
VWAP_ANCHOR_LOOKBACK = 500       # candles searched for the auto anchor

# ======================================================
# DIVERGENCE DETECTION
# ======================================================
DIVERGENCE_LOOKBACK_BARS = 80    # only swings inside this window count
DIVERGENCE_MIN_RSI_GAP = 2.0     # RSI must differ by this much between swings

# ======================================================
# MULTI-TIMEFRAME CONFLUENCE
# ======================================================
CONFLUENCE_TIMEFRAMES = ["1h", "4h", "1d"]
CONFLUENCE_CANDLES = 600         # candles fetched per timeframe (EMA200 needs 200+)

# ======================================================
# MARKET STRUCTURE
# ======================================================
STRUCTURE_SWING_LOOKBACK = 5     # swing sensitivity for HH/HL/LH/LL detection
STRUCTURE_MAX_SWINGS = 20        # recent swings considered for BOS/CHOCH

# ======================================================
# REPORT / RISK
# ======================================================
NEAR_LEVEL_PCT = 0.01            # price within 1% of a level = "near" the level
RISK_HIGH_ATR_PCT = 0.04         # ATR > 4% of price => high volatility risk
RISK_LOW_ATR_PCT = 0.015         # ATR < 1.5% of price => low volatility risk

# ======================================================
# BACKTESTING (default strategy rules)
# ======================================================
BACKTEST_INITIAL_CASH = 10000.0
BACKTEST_FEES = 0.001            # 0.1% taker fee per side
BACKTEST_RSI_BUY = 35            # BUY: RSI below this ...
BACKTEST_RSI_SELL = 70           # SELL: RSI above this ...
BACKTEST_USE_VAL_FILTER = True   # BUY requires price below VAL
BACKTEST_USE_VAH_TARGET = True   # SELL triggers when price reaches VAH

# Parameter sweep grid for the dashboard strategy lab
SWEEP_RSI_BUY = [25, 30, 35, 40]
SWEEP_RSI_SELL = [60, 65, 70, 75]

# Walk-forward validation: the history is split into WALK_FORWARD_SPLITS
# segments. Each segment optimizes on its in-sample part and is then scored on
# the untouched out-of-sample part that follows. Out-of-sample results are the
# only ones that mean anything — in-sample results are curve-fitted by design.
WALK_FORWARD_SPLITS = 4
WALK_FORWARD_TRAIN_PCT = 0.7     # share of each segment used for optimization

# ======================================================
# DATA COLLECTION (main.py --collect, for Task Scheduler)
# ======================================================
COLLECT_SYMBOLS = SYMBOL_CHOICES  # symbols kept warm by scheduled collection
COLLECT_TIMEFRAMES = TIMEFRAMES   # timeframes kept warm per symbol

# ======================================================
# SELL-SIGNAL ALERTS (main.py --alerts, Telegram)
# ======================================================
# Credentials live in .env, never here:
#   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
ALERT_SYMBOLS = ["ETH/USDT", "BTC/USDT"]  # symbols watched for signals
# Every symbol is checked on EVERY timeframe listed here, so a signal on the
# 4h is not missed while watching the 1h. Each symbol+timeframe+side is
# de-duplicated independently.
ALERT_TIMEFRAMES = ["1h", "4h"]
ALERT_TIMEFRAME = ALERT_TIMEFRAMES[0]      # back-compat default for single-tf callers
ALERT_CANDLES = 600                        # candles fetched per alert check
ALERT_RECENT_BARS = 3                      # only alert if the signal fired within
                                           # this many latest closed candles
ALERT_ON_SELL = True                       # notify on new sell signals
ALERT_ON_BUY = True                        # notify on new buy signals
ALERT_COOLDOWN_BARS = 6                    # min candles between alerts of the
                                           # same symbol + side (anti-spam)
ALERT_STATE_FILE = os.path.join(OUTPUT_DIR, "alert_state.json")
SIGNAL_LOG_FILE = os.path.join(OUTPUT_DIR, "signal_history.csv")

# ======================================================
# SIGNAL SCORECARD (was the signal right?)
# ======================================================
# Forward horizons (in candles) each signal is graded over. A SELL "hits" when
# price is lower N candles later; a BUY hits when price is higher.
SCORECARD_HORIZONS = [6, 24, 72]
SCORECARD_MIN_MOVE_PCT = 0.002   # moves smaller than 0.2% count as "flat", not a hit

# ======================================================
# DASHBOARD
# ======================================================
DASHBOARD_TITLE = "Crypto Market Intelligence"
CHART_CANDLES = 1000             # default candles shown on the chart (slider value)
CHART_MAX_CANDLES = 5000         # upper bound of the chart history slider
AUTO_REFRESH_SECONDS = 60        # cache lifetime for fetched candles
LOCAL_TZ = "Asia/Manila"         # UTC+8 — used by the "local time" display toggle
# Live auto-refresh choices (label -> seconds; None = off)
LIVE_REFRESH_CHOICES = {"Off": None, "10s": 10, "30s": 30, "60s": 60}
