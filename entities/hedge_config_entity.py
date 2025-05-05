from dataclasses import dataclass

@dataclass
class HedgeConfig:
    symbol: str
    qty_token1: float
    min_price: float
    max_price: float
    fee_apr_percent: float
    rebalance_threshold_usd: float
    total_usd_target: float