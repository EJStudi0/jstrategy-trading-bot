"""Conocimiento específico de Bitcoin: lo que distingue a BTC de cualquier otro activo.

Este módulo reúne los hechos estructurales de la red y del mercado que el bot usa
para situarse: calendario de halvings, fase del ciclo, sesiones de negociación y
el calendario de liquidación del funding de los perpetuos.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

BLOCKS_PER_HALVING = 210_000
TARGET_BLOCK_MINUTES = 10.0
INITIAL_SUBSIDY = 50.0
MAX_SUPPLY = 21_000_000.0

# Halvings ya ocurridos (hora UTC del bloque) y su altura.
HALVINGS: tuple[tuple[datetime, int], ...] = (
    (datetime(2012, 11, 28, 15, 24, tzinfo=timezone.utc), 210_000),
    (datetime(2016, 7, 9, 16, 46, tzinfo=timezone.utc), 420_000),
    (datetime(2020, 5, 11, 19, 23, tzinfo=timezone.utc), 630_000),
    (datetime(2024, 4, 20, 0, 9, tzinfo=timezone.utc), 840_000),
)
NEXT_HALVING_HEIGHT = 1_050_000
# Estimación de reserva si no hay conexión para consultar la altura actual.
NEXT_HALVING_FALLBACK = datetime(2028, 4, 15, tzinfo=timezone.utc)

# El funding de los perpetuos BTC-USDT se liquida a estas horas UTC.
FUNDING_HOURS_UTC = (0, 8, 16)


def subsidy_at(height: int) -> float:
    """Recompensa por bloque (BTC) vigente a una altura dada."""
    return INITIAL_SUBSIDY / (2 ** (height // BLOCKS_PER_HALVING))


def last_halving(now: datetime) -> tuple[datetime, int]:
    done = [hv for hv in HALVINGS if hv[0] <= now]
    return done[-1] if done else HALVINGS[0]


def estimate_next_halving(now: datetime, height: int | None = None) -> datetime:
    """Fecha estimada del próximo halving a partir de la altura de bloque actual."""
    if height is None or height >= NEXT_HALVING_HEIGHT:
        return NEXT_HALVING_FALLBACK
    remaining = NEXT_HALVING_HEIGHT - height
    return now + timedelta(minutes=remaining * TARGET_BLOCK_MINUTES)


@dataclass(frozen=True)
class CycleInfo:
    days_since_halving: int
    cycle_progress: float  # 0 = recién ocurrido el halving, 1 = a punto del siguiente
    next_halving: datetime
    days_to_next: int
    subsidy_btc: float
    annual_issuance_pct: float  # inflación monetaria anualizada aproximada
    phase: str

    def describe(self) -> str:
        sub = f"{self.subsidy_btc:g}".replace(".", ",")
        infl = f"{self.annual_issuance_pct:.2f}".replace(".", ",")
        return (
            f"día {self.days_since_halving} del ciclo ({self.cycle_progress * 100:.0f} %), fase «{self.phase}»; "
            f"próximo halving ~{self.next_halving:%Y-%m-%d} (faltan ~{self.days_to_next} días); "
            f"emisión {sub} BTC por bloque (~{infl} % anual)"
        )


def cycle_info(now: datetime | None = None, height: int | None = None) -> CycleInfo:
    """Situación de BTC dentro de su ciclo de cuatro años.

    Las fases son descriptivas (cómo se han comportado los tres ciclos completos
    observados), no una regla de trading: con tan pocos ciclos no hay base estadística
    para operar sobre ellas, y el bot **no** lo hace. Sirven para dar contexto.
    """
    now = now or datetime.now(timezone.utc)
    when, h0 = last_halving(now)
    nxt = estimate_next_halving(now, height)
    days = (now - when).days
    total = max((nxt - when).days, 1)
    progress = min(max(days / total, 0.0), 1.0)
    cur_height = height if height is not None else h0 + int((now - when).total_seconds() / 60 / TARGET_BLOCK_MINUTES)
    sub = subsidy_at(cur_height)
    mined = _supply_at(cur_height)
    issuance = sub * 6 * 24 * 365 / mined * 100.0
    if days < 180:
        phase = "post-halving temprano"
    elif days < 550:
        phase = "expansión histórica"
    elif days < 900:
        phase = "contracción histórica"
    else:
        phase = "acumulación pre-halving"
    return CycleInfo(days, progress, nxt, max((nxt - now).days, 0), sub, issuance, phase)


def _supply_at(height: int) -> float:
    supply, sub, h = 0.0, INITIAL_SUBSIDY, height
    while h > 0:
        n = min(h, BLOCKS_PER_HALVING)
        supply += n * sub
        h -= n
        sub /= 2.0
    return supply


def session_of(hour_utc: int) -> str:
    """Sesión dominante por hora UTC (BTC cotiza 24/7 pero la liquidez rota por regiones)."""
    if 0 <= hour_utc < 7:
        return "Asia"
    if 7 <= hour_utc < 13:
        return "Europa"
    if 13 <= hour_utc < 21:
        return "América"
    return "cierre América / apertura Asia"


def is_weekend(ts: pd.Timestamp | datetime) -> bool:
    """Fin de semana: sin futuros CME ni flujos de ETF, libro más fino."""
    return ts.weekday() >= 5


def hours_to_next_funding(ts: pd.Timestamp | datetime) -> float:
    h = ts.hour + ts.minute / 60.0
    nxt = min((fh for fh in (*FUNDING_HOURS_UTC, 24) if fh > h), default=24)
    return float(nxt - h)


def funding_annualized(rate_8h: float | np.ndarray) -> float | np.ndarray:
    """Coste anualizado de mantener un largo apalancado en el perpetuo."""
    return rate_8h * 3.0 * 365.0
