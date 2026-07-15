# Crypto Analyzer — Development Charter

The guiding document for this project. Read before adding any feature.

## Philosophy

This application is **not a price predictor and must never claim to know where
the market will go.** Instead it should:

- Measure current market conditions objectively.
- Explain those conditions in plain English.
- Quantify uncertainty.
- Grade every signal against future price action.
- Help users make better-informed decisions instead of making decisions for them.

**Every feature should increase transparency rather than optimism.**
When evidence conflicts, the application must explicitly say confidence is low.

---

## Core principles

### Local first
Everything runs locally: no cloud services, no AI API, no paid APIs, no external
databases. The user owns all data. Only public market data (Binance/CCXT) and
optional Telegram notifications are allowed.

### Modular architecture
Strict separation of responsibilities:

- `main.py` is **only** an orchestrator.
- Analysis modules never know about Streamlit.
- The dashboard never contains analysis logic.
- Indicators calculate data only.
- Report generation only interprets results.
- Strategy logic is isolated.
- Configuration belongs in `config.py`; runtime overrides in `settings_store.py`.
- Avoid circular dependencies.

### Design goals
Every feature should answer one of these:

- What is the market doing?
- Why is it doing that?
- How confident are we?
- What evidence supports this?
- What evidence contradicts this?
- What would invalidate this analysis?

**Never hide uncertainty.**

---

## Development priorities

1. **Market analysis** — volume profile, market structure, trend, momentum,
   volatility, VWAP, support/resistance, multi-timeframe confluence. The
   foundation; keep improving it.

2. **Explainability** — every signal explains itself. Not `SELL`, but:
   ```
   SELL
   Reasons:
     - RSI above threshold
     - Price inside VAH
     - Momentum weakening
     - Trend slowing
     - Resistance nearby
   Confidence: 67%
   Conflicting evidence:
     - Strong higher-timeframe trend
     - Increasing volume
   ```

3. **Signal quality** — a score from multiple independent factors (trend
   alignment, structure, momentum, volume, volatility, risk, higher-timeframe
   agreement). It represents **the quality of the setup, not a prediction.**

4. **Trade planning** — optional plans: entry, stop loss, TP1, TP2,
   risk/reward, ATR risk, nearest invalidating level. **Suggestions, not
   recommendations.**

5. **Strategy framework** — multiple interchangeable strategies (trend
   following, mean reversion, breakout, pullback, range). Strategies **consume**
   market analysis rather than duplicating indicator calculations.

6. **Performance evaluation** — expand the Scorecard: hit rate, average edge,
   MFE, MAE, win/loss distribution, precision, recall, expectancy, Sharpe,
   profit factor. Always distinguish **backtest vs walk-forward vs
   out-of-sample**. Never present optimized results without validation.

7. **Market regime detection** — trending, ranging, high/low volatility,
   accumulation, distribution. Strategies should adapt to the detected regime.

8. **Risk assessment** — consider ATR, Bollinger squeeze, recent CHOCH,
   distance to support/resistance, volume anomalies, trend strength, volatility
   expansion. **Explain exactly why a risk level was assigned.**

9. **Historical integrity** — avoid all look-ahead bias. Only use information
   available at the time. Trailing calculations stay trailing. Walk-forward is
   the primary validation method.

10. **User experience** — clarity over complexity. Prefer *"This setup has
    conflicting evidence"* over *"Strong Buy."* Plain English whenever possible.

---

## Coding standards

- Clean, maintainable Python; docstrings on public functions; type hints.
- Keep functions small. Prefer composition over inheritance.
- Write tests for new analysis logic.
- Avoid duplicated calculations. Keep configuration centralized.

---

## When adding a feature, ask

1. Does this improve analysis?
2. Does it reduce uncertainty?
3. Does it improve explainability?
4. Does it improve validation?
5. Does it avoid overfitting?
6. Can it be tested?

If the answer is "no" to most of these, reconsider the feature.

---

## Never add

- Price prediction models claiming future accuracy.
- "Guaranteed" buy/sell recommendations.
- Hidden heuristics or magic scores with no explanation.
- AI-generated trading advice.
- Look-ahead bias.
- Over-optimized strategies.
- Anything that reduces transparency.

---

## Ultimate goal

Crypto Analyzer should become an **explainable market intelligence platform**,
not a signal generator. It should help traders understand market structure,
evaluate evidence, measure uncertainty, validate strategies objectively, and
improve their decision-making over time — **not replace their judgment.**
