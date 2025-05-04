from datetime import datetime
from typing import List, Dict, Any
from pydantic import BaseModel


class HedgeResult(BaseModel):
    time: datetime
    close: float
    quantity_token1: float
    quantity_token2: float
    value_token1_usd: float
    value_token2_usd: float
    total_value_usd: float
    delta_total: float
    accumulated_fee: float
    short_action: str
    short_value_usd: float
    short_pnl_usd: float
    total_accumulated: float
    total_accumulated_with_fee: float
    short_blocks: List[Dict[str, Any]]
