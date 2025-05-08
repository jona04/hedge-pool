import asyncio
from adapters.binance_short_manager import BinanceShortManager
from adapters.binance_candle_streamer import BinanceCandleStreamer
from core.hedge_state_machine_with_execution import HedgeStateMachineWithExecution
from infrastructure.settings import settings
from entities.hedge_config_entity import HedgeConfig

hedge_task = None
streamer: BinanceCandleStreamer = None
manager: BinanceShortManager = None

async def start_hedge_execution(config: HedgeConfig):
    global hedge_task, streamer, manager

    if hedge_task and not hedge_task.done():
        return

    manager = BinanceShortManager(settings.BINANCE_KEY, settings.BINANCE_SECRET)
    await manager.__aenter__()

    hedge = HedgeStateMachineWithExecution(binance_manager=manager, config=config)

    streamer = BinanceCandleStreamer(
        symbol=config.symbol,
        hedge_simulator=hedge,
        rebalance_threshold_usd=config.rebalance_threshold_usd
    )

    hedge_task = asyncio.create_task(streamer.start())

async def stop_hedge_execution():
    global hedge_task, streamer, manager

    if streamer:
        await streamer.stop()
        streamer = None

    if hedge_task:
        hedge_task.cancel()
        hedge_task = None

    if manager:
        await manager.__aexit__()
        manager = None
