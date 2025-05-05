import math
import copy
from datetime import datetime
from typing import List, Optional
from scipy.optimize import minimize_scalar

from entities.hedge_result_entity import HedgeResult
from infrastructure.logger_config import logger


class HedgeStateMachine:
    def __init__(
        self,
        qty_token1: float,
        min_price: float,
        max_price: float,
        total_usd_target: float,
        fee_apr_percent: float = 0.0,
    ):
        self.qty_token1 = qty_token1
        self.min_price = min_price
        self.max_price = max_price
        self.fee_apr_percent = fee_apr_percent
        self.total_usd_target = total_usd_target
        self.short_blocks: List[dict] = []
        self.last_value_token1 = None
        self.accumulated_fee = 0.0
        self.results = []
        self.initial_total = None
        self._last_decrease_usd = 0.0

        self.sqrt_Pa = math.sqrt(self.min_price)
        self.sqrt_Pb = math.sqrt(self.max_price)

        self.sqrt_P = None
        self.L = None
        self.first_close_price = None

    def _calculate_adjusted_liquidity(self) -> float:
        def error_total_usd(L):
            token1 = L * (1 / self.sqrt_P - 1 / self.sqrt_Pb)
            token2 = L * (self.sqrt_P - self.sqrt_Pa)
            total = token1 * self.first_close_price + token2
            return abs(total - self.total_usd_target)

        result = minimize_scalar(error_total_usd, bounds=(1e-8, 1e8), method='bounded')
        return result.x

    def _calculate_lp_values(self, close_price: float):
        sqrt_P = math.sqrt(close_price)

        if close_price <= self.min_price:
            token1 = self.L * (1 / self.sqrt_Pa - 1 / self.sqrt_Pb)
            token2 = 0
        elif close_price >= self.max_price:
            token1 = 0
            token2 = self.L * (self.sqrt_Pb - self.sqrt_Pa)
        else:
            token1 = self.L * (1 / sqrt_P - 1 / self.sqrt_Pb)
            token2 = self.L * (sqrt_P - self.sqrt_Pa)

        value_token1 = token1 * close_price
        value_token2 = token2
        total_value = value_token1 + value_token2

        if not self.initial_total:
            self.initial_total = total_value

        return token1, token2, value_token1, value_token2, total_value

    async def on_new_price(self, close_price: float, timestamp: datetime, rebalance_threshold_usd: float = 10.0) -> HedgeResult:

        if self.first_close_price is None:
            self.first_close_price = close_price
            self.sqrt_P = math.sqrt(close_price)
            self.L = self._calculate_adjusted_liquidity()

        token1, token2, value_token1, value_token2, total_value = self._calculate_lp_values(close_price)

        if self.last_value_token1 is None:
            self.short_blocks.append({"price": close_price, "value": value_token1})
            self.last_value_token1 = value_token1
            action = "open"
            pnl_total = 0.0
            delta_token1 = 0.0
        else:
            delta_token1 = value_token1 - self.last_value_token1
            pnl_total = sum(
                block["value"] * ((block["price"] - close_price) / block["price"])
                for block in self.short_blocks
            )
            action = "none"

            if self.fee_apr_percent > 0:
                fee_rate_minute = (self.fee_apr_percent / 100) / 525600
                self.accumulated_fee += self.initial_total * fee_rate_minute

            if delta_token1 >= rebalance_threshold_usd:
                added_value = value_token1 - sum(b["value"] for b in self.short_blocks)
                if added_value > rebalance_threshold_usd:
                    self.short_blocks.append({"price": close_price, "value": added_value})
                    action = "increase"
                    self.last_value_token1 = value_token1

            elif delta_token1 <= -rebalance_threshold_usd:
                current_total_value_token1 = sum(b["value"] for b in self.short_blocks)
                target_value = value_token1
                reduction = current_total_value_token1 - target_value
                if reduction > rebalance_threshold_usd:
                    action = "decrease"
                    self._last_decrease_usd = reduction
                    new_blocks = []
                    for block in reversed(self.short_blocks):
                        if reduction <= 0:
                            new_blocks.insert(0, block)
                            continue
                        if block["value"] <= reduction:
                            reduction -= block["value"]
                        else:
                            block["value"] -= reduction
                            reduction = 0
                            new_blocks.insert(0, block)
                    self.short_blocks = new_blocks
                    self.last_value_token1 = value_token1

        short_value = sum(b["value"] for b in self.short_blocks)
        total_acumulated = total_value + pnl_total
        total_fee_acumulated = total_acumulated + self.accumulated_fee

        result = HedgeResult(
            time=timestamp,
            close=close_price,
            quantity_token1=round(token1, 2),
            quantity_token2=round(token2, 2),
            value_token1_usd=round(value_token1, 2),
            value_token2_usd=round(value_token2, 2),
            total_value_usd=round(total_value, 2),
            delta_total=round(delta_token1, 2),
            accumulated_fee=round(self.accumulated_fee, 3),
            short_action=action,
            short_value_usd=round(short_value, 2),
            short_pnl_usd=round(pnl_total, 2),
            total_accumulated=round(total_acumulated, 2),
            total_accumulated_with_fee=round(total_fee_acumulated, 2),
            short_blocks=copy.deepcopy(self.short_blocks),
        )

        self.results.append(result)
        return result
