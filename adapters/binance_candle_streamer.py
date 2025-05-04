import asyncio
from binance import BinanceSocketManager, AsyncClient
import pandas as pd
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
        """
        Streamer assíncrono de candles da Binance para um símbolo específico.

        Args:
            symbol (str): Par de trading, ex: 'BTCUSDT'
        """
        self.symbol = symbol.lower()
        self.client = None
        self.bm = None
        self.df = pd.DataFrame(columns=[
            "time", "close",
            "quantity_token1", "quantity_token2",
            "value_token1_usd", "value_token2_usd",
            "total_value_usd", "delta_total", "accumulated_fee",
            "short_action", "short_value_usd",
            "short_pnl_usd", "total_accumulated",
            "total_accumulated_with_fee", "short_blocks"
        ])
        self.hedge = hedge_simulator
        self.rebalance_threshold_usd = rebalance_threshold_usd

    async def start(self):
        """Inicializa cliente e começa a escutar candles de 1 minuto."""
        self.client = await AsyncClient.create(settings.BINANCE_KEY, settings.BINANCE_SECRET)
        self.bm = BinanceSocketManager(self.client)

        try:
            async with self.bm.futures_multiplex_socket([f"{self.symbol}@kline_1m"]) as stream:
                print(f"Iniciando stream de 1m para {self.symbol.upper()}...")
                while True:
                    try:
                        msg = await stream.recv()
                        kline = msg["data"]["k"]

                        if kline["x"]:  # Se candle estiver completo
                            await self._process_candle(kline)
                    except Exception as e:
                        print(f"Erro no stream: {e}")
                        break
        except asyncio.CancelledError:
            print("Cancelamento detectado (Ctrl+C). Finalizando stream...")
        finally:
            await self.stop()

    async def _process_candle(self, kline: dict):
        """Processa e armazena um candle fechado."""
        timestamp = pd.to_datetime(kline["t"], unit="ms")
        close = float(kline["c"])
        logger.info("testeeeeeeeeeeee")
        # Executar simulação de hedge e receber entidade
        result: HedgeResult = await self.hedge.on_new_price(
            close_price=close,
            timestamp=timestamp,
            rebalance_threshold_usd=self.rebalance_threshold_usd
        )

    
        # Adiciona a linha ao DataFrame
        self.df.loc[len(self.df)] = result.dict()

        logger.info("\nHedge result", extra=result.dict())

    async def stop(self):
        """Fecha conexão com Binance."""
        if self.client:
            await self.client.close_connection()
