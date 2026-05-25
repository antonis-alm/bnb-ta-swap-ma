from unittest.mock import MagicMock, patch

from dashboard.ui import (
    STRATEGY_TITLE,
    _build_dashboard_config,
    _ema_signal_message,
    render_custom_dashboard,
)


def test_build_dashboard_config_from_strategy_config():
    strategy_config = {
        "chain": "bsc",
        "protocol": "pancakeswap_v3",
        "base_token": "CAKE",
        "quote_token": "BNB",
        "ema_fast_period": 5,
        "ema_slow_period": 10,
    }

    config = _build_dashboard_config(strategy_config)

    assert config.indicator_name == "EMA Crossover"
    assert config.indicator_period == 5
    assert config.secondary_periods == [10]
    assert config.chain == "bsc"
    assert config.protocol == "pancakeswap_v3"
    assert config.base_token == "CAKE"
    assert config.quote_token == "BNB"


def test_ema_signal_message_uses_relation_and_position():
    assert "Bullish EMA regime" in _ema_signal_message({"prev_relation": "above", "current_side": "CAKE"})
    assert "Bearish EMA regime" in _ema_signal_message({"prev_relation": "below", "current_side": "BNB"})
    assert "Neutral EMA regime" in _ema_signal_message({"prev_relation": "equal", "current_side": "BNB"})
    assert "Waiting for first confirmed EMA relation" in _ema_signal_message({})


def test_render_custom_dashboard_uses_ta_template_pipeline():
    strategy_config = {
        "chain": "bsc",
        "base_token": "CAKE",
        "quote_token": "BNB",
        "ema_fast_period": 5,
        "ema_slow_period": 10,
    }
    session_state = {"prev_relation": "above", "current_side": "CAKE"}
    api_client = MagicMock()
    prepared_state = {"price_history": []}

    with (
        patch("dashboard.ui.st.title") as mock_title,
        patch("dashboard.ui.prepare_ta_session_state", return_value=prepared_state) as mock_prepare,
        patch("dashboard.ui.render_ta_dashboard") as mock_render,
        patch("dashboard.ui._render_positions_and_transactions_history") as mock_history,
    ):
        render_custom_dashboard("strat-1", strategy_config, api_client, session_state)

    mock_title.assert_called_once_with(STRATEGY_TITLE)
    mock_prepare.assert_called_once()
    prepare_args, prepare_kwargs = mock_prepare.call_args
    assert prepare_args[0] is api_client
    assert prepare_kwargs["session_state"] == session_state
    assert prepare_kwargs["config"].indicator_name == "EMA Crossover"

    mock_render.assert_called_once_with("strat-1", strategy_config, prepared_state, prepare_kwargs["config"])
    mock_history.assert_called_once_with(api_client)
