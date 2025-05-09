# core/hedge_state_machine.py
import math, copy
from datetime import datetime
from typing import List, Optional

from scipy.optimize import minimize_scalar
from entities.hedge_result_entity import HedgeResult


class HedgeStateMachine:
    """
    Mantém o estado da posição LP + hedge.

    Estratégia implementada
    -----------------------
    1. NÃO abre hedge no candle inicial. Apenas grava `price_reference`
       (preço de abertura da pool) e valores de token1/token2.
    2. Só abre o *primeiro* short (ação 'open') quando o USD em Token 1
       aumentar `rebalance_threshold_usd` em relação ao valor na abertura.
    3. Depois disso:
         • delta_token1  ≥ +threshold  → 'increase'
         • delta_token1  ≤ –threshold  → 'decrease'
    4. Se o preço voltar a ser ≥ price_reference  ⇒ 'close' (zera tudo).
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
        self.price_reference: Optional[float] = None      # preço de abertura
        self.value_token1_ref: Optional[float] = None     # $ token1 na abertura
        self.short_blocks: List[dict] = []               # blocos vivos
        self.hedge_active: bool = False                  # já existe short?
        self.last_value_token1: Optional[float] = None   # para cálculo do delta
        self._last_decrease_usd: float = 0.0
        self._pending_close_usd: float = 0.0

        # fee e métricas
        self.accumulated_fee = 0.0
        self.initial_total   = None
        self.results = []

        # pré-cálculos da curva
        self.sqrt_Pa = math.sqrt(self.min_price)
        self.sqrt_Pb = math.sqrt(self.max_price)
        self.sqrt_P  = None
        self.L       = None                       # liquidez ajustada (resolveremos no 1º preço)

    # --------------------------------------------------------------
    # helpers
    def _solve_liquidity(self, close_price: float) -> float:
        """Calcula L para que o total USD da posição bata `total_usd_target`."""
        sqrt_P = math.sqrt(close_price)

        def err(L):
            tok1 = L * (1 / sqrt_P - 1 / self.sqrt_Pb)
            tok2 = L * (sqrt_P - self.sqrt_Pa)
            return abs(tok1 * close_price + tok2 - self.total_usd_target)

        res = minimize_scalar(err, bounds=(1e-8, 1e8), method="bounded")
        return res.x

    def _lp_state(self, price: float):
        """Retorna token1, token2, valores em USD e total."""
        sqrt_P = math.sqrt(price)
        if price <= self.min_price:                 # inteiramente em token1
            t1 = self.L * (1 / self.sqrt_Pa - 1 / self.sqrt_Pb)
            t2 = 0
        elif price >= self.max_price:               # inteiramente em token2
            t1 = 0
            t2 = self.L * (self.sqrt_Pb - self.sqrt_Pa)
        else:                                       # dentro do range
            t1 = self.L * (1 / sqrt_P - 1 / self.sqrt_Pb)
            t2 = self.L * (sqrt_P - self.sqrt_Pa)

        v1 = t1 * price
        v2 = t2
        return t1, t2, v1, v2, v1 + v2

    # --------------------------------------------------------------
    async def on_new_price(
        self,
        close_price: float,
        timestamp: datetime,
        rebalance_threshold_usd: float,
        hedge_interval: int,
    ) -> HedgeResult:
        # 0️inicialização ---------------------------------------
        if self.price_reference is None:
            # primeira chamada
            self.price_reference = close_price
            self.sqrt_P          = math.sqrt(close_price)
            self.L               = self._solve_liquidity(close_price)
            _, _, self.value_token1_ref, _, _ = self._lp_state(close_price)

        # 1️calcula estado atual -------------------------------
        t1, t2, v1_usd, v2_usd, total_usd = self._lp_state(close_price)
        if self.initial_total is None:
            self.initial_total = total_usd

        # 2️acumula fee ----------------------------------------
        if self.fee_apr_percent > 0:
            fee_per_step = (self.fee_apr_percent / 100) / (525600 * 60 / hedge_interval)
            self.accumulated_fee += self.initial_total * fee_per_step

        # 3️determina ação desejada ----------------------------
        action = "hold"
        pnl_total = sum(
            blk["value"] * ((blk["price"] - close_price) / blk["price"])
            for blk in self.short_blocks
        )
        delta_v1 = v1_usd - (self.last_value_token1 or v1_usd)

        if not self.hedge_active:
            # ainda não existe hedge aberto
            if (v1_usd - self.value_token1_ref) >= rebalance_threshold_usd:
                # ▶ abre short inicial
                self.short_blocks.append({"price": close_price, "value": v1_usd})
                self.hedge_active      = True
                self.last_value_token1 = v1_usd
                action = "open"
        else:
            # hedge já ativo
            if (close_price >= self.price_reference) and self.short_blocks:
                self._pending_close_usd = sum(b["value"] for b in self.short_blocks)

                # ▶ fecha tudo
                action = "close"
                self.short_blocks.clear()
                self.hedge_active = False
            else:
                self._pending_close_usd = 0.0

                # lógica increase / decrease
                if delta_v1 >= rebalance_threshold_usd:
                    added = v1_usd - sum(b["value"] for b in self.short_blocks)
                    if added > rebalance_threshold_usd:
                        self.short_blocks.append({"price": close_price, "value": added})
                        action = "increase"
                elif delta_v1 <= -rebalance_threshold_usd:
                    current = sum(b["value"] for b in self.short_blocks)
                    reduction = current - v1_usd
                    if reduction > rebalance_threshold_usd:
                        self._last_decrease_usd = reduction
                        action = "decrease"
                        new_blocks = []
                        for blk in reversed(self.short_blocks):
                            if reduction <= 0:
                                new_blocks.insert(0, blk)
                                continue
                            if blk["value"] <= reduction:
                                reduction -= blk["value"]
                            else:
                                blk["value"] -= reduction
                                reduction = 0
                                new_blocks.insert(0, blk)
                        self.short_blocks = new_blocks
                # após qualquer incremento/decr.
                self.last_value_token1 = v1_usd

        short_value = sum(b["value"] for b in self.short_blocks)
        total_accum = total_usd + pnl_total
        total_with_fee = total_accum + self.accumulated_fee

        # 4️⃣  constrói resultado --------------------------------
        result = HedgeResult(
            time=timestamp,
            close=close_price,
            quantity_token1=round(t1, 4),
            quantity_token2=round(t2, 4),
            value_token1_usd=round(v1_usd, 2),
            value_token2_usd=round(v2_usd, 2),
            total_value_usd=round(total_usd, 2),
            delta_total=round(delta_v1, 2),
            accumulated_fee=round(self.accumulated_fee, 3),
            short_action=action,
            short_value_usd=round(short_value, 2),
            short_pnl_usd=round(pnl_total, 2),
            total_accumulated=round(total_accum, 2),
            total_accumulated_with_fee=round(total_with_fee, 2),
            short_blocks=copy.deepcopy(self.short_blocks),
        )
        self.results.append(result)
        return result
