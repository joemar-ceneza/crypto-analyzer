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
# The scheduled tasks log every few minutes forever — rotate so the log never
# grows unbounded. ~5 MB per file, 3 old files kept (~20 MB ceiling in total).
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
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
    "LINK/USDT",
    "LTC/USDT",
    "DOT/USDT",
    "UNI/USDT",
    "CAKE/USDT",
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
# MARKET REGIME DETECTION
# ======================================================
REGIME_TRENDING_ADX = 25         # ADX at/above this => trending
REGIME_RANGING_ADX = 20          # ADX below this => ranging; between => transitional
# Volatility is judged RELATIVE to the market's own recent history (a percentile),
# not an absolute %, so it works across symbols and timeframes alike.
REGIME_VOL_LOOKBACK = 200        # candles used for the volatility percentile
REGIME_HIGH_VOL_PCTILE = 0.70    # ATR above this percentile => high volatility
REGIME_LOW_VOL_PCTILE = 0.30     # ATR below this percentile => low volatility
REGIME_VOLUME_LOOKBACK = 20      # candles averaged for "recent volume"
REGIME_VOLUME_RISING = 1.2       # recent/median volume above this => rising
REGIME_VOLUME_FALLING = 0.8      # recent/median volume below this => falling

# ======================================================
# SIGNAL QUALITY (weights are public on purpose — no magic scores)
# ======================================================
# Each factor votes "supports" / "conflicts" / "neutral" for a signal. Confidence
# is supporting weight / (supporting + conflicting) — fully reconstructable from
# the factor table shown to the user.
SIGNAL_FACTOR_WEIGHTS = {
    "regime_fit": 3.0,           # is this signal type even valid in this regime?
    "trend_alignment": 3.0,      # does the signal agree with the trend?
    "higher_timeframe": 2.5,     # do other timeframes agree?
    "structure": 2.0,            # HH/HL vs LH/LL
    "momentum": 1.5,             # RSI / MACD / divergence
    "location": 1.5,             # where price sits vs value area and levels
    "volume": 1.0,               # is volume confirming?
    "volatility": 1.0,           # is volatility hostile?
    "risk": 1.0,                 # composite risk assessment
}
SIGNAL_CONFIDENCE_HIGH = 65      # >= this => "High" quality setup
SIGNAL_CONFIDENCE_LOW = 40       # <  this => "Low" quality setup

# ======================================================
# TRADE PLANNING (suggestions — never recommendations)
# ======================================================
# The stop goes just beyond the level that would invalidate the idea, but never
# so close that ordinary noise takes it out: whichever of the two is WIDER wins,
# and the plan says which one governed.
TRADE_PLAN_ATR_STOP_MULT = 1.5   # minimum stop distance, in ATR
TRADE_PLAN_LEVEL_BUFFER = 0.002  # place the stop this far beyond the level (0.2%)
TRADE_PLAN_MIN_RR = 1.5          # below this reward:risk the plan is flagged poor
TRADE_PLAN_MAX_TARGETS = 2       # TP1, TP2

# ======================================================
# REPORT / RISK
# ======================================================
NEAR_LEVEL_PCT = 0.01            # price within 1% of a level = "near" the level
RISK_HIGH_ATR_PCT = 0.04         # ATR > 4% of price => high volatility risk
RISK_LOW_ATR_PCT = 0.015         # ATR < 1.5% of price => low volatility risk

# ======================================================
# STRATEGIES (interchangeable — see strategies/)
# ======================================================
# The strategy used by the chart markers, alerts and backtests. Every strategy
# declares the regimes it suits; running one outside them lowers signal
# confidence and is called out in the UI.
#   mean_reversion | trend_following | breakout | pullback | range_trading
ACTIVE_STRATEGY = "mean_reversion"

# --- breakout ---
BREAKOUT_LOOKBACK = 20           # bars in the entry channel (prior highs)
BREAKOUT_EXIT_LOOKBACK = 10      # bars in the exit channel (prior lows)
BREAKOUT_VOLUME_MULT = 1.5       # volume must exceed this x its trailing median

# --- pullback ---
PULLBACK_TOLERANCE_PCT = 0.01    # how close to the EMA counts as "pulled back"
PULLBACK_RSI_RESET = 50          # RSI must have dipped to/below this, then turn up

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
# PERFORMANCE BREAKDOWN (which strategy / symbol / timeframe / RSI band worked?)
# ======================================================
# Every cut of the data makes each group smaller, and small groups produce
# spectacular hit rates by luck alone. A group with fewer graded signals than
# this is still shown, but is marked as under-sampled and never ranked.
BREAKDOWN_MIN_PER_GROUP = 10
# Best-vs-worst gaps narrower than this are reported as "no meaningful
# separation" rather than as a winner — a 3-point spread is noise.
BREAKDOWN_MIN_GAP_PCT = 10.0

# ======================================================
# CONFIDENCE CALIBRATION (does the confidence score actually mean anything?)
# ======================================================
# The confidence score is a hypothesis until measured. Calibration recomputes the
# confidence each past signal WOULD have had (using only data available at that
# bar) and checks whether higher confidence really did hit more often.
CALIBRATION_HORIZON = 24         # horizon the calibration is judged on
CALIBRATION_MAX_SIGNALS = 150    # most recent signals recomputed (cost control)
CALIBRATION_MIN_TOTAL = 20       # below this many graded signals: no verdict at all
CALIBRATION_MIN_PER_BUCKET = 5   # below this, a bucket's hit rate is not meaningful
CALIBRATION_EDGE_PCT = 10        # High must beat Low by this many points to count
# Signals clustered in one short window on correlated coins are ONE market
# episode, not N independent tests. Below these thresholds the calibration
# reports what it saw but refuses to draw a conclusion from it.
CALIBRATION_MIN_SPAN_DAYS = 90   # calendar span the signals must cover
CALIBRATION_MIN_SYMBOLS = 3      # distinct symbols the signals must come from

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
