# Crypto Analyzer — the complete guide

A plain-English walkthrough of what this project is, what every part does, how to
use it day to day, and — honestly — what it can and cannot do for your trading.

Read [README.md](README.md) for setup and [CLAUDE.md](CLAUDE.md) for the design
charter. This guide is the "explain it to me like I'm learning" version.

---

## Part 1 — What this project actually is

**It is a market analysis and self-grading tool. It is not a signal service and
not a fortune teller.**

Most crypto tools do one of two things: dump raw indicators on you and let you
guess, or promise "STRONG BUY" signals that quietly lose money. This project
deliberately does neither. Its whole job is to:

1. **Measure** the market objectively (trend, momentum, volume, structure, volatility).
2. **Explain** what those measurements mean in words — including the evidence *against* a trade.
3. **Quantify uncertainty** — it tells you when it doesn't know.
4. **Grade itself** — every signal it ever produced is scored against what price actually did next.

The single most important sentence in the whole project, from the charter:

> This application is **not a price predictor and must never claim to know where
> the market will go.**

If you internalise only one thing, make it that. Everything below serves it.

---

## Part 2 — The pieces, in plain English

The project is layered. Each layer only talks to the ones next to it.

```
Binance (public market data)
        │  fetched via CCXT
        ▼
Candle store (SQLite, output/market_data.db)
        │
        ▼
Indicators        →  raw math: RSI, MACD, ATR, EMAs, volume profile, VWAP
        │
        ▼
Analysis          →  interprets the math: trend, momentum, structure, regime, risk
        │
        ▼
Strategy engine   →  turns analysis into buy/sell signals (5 interchangeable strategies)
        │
        ├──►  Signal quality   →  scores each signal's setup (confidence + evidence)
        ├──►  Trade plan       →  entry / stop / targets / invalidation
        │
        ▼
Dashboard  ·  Telegram alerts  ·  Market report  ·  Scorecard (grades it all)
```

**Where each thing lives** (you rarely need to touch these, but now you know):

| Folder | What's in it |
|---|---|
| `data/` | fetching candles, saving to SQLite, the signal history log |
| `indicators/` | pure math — RSI, MACD, ATR, EMAs, volume profile, VWAP |
| `analysis/` | interpretation — trend, momentum, structure, regime, risk, scorecard, breakdown, calibration, trade plan |
| `strategies/` | the 5 strategies, each a small self-contained module |
| `alerts/` | the Telegram notifier and the signal watcher (the alert bot) |
| `dashboard/` | the Streamlit app: `app.py` router + `loaders`/`charts`/`formatting` + `views/` |
| `config.py` | every default setting in one place |
| `output/user_settings.json` | your overrides — what you change in the ⚙️ Settings view |

---

## Part 3 — The eight dashboard views

Start the dashboard with `python -m streamlit run dashboard/app.py`. Across the
top are eight views. Here's what each is *for*.

### 📊 Chart
The TradingView-style chart: candlesticks, EMAs (20/50/200), volume profile down
the left, support/resistance lines, POC/VAH/VAL, optional Fibonacci and VWAP, and
buy/sell triangles where the strategy fired. **Below the chart is the most
important panel in the app** — the signal explanation (see Part 5).

### 🔎 Scan
One row per coin in your watchlist: price, 24h change, trend, RSI, structure,
risk, and the most recent signal. Your at-a-glance "what's happening everywhere."

### 🔭 Confluence
The same analysis run on 1h, 4h and 1d **at once**, with a verdict on whether the
timeframes agree. A bullish 1h inside a bearish 1d is a weak setup; when all three
line up, that's real evidence.

### 📋 Market Report
The full written report for one coin — every indicator, the levels, the structure,
a plain-English summary, a risk level with its reasons, and three scenarios
(bullish / bearish / neutral) each with the price that would confirm it.
Downloadable as a markdown file.

### 🧪 Strategy Lab
Test the rules instead of trusting them. Pick a strategy, tune it, then:
- **Run backtest** — trades, win rate, return, drawdown, Sharpe, equity curve.
- **Parameter sweep** — tries RSI combinations (warning: overfits easily).
- **Walk-forward** — the honest test: optimise on old data, apply *untouched* to
  newer data. **Only the out-of-sample numbers count.**
