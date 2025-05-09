# core/hedge_state_machine_with_execution.py
import asyncio
from datetime import datetime

from adapters.binance_short_manager import BinanceShortManager
from core.hedge_state_machine import HedgeStateMachine
from entities.hedge_config_entity import HedgeConfig
from infrastructure.logger_config import trade_logger
from entities.hedge_result_entity import HedgeResult


class HedgeStateMachineWithExecution(HedgeStateMachine):
    def __init__(self, binance_manager: BinanceShortManager, config: HedgeConfig):
        super().__init__(
            qty_token1=config.qty_token1,
            min_price=config.min_price,
            max_price=config.max_price,
            total_usd_target=config.total_usd_target,
            fee_apr_percent=config.fee_apr_percent,
        )
        self.symbol = config.symbol
        self.manager = binance_manager
        self.price_precision = 1
        self._execution_lock = asyncio.Lock()

    async def on_new_price_and_execute(
        self,
        close_price: float,
        timestamp: datetime,
        rebalance_threshold_usd: float,
        hedge_interval: int,
    ) -> HedgeResult:
        async with self._execution_lock:
            result = await super().on_new_price(
                close_price,
                timestamp,
                rebalance_threshold_usd,
                hedge_interval,
            )

            act = result.short_action
            if act == "hold":
                return result  # nada a fazer

            # cálculo único de qty de acordo com a ação -------------------------
            if act == "open":
                qty = round(result.short_value_usd / close_price, self.price_precision)

            elif act == "increase":
                qty = round(result.short_blocks[-1]["value"] / close_price, self.price_precision)

            elif act == "decrease":
                qty = round(self._last_decrease_usd / close_price, self.price_precision)

            elif act == "close":
                qty = round(self._pending_close_usd / close_price, self.price_precision)
                self._pending_close_usd = 0.0

            payload = {
                "action": act,
                "symbol": self.symbol,
                "qty": qty,
                "price": close_price,
                "short_blocks": result.short_blocks,
                "timestamp": timestamp.isoformat(),
            }

            try:
                if qty and qty > 0:
                    if act in {"open", "increase"}:
                        await self.manager.open_short(symbol=self.symbol, quantity=qty)
                    elif act in {"decrease", "close"}:
                        await self.manager.reduce_short(symbol=self.symbol, quantity=qty)

            except Exception as e:
                payload["error"] = str(e)
                payload["message"] = "Necessário intervenção manual."
                trade_logger.error(payload)

            return result
