"""Dashboard UI for the BNB-TA-Swap-MA strategy."""

from __future__ import annotations

from typing import Any

import streamlit as st

from almanak.framework.dashboard.templates import (
    TADashboardConfig,
    prepare_ta_session_state,
    render_ta_dashboard,
)


STRATEGY_TITLE = "BNB-TA-Swap-MA Dashboard"


def _ema_signal_message(session_state: dict[str, Any]) -> str:
    prev_relation = str(session_state.get("prev_relation", "unknown")).lower()
    current_side = str(session_state.get("current_side", "BNB"))

    if prev_relation == "above":
        return f"Bullish EMA regime (fast EMA > slow EMA). Current side: {current_side}."
    if prev_relation == "below":
        return f"Bearish EMA regime (fast EMA < slow EMA). Current side: {current_side}."
    if prev_relation == "equal":
        return f"Neutral EMA regime (fast EMA == slow EMA). Current side: {current_side}."
    return "Waiting for first confirmed EMA relation."


def _build_dashboard_config(strategy_config: dict[str, Any]) -> TADashboardConfig:
    fast_period = int(strategy_config.get("ema_fast_period", 5))
    slow_period = int(strategy_config.get("ema_slow_period", 10))

    return TADashboardConfig(
        indicator_name="EMA Crossover",
        indicator_period=fast_period,
        secondary_periods=[slow_period],
        signal_type="momentum",
        value_format="{:.4f}",
        custom_signal_fn=_ema_signal_message,
        chain=str(strategy_config.get("chain", "bsc")),
        protocol=str(strategy_config.get("protocol", "pancakeswap_v3")),
        base_token=str(strategy_config.get("base_token", "CAKE")),
        quote_token=str(strategy_config.get("quote_token", "BNB")),
    )


def render_custom_dashboard(
    strategy_id: str,
    strategy_config: dict[str, Any],
    api_client: Any,
    session_state: dict[str, Any],
) -> None:
    st.title(STRATEGY_TITLE)

    config = _build_dashboard_config(strategy_config)
    prepared_state = prepare_ta_session_state(
        api_client,
        session_state=session_state,
        config=config,
    )

    render_ta_dashboard(strategy_id, strategy_config, prepared_state, config)
