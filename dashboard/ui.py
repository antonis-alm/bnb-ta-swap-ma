"""Dashboard UI for the BNB-TA-Swap-MA strategy."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import streamlit as st

from almanak.framework.dashboard.templates import (
    TADashboardConfig,
    prepare_ta_session_state,
    render_ta_dashboard,
)


STRATEGY_TITLE = "BNB-TA-Swap-MA Dashboard"
TRADE_PAGE_SIZE = 500
TRADE_MAX_PAGES = 40


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


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return 0.0


def _fetch_all_trade_rows(api_client: Any) -> tuple[list[Any], bool]:
    gateway_client = getattr(api_client, "_client", None)
    deployment_id = getattr(api_client, "_deployment_id", "")
    if not gateway_client or not deployment_id:
        response = api_client.get_trade_tape(limit=TRADE_PAGE_SIZE)
        return list(getattr(response, "rows", []) or []), bool(getattr(response, "has_more", False))

    rows: list[Any] = []
    before = None
    truncated = False

    for _ in range(TRADE_MAX_PAGES):
        response = gateway_client.get_trade_tape(
            deployment_id,
            limit=TRADE_PAGE_SIZE,
            before=before,
        )
        batch = list(getattr(response, "rows", []) or [])
        if not batch:
            break
        rows.extend(batch)
        if not getattr(response, "has_more", False):
            break
        timestamps = [r.timestamp for r in batch if getattr(r, "timestamp", None) is not None]
        if not timestamps:
            truncated = True
            break
        before = min(timestamps) - timedelta(microseconds=1)
    else:
        truncated = True

    seen: set[str] = set()
    unique_rows: list[Any] = []
    for row in rows:
        row_id = str(getattr(row, "id", ""))
        if row_id and row_id in seen:
            continue
        if row_id:
            seen.add(row_id)
        unique_rows.append(row)
    return unique_rows, truncated


def _render_positions_history(api_client: Any) -> None:
    st.subheader("All Position Events")
    events = api_client.get_position_events()
    if not events:
        st.info("No position events recorded yet.")
        return

    events_df = pd.DataFrame(events)
    events_df["timestamp"] = pd.to_datetime(events_df.get("timestamp"), errors="coerce", utc=True)
    events_df = events_df.dropna(subset=["timestamp"]).sort_values("timestamp")

    if events_df.empty:
        st.info("Position events are present but missing valid timestamps.")
        return

    events_df["event_type"] = events_df.get("event_type", "").fillna("UNKNOWN")
    events_df["position_id"] = events_df.get("position_id", "").fillna("")
    events_df["value_usd"] = events_df.get("value_usd", "0").map(_to_float)
    events_df["delta"] = events_df["event_type"].map({"OPEN": 1, "CLOSE": -1}).fillna(0).astype(int)
    events_df["active_positions"] = events_df["delta"].cumsum().clip(lower=0)

    total_positions = int(events_df["position_id"].replace("", pd.NA).dropna().nunique())
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Events", len(events_df))
    col_b.metric("Unique Positions", total_positions)
    col_c.metric("Open Positions (timeline)", int(events_df["active_positions"].iloc[-1]))

    st.markdown("**Active positions over time**")
    st.line_chart(events_df.set_index("timestamp")[["active_positions"]], use_container_width=True)

    daily_event_counts = (
        events_df.set_index("timestamp")
        .groupby("event_type")
        .resample("1D")
        .size()
        .unstack("event_type", fill_value=0)
    )
    if not daily_event_counts.empty:
        st.markdown("**Position events per day**")
        st.bar_chart(daily_event_counts, use_container_width=True)

    table_columns = [
        "timestamp",
        "position_id",
        "position_type",
        "event_type",
        "chain",
        "protocol",
        "token0",
        "token1",
        "amount0",
        "amount1",
        "value_usd",
        "tx_hash",
    ]
    available_columns = [col for col in table_columns if col in events_df.columns]
    st.dataframe(events_df[available_columns], hide_index=True, use_container_width=True)


def _render_transactions_history(api_client: Any) -> None:
    st.subheader("All Transactions")
    rows, truncated = _fetch_all_trade_rows(api_client)
    if not rows:
        st.info("No transaction history recorded yet.")
        return

    tx_df = pd.DataFrame(
        [
            {
                "timestamp": getattr(row, "timestamp", None),
                "cycle_id": getattr(row, "cycle_id", ""),
                "intent_type": getattr(row, "intent_type", ""),
                "token_in": getattr(row, "token_in", ""),
                "amount_in": getattr(row, "amount_in", ""),
                "token_out": getattr(row, "token_out", ""),
                "amount_out": getattr(row, "amount_out", ""),
                "amount_in_usd": _to_float(getattr(row, "amount_in_usd", "0")),
                "amount_out_usd": _to_float(getattr(row, "amount_out_usd", "0")),
                "gas_usd": _to_float(getattr(row, "gas_usd", "0")),
                "protocol": getattr(row, "protocol", ""),
                "chain": getattr(row, "chain", ""),
                "success": bool(getattr(row, "success", False)),
                "tx_hash": getattr(row, "tx_hash", ""),
                "error": getattr(row, "error", ""),
            }
            for row in rows
        ]
    )

    tx_df["timestamp"] = pd.to_datetime(tx_df["timestamp"], errors="coerce", utc=True)
    tx_df = tx_df.dropna(subset=["timestamp"]).sort_values("timestamp")

    if tx_df.empty:
        st.info("Transactions are present but missing valid timestamps.")
        return

    tx_df["notional_usd"] = tx_df[["amount_in_usd", "amount_out_usd"]].max(axis=1)
    tx_df["cumulative_notional_usd"] = tx_df["notional_usd"].cumsum()
    tx_df["cumulative_gas_usd"] = tx_df["gas_usd"].cumsum()

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Transactions", len(tx_df))
    col_b.metric("Total Notional (USD)", f"{tx_df['notional_usd'].sum():,.2f}")
    col_c.metric("Total Gas (USD)", f"{tx_df['gas_usd'].sum():,.2f}")

    st.markdown("**Cumulative transaction notional and gas**")
    st.line_chart(
        tx_df.set_index("timestamp")[["cumulative_notional_usd", "cumulative_gas_usd"]],
        use_container_width=True,
    )

    tx_counts = tx_df.set_index("timestamp").resample("1D").size().to_frame("transactions")
    if not tx_counts.empty:
        st.markdown("**Transactions per day**")
        st.bar_chart(tx_counts, use_container_width=True)

    if truncated:
        st.warning("Transaction history reached dashboard pagination limits. Showing the newest available rows.")

    st.dataframe(
        tx_df[
            [
                "timestamp",
                "cycle_id",
                "intent_type",
                "token_in",
                "amount_in",
                "token_out",
                "amount_out",
                "amount_in_usd",
                "amount_out_usd",
                "gas_usd",
                "protocol",
                "chain",
                "success",
                "tx_hash",
                "error",
            ]
        ],
        hide_index=True,
        use_container_width=True,
    )


def _render_positions_and_transactions_history(api_client: Any) -> None:
    st.divider()
    st.header("Positions & Transactions History")
    _render_positions_history(api_client)
    st.divider()
    _render_transactions_history(api_client)


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
    _render_positions_and_transactions_history(api_client)
