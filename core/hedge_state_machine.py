import math
import copy
from datetime import datetime
from typing import List

import pandas as pd

from entities.hedge_result_entity import HedgeResult


class HedgeStateMachine:
    def __init__(self, qty_token1, qty_token2, min_price, max_price, fee_apr_percent=0.0):
        self.qty_token1 = qty_token1
        self.qty_token2 = qty_token2
        self.min_price = min_price
        self.max_price = max_price
        self.fee_apr_percent = fee_apr_percent

        self.short_blocks: List[dict] = []
        self.last_total_value = None
        self.initial_value = None
        self.accumulated_fee = 0.0
        self.results = []
        self.initial_total = None

        sqrt_Pa = math.sqrt(self.min_price)
        sqrt_Pb = math.sqrt(self.max_price)
        sqrt_P_mid = math.sqrt((self.min_price + self.max_price) / 2)

        L_from_token1 = qty_token1 / (1 / sqrt_P_mid - 1 / sqrt_Pb)
        L_from_token2 = qty_token2 / (sqrt_P_mid - sqrt_Pa)
        self.L = (L_from_token1 + L_from_token2) / 2

        self.sqrt_Pa = sqrt_Pa
        self.sqrt_Pb = sqrt_Pb

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

    def on_new_price(self, close_price: float, timestamp: datetime, rebalance_threshold_usd: float = 10.0) -> HedgeResult:
        token1, token2, value_token1, value_token2, total_value = self._calculate_lp_values(close_price)

        if self.last_total_value is None:
            self.short_blocks.append({"price": close_price, "value": value_token1})
            self.last_total_value = total_value
            self.initial_value = total_value
            action = "open"
            pnl_total = 0.0
            delta_total = 0.0
        else:
            delta_total = total_value - self.last_total_value
            pnl_total = sum(
                block["value"] * ((block["price"] - close_price) / block["price"])
                for block in self.short_blocks
            )
            action = "none"

            if self.fee_apr_percent > 0:
                fee_rate_minute = (self.fee_apr_percent / 100) / 525600
                self.accumulated_fee += self.initial_total * fee_rate_minute

            if delta_total <= -rebalance_threshold_usd:
                added_value = value_token1 - sum(b["value"] for b in self.short_blocks)
                if added_value > rebalance_threshold_usd:
                    self.short_blocks.append({"price": close_price, "value": added_value})
                    action = "increase"
                    self.last_total_value = total_value

            elif sum(b["value"] for b in self.short_blocks) > 0 and delta_total >= rebalance_threshold_usd:
                current_total_value = sum(b["value"] for b in self.short_blocks)
                target_value = value_token1
                reduction = current_total_value - target_value
                if reduction > rebalance_threshold_usd:
                    action = "decrease"
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
                    self.last_total_value = total_value

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
            delta_total=round(delta_total, 2),
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
