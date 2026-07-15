# crypto-analyzer

A personal cryptocurrency **trading intelligence dashboard**. It pulls live and
historical market data from Binance, runs a full technical-analysis stack over
it, shows it on a TradingView-style chart, writes a plain-English market report,
explains and plans every signal, grades its own signals afterwards, and can
message you on Telegram when one fires.

Everything runs **locally on your own PC**. No cloud, no account, no API key.

> **What this is not:** it does not predict prices. It measures conditions and
> probabilities, and it tells you when it doesn't know. See [Disclaimer](#disclaimer).

---

## Table of contents

- [Quick start](#quick-start)
- [The big idea](#the-big-idea)
- [The dashboard, view by view](#the-dashboard-view-by-view)
- [Understanding the analysis](#understanding-the-analysis)
- [Signal explainability](#signal-explainability)
- [Trade plans](#trade-plans)
- [Strategies](#strategies)
- [The strategy rules (and their known weakness)](#the-strategy-rules-and-their-known-weakness)
- [Telegram alerts](#telegram-alerts)
- [Running it automatically (Task Scheduler)](#running-it-automatically-task-scheduler)
- [Command-line reference](#command-line-reference)
- [Settings](#settings)
- [Sharing with a friend](#sharing-with-a-friend)
- [Project structure](#project-structure)
- [Data storage](#data-storage)
- [Tests & CI](#tests--ci)
- [Troubleshooting](#troubleshooting)
- [Disclaimer](#disclaimer)

---

## Quick start

```bash
# 1. Get the code
git clone https://github.com/joemar-ceneza/crypto-analyzer
cd crypto-analyzer

# 2. Create a virtual environment (any location works)
python -m venv .venv
.venv\Scripts\activate

# 3. Install
pip install -r requirements.txt

# 4. Run the dashboard
python -m streamlit run dashboard/app.py
```

Open <http://localhost:8501>. That's it — market data is public, so **nothing
needs configuring** to get started. (Telegram alerts are optional; see below.)

On Windows you can also just double-click **`run_dashboard.bat`**.

**Requirements:** Python 3.11+ (built on 3.13), internet access to Binance's
public endpoints. Developed on Windows; the analysis code is OS-independent and
CI runs it on Linux.

---

## The big idea

Most trading tools either show you raw indicators (and leave you to guess) or
promise predictions (and quietly lose you money). This one takes a third path:

1. **Measure the market objectively** — volume profile, structure, momentum,
   trend, volatility, VWAP.
2. **Explain what it means in words**, including the risks and what would
   invalidate the read.
3. **Argue with itself.** Every signal shows the evidence *against* it, not just
   for it, and drops its confidence when the evidence conflicts.
4. **Grade itself.** Every signal gets scored against what price actually did
   next, so you can see whether to trust it — instead of taking its word for it.

Points 3 and 4 are the ones most tools skip. They're
[Signal explainability](#signal-explainability) and the [Scorecard](#-scorecard).

**A worked example of why this matters.** The default SELL rule fires whenever
price reaches the value-area high. In a strong uptrend it fires constantly — and
the Scorecard measured those sells hitting only **26% of the time**. The
explainability engine independently rates the same setup at **24% confidence**,
listing *"trend is bullish"*, *"timeframes lean bullish"* and *"volume is rising"*
as conflicting evidence. Two different methods, one conclusion: **ignore that
signal.** One measured it afterwards; the other warned you beforehand.

---

## The dashboard, view by view

The sidebar controls apply everywhere: **symbol**, **timeframe**, **candles
shown**, **VWAP**, **local time**, and **live auto-refresh**.

### 📊 Chart
A TradingView-style chart in four stacked panels:

| Panel | Shows |
|---|---|
| **Price** | Candlesticks, EMA 20/50/200, volume profile (left histogram), POC/VAH/VAL, support & resistance, optional Fibonacci, optional VWAP, buy/sell markers |
| **Volume** | Volume bars, colored by candle direction |
| **RSI** | RSI with 30/70 guide lines |
| **MACD** | MACD line, signal line, histogram (green above zero, red below) |

- **Candles shown** — how much history to load *and* draw. On the 1h timeframe,
  **720 candles ≈ 1 month**; the default 1000 ≈ 41 days. Max 5000.
- **Local time** — the chart axis is **UTC by default**. Toggle this to show
  Manila time (UTC+8). Only the *display* changes; storage and analysis are
  always UTC.
- **Live auto-refresh** — Off / 10s / 30s / 60s. When on, the chart re-fetches
  and redraws itself on that interval and shows an "updated" timestamp.
- **VWAP** — Off / VWAP / VWAP + bands (see [VWAP](#vwap)).
- Drag to zoom, scroll to zoom, **double-click to reset**.

Below the chart sits the **signal explanation panel** — the most recent signal
with its confidence, supporting *and* conflicting evidence, the regime, the
invalidation level, and an expandable table showing exactly how the confidence
was computed. See [Signal explainability](#signal-explainability).

### 🔎 Scan
Every quick-pick symbol in one table: price, 24h change, trend, RSI, market
structure, risk, and its most recent signal ("SELL, 10 bars ago"). Your
at-a-glance overview of the whole watchlist. Cached ~5 minutes.

### 🔭 Confluence
The same analysis run on **1h, 4h, and 1d at once**, with a per-timeframe
breakdown and an overall alignment verdict and score.

Why it matters: a bullish 1h inside a bearish 1d is a much weaker setup than
one where every timeframe agrees. The verdict says whether the timeframes
**align** (strong evidence) or **conflict** (low conviction).

### 📋 Market Report
The full automated report, rendered and downloadable as markdown:

- Current price, trend, timeframe
- Volume profile (POC / VAH / VAL / HVN / LVN)
- Support and resistance levels, ranked by strength (★)
- Every indicator with its reading and interpretation
- Market structure and the last BOS/CHOCH event
- Multi-timeframe confluence table
- **Analysis Summary** — a plain-English narrative
- **Risk Level** (Low / Medium / High) with the reasons behind it
- **Three scenarios** — bullish, bearish, and neutral, each with the level that
  would confirm it

Reports are also saved to `output/reports/` every time you run `python main.py`.

### 🧪 Strategy Lab
Test the rules instead of trusting them. Tune the rules at the top, then:

- **▶ Run backtest** — one backtest with the current rules. Reports total
  trades, win rate, return, final value, max drawdown, Sharpe, and an equity
  curve.
- **🧮 Parameter sweep** — tries every RSI buy/sell combination and ranks them
  by return. **Warning:** a grid this small overfits easily. The best cell is a
  *hypothesis*, not a result.
- **🔬 Walk-forward** — the honest test. See below.
- **Use full stored history** — backtest over every candle ever collected
  (grown by `--collect`) instead of just what the chart loaded.

**Walk-forward validation** is the antidote to the sweep's overfitting. It cuts
history into segments; in each one it optimizes the rules on the first 70%
(**in-sample**), then applies those exact rules — untouched — to the remaining
30% (**out-of-sample**). Compare the two columns:

- In-sample great, out-of-sample bad → the rules are **curve-fitted**, not predictive.
- Both decent, consistency high → the edge might be real.

**Only the out-of-sample numbers are evidence.** If a run produces **0 trades**,
that is not a "0% result" — it means the rules never fired and there is nothing
to measure. The app says so explicitly instead of pretending it broke even.

> First backtest takes ~1 minute (VectorBT compiles Numba). Later runs are fast.

### 📜 Signals
The complete history log of every buy/sell signal the strategy has ever flagged
— time, symbol, timeframe, side, price, RSI. Grown by `python main.py` and by
scheduled `--alerts` runs. Stored in `output/signal_history.csv`.

### 🎯 Scorecard
**"Were the signals actually right?"** — the most important view in the app.

Every logged signal is graded against what price really did afterwards, over
several horizons (6 / 24 / 72 candles):

- A **SELL hits** if price was **lower** N candles later.
- A **BUY hits** if price was **higher** N candles later.
- Moves under 0.2% count as **flat** (noise, neither hit nor miss).
- Signals too recent to grade are **pending** — never guessed.

| Column | Meaning |
|---|---|
| `graded` | signals with enough future data to judge |
| `hit_rate_pct` | share of graded signals that moved the right way |
| `avg_edge_pct` | average move *in the signal's favour* (positive is good for both sides) |
| `pending` | too recent to grade yet |

If a rule is doing **worse than a coin flip** over a meaningful sample, the view
says so in a red banner. That is the point — it is designed to tell you bad news.

### ⚙️ Settings
Change how the app behaves **without editing code**:

- **Alerts** — which symbols and which timeframes to watch, buy/sell toggles,
  cooldown, signal freshness.
- **Strategy rules** — RSI buy/sell thresholds, VAL/VAH filters. These drive the
  chart markers, the alerts, *and* the backtests together.

Saved to `output/user_settings.json` and picked up by the dashboard, the CLI,
and the scheduled alert task — **no restart needed**. Anything you don't
override falls back to `config.py`. **Reset** restores all defaults.

---

## Understanding the analysis

### Volume Profile
Instead of asking "what was the price?", volume profile asks **"where did people
actually trade?"** Each candle's volume is spread across the prices it covered,
building a histogram of activity by price.

| Term | Meaning | Why it matters |
|---|---|---|
| **POC** (Point of Control) | The single price with the most volume | The market's "fair value" magnet — price often returns to it |
| **VAH / VAL** (Value Area High/Low) | The band containing 70% of all volume | Inside = balance/rotation; outside = imbalance |
| **HVN** (High Volume Node) | A local peak of volume | Price moves *slowly* through it — acts as support/resistance |
| **LVN** (Low Volume Node) | A local trough of volume | Price moves *fast* through it — few traders to stop it |

### Support & Resistance
Levels are gathered from four sources, then **clustered** (nearby levels merge)
and ranked by strength (★ = more sources agreeing):

1. **Swing highs/lows** — confirmed fractal pivots
2. **Pivot points** — classic floor-trader P/R1-R3/S1-S3
3. **Fibonacci retracements** — of the dominant swing
4. **Volume nodes** — HVNs from the volume profile

### Trend
- **EMA 20 / 50 / 200** — a clean "stack" (20 > 50 > 200) signals a healthy
  uptrend; the reverse a downtrend; tangled EMAs mean no trend.
- **ADX** — trend *strength*, not direction. Above 25 = a real trend with
  participation; below = choppy/rotational.
- **Verdict** — Bullish / Weak Bullish / Neutral / Weak Bearish / Bearish.

### Momentum
- **RSI** (0–100) — above 70 overbought, below 30 oversold.
- **MACD** — trend-following momentum; crossovers flag momentum shifts.
- **Stochastic RSI** — a more sensitive RSI-of-RSI.
- **Divergence** — when price makes a lower low but RSI makes a *higher* low
  (bullish), or price makes a higher high but RSI a *lower* high (bearish).
  Often an early warning that a move is running out of fuel.

### Volatility
- **ATR** — average true range, in price terms and as a % of price.
- **Bollinger Bands** — ±2σ around a 20-period average.
- **Squeeze** — unusually narrow bands, which often precede an expansion move.

### Market Structure
Reads price the way a discretionary trader does:

- **HH / HL** (higher highs, higher lows) = uptrend
- **LH / LL** (lower highs, lower lows) = downtrend
- **BOS** (Break of Structure) — price breaks *in the trend's direction*:
  continuation.
- **CHOCH** (Change of Character) — price breaks *against* the trend: the first
  hint the structure may be turning. One CHOCH is a warning, not a confirmation.

### VWAP
The **Volume Weighted Average Price** — the average price actually paid,
weighted by volume. It answers "are buyers today up or down on the day?"

- **Session VWAP** — resets daily. The classic intraday fair-value line.
  Price above = buyers in control; below = sellers.
- **Anchored VWAP** — accumulates from a chosen bar (by default the last major
  swing high/low). Answers "what's the average price paid *since that move
  started*?"
- **Bands (±1σ)** — typical dispersion around session VWAP.

### Risk Level
A composite score (Low / Medium / High) of how hostile conditions are to
*opening a new position right now* — elevated volatility, RSI extremes, price
pressed into a level, a recent CHOCH, or a Bollinger squeeze all add risk. The
report always lists the specific reasons.

---

## Signal explainability

A bare `SELL` tells you nothing about whether to trust it. Every signal in this
app therefore arrives fully argued:

```
🟥 SELL — confidence 24% (Low)
   "SELL setup with conflicting evidence. The evidence largely argues
    against this signal."

✅ Supporting evidence          ⚠️ Conflicting evidence
 • RSI 61 · MACD bearish         • Trending up — this signal fights the trend
 • Price pressing into            • Trend is bullish — a SELL trades against it
   resistance 1,889.34            • Timeframes lean bullish (+4) — they disagree
                                  • Volume is rising — fuelling the move

Regime: Trending up · normal volatility
Invalidation: a decisive close above 1,889.34 would invalidate this SELL.
```

### Market regime
Because the same signal means different things in different markets, regime is
detected first, on three independent axes:

| Axis | Values | Basis |
|---|---|---|
| **Direction** | Trending (up/down) / Ranging / Transitional | ADX strength + trend verdict |
| **Volatility** | High / Normal / Low | ATR vs **its own** recent percentile — relative, so it works on any coin or timeframe |
| **Phase** | Accumulation / Distribution / — | Only offered inside a range; based on price vs POC and structure |

The regime sets two flags that drive everything else:
`trend_following_reliable` and `mean_reversion_reliable`. In a trend, the app
says outright that mean-reversion signals fail often. Every regime verdict
lists its reasons.

### The confidence score
Nine independent factors each vote **supports / conflicts / neutral**, with a
published weight:

| Factor | Weight | Asks |
|---|---|---|
| `regime_fit` | 3.0 | Is this *kind* of signal even valid in this regime? |
| `trend_alignment` | 3.0 | Does it agree with the trend? |
| `higher_timeframe` | 2.5 | Do other timeframes agree? |
| `structure` | 2.0 | Do HH/HL vs LH/LL back it? |
| `momentum` | 1.5 | RSI / MACD / divergence |
| `location` | 1.5 | Is price at a sensible place to act? |
| `volume` | 1.0 | Is participation confirming or fading? |
| `volatility` | 1.0 | Is volatility hostile? |
| `risk` | 1.0 | The composite risk read |

```
confidence = supporting weight ÷ (supporting + conflicting weight)
```

Neutral factors **abstain** rather than dragging everything to 50%. Weights live
in `config.SIGNAL_FACTOR_WEIGHTS` and the full factor table is shown in the UI,
so **any number the app reports can be reconstructed by hand.** A magic score
would violate the [charter](CLAUDE.md).

> **Read this carefully:** confidence measures **how well the evidence agrees —
> not the probability that price will move.** A 90% signal is one where the
> factors align, not one that is going to work. Verify with the
> [Scorecard](#-scorecard).

### Validating the score itself
A confidence score nobody checks is decoration. The **🔬 Validate the confidence
score** button (Scorecard view) rebuilds the confidence every past signal *would*
have had — from candles at or before its own bar, main timeframe *and*
confluence timeframes — then compares hit rates across the Low / Moderate / High
bands.

- If High-confidence signals hit more often → the score is informative.
- If they don't → the app **says the score is decoration** and tells you to
  retune the weights.

Confidence is **recomputed, never read from a log**, so it always reflects the
current weights: retune them in Settings and the whole history is re-graded.

**It also refuses to over-claim.** Signals clustered in a short window on
correlated coins are *one market episode observed many times*, not many
independent tests. When the sample is too narrow (< 90 days, < 3 symbols, or
one-sided), the verdict reports what it saw and then explicitly declines to draw
a conclusion from it.

### No look-ahead
When a Telegram alert explains a signal, the analysis behind it is computed
**only from candles up to and including the signal's own bar** — never the full
chart. Explaining a past signal using bars that hadn't happened yet would be
look-ahead bias dressed up as insight.

---

## Trade plans

Every signal comes with an optional plan describing **where the idea would be
entered, exited, and proven wrong** — in the dashboard's signal panel and in
your Telegram alerts:

```
📐 Trade plan (suggestion, not a recommendation)
   Entry 1,879.84 · Stop 1,899.37 (1.04% risk, 1.5x ATR)
   TP1 1,868.64 — 0.6x R:R (support)
   TP2 1,828.46 — 2.6x R:R (support)
   Invalidation: 1,890.83 — nearest resistance

⚠️ The first target pays 0.6x what it risks — below the 1.5x floor.
⚠️ The signal itself is low confidence (24%) — a tidy plan does not fix a bad setup.
```

| Field | How it's decided |
|---|---|
| **Entry** | current price |
| **Stop** | just beyond the invalidating level — **or** `1.5 × ATR`, whichever is **wider**. The plan says which one governed. |
| **TP1 / TP2** | the next real levels ahead (resistance/support, value-area edge, POC) |
| **Reward:risk** | `(target − entry) ÷ (entry − stop)`, per target |
| **ATR risk** | the stop distance in ATR multiples, plus ATR as a % of price |
| **Invalidation** | the nearest level whose loss kills the idea |

Two deliberate choices:

- **The stop is never tighter than ATR noise.** A stop inside the market's
  ordinary wiggle isn't a stop, it's a donation. Structure sets it unless
  structure sits inside the noise, and the plan tells you which won.
- **Targets are real levels, not round multiples of risk.** A target at "2R" in
  the middle of nowhere is a number, not a plan.

**The plan argues against itself too.** It flags reward:risk below the floor, a
stop that's uncomfortably wide, and a low-confidence signal underneath. If price
has no level ahead of it to aim at, it says **there is no plan** rather than
inventing a target. And because the backtester is long-only, a SELL plan
discloses that shorting it has never been tested here.

> These are **suggestions, not recommendations.** A plan describes the geometry
> of a setup. It says nothing about whether the trade will work.

---

## Strategies

Strategies are **interchangeable**. Each is a small module in `strategies/` that
*consumes* the shared market analysis — it never calculates its own indicators —
and declares the market regimes it is designed for. That declaration is the
important part: it is what lets the app tell you when you are running the wrong
tool for the market.

| Strategy | Suited to | Entry | Exit |
|---|---|---|---|
| **Mean Reversion** *(default)* | Ranging | below VAL **and** RSI < buy **and** MACD cross up | reaches VAH **or** RSI > sell |
| **Trend Following** | Trending | EMA 20>50>200 **and** ADX ≥ min **and** MACD cross up | closes below EMA 50 **or** MACD cross down |
| **Breakout** | Trending, Transitional | closes above the prior N-bar high **on rising volume** | closes below the prior N-bar low |
| **Pullback** | Trending | uptrend **and** price dips to EMA 20 **and** RSI turns up | closes below EMA 50 **or** RSI > sell |
| **Range Trading** | Ranging | price at/below VAL (no momentum gate) | price at/above VAH **or** RSI > sell |

Pick the default in **⚙️ Settings** — it drives the chart markers, the alerts,
and the backtests together. Test any other one ad-hoc in the **🧪 Strategy Lab**
without changing your default.

### Regime fit — the point of all this
When the active strategy doesn't match the current regime, the app says so, in
the Strategy Lab and in every signal's confidence:

> ⚠️ **Mean Reversion** is built for **Ranging** markets, but the regime right
> now is **Trending**. Suited to it: **Trend Following, Breakout, Pullback**.
> Signals from it will score low confidence, and rightly so.

That warning is generated from the strategy's own `suitable_regimes` — nothing
is hardcoded, so a new strategy is covered the moment you register it.

### Comparing them
**⚖️ Compare all** runs every strategy over the same candles. Inputs are built
once and shared, so it costs barely more than a single backtest.

**It ranks nothing.** One window on one symbol is a single sample, and `suits`
describes the regime a strategy is *designed* for while the test window almost
certainly spans several. Use it to spot strategies that never fire, and to see
how differently one market treats each approach — then confirm anything
interesting with **Walk-forward**.

### Adding your own
1. Create `strategies/my_idea.py` with a `SPEC` (a `StrategySpec`) and a
   `generate(inputs, rules) -> (entries, exits)`.
2. Add the module to `_MODULES` in `strategies/__init__.py`.

That's it — it appears in the Settings picker, the Strategy Lab, Compare all,
the alerts and the signal log automatically. Read what you need from `inputs`
(RSI, MACD, EMAs, ADX, ATR, trailing VAL/VAH/POC, shifted channel highs/lows,
volume ratio) and **never recompute an indicator** — that's what the bundle is
for, and it's what keeps every strategy honest about look-ahead.

---

## The strategy rules (and their known weakness)

Default rules, used by the chart markers, the alerts, and the backtester alike:

- **BUY** — price below trailing VAL **AND** RSI < 35 **AND** MACD bullish crossover
- **SELL** — price reaches trailing VAH **OR** RSI > 70

**⚠️ These rules are deliberately asymmetric, and it shows.** BUY is an **AND**
of three conditions (one of which — a MACD crossover — happens on a single
candle), so it fires very rarely. SELL is an **OR** of two conditions, one of
which ("price reached VAH") is true constantly during a rally. The practical
result: **lots of sell signals, almost no buy signals.** On a real 1500-candle
ETH sample this produced 1 buy vs 292 sell conditions.

Worse, in a sustained uptrend those sells have historically been **wrong more
often than right** — check the [Scorecard](#-scorecard) on your own data to see
the current numbers.

**This is a real limitation, not a display bug.** To rebalance, open
**⚙️ Settings** and try:
- Turning **SELL at VAH** off (leaves RSI > 70 only) — removes most sell noise.
- Raising **BUY when RSI below** (e.g. 40–45) — lets buys actually fire.
- Turning **BUY only below VAL** off — the biggest single unblocker for buys.

Then re-run the **Scorecard** and **Walk-forward** to see if the change actually
helped. That loop — change → measure → keep or revert — is what the app is for.

**No look-ahead bias:** VAL/VAH are recomputed from a *trailing* window at each
bar. Using the final chart's profile would leak the future into the past and
make every backtest look brilliant and worthless.

---

## Telegram alerts

Get a message when a **new buy or sell signal** fires. Each alert includes the
trigger, the price, the candle close time, and a **"why now" context line**
(trend, structure, RSI, risk).

**Setup (~2 minutes):**

1. In Telegram, message **@BotFather** → `/newbot` → copy the **bot token**.
2. Message **@userinfobot** to get your numeric **chat id**.
3. Copy `.env.example` to `.env` and fill in:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-your-token
   TELEGRAM_CHAT_ID=123456789
   ```
4. Test it:
   ```
   python main.py --test-alert
   ```

**How it avoids spam:**
- Only the **rising edge** of a signal counts (the moment it first becomes true).
- Only signals within the last `ALERT_RECENT_BARS` closed candles fire.
- Each symbol+timeframe+side is de-duplicated via `output/alert_state.json`.
- A per-symbol **cooldown** blocks rapid repeats.
- Signals are read from **closed candles only**, so a forming candle can't
  "repaint" an alert.

**Multiple timeframes:** every symbol is checked on every timeframe in
`ALERT_TIMEFRAMES` (default `1h` and `4h`), so a 4h signal isn't missed while
you're watching the 1h.

**Important:** alerts only fire when the check actually runs. It is a scheduled
task, not a live daemon — see below.

---

## Running it automatically (Task Scheduler)

Two very different jobs:

### The alert bot / data collector — *periodic tasks*
These run for a few seconds and exit. Schedule them to repeat.

| Task | Program | Arguments |
|---|---|---|
| Alerts | `<your venv>\Scripts\python.exe` | `main.py --alerts` |
| Collector | `<your venv>\Scripts\python.exe` | `main.py --collect` |

- **Start in:** the `crypto-analyzer` folder (required — it uses relative paths).
- **Program must be your venv's `python.exe`**, not the global Python, or it
  will fail instantly with `ModuleNotFoundError: No module named 'ccxt'`.
- Repeat every **15–30 min** for 1h-timeframe alerts. Checking more often gains
  nothing: a new signal can only appear when a candle closes.
- If your PC is off at the scheduled time, that check is simply skipped.

### The dashboard — *a long-running server*
Don't schedule this on a timer; it's a web server that must stay alive.

- **On demand (recommended):** double-click `run_dashboard.bat`.
- **Always on:** a Task Scheduler task with trigger **At log on**, program
  `<venv>\Scripts\python.exe`, arguments
  `-m streamlit run dashboard/app.py --server.headless true --server.port 8501`.
  In **Settings**, untick *"Stop the task if it runs longer than…"* or Windows
  will kill it after 3 days.

---

## Command-line reference

```bash
python main.py                              # full analysis + report for ETH/USDT 1h
python main.py --symbol BTC/USDT            # a different market
python main.py --timeframe 4h               # 5m | 15m | 1h | 4h | 1d
python main.py --candles 3000               # how much history to analyze
python main.py --backtest                   # also run the strategy backtest
python main.py --collect                    # incremental data collection, then exit
python main.py --alerts                     # check for new signals + notify, then exit
python main.py --test-alert                 # send a Telegram test message
python -m streamlit run dashboard/app.py    # the dashboard
```

A plain `python main.py` run: fetches candles → stores them → runs the full
analysis → writes the narrative → runs confluence → logs any signals → saves a
markdown report to `output/reports/`.

---

## Settings

`config.py` holds **all** defaults — every threshold, period, path, and symbol
list, documented inline. Nothing is hardcoded elsewhere.

The **⚙️ Settings** view overrides a safe subset at runtime
(`output/user_settings.json`), which wins over `config.py` without a restart.
Editable keys are whitelisted in `settings_store.py` — it's a settings layer,
not arbitrary code injection.

Key groups in `config.py`:

| Group | Controls |
|---|---|
| Exchange / data | exchange id, default symbol, quick-pick list, timeframes, history depth, retries |
| Volume profile | bins, value-area %, HVN/LVN thresholds, lookback |
| Support/resistance | swing sensitivity, clustering %, max levels, fib ratios |
| Indicators | EMA/SMA/ADX/RSI/MACD/Stoch/ATR/Bollinger periods and thresholds |
| VWAP | session reset frequency, anchor mode/lookback |
| Market structure | swing lookback, swings considered |
| Report / risk | "near level" %, ATR risk thresholds |
| Backtesting | starting cash, fees, rule defaults, sweep grid, walk-forward splits |
| Scorecard | grading horizons, minimum move |
| Alerts | symbols, timeframes, buy/sell toggles, cooldown, freshness, state file |
| Dashboard | title, default candles, refresh interval, local timezone |

---

## Sharing with a friend

Two separate things — the **app** and the **signals**.

**The app:** the repo is public. Your friend clones it and follows
[Quick start](#quick-start). Your `.env` is **not** in the repo (it's
gitignored), so she creates her own.

**The signals** — three options:

| Approach | Need her chat id? | How |
|---|---|---|
| **Telegram channel** ⭐ | **No** | Create a channel, add your bot as an admin, set `TELEGRAM_CHAT_ID=@your_channel` (or its `-100…` id). Invite her — she just joins. |
| Direct messages | **Yes** | `TELEGRAM_CHAT_ID=111111,222222` — comma-separated. Each person must message your bot `/start` first; Telegram only lets bots message people who contacted them. |
| She runs her own copy | **No** | Her own bot, her own `.env`, her own PC. Fully independent of yours. |

The channel is easiest for one or many friends. Note that signals come from
**your** running bot — if your PC is off, nobody gets them.

---

## Project structure

```
crypto-analyzer/
├── CLAUDE.md                   # development charter — read before adding features
├── main.py                     # CLI orchestrator — numbered steps only, no logic
├── config.py                   # every setting and constant
├── settings_store.py           # runtime overrides layered over config.py
├── utils.py                    # generic helpers (retry, logging, formatting)
├── conftest.py                 # pytest fixtures (synthetic candles, temp DB)
├── run_dashboard.bat           # double-click dashboard launcher (Windows)
├── data/
│   ├── exchange.py             # CCXT/Binance: candles, tickers, symbol list
│   ├── database.py             # SQLite candle store (PostgreSQL-swappable)
│   ├── collector.py            # incremental collection for Task Scheduler
│   └── signal_log.py           # buy/sell signal history (CSV)
├── indicators/
│   ├── volume_profile.py       # POC, VAH, VAL, HVN, LVN
│   ├── support_resistance.py   # swings, pivots, fibonacci, clustered S/R
│   ├── trend.py                # EMA 20/50/200, SMA, ADX, trend verdict
│   ├── momentum.py             # RSI, MACD, Stoch RSI, RSI divergence
│   ├── volatility.py           # ATR, Bollinger Bands, squeeze
│   └── vwap.py                 # session VWAP, anchored VWAP, ±1σ bands
├── analysis/
│   ├── market_structure.py     # HH/HL/LH/LL, BOS, CHOCH
│   ├── regime.py               # trending/ranging, volatility, accumulation phase
│   ├── signal_quality.py       # factors, confidence, conflicting evidence
│   ├── trade_plan.py           # entry/stop/targets/R:R/invalidation
│   ├── confluence.py           # multi-timeframe alignment (live + historical)
│   ├── scorecard.py            # grades signals against what price did next
│   ├── calibration.py          # grades the grader: is confidence informative?
│   └── report_generator.py     # analysis aggregation + markdown report
├── strategies/                 # interchangeable strategies (consume analysis)
│   ├── base.py                 # the StrategySpec contract
│   ├── inputs.py               # every input, computed once, all trailing
│   ├── mean_reversion.py       # fade extremes back to value (Ranging)
│   ├── trend_following.py      # ride confirmed trends (Trending)
│   ├── breakout.py             # break the range on volume (Trending/Transitional)
│   ├── pullback.py             # buy dips inside an uptrend (Trending)
│   └── range_trading.py        # fade the value-area edges (Ranging)
├── backtesting/
│   └── strategy.py             # runs strategies: VectorBT, sweep, walk-forward, compare
├── alerts/
│   ├── notifier.py             # Telegram sender (credentials from .env)
│   └── signal_watcher.py       # new signal detection + dedup + cooldown
├── ai/
│   └── analyzer.py             # rule-based narrative (no API key needed)
├── dashboard/
│   └── app.py                  # Streamlit + Plotly dashboard (8 views)
├── tests/                      # pytest suite — synthetic data, no network
├── .github/workflows/ci.yml    # CI: pytest on every push
├── logs/automation.log         # all runs log here
└── output/                     # database, reports, signal history, settings
```

**Architecture rules this project follows:**
- `main.py` is a pure orchestrator — numbered steps calling modules, no logic.
- Each module exposes a small public API; everything else is `_private`.
- `utils.py` holds only generic helpers — no project-specific logic.
- `config.py` is the single source of truth for defaults.

---

## Data storage

Everything lives in `output/` (gitignored — your data stays yours):

| File | What |
|---|---|
| `market_data.db` | SQLite candle store, keyed by (symbol, timeframe, timestamp). Grows via `--collect`. |
| `signal_history.csv` | Every buy/sell signal ever flagged. Feeds the Signals and Scorecard views. |
| `alert_state.json` | Which signals were already alerted (prevents duplicates). |
| `user_settings.json` | Your Settings-view overrides. |
| `reports/` | Timestamped markdown market reports. |

**All timestamps are stored and computed in UTC**, always. The "Local time"
toggle only changes what's *displayed*.

Deleting `output/` is safe — the app rebuilds what it needs (you'd lose your
signal history and collected candles).

---

## Tests & CI

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

61 tests covering the indicator math, volume profile, market structure,
strategy signals, database round-trips, alerts, settings, VWAP, and scorecard
grading. They use **synthetic data and hit no network**, so they're fast and
deterministic. GitHub Actions runs the same suite on every push
(`.github/workflows/ci.yml`).

These tests earn their keep — they've already caught two real bugs: an RSI
formula returning a neutral 50 on one-sided markets, and duplicate swing
detection on equal-value tops.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'ccxt'`**
You're running the wrong Python. Use your venv's interpreter — this is the #1
cause of a failing Task Scheduler job (`LastTaskResult: 1`).

**`pip install` fails with a long-path error**
vectorbt's Jupyter assets exceed Windows' 260-char limit. Either enable Long
Path support (`LongPathsEnabled = 1`, needs admin), or install via a short
alias:
```bash
subst J: "C:\path\to\crypto-analyzer"
J:\.venv\Scripts\python.exe -m pip install -r J:\requirements.txt
subst J: /D
```

**No Telegram messages arriving**
Run `python main.py --test-alert`. If that works but alerts never come, there's
probably just no *new* signal — silence is the normal state. Check
`logs/automation.log` for `Alert check complete`.

**"I only see sell signals"**
Expected — see [the strategy rules](#the-strategy-rules-and-their-known-weakness).

**Scheduled task shows `LastTaskResult: 1`**
It failed. Check the program path is your venv's `python.exe` and that
**Start in** is the project folder.

**The chart won't show more than a few weeks**
Raise **Candles shown** in the sidebar. On 1h, 720 candles ≈ 1 month.

**Everything's slow on the first backtest**
VectorBT compiles Numba on first use (~1 min). Subsequent runs are fast.

Logs for every run are in `logs/automation.log`.

---

## Disclaimer

This tool describes market conditions and probabilities. **It is not financial
advice, and it makes no claim to predict future prices.** Signals are
mechanical rules, not recommendations — and the Scorecard exists precisely
because those rules are often wrong. Cryptocurrency trading carries a real risk
of losing your money. Do your own research, size positions responsibly, and
never trade money you can't afford to lose.
