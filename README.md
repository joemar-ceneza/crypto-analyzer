# crypto-analyzer

## What This Does
A personal cryptocurrency trading intelligence dashboard. It pulls live and
historical OHLCV data from Binance (public API, no key needed), runs a full
technical-analysis stack — volume profile (POC/VAH/VAL/HVN/LVN), support &
resistance, EMAs/ADX, RSI/MACD/Stoch RSI, ATR/Bollinger, RSI divergence,
market structure (HH/HL/LH/LL, BOS, CHOCH) — and presents:

- a TradingView-style interactive chart (candles, volume, EMAs, levels,
  fibonacci, buy/sell markers, RSI and MACD subpanels)
- multi-timeframe confluence: the same analysis on 1h/4h/1d with an
  alignment verdict and score
- an automated markdown market report with scenarios and risk assessment
- a rule-based analysis narrative (explains reasoning, highlights risk,
  never claims to predict price)
- a strategy lab: VectorBT backtester with tunable rules and an RSI
  parameter sweep (win rate, drawdown, Sharpe, equity curve)
- scheduled data collection (`--collect`) that grows the SQLite candle
  history over time via Windows Task Scheduler

Works for any symbol on the exchange — ETH/USDT is just the default.

## Requirements
- Python 3.11+ (built on 3.13)
- Windows OS (analysis modules are OS-independent; CI runs on Linux)
- Internet access to Binance public endpoints

## Setup
1. Clone or download this project
2. Create the virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate
   ```
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
   (Exact tested versions are pinned in `requirements.lock.txt`.)
4. No credentials required — public market data only. `.env.example` lists
   optional keys for future features.

> **Windows note:** if `pip install` fails with a long-path error
> (vectorbt → jupyter assets exceed the 260-char limit), enable Windows
> Long Path support (`LongPathsEnabled = 1`, needs admin) or install
> through a short drive alias:
> ```
> subst J: "C:\path\to\crypto-analyzer"
> J:\venv\Scripts\python.exe -m pip install -r J:\requirements.txt
> subst J: /D
> ```

## How to Run

**Interactive dashboard:**
```
venv\Scripts\python.exe -m streamlit run dashboard/app.py
```
Tabs: **Chart** (candles + indicators), **Confluence** (1h/4h/1d alignment),
**Market Report** (downloadable markdown), **Strategy Lab** (tunable
backtest + parameter sweep).

**CLI report generation:**
```
venv\Scripts\python.exe main.py                          # ETH/USDT 1h
venv\Scripts\python.exe main.py --symbol BTC/USDT --timeframe 4h
venv\Scripts\python.exe main.py --backtest               # + strategy backtest
```
Reports are saved to `output/reports/`.

**Scheduled data collection (Task Scheduler):**
```
venv\Scripts\python.exe main.py --collect
```
Incrementally tops up the SQLite store for every symbol/timeframe in
`config.COLLECT_SYMBOLS` / `COLLECT_TIMEFRAMES`. Point a Windows Task
Scheduler job at the full venv python path with the `--collect` argument
(e.g. hourly) and the candle history grows on its own.

## Default Strategy Rules (backtest & chart markers)
- **BUY:** price below trailing VAL **and** RSI < 35 **and** MACD bullish crossover
- **SELL:** price reaches trailing VAH **or** RSI > 70
- Defaults live in `config.py` (`BACKTEST_*`); the dashboard Strategy Lab
  overrides them per run. VAL/VAH are computed from a trailing window per
  bar — no look-ahead bias.

## Tests
```
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
venv\Scripts\python.exe -m pytest -q
```
GitHub Actions runs the same suite on every push (`.github/workflows/ci.yml`).

## Project Structure
```
crypto-analyzer/
├── main.py                     # CLI orchestrator (numbered steps only)
├── config.py                   # every setting and constant
├── utils.py                    # generic helpers (retry, logging, formatting)
├── conftest.py                 # pytest fixtures (synthetic candles, temp DB)
├── data/
│   ├── exchange.py             # CCXT/Binance candles, tickers, symbol list
│   ├── database.py             # SQLite candle store (PostgreSQL-swappable)
│   └── collector.py            # incremental collection for Task Scheduler
├── indicators/
│   ├── volume_profile.py       # POC, VAH, VAL, HVN, LVN
│   ├── support_resistance.py   # swings, pivots, fibonacci, clustered S/R
│   ├── trend.py                # EMA 20/50/200, SMA, ADX, trend verdict
│   ├── momentum.py             # RSI, MACD, Stoch RSI, RSI divergence
│   └── volatility.py           # ATR, Bollinger Bands
├── analysis/
│   ├── market_structure.py     # HH/HL/LH/LL, BOS, CHOCH
│   ├── confluence.py           # multi-timeframe alignment scoring
│   └── report_generator.py     # analysis aggregation + markdown report
├── backtesting/
│   └── strategy.py             # tunable rules + VectorBT + parameter sweep
├── ai/
│   └── analyzer.py             # rule-based narrative (no API key needed)
├── dashboard/
│   └── app.py                  # Streamlit + Plotly dashboard
├── tests/                      # pytest suite (synthetic data, no network)
├── .github/workflows/ci.yml    # CI: pytest on every push
├── logs/                       # automation.log
└── output/                     # market_data.db + reports/
```

## Logs
Logs are saved to `logs/automation.log`.

## Disclaimer
This tool describes market conditions and probabilities. It is not financial
advice and makes no claim to predict future prices.
