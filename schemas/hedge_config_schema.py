from pydantic import BaseModel, Field

class HedgeConfigSchema(BaseModel):
    symbol: str = Field(..., example="VIRTUALUSDT")
    qty_token1: float = Field(..., example=76.9)
    total_usd_target: float = Field(..., example=300.9)
    min_price: float = Field(..., example=1.57)
    max_price: float = Field(..., example=1.84)
    fee_apr_percent: float = Field(..., example=600.0)
    rebalance_threshold_usd: float = Field(..., example=6.0)
