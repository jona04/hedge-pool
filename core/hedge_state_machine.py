# core/hedge_state_machine.py
import math, copy
from datetime import datetime
from typing import List, Optional

from scipy.optimize import minimize_scalar
from entities.hedge_result_entity import HedgeResult


class HedgeStateMachine:
    """
    Estratégia bidirecional (hedge para BAIXO e para CIMA).

    • price_reference  ...........  preço da pool na abertura
    • rebalance_threshold_usd ....  variação mínima em USD (Token1) p/ agir
    • modo None  → ainda sem hedge
      modo 'down' → preço caiu e ativou hedge-down
      modo 'up'   → preço subiu e ativou hedge-up

    Ações emitidas:  hold | open | increase | decrease | close
    (A executora trata todas da mesma forma: open/ increase => open_short,
     decrease/close => reduce_short)
    """

    # --------------------------------------------------------------
    def __init__(
        self,
        qty_token1: float,
        min_price: float,
        max_price: float,
        total_usd_target: float,
        fee_apr_percent: float = 0.0,
    ):
        # parâmetros fixos da pool
        self.qty_token1 = qty_token1
        self.min_price  = min_price
        self.max_price  = max_price
        self.total_usd_target = total_usd_target
        self.fee_apr_percent  = fee_apr_percent

        # estado dinâmico
        self.mode: Optional[str] = None            # None | 'down' | 'up'
        self.price_reference: Optional[float] = None
        self.value_token1_ref: Optional[float] = None
        self.short_blocks: List[dict] = []
        self.last_v1_for_delta: Optional[float] = None
        self._last_decrease_usd: float  = 0.0
        self._pending_close_usd: float = 0.0

        # fee/ métricas
        self.accumulated_fee = 0.0
        self.initial_total   = None
        self.results = []

        # pré-cálculos da curva
        self.sqrt_Pa = math.sqrt(self.min_price)
        self.sqrt_Pb = math.sqrt(self.max_price)
        self.sqrt_P  = None
        self.L       = None                       # liquidez ajustada (solver)

    # ---------------- helpers -------------------------------------
    def _solve_liquidity(self, price: float) -> float:
        """Resolve L para que total USD da pool = target."""
        sqrt_P = math.sqrt(price)

        def err(L):
            t1 = L * (1/ sqrt_P - 1/ self.sqrt_Pb)
            t2 = L * (sqrt_P - self.sqrt_Pa)
            return abs(t1*price + t2 - self.total_usd_target)

        res = minimize_scalar(err, bounds=(1e-8, 1e8), method="bounded")
        return res.x

    def _lp_state(self, price: float):
        sqrt_P = math.sqrt(price)
        if price <= self.min_price:
            t1 = self.L * (1/ self.sqrt_Pa - 1/ self.sqrt_Pb)
            t2 = 0
        elif price >= self.max_price:
            t1 = 0
            t2 = self.L * (self.sqrt_Pb - self.sqrt_Pa)
        else:
            t1 = self.L * (1/ sqrt_P - 1/ self.sqrt_Pb)
            t2 = self.L * (sqrt_P - self.sqrt_Pa)

        v1 = t1 * price
        v2 = t2
        return t1, t2, v1, v2, v1 + v2

    # ---------------- main ----------------------------------------
    async def on_new_price(
        self,
        close_price: float,
        timestamp: datetime,
        rebalance_threshold_usd: float,
        hedge_interval: int,
    ) -> HedgeResult:

        # 0) primeira chamada → salva referência
        if self.price_reference is None:
            self.price_reference  = close_price
            self.sqrt_P = math.sqrt(close_price)
            self.L      = self._solve_liquidity(close_price)
            _, _, self.value_token1_ref, _, _ = self._lp_state(close_price)

        # 1) estado atual
        t1, t2, v1_usd, v2_usd, total_usd = self._lp_state(close_price)
        if self.initial_total is None:
            self.initial_total = total_usd

        # fee proporcional ao passo
        if self.fee_apr_percent > 0:
            step_factor = (self.fee_apr_percent / 100) / (525600 * 60 / hedge_interval)
            self.accumulated_fee += self.initial_total * step_factor

        action = "hold"
        pnl_total = sum(
            blk["value"] * ((blk["price"] - close_price) / blk["price"])
            for blk in self.short_blocks
        )

        # 2) lógica de transição de estado --------------------------
        if self.mode is None:
            # --- ainda sem hedge ---
            # preço CAIU → Token1 USD aumentou
            if   v1_usd - self.value_token1_ref >= rebalance_threshold_usd:
                self.mode = "down"
                self.short_blocks = [{"price": close_price, "value": v1_usd}]
                self.last_v1_for_delta = v1_usd
                action = "open"
            # preço SUBIU → Token1 USD diminuiu
            elif self.value_token1_ref - v1_usd >= rebalance_threshold_usd:
                self.mode = "up"
                self.short_blocks = [{"price": close_price, "value": v1_usd}]
                self.last_v1_for_delta = v1_usd
                action = "open"

        # --- hedge-DOWN ativo --------------------------------------
        elif self.mode == "down":
            # Se preço voltou para cima do reference → fecha tudo
            if close_price >= self.price_reference and self.short_blocks:
                self._pending_close_usd = sum(b["value"] for b in self.short_blocks)
                self.short_blocks.clear()
                self.mode = None
                action = "close"
            else:
                delta = v1_usd - self.last_v1_for_delta
                if delta >= rebalance_threshold_usd:
                    # increase
                    added = v1_usd - sum(b["value"] for b in self.short_blocks)
                    if added > rebalance_threshold_usd:
                        self.short_blocks.append({"price": close_price, "value": added})
                        self.last_v1_for_delta = v1_usd
                        action = "increase"
                elif delta <= -rebalance_threshold_usd:
                    # decrease
                    reduction_needed = sum(b["value"] for b in self.short_blocks) - v1_usd
                    if reduction_needed > rebalance_threshold_usd:
                        self._last_decrease_usd = reduction_needed
                        self.last_v1_for_delta = v1_usd
                        action = "decrease"
                        new_blocks = []
                        for blk in reversed(self.short_blocks):
                            if reduction_needed <= 0:
                                new_blocks.insert(0, blk)
                                continue
                            if blk["value"] <= reduction_needed:
                                reduction_needed -= blk["value"]
                            else:
                                blk["value"] -= reduction_needed
                                reduction_needed = 0
                                new_blocks.insert(0, blk)
                        self.short_blocks = new_blocks

        # --- hedge-UP ativo ----------------------------------------
        elif self.mode == "up":
            # Se preço voltou para baixo do reference → fecha tudo
            if close_price <= self.price_reference and self.short_blocks:
                self._pending_close_usd = sum(b["value"] for b in self.short_blocks)
                self.short_blocks.clear()
                self.mode = None
                action = "close"
            else:
                delta = self.last_v1_for_delta - v1_usd  # invertido!
                if delta >= rebalance_threshold_usd:
                    # DECREASE (token1 desceu → precisamos reduzir short)
                    reduction_needed = sum(b["value"] for b in self.short_blocks) - v1_usd
                    if reduction_needed > rebalance_threshold_usd:
                        self._last_decrease_usd = reduction_needed
                        self.last_v1_for_delta = v1_usd
                        action = "decrease"
                        new_blocks = []
                        for blk in reversed(self.short_blocks):
                            if reduction_needed <= 0:
                                new_blocks.insert(0, blk)
                                continue
                            if blk["value"] <= reduction_needed:
                                reduction_needed -= blk["value"]
                            else:
                                blk["value"] -= reduction_needed
                                reduction_needed = 0
                                new_blocks.insert(0, blk)
                        self.short_blocks = new_blocks
                elif delta <= -rebalance_threshold_usd:
                    # INCREASE (token1 subiu de volta)
                    added = v1_usd - sum(b["value"] for b in self.short_blocks)
                    if added > rebalance_threshold_usd:
                        self.short_blocks.append({"price": close_price, "value": added})
                        self.last_v1_for_delta = v1_usd
                        action = "increase"

        # 3) resultado ------------------------------------------------
        short_value  = sum(b["value"] for b in self.short_blocks)
        total_accum  = total_usd + pnl_total
        total_with_f = total_accum + self.accumulated_fee

        res = HedgeResult(
            time=timestamp,
            close=close_price,
            quantity_token1=round(t1, 4),
            quantity_token2=round(t2, 4),
            value_token1_usd=round(v1_usd, 2),
            value_token2_usd=round(v2_usd, 2),
            total_value_usd=round(total_usd, 2),
            delta_total=round(v1_usd - self.value_token1_ref, 2),
            accumulated_fee=round(self.accumulated_fee, 3),
            short_action=action,
            short_value_usd=round(short_value, 2),
            short_pnl_usd=round(pnl_total, 2),
            total_accumulated=round(total_accum, 2),
            total_accumulated_with_fee=round(total_with_f, 2),
            short_blocks=copy.deepcopy(self.short_blocks),
        )
        self.results.append(res)
        return res