- **Compare all** — every strategy over the same candles.

### 📜 Signals
The running log of every buy/sell signal the strategy has ever flagged. This is
the raw material the Scorecard grades.

### 🎯 Scorecard  ← *the view that makes this project honest*
Three sections, increasing depth:
1. **Summary** — for BUY and SELL, at 6/24/72-candle horizons: hit rate, average
   edge, profit factor, MFE/MAE (how far price ran for you vs against you).
2. **Breakdown** — the same signals sliced by strategy, symbol, timeframe, side,
   or RSI band. Answers "which of my signals actually work?" It refuses to rank
   groups too small to trust.
3. **Calibration** — grades the confidence score itself: did higher-confidence
   signals really hit more often? If not, the score is decoration and it says so.

### ⚙️ Settings
Change strategy, watched symbols/timeframes, alert toggles, cooldowns and the rule
thresholds — no code edits, no restart. Saved to `output/user_settings.json`.

---

## Part 4 — The analysis concepts (what the words mean)

- **Volume Profile (POC / VAH / VAL)** — where the most trading happened by price.
  POC = the busiest price (a magnet). VAH/VAL = the top/bottom of the zone holding
  70% of volume. Price tends to respect these.
- **Support / Resistance** — price levels that have repeatedly stopped moves,
  ranked by how many times (shown with stars).
- **Trend** — from the EMAs and ADX. ADX ≥ 25 = strong trend; < 20 = no trend
  (ranging).
- **Momentum (RSI / MACD)** — RSI over 70 = overbought, under 30 = oversold. MACD
  crossing its signal line = momentum shift. Divergence (price up but RSI down) =
  a possible weakening.
- **Volatility (ATR / Bollinger)** — how much price moves. Drives stop distance.
- **Market Structure (BOS / CHOCH)** — higher-highs/higher-lows = uptrend.
  BOS = break of structure (trend continues). CHOCH = change of character (trend
  may be reversing).
- **VWAP** — the volume-weighted average price; institutions watch it.
- **Regime** — the big-picture context on three axes: direction (trending /
  ranging), volatility (high / low, measured *relative* to that coin's own
  history), and phase (accumulation / distribution). **Strategies win or lose
  mostly on whether they match the regime.**
- **Risk level** — Low / Medium / High, with the exact reasons (near resistance,
  volatility expanding, recent CHOCH, etc.).

---

## Part 5 — How to read a signal (the heart of using this)

When a signal fires, the app never just says "BUY." It shows:

1. **A confidence score (0–100%)** with a colour — 🟩 High (≥65), 🟨 Moderate,
   🟥 Low (<40). This is **not** the probability the trade wins. It is *how well
   the evidence agrees with itself*.
2. **Supporting evidence** — the factors that back the signal.
3. **Conflicting evidence** — the factors that argue against it. **Read this first.**
4. **Regime fit** — is this strategy suited to the current market?
5. **Invalidation** — the price that would prove the idea wrong.
6. **A trade plan** — entry, stop, TP1/TP2, reward:risk. A *suggestion about
   geometry*, never a recommendation.

**How the confidence is built** (no magic — you can see every number): nine factors
each vote *supports / conflicts / neutral*, with weights. Confidence = supporting
weight ÷ (supporting + conflicting weight). The weights live in
`config.SIGNAL_FACTOR_WEIGHTS`. Regime fit and trend alignment carry the most.

**A worked example of why this matters:** in a strong uptrend the default SELL rule
fires constantly (price keeps tapping the value-area high). The Scorecard measured
those sells hitting ~26% of the time. The confidence engine independently scored
the same setup at ~24%, listing "trend is bullish" and "volume rising" as
conflicts. Two methods, one conclusion: **ignore that signal.** One warned you
before, the other proved it after.

---

## Part 6 — How to actually use it, day to day

A realistic workflow:

1. **Open the dashboard.** Glance at 🔎 Scan to see where things stand.
2. **Pick a coin, open 📊 Chart.** Read the signal explanation panel underneath.
   - Low confidence or lots of conflicting evidence? → skip it.
   - High confidence, few conflicts, strategy suits the regime? → worth a look.
