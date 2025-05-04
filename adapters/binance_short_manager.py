# hedge_binance.py
import math
import copy
from typing import List, Dict, Any, Optional

import pandas as pd
from binance.async_client import AsyncClient
from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_TYPE_MARKET

# -----------------------------------------------------------------------------
# 1. BinanceShortManager
# -----------------------------------------------------------------------------
class BinanceShortManager:
    """
    Thin async wrapper around the Binance Futures API dedicated to *short blocks*.

    It exposes only the primitives needed by simulate_dynamic_hedge_async:
    - open_short  (SELL  → increases notional short)
    - reduce_short (BUY  → decreases / closes part of the short)

    All order‐tracking (orderId, entryPrice) is returned so the caller can
    compute PnL independently if desired.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        tld: str = "com",
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._client: Optional[AsyncClient] = None
        self._tld = tld

    # ----------------------------------------------------------------------
    # LIFECYCLE
    # ----------------------------------------------------------------------
    async def __aenter__(self) -> "BinanceShortManager":
        self._client = await AsyncClient.create(
            self._api_key,
            self._api_secret,
            tld=self._tld,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.close_connection()

    # ----------------------------------------------------------------------
    # PUBLIC ACTIONS
    # ----------------------------------------------------------------------
    async def open_short(
        self, *, symbol: str, quantity: float
    ) -> Dict[str, Any]:
        """
        Market-sells quantity contracts → adds *one* short block.

        Returns the raw Binance order payload (for orderId, price, etc.).
        """
        order = await self._client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=quantity,
            positionSide="SHORT",
        )
        print("order",order)
        return order

    async def reduce_short(
        self, *, symbol: str, quantity: float
    ) -> Dict[str, Any]:
        """
        Market-buys quantity contracts → reduces (or completely closes) shorts.
        """
        order = await self._client.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY,
            type=ORDER_TYPE_MARKET,
            quantity=quantity,
            positionSide="SHORT",
        )
        return order

