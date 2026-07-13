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

# ======================================================
# DASHBOARD
# ======================================================
DASHBOARD_TITLE = "Crypto Market Intelligence"
CHART_CANDLES = 300              # candles rendered on the chart
AUTO_REFRESH_SECONDS = 60        # dashboard data refresh interval