3. **Check 🔭 Confluence.** Do 1h/4h/1d agree? Disagreement = weaker.
4. **Read the 📐 trade plan.** If reward:risk is below ~1.5, the geometry is poor
   even if the setup looks nice.
5. **Sanity-check against 🎯 Scorecard.** Has *this kind* of signal (this strategy,
   this timeframe) actually worked historically? Use the Breakdown.
6. **Let alerts do the watching.** With the Task Scheduler bot running, you get a
   Telegram message when a fresh signal fires — you don't have to sit and stare.

**Your alerts are currently set to:** mean_reversion strategy, 10 coins, **4h and
1d only**, both buy and sell. Those timeframes were chosen because they're the only
ones with a profit factor above 1.0 on your own 598-day history.

**The CLI**, for the scheduled jobs and one-offs:
- `python main.py` — full analysis + report for one coin.
- `python main.py --collect` — top up the candle store (the hourly scheduled job).
- `python main.py --alerts` — check for fresh signals, notify (the 5-minute job).
- `python main.py --backtest` — quick backtest from the terminal.

---

## Part 7 — The honest advice on "winning every trade"

You asked how to succeed on *every* trade, buy or sell. Here is the truthful
answer, and it is the most valuable thing in this guide:

### There is no way to win every trade. Not with this tool, not with any tool.

Anyone — any person, any app, any "signal group" — who tells you they can make you
win every trade is either mistaken or selling you something. Markets are partly
random. The best professional traders in the world lose on a large share of their
trades. **Your own data proves it:** across 2,027 signals over 598 days and every
market condition, even your *best* configurations hit around 50% of the time. The
project was built, deliberately, to reject the promise you just asked for. That's
what the charter means by "not a price predictor."

### So what does "success" actually mean?

**Success is not winning every trade. It is making more on your winners than you
lose on your losers, over many trades.** That single idea is what the **profit
factor** column measures. A profit factor of 1.4 means that for every $1 lost on
wrong calls, $1.40 came back on right ones — *even though nearly half the calls
were wrong.* You get rich slowly by being right about the math, not about the next
candle.

### The advice that actually helps — process, not prediction

1. **Risk a fixed small amount per trade** (many use 1–2% of the account). This is
   the one rule that matters more than all the others combined. It's what keeps a
   losing streak — and you *will* have losing streaks — from ending you.
2. **Always know your invalidation before you enter.** The trade plan gives it to
   you. If you can't say where you're wrong, you don't have a trade, you have a hope.
3. **Let reward:risk do the work.** Only take setups where the plan's reward:risk
   is comfortably above 1. With 2:1, you can be wrong more than half the time and
   still come out ahead.
4. **Respect the regime.** The biggest, most consistent way these rules lose money
   is running a strategy in the wrong regime — mean-reversion in a strong trend, or
   breakout in a chop. The dashboard warns you; believe it.
5. **Read the conflicting evidence, and skip when it's loud.** Low confidence isn't
   a weak buy — it's the app telling you the evidence disagrees with itself. The
   best trade is often no trade.
6. **Cut losers fast, let winners run.** Take the stop when it hits. Don't move it
   further away to avoid being wrong — that's how a small loss becomes a big one.
7. **Judge yourself over 30+ trades, never one.** One win proves nothing; one loss
   proves nothing. Use the Scorecard to see if your *process* has an edge, and
   change the process, not your mood.
8. **Trade small or on paper until the Scorecard shows an edge on *your* decisions.**
   The tool grades its signals; nothing grades your discipline but your results.

### The uncomfortable truth

This project's honesty is a feature, not a limitation. A tool that told you every
signal was a winner would feel better and cost you money. This one tells you when
it doesn't know — and knowing when you don't know is the actual edge. Use it to
**avoid bad trades and size good ones**, not to find certainty that doesn't exist.

> Trade on probabilities, manage your risk, and survive long enough for the math
> to work. That is the only "system" that succeeds — and no honest tool will ever
> promise you more.

*Nothing in this project or this guide is financial advice. It is a technical
analysis tool. The decisions, and the risk, are yours.*
