from adapters.binance_short_manager import BinanceShortManager
from adapters.binance_candle_streamer import BinanceCandleStreamer
from core.hedge_state_machine_with_execution import HedgeStateMachineWithExecution
from entities.hedge_config_entity import HedgeConfig
from infrastructure.settings import settings

async def start_hedge_execution(config: HedgeConfig):
    manager = BinanceShortManager(settings.BINANCE_KEY, settings.BINANCE_SECRET)
    await manager.__aenter__()

    hedge = HedgeStateMachineWithExecution(
        binance_manager=manager,
        config = config
    )

    streamer = BinanceCandleStreamer(config.symbol, hedge, config.rebalance_threshold_usd)
    await streamer.start()
