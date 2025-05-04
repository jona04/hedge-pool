from core.hedge_state_machine import HedgeStateMachine
from adapters.binance_short_manager import BinanceShortManager
from entities.hedge_config_entity import HedgeConfig
from infrastructure.logger_config import trade_logger
from entities.hedge_result_entity import HedgeResult


class HedgeStateMachineWithExecution(HedgeStateMachine):
    def __init__(self, binance_manager: BinanceShortManager, config: HedgeConfig):
        super().__init__(
            qty_token1=config.qty_token1,
            qty_token2=config.qty_token2,
            min_price=config.min_price,
            max_price=config.max_price,
            fee_apr_percent=config.fee_apr_percent,
        )
        self.symbol = config.symbol
        self.manager = binance_manager
        self.price_precision = 1

    async def on_new_price(self, close_price, timestamp, rebalance_threshold_usd=0.0) -> HedgeResult:
        result = super().on_new_price(close_price, timestamp, rebalance_threshold_usd)

        action = result.short_action
        short_blocks = result.short_blocks

        try:
            if action == "open":
                qty = round(result.value_token1_usd / close_price, self.price_precision)
                await self.manager.open_short(symbol=self.symbol, quantity=qty)
                trade_logger.info({
                    "action": action,
                    "symbol": self.symbol,
                    "qty": qty,
                    "price": close_price,
                    "value_usd": result.value_token1_usd,
                    "short_blocks": short_blocks,
                    "timestamp": timestamp.isoformat()
                })

            elif action == "increase":
                added_value = short_blocks[-1]["value"]
                qty = round(added_value / close_price, self.price_precision)
                await self.manager.open_short(symbol=self.symbol, quantity=qty)
                trade_logger.info({
                    "action": action,
                    "symbol": self.symbol,
                    "qty": qty,
                    "price": close_price,
                    "value_usd": added_value,
                    "short_blocks": short_blocks,
                    "timestamp": timestamp.isoformat()
                })

            elif action == "decrease":
                previous_value = sum(b["value"] for b in self.short_blocks)
                target_value = result.value_token1_usd
                excess_value = previous_value - target_value
                qty = round(excess_value / close_price, self.price_precision)
                await self.manager.reduce_short(symbol=self.symbol, quantity=qty)
                trade_logger.info({
                    "action": action,
                    "symbol": self.symbol,
                    "qty": qty,
                    "price": close_price,
                    "previous_value": previous_value,
                    "target_value": target_value,
                    "excess_value": excess_value,
                    "short_blocks": short_blocks,
                    "timestamp": timestamp.isoformat()
                })

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
