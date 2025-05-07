from core.hedge_state_machine import HedgeStateMachine
from adapters.binance_short_manager import BinanceShortManager
from entities.hedge_config_entity import HedgeConfig
from infrastructure.logger_config import trade_logger, logger
from entities.hedge_result_entity import HedgeResult
import asyncio


class HedgeStateMachineWithExecution(HedgeStateMachine):
    def __init__(self, binance_manager: BinanceShortManager, config: HedgeConfig):
        super().__init__(
            qty_token1=config.qty_token1,
            min_price=config.min_price,
            max_price=config.max_price,
            total_usd_target=config.total_usd_target,
            fee_apr_percent=config.fee_apr_percent
        )
        self.symbol = config.symbol
        self.manager = binance_manager
        self.price_precision = 1
        self._execution_lock = asyncio.Lock()

    async def on_new_price_and_execute(self, close_price, timestamp, rebalance_threshold_usd=0.0) -> HedgeResult:
        async with self._execution_lock:
            result = await super().on_new_price(close_price, timestamp, rebalance_threshold_usd)

            action = result.short_action
            short_blocks = result.short_blocks
            try:
                if action == "open":
                    qty = round(result.value_token1_usd / close_price, self.price_precision)

                    trade_logger.info({
                        "action": action,
                        "symbol": self.symbol,
                        "qty": qty,
                        "price": close_price,
                        "value_usd": result.value_token1_usd,
                        "short_blocks": short_blocks,
                        "timestamp": timestamp.isoformat()
                    })

                    await self.manager.open_short(symbol=self.symbol, quantity=qty)

                elif action == "increase":
                    added_value = short_blocks[-1]["value"]
                    qty = round(added_value / close_price, self.price_precision)

                    trade_logger.info({
                        "action": action,
                        "symbol": self.symbol,
                        "qty": qty,
                        "price": close_price,
                        "value_usd": added_value,
                        "short_blocks": short_blocks,
                        "timestamp": timestamp.isoformat()
                    })

                    await self.manager.open_short(symbol=self.symbol, quantity=qty)

                elif action == "decrease":
                    excess_value = self._last_decrease_usd
                    qty = round(excess_value / close_price, self.price_precision)

                    trade_logger.info({
                        "action": action,
                        "symbol": self.symbol,
                        "qty": qty,
                        "price": close_price,
                        "excess_value": excess_value,
                        "short_blocks": short_blocks,
                        "timestamp": timestamp.isoformat()
                    })

                    await self.manager.reduce_short(symbol=self.symbol, quantity=qty)

            except Exception as e:
                trade_logger.error({
                    "action": action,
                    "symbol": self.symbol,
                    "price": close_price,
                    "short_blocks": short_blocks,
                    "error": str(e),
                    "message": "Necessario intervenção manual.",
                    "timestamp": timestamp.isoformat()
                })

            return result
