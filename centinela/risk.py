"""Gestor de riesgo con estado. El mismo objeto gobierna el backtest y la operativa real.

Capas, de más rápida a más lenta:

1. **Parada de desplome** (intravela): si el precio cae más de ``crash_sigmas``
   desviaciones diarias por debajo del máximo reciente, se vende todo y se espera.
2. **Gobernador de caída**: si la cartera retrocede ``dd_reduce`` desde su máximo se
   opera a medio tamaño; si retrocede ``dd_halt`` se sale del mercado y se enfría.
   Es el cortafuegos por si la estrategia deja de funcionar: limita lo que puede
   perderse antes de que un humano revise.

El dimensionado normal (tendencia x volatilidad) vive en ``strategy``; aquí solo
hay límites que **reducen** exposición, nunca la aumentan.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

HOUR_MS = 3_600_000


@dataclass(frozen=True)
class RiskConfig:
    # Parada de desplome (0 = desactivada).
    crash_sigmas: float = 0.0
    crash_lookback_h: int = 24
    crash_cooldown_h: int = 24
    # Gobernador de caída de la cartera (0 = desactivado).
    dd_reduce: float = 0.0
    dd_halt: float = 0.0
    dd_cooldown_h: int = 24 * 14
    dd_reduce_factor: float = 0.5

    def __post_init__(self) -> None:
        if self.crash_sigmas < 0 or self.dd_reduce < 0 or self.dd_halt < 0:
            raise ValueError("los umbrales de riesgo no pueden ser negativos")
        if self.dd_halt and self.dd_reduce and self.dd_reduce >= self.dd_halt:
            raise ValueError("dd_reduce debe ser menor que dd_halt")


@dataclass
class RiskState:
    """Estado persistente (se guarda en disco en vivo para sobrevivir a reinicios)."""

    peak_equity: float = 0.0
    halted_until_ms: int = 0  # gobernador de caída: fuera del mercado hasta esta marca
    cooldown_until_ms: int = 0  # tras parada de desplome
    stop_level: float = float("nan")
    halts: int = 0
    stops: int = 0
    last_reason: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["stop_level"] != d["stop_level"]:
            d["stop_level"] = None
        return d

    @classmethod
    def from_dict(cls, d: dict | None) -> "RiskState":
        if not d:
            return cls()
        d = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        if d.get("stop_level") is None:
            d["stop_level"] = float("nan")
        return cls(**d)


class RiskManager:
    """Aplica los límites de ``RiskConfig`` sobre el objetivo bruto de la estrategia.

    ``sigma_daily`` y ``ref_high`` son series alineadas con las velas: la volatilidad
    diaria prevista y el máximo de cierres de la ventana de referencia.
    """

    def __init__(
        self,
        cfg: RiskConfig,
        sigma_daily: np.ndarray | None = None,
        ref_high: np.ndarray | None = None,
        state: RiskState | None = None,
    ) -> None:
        self.cfg = cfg
        self.sigma_daily = sigma_daily
        self.ref_high = ref_high
        self.state = state or RiskState()

    # ------------------------------------------------------------ protocolo
    def on_close(self, ts_ms: int, equity: float, weight: float, raw_target: float, close: float, row: int) -> float:
        cfg, st = self.cfg, self.state
        target = raw_target
        reason = ""
        if equity > st.peak_equity:
            st.peak_equity = equity

        # --- gobernador de caída
        if cfg.dd_halt > 0 or cfg.dd_reduce > 0:
            if st.halted_until_ms and ts_ms >= st.halted_until_ms:
                # fin del enfriamiento: se reanuda midiendo la caída desde el capital actual
                st.halted_until_ms = 0
                st.peak_equity = equity
            dd = equity / st.peak_equity - 1.0 if st.peak_equity > 0 else 0.0
            if st.halted_until_ms:
                target, reason = 0.0, "gobernador de caída: en enfriamiento"
            elif cfg.dd_halt > 0 and dd <= -cfg.dd_halt:
                st.halted_until_ms = ts_ms + cfg.dd_cooldown_h * HOUR_MS
                st.halts += 1
                target, reason = 0.0, f"gobernador de caída: cartera {dd:.1%} desde máximos, fuera del mercado"
            elif cfg.dd_reduce > 0 and dd <= -cfg.dd_reduce:
                target = raw_target * cfg.dd_reduce_factor
                reason = f"gobernador de caída: cartera {dd:.1%} desde máximos, tamaño reducido"

        # --- enfriamiento tras parada de desplome
        if st.cooldown_until_ms:
            if ts_ms >= st.cooldown_until_ms:
                st.cooldown_until_ms = 0
            else:
                target, reason = 0.0, "enfriamiento tras parada de desplome"

        # --- nivel de parada para la próxima vela
        st.stop_level = self._stop_for(row)
        st.last_reason = reason
        return target

    def stop_level(self) -> float:
        return self.state.stop_level

    def on_stop(self, ts_ms: int, price: float) -> None:
        st = self.state
        st.stops += 1
        st.cooldown_until_ms = ts_ms + self.cfg.crash_cooldown_h * HOUR_MS
        st.stop_level = float("nan")
        st.last_reason = f"parada de desplome ejecutada a {price:,.0f}"

    # -------------------------------------------------------------- interno
    def _stop_for(self, row: int) -> float:
        if self.cfg.crash_sigmas <= 0 or self.sigma_daily is None or self.ref_high is None:
            return float("nan")
        sig = float(self.sigma_daily[row])
        hi = float(self.ref_high[row])
        if not (sig == sig and hi == hi) or sig <= 0:
            return float("nan")
        return hi * math.exp(-self.cfg.crash_sigmas * sig)


def is_full_exit(target: float, current: float, eps: float = 0.005) -> bool:
    """El objetivo pide salir del todo y todavía queda posición."""
    return target <= eps and current > eps


def should_rebalance(target: float, current: float, band: float, eps: float = 0.005) -> bool:
    """Regla de rebalanceo única para backtest y operativa real.

    Solo se opera si el peso actual se aleja del objetivo más que la banda (evita
    pagar comisiones por ajustes mínimos), salvo que toque salir por completo:
    una salida total nunca se retrasa.
    """
    return abs(target - current) >= band or is_full_exit(target, current, eps)


def crash_inputs(close, vol_ann, lookback_h: int) -> tuple[np.ndarray, np.ndarray]:
    """Series que necesita la parada de desplome: sigma diaria y máximo de cierres reciente."""
    sigma_daily = (vol_ann / np.sqrt(365.0)).to_numpy("float64")
    ref_high = close.rolling(lookback_h, min_periods=1).max().to_numpy("float64")
    return sigma_daily, ref_high
