from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

from strategy import BNBTASwapMAStrategy


def _make_strategy(force_action: str = "") -> BNBTASwapMAStrategy:
    return BNBTASwapMAStrategy(
        config={
            "chain": "bsc",
            "base_token": "CAKE",
            "quote_token": "BNB",
            "signal_token": "CAKE",
            "ema_fast_period": 5,
            "ema_slow_period": 10,
            "ema_timeframe": "5m",
            "candle_minutes": 5,
            "trade_size_usd": 100,
            "max_slippage_bps": 50,
            "force_action": force_action,
        },
        chain="bsc",
        wallet_address="0x" + "1" * 40,
    )


def _market(ts: datetime, ema_fast: Decimal, ema_slow: Decimal, bnb_usd: Decimal, cake_usd: Decimal) -> MagicMock:
    market = MagicMock()
    market.timestamp = ts

    def ema_side_effect(token: str, period: int, timeframe: str):
        obj = MagicMock()
        if period == 5:
            obj.value = ema_fast
        elif period == 10:
            obj.value = ema_slow
        else:
            raise ValueError("unsupported period")
        return obj

    market.ema.side_effect = ema_side_effect

    def balance_side_effect(token: str):
        obj = MagicMock()
        obj.balance_usd = bnb_usd if token == "BNB" else cake_usd
        obj.balance = Decimal("1")
        return obj

    market.balance.side_effect = balance_side_effect
    return market


def test_buy_cake_on_bullish_crossover():
    strategy = _make_strategy()
    strategy._state.prev_relation = "below"
    strategy._state.current_side = "BNB"

    market = _market(
        ts=datetime(2026, 1, 1, 12, 5, 0),
        ema_fast=Decimal("10"),
        ema_slow=Decimal("9"),
        bnb_usd=Decimal("1000"),
        cake_usd=Decimal("0"),
    )

    intent = strategy.decide(market)
    assert intent.intent_type.value == "SWAP"
    assert intent.from_token == "BNB"
    assert intent.to_token == "CAKE"


def test_buy_bnb_on_bearish_crossover():
    strategy = _make_strategy()
    strategy._state.prev_relation = "above"
    strategy._state.current_side = "CAKE"

    market = _market(
        ts=datetime(2026, 1, 1, 12, 10, 0),
        ema_fast=Decimal("9"),
        ema_slow=Decimal("10"),
        bnb_usd=Decimal("0"),
        cake_usd=Decimal("1000"),
    )

    intent = strategy.decide(market)
    assert intent.intent_type.value == "SWAP"
    assert intent.from_token == "CAKE"
    assert intent.to_token == "BNB"


def test_hold_when_no_new_crossover():
    strategy = _make_strategy()
    strategy._state.prev_relation = "above"

    market = _market(
        ts=datetime(2026, 1, 1, 12, 15, 0),
        ema_fast=Decimal("11"),
        ema_slow=Decimal("10"),
        bnb_usd=Decimal("1000"),
        cake_usd=Decimal("1000"),
    )

    intent = strategy.decide(market)
    assert intent.intent_type.value == "HOLD"


def test_requires_confirmed_5m_close():
    strategy = _make_strategy()
    strategy._state.prev_relation = "below"

    market = _market(
        ts=datetime(2026, 1, 1, 12, 7, 0),
        ema_fast=Decimal("10"),
        ema_slow=Decimal("9"),
        bnb_usd=Decimal("1000"),
        cake_usd=Decimal("0"),
    )

    intent = strategy.decide(market)
    assert intent.intent_type.value == "HOLD"


def test_no_duplicate_trade_same_candle():
    strategy = _make_strategy()
    strategy._state.prev_relation = "below"
    strategy._state.current_side = "BNB"

    ts = datetime(2026, 1, 1, 12, 20, 0)
    market = _market(
        ts=ts,
        ema_fast=Decimal("10"),
        ema_slow=Decimal("9"),
        bnb_usd=Decimal("1000"),
        cake_usd=Decimal("0"),
    )

    first_intent = strategy.decide(market)
    second_intent = strategy.decide(market)

    assert first_intent.intent_type.value == "SWAP"
    assert second_intent.intent_type.value == "HOLD"


