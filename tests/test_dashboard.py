from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from dashboard.ui import (
    STRATEGY_TITLE,
    _positions_dataframe,
    _to_float,
    _transactions_dataframe,
    render_custom_dashboard,
)


def test_to_float_handles_supported_types():
    assert _to_float(None) == 0.0
    assert _to_float(12) == 12.0
    assert _to_float("42.5") == 42.5
    assert _to_float("not-a-number") == 0.0


def test_positions_dataframe_builds_active_positions_timeline():
    api_client = MagicMock()
    api_client.get_position_events.return_value = [
        {
            "timestamp": "2026-01-01T00:00:00Z",
            "event_type": "OPEN",
            "position_id": "p1",
            "value_usd": "100",
        },
        {
            "timestamp": "2026-01-01T01:00:00Z",
            "event_type": "CLOSE",
            "position_id": "p1",
            "value_usd": "110",
        },
    ]

    frame = _positions_dataframe(api_client)

    assert list(frame["active_positions"]) == [1, 0]
    assert list(frame["value_usd"]) == [100.0, 110.0]


def test_transactions_dataframe_builds_notional_and_gas_metrics():
    row = SimpleNamespace(
        id="r1",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        cycle_id="cycle-1",
        intent_type="SWAP",
        token_in="BNB",
        amount_in="1",
        token_out="CAKE",
        amount_out="20",
        amount_in_usd="10",
        amount_out_usd="11",
        gas_usd="0.2",
        protocol="pancakeswap_v3",
        chain="bsc",
        success=True,
        tx_hash="0xabc",
        error="",
    )

    api_client = MagicMock()
    api_client._client = None
    api_client._deployment_id = ""
    api_client.get_trade_tape.return_value = SimpleNamespace(rows=[row], has_more=False)

    frame, truncated = _transactions_dataframe(api_client)

    assert not truncated
    assert float(frame["notional_usd"].iloc[0]) == 11.0
    assert float(frame["cumulative_gas_usd"].iloc[0]) == 0.2


class _FakeTab:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_render_custom_dashboard_uses_custom_sections():
    strategy_config = {"chain": "bsc", "base_token": "CAKE", "quote_token": "BNB"}
    session_state = {"prev_relation": "above", "current_side": "CAKE"}
    api_client = MagicMock()

    with (
        patch("dashboard.ui.st.title") as mock_title,
        patch("dashboard.ui.st.tabs", return_value=[_FakeTab(), _FakeTab()]) as mock_tabs,
        patch("dashboard.ui._render_overview") as mock_overview,
        patch("dashboard.ui._positions_dataframe", return_value="positions") as mock_pos_df,
        patch("dashboard.ui._transactions_dataframe", return_value=("tx", False)) as mock_tx_df,
        patch("dashboard.ui._render_positions") as mock_render_positions,
        patch("dashboard.ui._render_transactions") as mock_render_transactions,
    ):
        render_custom_dashboard("strat-1", strategy_config, api_client, session_state)

    mock_title.assert_called_once_with(STRATEGY_TITLE)
    mock_tabs.assert_called_once_with(["Positions", "Transactions"])
    mock_overview.assert_called_once_with(strategy_config, session_state)
    mock_pos_df.assert_called_once_with(api_client)
    mock_tx_df.assert_called_once_with(api_client)
    mock_render_positions.assert_called_once_with("positions")
    mock_render_transactions.assert_called_once_with("tx", False)
