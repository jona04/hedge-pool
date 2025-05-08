import asyncio
import pandas as pd
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from binance import BinanceSocketManager, AsyncClient

from core.hedge_state_machine_with_execution import HedgeStateMachineWithExecution
from infrastructure.logger_config import logger
from infrastructure.settings import settings
from entities.hedge_result_entity import HedgeResult


class BinanceCandleStreamer:
    def __init__(
        self,
        symbol: str,
        hedge_simulator: HedgeStateMachineWithExecution,
        rebalance_threshold_usd: float,
    ):
        self.symbol = symbol.lower()
        self.client = None
        self.bm = None
        self.hedge = hedge_simulator
        self.rebalance_threshold_usd = rebalance_threshold_usd
        self._last_close_price = None
        self.scheduler = AsyncIOScheduler()
        self.df = pd.DataFrame(columns=[
            "time", "close",
            "quantity_token1", "quantity_token2",
            "value_token1_usd", "value_token2_usd",
            "total_value_usd", "delta_total", "accumulated_fee",
            "short_action", "short_value_usd",
            "short_pnl_usd", "total_accumulated",
            "total_accumulated_with_fee", "short_blocks"
        ])

    async def start(self):
        self.client = await AsyncClient.create(settings.BINANCE_KEY, settings.BINANCE_SECRET)
        self.bm = BinanceSocketManager(self.client)

        # Inicia execução periódica do hedge
        self.scheduler.add_job(self._execute_hedge, "interval", seconds=5)
        self.scheduler.start()

        # Inicia stream da Binance
        try:
            async with self.bm.futures_multiplex_socket([f"{self.symbol}@kline_1m"]) as stream:
                logger.info(f"Iniciando stream de 1m para {self.symbol.upper()}...")
                while True:
                    try:
                        msg = await stream.recv()
                        kline = msg["data"]["k"]
                        self._last_close_price = float(kline["c"])
                    except Exception as e:
                        logger.error(f"Erro no stream: {e}")
                        break
        except asyncio.CancelledError:
            logger.info("Cancelamento detectado. Finalizando stream...")
        finally:
            await self.stop()

    async def _execute_hedge(self):
        """Executa hedge com o último preço disponível."""
        if self._last_close_price is None:
            return

        timestamp = datetime.utcnow()
        result: HedgeResult = await self.hedge.on_new_price_and_execute(
            close_price=self._last_close_price,
            timestamp=timestamp,
            rebalance_threshold_usd=self.rebalance_threshold_usd
        )
        self.df.loc[len(self.df)] = result.dict()
        logger.info("Hedge result", extra=result.dict())

    async def stop(self):
        self.scheduler.shutdown(wait=False)
        if self.client:
            await self.client.close_connection()
