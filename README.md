# crypto_analyzer

## What This Does
A personal cryptocurrency trading intelligence dashboard. It pulls live and
historical OHLCV data from Binance (public API, no key needed), runs a full
technical-analysis stack — volume profile (POC/VAH/VAL/HVN/LVN), support &
resistance, EMAs/ADX, RSI/MACD/Stoch RSI, ATR/Bollinger, market structure
(HH/HL/LH/LL, BOS, CHOCH) — and presents:

- a TradingView-style interactive chart (candles, volume, EMAs, levels,
  fibonacci, buy/sell markers)
- an automated markdown market report with scenarios and risk assessment
- a rule-based analysis narrative (explains reasoning, highlights risk,
  never claims to predict price)
- a VectorBT strategy backtester (win rate, drawdown, Sharpe, equity curve)

Works for any symbol on the exchange — ETH/USDT is just the default.

> **Pending feature:** the Alert System (Telegram/email notifications) is
> intentionally NOT built yet — it is on hold until explicitly approved.

## Requirements
- Python 3.11+ (built on 3.13)
- Windows OS
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
> (vectorbt → jupyter assets exceed the 260-char limit), either enable
> Windows Long Path support (admin) or install through a short drive alias:
> ```
> subst J: "C:\path\to\crypto_analyzer"
> J:\venv\Scripts\python.exe -m pip install -r J:\requirements.txt
> subst J: /D
> ```

## How to Run

**Interactive dashboard:**
```
venv\Scripts\python.exe -m streamlit run dashboard/app.py
```

**CLI report generation:**
```
venv\Scripts\python.exe main.py                          # ETH/USDT 1h
venv\Scripts\python.exe main.py --symbol BTC/USDT --timeframe 4h
venv\Scripts\python.exe main.py --backtest               # + strategy backtest
```
Reports are saved to `output/reports/`.

## Default Strategy Rules (backtest & chart markers)
- **BUY:** price below trailing VAL **and** RSI < 35 **and** MACD bullish crossover
- **SELL:** price reaches trailing VAH **or** RSI > 70
- Tunable in `config.py` (`BACKTEST_*` settings). VAL/VAH are computed from a
  trailing window per bar — no look-ahead bias.

## Project Structure
```
crypto_analyzer/
├── main.py                     # CLI orchestrator (numbered steps only)
├── config.py                   # every setting and constant
├── utils.py                    # generic helpers (retry, logging, formatting)
├── data/
│   ├── exchange.py             # CCXT/Binance candles, tickers, symbol list
│   └── database.py             # SQLite candle store (PostgreSQL-swappable)
├── indicators/
│   ├── volume_profile.py       # POC, VAH, VAL, HVN, LVN
│   ├── support_resistance.py   # swings, pivots, fibonacci, clustered S/R
│   ├── trend.py                # EMA 20/50/200, SMA, ADX, trend verdict
│   ├── momentum.py             # RSI, MACD, Stochastic RSI
│   └── volatility.py           # ATR, Bollinger Bands
├── analysis/
│   ├── market_structure.py     # HH/HL/LH/LL, BOS, CHOCH
│   └── report_generator.py     # analysis aggregation + markdown report
├── backtesting/
│   └── strategy.py             # signal rules + VectorBT portfolio
├── ai/
│   └── analyzer.py             # rule-based narrative (no API key needed)
├── dashboard/
│   └── app.py                  # Streamlit + Plotly dashboard
├── logs/                       # automation.log
└── output/                     # market_data.db + reports/
```

## Logs
Logs are saved to `logs/automation.log`.

## Disclaimer
This tool describes market conditions and probabilities. It is not financial
advice and makes no claim to predict future prices.
