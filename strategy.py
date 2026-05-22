import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from almanak.framework.intents import Intent
from almanak.framework.market import MarketSnapshot
from almanak.framework.strategies import StatelessStrategy, almanak_strategy

logger = logging.getLogger(__name__)

RELATION_ABOVE = "above"
RELATION_BELOW = "below"
RELATION_EQUAL = "equal"


@dataclass
class EMAStrategyState:
    prev_relation: str | None = None
    last_processed_bucket: datetime | None = None
    current_side: str = "BNB"


@almanak_strategy(
    name="BNB-TA-Swap-MA",
    description="CAKE/BNB 5m EMA(5/10) crossover swap strategy on PancakeSwap V3 BSC",
    version="1.0.0",
    author="Generated",
    tags=["ema", "swap", "pancakeswap_v3", "bsc"],
    supported_chains=["bsc"],
    supported_protocols=["pancakeswap_v3"],
    intent_types=["SWAP", "HOLD"],
    default_chain="bsc",
)
class BNBTASwapMAStrategy(StatelessStrategy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.base_token = str(self.get_config("base_token", "CAKE"))
        self.quote_token = str(self.get_config("quote_token", "BNB"))
        self.signal_token = str(self.get_config("signal_token", self.base_token))

        self.ema_fast_period = int(self.get_config("ema_fast_period", 5))
        self.ema_slow_period = int(self.get_config("ema_slow_period", 10))
        self.ema_timeframe = str(self.get_config("ema_timeframe", "5m"))
        self.candle_minutes = int(self.get_config("candle_minutes", 5))

        self.trade_size_usd = Decimal(str(self.get_config("trade_size_usd", "100")))
        self.max_slippage_bps = int(self.get_config("max_slippage_bps", 50))
        self.force_action = str(self.get_config("force_action", "")).strip()

        self._state = EMAStrategyState(current_side=self.quote_token)

    def _bucket_start(self, ts: datetime) -> datetime:
        minute = (ts.minute // self.candle_minutes) * self.candle_minutes
        return ts.replace(minute=minute, second=0, microsecond=0)

    @staticmethod
    def _classify_relation(fast: Decimal, slow: Decimal) -> str:
        if fast > slow:
            return RELATION_ABOVE
        if fast < slow:
            return RELATION_BELOW
        return RELATION_EQUAL

    def _forced_intent(self) -> Intent:
        slippage = Decimal(str(self.max_slippage_bps)) / Decimal("10000")
        if self.force_action == "buy_cake":
            return Intent.swap(
                from_token=self.quote_token,
                to_token=self.base_token,
                amount_usd=self.trade_size_usd,
                max_slippage=slippage,
                protocol="pancakeswap_v3",
                chain=self.chain,
            )
        if self.force_action == "buy_bnb":
            return Intent.swap(
                from_token=self.base_token,
                to_token=self.quote_token,
                amount_usd=self.trade_size_usd,
                max_slippage=slippage,
                protocol="pancakeswap_v3",
                chain=self.chain,
            )
        return Intent.hold(reason=f"Unknown force_action: {self.force_action}")

    def _has_balance_for(self, market: MarketSnapshot, token: str) -> bool:
        balance = market.balance(token)
        return balance.balance_usd >= self.trade_size_usd

    def decide(self, market: MarketSnapshot) -> Intent:
        if self.force_action:
            return self._forced_intent()

        ts = market.timestamp
        if ts.minute % self.candle_minutes != 0 or ts.second != 0:
            return Intent.hold(reason="Waiting for confirmed 5m candle close")

        bucket = self._bucket_start(ts)
        if self._state.last_processed_bucket == bucket:
            return Intent.hold(reason="No new closed candle")

        try:
            fast = market.ema(
                self.signal_token,
                period=self.ema_fast_period,
                timeframe=self.ema_timeframe,
            ).value
            slow = market.ema(
                self.signal_token,
                period=self.ema_slow_period,
                timeframe=self.ema_timeframe,
            ).value
        except ValueError as exc:
            self._state.last_processed_bucket = bucket
            return Intent.hold(reason=f"EMA data unavailable: {exc}")

        relation = self._classify_relation(Decimal(str(fast)), Decimal(str(slow)))
        prev_relation = self._state.prev_relation

        self._state.last_processed_bucket = bucket
        self._state.prev_relation = relation

        if prev_relation is None:
            return Intent.hold(reason="Initialized EMA state")

        bullish_cross = prev_relation in (RELATION_BELOW, RELATION_EQUAL) and relation == RELATION_ABOVE
        bearish_cross = prev_relation in (RELATION_ABOVE, RELATION_EQUAL) and relation == RELATION_BELOW

        slippage = Decimal(str(self.max_slippage_bps)) / Decimal("10000")

        if bullish_cross:
            if self._state.current_side == self.base_token:
                return Intent.hold(reason="Already holding CAKE")
            try:
                has_balance = self._has_balance_for(market, self.quote_token)
            except ValueError as exc:
                return Intent.hold(reason=f"Balance unavailable: {exc}")
            if not has_balance:
                return Intent.hold(reason=f"Insufficient {self.quote_token} balance")
            return Intent.swap(
                from_token=self.quote_token,
                to_token=self.base_token,
                amount_usd=self.trade_size_usd,
                max_slippage=slippage,
                protocol="pancakeswap_v3",
                chain=self.chain,
            )

        if bearish_cross:
            if self._state.current_side == self.quote_token:
                return Intent.hold(reason="Already holding BNB")
            try:
                has_balance = self._has_balance_for(market, self.base_token)
            except ValueError as exc:
                return Intent.hold(reason=f"Balance unavailable: {exc}")
            if not has_balance:
                return Intent.hold(reason=f"Insufficient {self.base_token} balance")
            return Intent.swap(
                from_token=self.base_token,
                to_token=self.quote_token,
                amount_usd=self.trade_size_usd,
                max_slippage=slippage,
                protocol="pancakeswap_v3",
                chain=self.chain,
            )

        return Intent.hold(reason="No new EMA crossover")

    def on_intent_executed(self, intent: Intent, success: bool, result: Any) -> None:
        if not success:
            return
        intent_type = getattr(intent, "intent_type", None)
        if not intent_type or getattr(intent_type, "value", "") != "SWAP":
            return

        to_token = getattr(intent, "to_token", None)
        if to_token in (self.base_token, self.quote_token):
            self._state.current_side = to_token

    def get_status(self) -> dict[str, Any]:
        return {
            "strategy": "BNB-TA-Swap-MA",
            "chain": self.chain,
            "base_token": self.base_token,
            "quote_token": self.quote_token,
            "signal_token": self.signal_token,
            "ema_fast_period": self.ema_fast_period,
            "ema_slow_period": self.ema_slow_period,
            "ema_timeframe": self.ema_timeframe,
            "current_side": self._state.current_side,
            "prev_relation": self._state.prev_relation,
            "last_processed_bucket": self._state.last_processed_bucket.isoformat()
            if self._state.last_processed_bucket
            else None,
        }

    def get_persistent_state(self) -> dict[str, Any]:
        return {
            "prev_relation": self._state.prev_relation,
            "last_processed_bucket": self._state.last_processed_bucket.isoformat()
            if self._state.last_processed_bucket
            else None,
            "current_side": self._state.current_side,
        }

    def load_persistent_state(self, state: dict[str, Any]) -> None:
        if not state:
            return
        self._state.prev_relation = state.get("prev_relation")
        bucket = state.get("last_processed_bucket")
        self._state.last_processed_bucket = datetime.fromisoformat(bucket) if bucket else None
        self._state.current_side = state.get("current_side", self.quote_token)
