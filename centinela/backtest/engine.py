"""Motor de backtest vela a vela para una cartera BTC/efectivo (largo o fuera).

Supuestos, todos deliberadamente conservadores:

* La decisión se toma al **cierre** de la vela ``t`` con datos hasta ``t`` y se ejecuta
  en la **apertura** de ``t+1`` (nunca al precio que originó la señal).
* Cada ejecución paga comisión y deslizamiento sobre el nominal negociado.
* En las horas sin mercado (``gap``) no se ejecuta nada.
* El efectivo no rinde intereses (tipo libre de riesgo = 0).
* Paradas de emergencia intravela: si el mínimo de la vela toca el nivel, se vende a
  ese nivel (o a la apertura si abrió por debajo) con un deslizamiento agravado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from ..risk import is_full_exit, should_rebalance


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 10_000.0
    fee: float = 0.0010  # comisión por lado (0,10 %)
    slippage: float = 0.0002  # deslizamiento por lado (0,02 %)
    band: float = 0.10  # banda de no-operación: no rebalancear si |objetivo - actual| < banda
    max_exposure: float = 1.0
    stop_slippage: float = 0.0030  # deslizamiento de una venta de emergencia en pleno desplome
    exit_eps: float = 0.005  # por debajo de este peso objetivo se considera "salir del todo"


def as_utc(x) -> pd.Timestamp | None:
    """Convierte una fecha (texto, datetime o Timestamp, con o sin zona) a Timestamp UTC."""
    if x is None:
        return None
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


class RiskHook(Protocol):
    """Capa de riesgo con estado, compartida entre el backtest y la operativa real."""

    def on_close(self, ts_ms: int, equity: float, weight: float, raw_target: float, close: float, row: int) -> float:
        """Devuelve el objetivo final tras aplicar los límites de riesgo."""
        ...

    def stop_level(self) -> float:
        """Precio de parada de emergencia vigente para la próxima vela (NaN si no hay)."""
        ...

    def on_stop(self, ts_ms: int, price: float) -> None:
        """Notificación de que la parada de emergencia se ha ejecutado."""
        ...


@dataclass
class BacktestResult:
    equity: pd.Series  # valor de la cartera al cierre de cada vela
    weight: pd.Series  # fracción de la cartera en BTC al cierre
    target: pd.Series  # objetivo decidido al cierre (tras riesgo)
    trades: pd.DataFrame  # ejecuciones
    benchmark: pd.Series  # comprar y mantener con el mismo capital y costes
    config: BacktestConfig
    fees_paid: float = 0.0
    meta: dict = field(default_factory=dict)

    def window(self, start=None, end=None) -> "BacktestResult":
        """Recorta el resultado a un periodo (las curvas se renormalizan al capital inicial)."""
        sl = slice(as_utc(start), as_utc(end))
        eq = self.equity.loc[sl]
        if eq.empty:
            raise ValueError("periodo sin datos")
        k = self.config.initial_capital
        tr = self.trades
        if not tr.empty:
            tr = tr[(tr["time"] >= eq.index[0]) & (tr["time"] <= eq.index[-1])]
        bench = self.benchmark.loc[sl]
        return BacktestResult(
            equity=eq / eq.iloc[0] * k,
            weight=self.weight.loc[sl],
            target=self.target.loc[sl],
            trades=tr,
            benchmark=bench / bench.iloc[0] * k,
            config=self.config,
            fees_paid=float(tr["fee"].sum()) if not tr.empty else 0.0,
            meta=dict(self.meta),
        )


def run_backtest(
    bars: pd.DataFrame,
    target: pd.Series,
    config: BacktestConfig | None = None,
    risk: RiskHook | None = None,
    start=None,
    end=None,
) -> BacktestResult:
    """Simula la cartera siguiendo ``target`` (peso en BTC decidido al cierre de cada vela)."""
    cfg = config or BacktestConfig()
    idx = bars.index
    o = bars["open"].to_numpy("float64")
    h = bars["high"].to_numpy("float64")
    l = bars["low"].to_numpy("float64")
    c = bars["close"].to_numpy("float64")
    gap = bars["gap"].to_numpy(bool) if "gap" in bars else np.zeros(len(bars), bool)
    tgt = target.reindex(idx).to_numpy("float64")
    ts = idx.as_unit("ms").asi8

    i0 = 0 if start is None else int(idx.searchsorted(as_utc(start)))
    i1 = len(idx) if end is None else int(idx.searchsorted(as_utc(end)))
    if i1 - i0 < 2:
        raise ValueError("periodo de backtest demasiado corto")

    n = i1 - i0
    equity = np.empty(n)
    weight = np.empty(n)
    applied = np.full(n, np.nan)
    cash = cfg.initial_capital
    qty = 0.0
    pending = np.nan
    fees = 0.0
    fee, slip, band, eps = cfg.fee, cfg.slippage, cfg.band, cfg.exit_eps
    t_time: list = []
    t_side: list = []
    t_qty: list = []
    t_px: list = []
    t_fee: list = []
    t_w0: list = []
    t_w1: list = []
    t_kind: list = []

    for i in range(i0, i1):
        oi = o[i]
        tradable = not gap[i]
        # 1) apertura: ejecutar lo decidido al cierre anterior
        if tradable and pending == pending:
            eq = cash + qty * oi
            cur = qty * oi / eq if eq > 0 else 0.0
            diff = pending - cur
            full_exit = is_full_exit(pending, cur, eps)
            if should_rebalance(pending, cur, band, eps):
                q = 0.0
                if diff > 0:
                    px = oi * (1.0 + slip)
                    q = min((pending * eq - qty * oi) / oi, cash / (px * (1.0 + fee)))
                    if q > 0:
                        f = q * px * fee
                        cash -= q * px + f
                        qty += q
                        fees += f
                        side = "buy"
                else:
                    px = oi * (1.0 - slip)
                    q = qty if full_exit else min(qty, (qty * oi - pending * eq) / oi)
                    if q > 0:
                        f = q * px * fee
                        cash += q * px - f
                        qty -= q
                        fees += f
                        side = "sell"
                if q > 0:
                    eq2 = cash + qty * oi
                    t_time.append(idx[i]); t_side.append(side); t_qty.append(q); t_px.append(px)  # noqa: E702
                    t_fee.append(f); t_w0.append(cur); t_w1.append(qty * oi / eq2 if eq2 > 0 else 0.0)  # noqa: E702
                    t_kind.append("rebalance")
        # 2) intravela: parada de emergencia
        if risk is not None and qty > 0 and tradable:
            lvl = risk.stop_level()
            if lvl == lvl and l[i] <= lvl:
                px = min(oi, lvl) * (1.0 - cfg.stop_slippage)
                eq = cash + qty * oi
                cur = qty * oi / eq if eq > 0 else 0.0
                f = qty * px * fee
                cash += qty * px - f
                fees += f
                t_time.append(idx[i]); t_side.append("sell"); t_qty.append(qty); t_px.append(px)  # noqa: E702
                t_fee.append(f); t_w0.append(cur); t_w1.append(0.0); t_kind.append("stop")  # noqa: E702
                qty = 0.0
                risk.on_stop(int(ts[i]), px)
        # 3) cierre: valorar
        ci = c[i]
        eq_c = cash + qty * ci
        w_c = qty * ci / eq_c if eq_c > 0 else 0.0
        k = i - i0
        equity[k] = eq_c
        weight[k] = w_c
        # 4) decisión para la próxima apertura
        raw = tgt[i]
        if raw == raw:
            raw = min(max(raw, 0.0), cfg.max_exposure)
            final = risk.on_close(int(ts[i]), eq_c, w_c, raw, ci, i) if risk is not None else raw
            pending = min(max(final, 0.0), cfg.max_exposure)
            applied[k] = pending
        elif risk is not None:
            risk.on_close(int(ts[i]), eq_c, w_c, 0.0, ci, i)

    sub = idx[i0:i1]
    trades = pd.DataFrame(
        {"time": t_time, "side": t_side, "qty": t_qty, "price": t_px, "fee": t_fee,
         "w_before": t_w0, "w_after": t_w1, "kind": t_kind}
    )  # fmt: skip
    # Referencia: comprar todo en la primera apertura (pagando costes) y no tocar.
    first_px = o[i0] * (1.0 + slip)
    bh_qty = cfg.initial_capital / (first_px * (1.0 + fee))
    bench = pd.Series(bh_qty * c[i0:i1], index=sub, name="benchmark")
    return BacktestResult(
        equity=pd.Series(equity, index=sub, name="equity"),
        weight=pd.Series(weight, index=sub, name="weight"),
        target=pd.Series(applied, index=sub, name="target"),
        trades=trades,
        benchmark=bench,
        config=cfg,
        fees_paid=fees,
    )