def test_reset_then_fresh_bullish_crossover():
    strategy = _make_strategy()
    strategy._state.prev_relation = "above"
    strategy._state.current_side = "BNB"

    equal_market = _market(
        ts=datetime(2026, 1, 1, 12, 25, 0),
        ema_fast=Decimal("10"),
        ema_slow=Decimal("10"),
        bnb_usd=Decimal("1000"),
        cake_usd=Decimal("0"),
    )
    bullish_market = _market(
        ts=datetime(2026, 1, 1, 12, 30, 0),
        ema_fast=Decimal("11"),
        ema_slow=Decimal("10"),
        bnb_usd=Decimal("1000"),
        cake_usd=Decimal("0"),
    )

    intent_equal = strategy.decide(equal_market)
    intent_bull = strategy.decide(bullish_market)

    assert intent_equal.intent_type.value == "HOLD"
    assert intent_bull.intent_type.value == "SWAP"
    assert intent_bull.to_token == "CAKE"


def test_reset_then_fresh_bearish_crossover():
    strategy = _make_strategy()
    strategy._state.prev_relation = "below"
    strategy._state.current_side = "CAKE"

    equal_market = _market(
        ts=datetime(2026, 1, 1, 12, 35, 0),
        ema_fast=Decimal("10"),
        ema_slow=Decimal("10"),
        bnb_usd=Decimal("0"),
        cake_usd=Decimal("1000"),
    )
    bearish_market = _market(
        ts=datetime(2026, 1, 1, 12, 40, 0),
        ema_fast=Decimal("9"),
        ema_slow=Decimal("10"),
        bnb_usd=Decimal("0"),
        cake_usd=Decimal("1000"),
    )

    intent_equal = strategy.decide(equal_market)
    intent_bear = strategy.decide(bearish_market)

    assert intent_equal.intent_type.value == "HOLD"
    assert intent_bear.intent_type.value == "SWAP"
    assert intent_bear.to_token == "BNB"


def test_hold_when_ema_unavailable():
    strategy = _make_strategy()
    strategy._state.prev_relation = "below"

    market = MagicMock()
    market.timestamp = datetime(2026, 1, 1, 12, 45, 0)
    market.ema.side_effect = ValueError("no ohlcv")

    intent = strategy.decide(market)
    assert intent.intent_type.value == "HOLD"


def test_force_action_buy_cake_bypasses_signal():
    strategy = _make_strategy(force_action="buy_cake")
    market = MagicMock()

    intent = strategy.decide(market)
    assert intent.intent_type.value == "SWAP"
    assert intent.from_token == "BNB"
    assert intent.to_token == "CAKE"


def test_force_action_buy_bnb_bypasses_signal():
    strategy = _make_strategy(force_action="buy_bnb")
    market = MagicMock()

    intent = strategy.decide(market)
    assert intent.intent_type.value == "SWAP"
    assert intent.from_token == "CAKE"
    assert intent.to_token == "BNB"


def test_insufficient_balance_holds():
    strategy = _make_strategy()
    strategy._state.prev_relation = "below"
    strategy._state.current_side = "BNB"

    market = _market(
        ts=datetime(2026, 1, 1, 12, 50, 0),
        ema_fast=Decimal("11"),
        ema_slow=Decimal("10"),
        bnb_usd=Decimal("20"),
        cake_usd=Decimal("0"),
    )

    intent = strategy.decide(market)
    assert intent.intent_type.value == "HOLD"


def test_persistence_round_trip():
    strategy = _make_strategy()
    strategy._state.prev_relation = "equal"
    strategy._state.current_side = "CAKE"
    strategy._state.last_processed_bucket = datetime(2026, 1, 1, 13, 0, 0)

    state = strategy.get_persistent_state()

    fresh = _make_strategy()
    fresh.load_persistent_state(state)

    restored = fresh.get_persistent_state()
    assert restored == state
