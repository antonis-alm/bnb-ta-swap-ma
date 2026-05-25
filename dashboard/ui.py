"""Custom Streamlit dashboard for the BNB-TA-Swap-MA strategy."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import streamlit as st


STRATEGY_TITLE = "BNB-TA-Swap-MA Dashboard"
TRADE_PAGE_SIZE = 500
TRADE_MAX_PAGES = 40


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


def _render_overview(strategy_config: dict[str, Any], session_state: dict[str, Any]) -> None:
    chain = str(strategy_config.get("chain", "bsc"))
    protocol = str(strategy_config.get("protocol", "pancakeswap_v3"))
    base = str(strategy_config.get("base_token", "CAKE"))
    quote = str(strategy_config.get("quote_token", "BNB"))
    signal = str(strategy_config.get("signal_token", base))
    fast = int(strategy_config.get("ema_fast_period", 5))
    slow = int(strategy_config.get("ema_slow_period", 10))

    prev_relation = str(session_state.get("prev_relation", "unknown")).upper()
    current_side = str(session_state.get("current_side", quote))

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Chain", chain.upper())
    col_b.metric("Protocol", protocol)
    col_c.metric("Pair", f"{base}/{quote}")

    col_d, col_e, col_f = st.columns(3)
    col_d.metric("Signal Token", signal)
    col_e.metric("EMA Window", f"{fast}/{slow}")
    col_f.metric("Current Side", current_side)

    st.caption(f"Previous relation: {prev_relation}")


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


def _positions_dataframe(api_client: Any) -> pd.DataFrame:
    events = api_client.get_position_events()
    if not events:
        return pd.DataFrame()

    frame = pd.DataFrame(events)
    frame["timestamp"] = pd.to_datetime(frame.get("timestamp"), errors="coerce", utc=True)
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")

    if frame.empty:
        return frame

    frame["event_type"] = frame.get("event_type", "").fillna("UNKNOWN")
    frame["position_id"] = frame.get("position_id", "").fillna("")
    frame["value_usd"] = frame.get("value_usd", "0").map(_to_float)
    frame["delta"] = frame["event_type"].map({"OPEN": 1, "CLOSE": -1}).fillna(0).astype(int)
    frame["active_positions"] = frame["delta"].cumsum().clip(lower=0)

    return frame


def _transactions_dataframe(api_client: Any) -> tuple[pd.DataFrame, bool]:
    rows, truncated = _fetch_all_trade_rows(api_client)
    if not rows:
        return pd.DataFrame(), truncated

    frame = pd.DataFrame(
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

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")
    if frame.empty:
        return frame, truncated

    frame["notional_usd"] = frame[["amount_in_usd", "amount_out_usd"]].max(axis=1)
    frame["cumulative_notional_usd"] = frame["notional_usd"].cumsum()
    frame["cumulative_gas_usd"] = frame["gas_usd"].cumsum()

    return frame, truncated


def _render_positions(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.info("No position events recorded yet.")
        return

    unique_positions = int(frame["position_id"].replace("", pd.NA).dropna().nunique())

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Events", len(frame))
    col_b.metric("Unique Positions", unique_positions)
    col_c.metric("Open Positions", int(frame["active_positions"].iloc[-1]))

    st.markdown("**Active positions over time**")
    st.line_chart(frame.set_index("timestamp")[["active_positions"]], use_container_width=True)

    per_day = (
        frame.set_index("timestamp")
        .groupby("event_type")
        .resample("1D")
        .size()
        .unstack("event_type", fill_value=0)
    )
    if not per_day.empty:
        st.markdown("**Position events per day**")
        st.bar_chart(per_day, use_container_width=True)

    preferred_columns = [
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
    columns = [name for name in preferred_columns if name in frame.columns]
    st.dataframe(frame[columns], hide_index=True, use_container_width=True)


def _render_transactions(frame: pd.DataFrame, truncated: bool) -> None:
    if frame.empty:
        st.info("No transaction history recorded yet.")
        return

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Transactions", len(frame))
    col_b.metric("Total Notional (USD)", f"{frame['notional_usd'].sum():,.2f}")
    col_c.metric("Total Gas (USD)", f"{frame['gas_usd'].sum():,.2f}")

    st.markdown("**Cumulative notional and gas**")
    st.line_chart(
        frame.set_index("timestamp")[["cumulative_notional_usd", "cumulative_gas_usd"]],
        use_container_width=True,
    )

    per_day = frame.set_index("timestamp").resample("1D").size().to_frame("transactions")
    if not per_day.empty:
        st.markdown("**Transactions per day**")
        st.bar_chart(per_day, use_container_width=True)

    if truncated:
        st.warning("Reached pagination limits. Showing newest available transactions.")

    st.dataframe(
        frame[
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


def render_custom_dashboard(
    strategy_id: str,
    strategy_config: dict[str, Any],
    api_client: Any,
    session_state: dict[str, Any],
) -> None:
    del strategy_id

    st.title(STRATEGY_TITLE)
    _render_overview(strategy_config, session_state)

    positions_tab, transactions_tab = st.tabs(["Positions", "Transactions"])
    with positions_tab:
        _render_positions(_positions_dataframe(api_client))

    with transactions_tab:
        tx_frame, truncated = _transactions_dataframe(api_client)
        _render_transactions(tx_frame, truncated)
