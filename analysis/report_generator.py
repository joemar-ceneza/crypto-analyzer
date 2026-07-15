"""
Automated market report generation.

`run_analysis()` executes every indicator/analysis module over one candle
set and returns a single structured dict — the one source of truth shared
by the report, the dashboard, the AI layer, and the backtester.

`generate_report()` renders that dict into the standard markdown report
and saves it to output/reports/.

The report describes probabilities and conditions — it never claims to
predict future price.
"""

import logging
import os
from datetime import datetime, timezone

import pandas as pd

import config
import utils
from indicators import momentum, support_resistance, trend, volatility, volume_profile, vwap
from analysis import market_structure


# ======================================================
# ANALYSIS AGGREGATION
# ======================================================
def run_analysis(symbol: str, timeframe: str, candles: pd.DataFrame) -> dict:
    """
    Runs the complete technical analysis stack over a candle DataFrame.
    Returns one structured dict consumed by report/dashboard/AI/backtest.
    """
    if candles.empty or len(candles) < 50:
        raise ValueError(
            f"Not enough candles for analysis ({len(candles)}) — need at least 50."
        )

    profile = volume_profile.run_volume_profile(candles)
    levels = support_resistance.run_support_resistance(
        candles, volume_nodes=profile["hvn"]
    )
    trend_result = trend.run_trend_analysis(candles)
    momentum_result = momentum.run_momentum_analysis(candles)
    volatility_result = volatility.run_volatility_analysis(candles)
    structure_result = market_structure.run_market_structure(candles)
    vwap_result = vwap.run_vwap(candles)

    price = float(candles["close"].iloc[-1])
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "generated_at": datetime.now(timezone.utc),
        "price": price,
        "candles": candles,
        "volume_profile": profile,
        "levels": levels,
        "trend": trend_result,
        "momentum": momentum_result,
        "volatility": volatility_result,
        "structure": structure_result,
        "vwap": vwap_result,
        "risk": _assess_risk(price, momentum_result, volatility_result, levels, structure_result),
    }


# ======================================================
# RISK ASSESSMENT
# ======================================================
def _assess_risk(
    price: float,
    momentum_result: dict,
    volatility_result: dict,
    levels: dict,
    structure_result: dict,
) -> dict:
    """
    Scores current conditions into Low / Medium / High risk with reasons.
    Risk here means: how hostile are conditions to a new position right now.
    """
    score = 0
    reasons: list[str] = []

    if volatility_result["atr_pct"] >= config.RISK_HIGH_ATR_PCT:
        score += 2
        reasons.append(
            f"Volatility is elevated (ATR {volatility_result['atr_pct']:.1%} of price)"
        )
    elif volatility_result["atr_pct"] <= config.RISK_LOW_ATR_PCT:
        reasons.append("Volatility is subdued")
    else:
        score += 1

    if momentum_result["rsi"] >= config.RSI_OVERBOUGHT:
        score += 2
        reasons.append(f"RSI is overbought ({momentum_result['rsi']:.0f})")
    elif momentum_result["rsi"] <= config.RSI_OVERSOLD:
        score += 2
        reasons.append(f"RSI is oversold ({momentum_result['rsi']:.0f})")

    nearest_resistance = levels["resistances"][0]["price"] if levels["resistances"] else None
    nearest_support = levels["supports"][0]["price"] if levels["supports"] else None
    if nearest_resistance and utils.pct_distance(price, nearest_resistance) <= config.NEAR_LEVEL_PCT:
        score += 1
        reasons.append("Price is pressing into resistance")
    if nearest_support and utils.pct_distance(price, nearest_support) <= config.NEAR_LEVEL_PCT:
        score += 1
        reasons.append("Price is sitting on support")

    last_event = structure_result["last_event"]
    if last_event and last_event["kind"] == "CHOCH":
        score += 2
        reasons.append(
            f"Recent Change of Character ({last_event['direction']}) — structure may be turning"
        )

    divergence = momentum_result["divergence"]
    if divergence["type"]:
        score += 1
        reasons.append(
            f"{divergence['type'].capitalize()} RSI divergence — momentum "
            f"disagrees with price"
        )

    if volatility_result["bb_squeeze"]:
        score += 1
        reasons.append("Bollinger squeeze — an expansion move may be building")

    level = "Low" if score <= 1 else "Medium" if score <= 3 else "High"
    return {"level": level, "score": score, "reasons": reasons}


# ======================================================
# SCENARIO BUILDER
# ======================================================
def _build_scenarios(analysis: dict) -> dict[str, str]:
    """Builds bullish / bearish / neutral scenario descriptions from levels."""
    price = analysis["price"]
    profile = analysis["volume_profile"]
    resistances = analysis["levels"]["resistances"]
    supports = analysis["levels"]["supports"]

    # Scenarios pivot on the NEAREST levels — those get tested first
    resistance_txt = (
        utils.format_price(min(level["price"] for level in resistances))
        if resistances else "recent highs"
    )
    support_txt = (
        utils.format_price(max(level["price"] for level in supports))
        if supports else "recent lows"
    )

    bullish = (
        f"A sustained break and hold above VAH {utils.format_price(profile['vah'])} "
        f"and resistance {resistance_txt}, ideally on rising volume, would open the "
        f"path toward the next resistance cluster. Confirmation matters more than the "
        f"first poke through."
    )
    bearish = (
        f"Losing VAL {utils.format_price(profile['val'])} and support {support_txt} "
        f"on a closing basis would suggest acceptance below value and open room "
        f"toward lower-volume territory, where moves tend to travel faster."
    )
    neutral = (
        f"While price holds between VAL {utils.format_price(profile['val'])} and "
        f"VAH {utils.format_price(profile['vah'])}, rotation around POC "
        f"{utils.format_price(profile['poc'])} is the base case — range-trading "
        f"conditions, mean-reversion favored over breakout chasing."
    )
    return {"bullish": bullish, "bearish": bearish, "neutral": neutral}


