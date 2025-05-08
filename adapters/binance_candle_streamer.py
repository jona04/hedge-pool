import asyncio
from typing import Optional

import pandas as pd
from datetime import datetime, timedelta
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
        hedge_interval_seconds: int = 10
    ):
        self.symbol = symbol.lower()
        self.client = None
        self.bm = None
        self.hedge = hedge_simulator
        self.rebalance_threshold_usd = rebalance_threshold_usd
        self._last_hedge_time: Optional[datetime] = None
        self.hedge_interval = hedge_interval_seconds
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

        # Inicia stream da Binance
        try:
            async with self.bm.futures_multiplex_socket([f"{self.symbol}@kline_1m"]) as stream:
                logger.info(f"Iniciando stream de 1m para {self.symbol.upper()}...")
                while True:
                    try:
                        msg = await stream.recv()
                        kline = msg.get("data", {}).get("k")
                        if not kline:
                            continue
                        close = float(kline["c"])
                        now = datetime.utcnow()

                        # Executa hedge a cada 5 segundos
                        if (
                            self._last_hedge_time is None or
                            (now - self._last_hedge_time) >= timedelta(seconds=self.hedge_interval)
                        ):
                            self._last_hedge_time = now
                            await self._execute_hedge(close, now)

                    except Exception as e:
                        logger.error(f"Erro no stream: {e}")
                        break
        except asyncio.CancelledError:
            logger.info("Cancelamento detectado. Finalizando stream...")
        finally:
            await self.stop()

    async def _execute_hedge(self, close_price: float, timestamp: datetime):
        """Executa hedge com o último preço disponível."""
        result: HedgeResult = await self.hedge.on_new_price_and_execute(
            close_price=close_price,
            timestamp=timestamp,
            rebalance_threshold_usd=self.rebalance_threshold_usd
        )
        self.df.loc[len(self.df)] = result.dict()
        logger.info("Hedge result", extra=result.dict())

    async def stop(self):
        if self.client:
            await self.client.close_connection()
