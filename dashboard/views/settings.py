"""Settings view — edit alert + strategy settings from the dashboard."""

import streamlit as st

import config
import settings_store
import strategies


def render() -> None:
    """Edit alert + strategy settings from the dashboard (persisted to JSON)."""
    st.caption(
        "Overrides saved here persist to `output/user_settings.json` and are picked "
        "up by the dashboard, the CLI, and the scheduled alert task — no code edits, "
        "no restart. Anything left alone falls back to `config.py`."
    )

    with st.form("settings_form"):
        st.markdown("##### Active strategy")
        specs = strategies.all_specs()
        labels = {spec.label: spec.name for spec in specs}
        current = settings_store.get("ACTIVE_STRATEGY")
        current_label = strategies.spec(current).label
        chosen_label = st.selectbox(
            "Strategy used by chart markers, alerts and backtests",
            list(labels), index=list(labels).index(current_label),
        )
        chosen_strategy = labels[chosen_label]
        chosen_spec = strategies.spec(chosen_strategy)
        st.caption(
            f"{chosen_spec.description}  \n"
            f"**Entry:** {chosen_spec.entry_rule}  \n"
            f"**Exit:** {chosen_spec.exit_rule}  \n"
            f"**Suited to:** {', '.join(chosen_spec.suitable_regimes)} markets"
        )

        st.markdown("##### Alerts")
        columns = st.columns(2)
        alert_symbols = columns[0].multiselect(
            "Symbols to watch", options=config.SYMBOL_CHOICES,
            default=settings_store.get("ALERT_SYMBOLS"),
        )
        alert_timeframes = columns[1].multiselect(
            "Timeframes to watch", options=config.TIMEFRAMES,
            default=settings_store.get("ALERT_TIMEFRAMES"),
            help="Every symbol is checked on every timeframe selected.",
        )
        toggle_columns = st.columns(4)
        alert_on_buy = toggle_columns[0].toggle(
            "Alert on BUY", value=settings_store.get("ALERT_ON_BUY")
        )
        alert_on_sell = toggle_columns[1].toggle(
            "Alert on SELL", value=settings_store.get("ALERT_ON_SELL")
        )
        cooldown = toggle_columns[2].number_input(
            "Cooldown (bars)", min_value=0, max_value=100,
            value=settings_store.get("ALERT_COOLDOWN_BARS"),
        )
        recent = toggle_columns[3].number_input(
            "Signal freshness (bars)", min_value=1, max_value=20,
            value=settings_store.get("ALERT_RECENT_BARS"),
        )

        st.markdown("##### Strategy rules (chart markers, alerts, backtest)")
        rule_columns = st.columns(4)
        rsi_buy = rule_columns[0].slider(
            "BUY when RSI below", 10, 50, settings_store.get("BACKTEST_RSI_BUY"), step=5
        )
        rsi_sell = rule_columns[1].slider(
            "SELL when RSI above", 50, 90, settings_store.get("BACKTEST_RSI_SELL"), step=5
        )
        use_val = rule_columns[2].toggle(
            "BUY only below VAL", value=settings_store.get("BACKTEST_USE_VAL_FILTER")
        )
        use_vah = rule_columns[3].toggle(
            "SELL at VAH", value=settings_store.get("BACKTEST_USE_VAH_TARGET"),
            help="Turning this OFF removes most sell signals — 'price reached VAH' "
                 "fires constantly in an uptrend.",
        )

        saved = st.form_submit_button("💾 Save settings", type="primary")

    if saved:
        settings_store.save_overrides(
            {
                "ACTIVE_STRATEGY": chosen_strategy,
                "ALERT_SYMBOLS": alert_symbols,
                "ALERT_TIMEFRAMES": alert_timeframes,
                "ALERT_ON_BUY": alert_on_buy,
                "ALERT_ON_SELL": alert_on_sell,
                "ALERT_COOLDOWN_BARS": int(cooldown),
                "ALERT_RECENT_BARS": int(recent),
                "BACKTEST_RSI_BUY": int(rsi_buy),
                "BACKTEST_RSI_SELL": int(rsi_sell),
                "BACKTEST_USE_VAL_FILTER": use_val,
                "BACKTEST_USE_VAH_TARGET": use_vah,
            }
        )
        st.cache_data.clear()
        st.success("Settings saved. The next alert check will use them.")

    if st.button("↩️ Reset to config.py defaults"):
        settings_store.reset()
        st.cache_data.clear()
        st.rerun()

    overrides = settings_store.load_overrides()
    if overrides:
        with st.expander(f"Active overrides ({len(overrides)})"):
            st.json(overrides)