# ======================================================
# REPORT RENDERING
# ======================================================
def _render_levels(levels: list[dict]) -> str:
    """Renders S/R levels as a markdown bullet list with strength markers."""
    if not levels:
        return "- (none detected)\n"
    lines = []
    for level in levels:
        stars = "★" * min(int(round(level["strength"])), 5)
        lines.append(f"- {utils.format_price(level['price'])}  {stars}")
    return "\n".join(lines) + "\n"


def _render_confluence(confluence: dict | None) -> str:
    """Renders the multi-timeframe confluence section (empty when absent)."""
    if not confluence:
        return ""
    lines = ["\n## Multi-Timeframe Confluence",
             "| Timeframe | Trend | Structure | RSI | MACD | vs POC | Divergence |",
             "|---|---|---|---|---|---|---|"]
    for row in confluence["rows"]:
        lines.append(
            f"| {row['timeframe']} | {row['trend']} | {row['structure']} | "
            f"{row['rsi']:.0f} | {row['macd_state']} | {row['price_vs_poc']} | "
            f"{row['divergence']} |"
        )
    lines.append(f"\n**Verdict:** {confluence['verdict']} (score {confluence['total_score']:+d})")
    return "\n".join(lines) + "\n"


def generate_report(
    analysis: dict, summary_text: str = "", confluence: dict | None = None
) -> str:
    """
    Renders the standard market report from an analysis dict, saves it to
    output/reports/, and returns the markdown text.
    `summary_text` — the narrative from the AI layer (optional).
    `confluence` — result of confluence.run_confluence() (optional).
    """
    profile = analysis["volume_profile"]
    momentum_result = analysis["momentum"]
    trend_result = analysis["trend"]
    structure_result = analysis["structure"]
    risk = analysis["risk"]
    scenarios = _build_scenarios(analysis)
    timestamp = analysis["generated_at"].strftime("%Y-%m-%d %H:%M UTC")

    last_event = structure_result["last_event"]
    last_event_txt = (
        f"{last_event['kind']} ({last_event['direction']}) at "
        f"{utils.format_price(last_event['price'])}"
        if last_event
        else "None detected in window"
    )

    report = f"""# {analysis['symbol']} Market Report

**Generated:** {timestamp}
**Timeframe:** {analysis['timeframe']}
**Current Price:** {utils.format_price(analysis['price'])}
**Trend:** {trend_result['trend']}

## Volume Profile
- **POC:** {utils.format_price(profile['poc'])}
- **VAH:** {utils.format_price(profile['vah'])}
- **VAL:** {utils.format_price(profile['val'])}
- Price is **{profile['price_vs_poc']}** the POC, {'inside' if profile['inside_value_area'] else 'outside'} the value area
- HVNs: {', '.join(utils.format_price(p) for p in profile['hvn'][:5]) or 'none'}
- LVNs: {', '.join(utils.format_price(p) for p in profile['lvn'][:5]) or 'none'}

## Support Levels
{_render_levels(analysis['levels']['supports'])}
## Resistance Levels
{_render_levels(analysis['levels']['resistances'])}
## Indicators
- **RSI:** {momentum_result['rsi']:.1f} — {momentum_result['rsi_state']}
- **MACD:** {momentum_result['macd_state']} (histogram {momentum_result['macd_hist']:+.2f})
- **Stoch RSI:** %K {momentum_result['stoch_rsi_k']:.0f} / %D {momentum_result['stoch_rsi_d']:.0f}
- **Divergence:** {(momentum_result['divergence']['type'] or 'none').capitalize()}{' — ' + momentum_result['divergence']['detail'] if momentum_result['divergence']['type'] else ''}
- **VWAP:** session {utils.format_price(analysis['vwap']['vwap_session'])} — price is **{analysis['vwap']['price_vs_vwap']}** it; anchored {utils.format_price(analysis['vwap']['vwap_anchored'])} (from {analysis['vwap']['anchor_time'].strftime('%Y-%m-%d %H:%M UTC')})
- **EMA trend:** {trend_result['ema_alignment']}
- **ADX:** {trend_result['adx']:.1f} ({'trending' if trend_result['adx'] >= config.ADX_TREND_THRESHOLD else 'weak trend / ranging'})
- **ATR:** {utils.format_price(analysis['volatility']['atr'])} ({analysis['volatility']['atr_pct']:.2%} of price)
- **Bollinger:** position {analysis['volatility']['bb_position']:.0%} of band{' — squeeze active' if analysis['volatility']['bb_squeeze'] else ''}

## Market Structure
- **State:** {structure_result['structure']}
- **Last event:** {last_event_txt}
{_render_confluence(confluence)}
## Analysis Summary
{summary_text or '_No narrative generated._'}

## Risk Level: {risk['level']}
{chr(10).join('- ' + reason for reason in risk['reasons']) or '- No specific risk flags'}

## Possible Scenarios
1. **Bullish:** {scenarios['bullish']}
2. **Bearish:** {scenarios['bearish']}
3. **Neutral:** {scenarios['neutral']}

---
*This report describes current market conditions and probabilities. It is not
financial advice and makes no claim to predict future prices.*
"""

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    safe_symbol = analysis["symbol"].replace("/", "-")
    filename = (
        f"{safe_symbol}_{analysis['timeframe']}_"
        f"{analysis['generated_at'].strftime('%Y%m%d_%H%M')}.md"
    )
    report_path = os.path.join(config.REPORT_DIR, filename)
    with open(report_path, "w", encoding="utf-8") as report_file:
        report_file.write(report)
    logging.info("Report saved: %s", report_path)

    return report
