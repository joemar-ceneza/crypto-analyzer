# Matching this project's settings in TradingView (Binance)

Every indicator setting the app uses, in the form you'd type into TradingView —
so the chart on Binance shows the same picture the dashboard does.

All values are the live defaults from [`config.py`](config.py). If you change one
there, change it here too, or the two charts quietly stop agreeing.

> **Read this first:** matching the indicators does **not** reproduce the app's
> signals. See [What you cannot copy](#what-you-cannot-copy).

---

## 1. Chart indicators — the ones the dashboard draws

Add these to your Binance/TradingView chart and set them exactly as below.

### Moving averages — add **EMA** three times
| Instance | Length | Source | Notes |
|---|---|---|---|
| EMA fast | **20** | Close | `EMA_FAST` |
| EMA mid | **50** | Close | `EMA_MID` |
| EMA slow | **200** | Close | `EMA_SLOW` |

TradingView: *Indicators → Moving Average Exponential*. Add it three times and
set the length on each.

### RSI
| Setting | Value |
|---|---|
| Length | **14** (`RSI_PERIOD`) |
| Source | Close |
| Upper band | **70** (`RSI_OVERBOUGHT`) |
| Lower band | **30** (`RSI_OVERSOLD`) |

These are TradingView's defaults — adding RSI unchanged already matches.

### MACD
| Setting | Value |
|---|---|
| Fast length | **12** (`MACD_FAST`) |
| Slow length | **26** (`MACD_SLOW`) |
| Signal smoothing | **9** (`MACD_SIGNAL`) |
| Source | Close |
| MA type | EMA (both) |

Also TradingView's defaults.

### VWAP
| Setting | Value |
|---|---|
| Anchor period | **Session** (daily — `VWAP_SESSION_FREQ = "D"`) |
| Source | hlc3 |
| Bands calculation mode | **Standard Deviation** |
| Bands multiplier | **1** — the app plots `vwap ± 1σ`, volume-weighted within the session, so the bands widen as the session develops |
| Number of bands | **1** (the app's "VWAP + bands" toggle draws one pair) |

For the app's **anchored** VWAP, use TradingView's *Anchored VWAP* tool and drop
the anchor on the same swing high/low the app picked (`VWAP_ANCHOR_MODE = "auto"`
means the app chooses the most significant swing in the last **500** candles —
you must place TradingView's anchor by hand to match).

### Fibonacci retracement
Levels: **0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0** (`FIB_LEVELS`)

TradingView's default retracement set already includes all of these — just
uncheck any extras (1.272, 1.618) so the two charts agree.

### Volume Profile
| App setting | Value | TradingView equivalent |
|---|---|---|
| `VALUE_AREA_PCT = 0.7` | 70% | **Value Area Volume = 70** |
| `VOLUME_PROFILE_BINS = 100` | 100 bins | **Rows Layout = Number of Rows**, **Row Size = 100** |
| `VOLUME_PROFILE_LOOKBACK = 500` | last 500 candles | *(no exact match — see below)* |

Use **Volume Profile Visible Range (VPVR)** and scroll so roughly the last **500
candles** are visible. This is the one indicator that **cannot match exactly**:
the app always profiles a fixed 500-candle window, while VPVR profiles whatever
is on screen. Zoom changes VPVR's POC/VAH/VAL; it never changes the app's.

⚠️ Volume Profile is a **paid TradingView feature**. If your plan doesn't include
it, the app's Chart view is the only place you'll see this.

---

## 2. Analysis-only indicators — used but not drawn

The app computes these for the market report, regime detection and risk level.
Add them to TradingView only if you want to see what the report is reacting to.

| Indicator | App settings | TradingView |
|---|---|---|
| **ATR** | length **14** (`ATR_PERIOD`) | *Average True Range*, default |
| **Bollinger Bands** | length **20**, StdDev **2.0** | *Bollinger Bands*, default |
| **ADX** | length **14**, trend threshold **25** | *ADX and DI*, length 14 |
| **Stochastic RSI** | RSI length **14**, K **3**, D **3** | *Stochastic RSI*, default |

**How the app reads ADX** (`REGIME_TRENDING_ADX` / `REGIME_RANGING_ADX`):

| ADX | App calls the market |
|---|---|
| **≥ 25** | Trending |
| **20 – 25** | Transitional |
| **< 20** | Ranging |

---

## 3. Recommended chart setup

Based on what the Scorecard measured across **2,027 signals over 598 days**:

- **Use the 4h or 1d chart.** Both have a profit factor above 1.0 (4h ≈ 1.34,
  1d ≈ 1.26). The **1h (0.73) and 15m (0.71) are below 1.0** — on those
  timeframes the wrong calls moved further than the right ones, on *both*
  strategies. See the Scorecard → Breakdown view for the live numbers.
- **Watch the 60–70 RSI band with suspicion.** It grades worst of any band
  (profit factor 0.53). The 40–50 band grades best (1.47).
- **Timezone:** the app stores and analyses everything in **UTC**. Set
  TradingView to UTC to line the candles up, or expect a UTC+8 offset against
  the dashboard's Manila display toggle.

---

## What you cannot copy

Indicators are the easy half. These are the app's own logic and have **no
TradingView equivalent** — no setting will reproduce them:

- **Buy/sell signals** — produced by the strategy engine in [`strategies/`](strategies/).
  TradingView will show the same RSI; it will not show the same decisions.
- **Signal confidence** — the 9-factor weighted vote in `analysis/signal_quality.py`.
- **Market regime** — the three-axis read in `analysis/regime.py`.
- **Market structure** — BOS/CHOCH detection in `analysis/market_structure.py`.
- **Trade plans** — entry/stop/TP1/TP2/R:R in `analysis/trade_plan.py`.
- **The Scorecard and Breakdown** — grading past signals against what price
  actually did. This is the part that tells you when to *distrust* the chart,
  and it is the reason the app exists.

Copying the indicators gives you the same **view**. It does not give you the
same **analysis** — and per the [charter](CLAUDE.md), the analysis is the point.
