"""Informe HTML autocontenido del backtest (sin dependencias ni peticiones externas).

El fichero generado funciona abierto directamente en el navegador, en claro y en
oscuro, y en el móvil. Los gráficos se dibujan en SVG con un pequeño script propio.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .. import btc
from ..config import Config
from . import validation
from .engine import BacktestResult
from .metrics import bootstrap_excess, bootstrap_sharpe, compute_metrics, yearly_table

TEMPLATE = Path(__file__).with_name("report_template.html")
DAY_MS = 86_400_000

_KEEP = (
    "years", "total_return", "cagr", "vol", "sharpe", "sortino", "max_drawdown", "calmar",
    "avg_exposure", "time_in_market", "executions_per_year", "turnover_per_year",
    "worst_month", "pct_positive_months", "max_underwater_days", "episodes", "episode_win_rate",
)  # fmt: skip


def _clean(x):
    """Convierte a tipos JSON; NaN/inf pasan a null."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if np.isfinite(v) else None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (pd.Timestamp, datetime)):
        return str(x)[:10]
    return x


def _metrics(res: BacktestResult) -> dict:
    m = compute_metrics(res.equity, res.weight, res.trades)
    b = compute_metrics(res.benchmark)
    return {"s": {k: m.get(k) for k in _KEEP}, "b": {k: b.get(k) for k in _KEEP}}


def build_data(cfg: Config, bars: pd.DataFrame, res: BacktestResult, robustness: bool = True) -> dict:
    """Reúne todo lo que muestra el informe en un diccionario serializable."""
    eq = res.equity.resample("1D").last().dropna()
    bh = res.benchmark.resample("1D").last().reindex(eq.index).ffill()
    w = res.weight.resample("1D").mean().reindex(eq.index).fillna(0.0)
    days = (eq.index.as_unit("ms").asi8 // DAY_MS).astype(int)
    first, last = res.equity.index[0], res.equity.index[-1]
    cut = pd.Timestamp(validation.HOLDOUT_START, tz="UTC")

    periods = [{"id": "todo", "label": "Todo el periodo", "from": str(first)[:10], "to": str(last)[:10], **_metrics(res)}]
    parts = validation.split_design_holdout(res)
    if "diseño" in parts:
        r = parts["diseño"]
        periods.append({"id": "diseno", "label": "Diseño (hasta 2024)", "from": str(first)[:10], "to": "2024-12-31", **_metrics(r)})
    if "fuera de muestra" in parts:
        r = parts["fuera de muestra"]
        periods.append(
            {"id": "fuera", "label": "Fuera de muestra (2025 →)", "from": str(max(cut, first))[:10], "to": str(last)[:10], **_metrics(r)}
        )
    year_ago = last - pd.Timedelta(days=365)
    if year_ago > first + pd.Timedelta(days=90):
        r = res.window(year_ago, None)
        periods.append({"id": "12m", "label": "Últimos 12 meses", "from": str(year_ago)[:10], "to": str(last)[:10], **_metrics(r)})

    yt = yearly_table(res.equity, res.benchmark)
    years = [
        {"y": int(y), "s": row["estrategia"], "b": row["btc_hold"], "ds": row["dd_estrategia"], "db": row["dd_btc"],
         "oos": bool(y >= cut.year)}
        for y, row in yt.iterrows()
    ]  # fmt: skip

    data = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "profile": cfg.profile,
        "fee": cfg.execution.fee,
        "slippage": cfg.execution.slippage,
        "band": cfg.effective_band,
        "target_vol": cfg.strategy.target_vol,
        "allocation": cfg.allocation,
        "speeds": list(cfg.strategy.trend_speeds_days),
        "holdout": validation.HOLDOUT_START,
        "last_price": float(bars["close"].iloc[-1]),
        "t": days.tolist(),
        "eq": np.round(eq.to_numpy("float64"), 2).tolist(),
        "bh": np.round(bh.to_numpy("float64"), 2).tolist(),
        "w": np.round(w.to_numpy("float64") * 100.0, 1).tolist(),
        "periods": periods,
        "years": years,
        "halvings": [int(h[0].timestamp() * 1000 // DAY_MS) for h in btc.HALVINGS],
        "halts": int(res.meta.get("halts", 0)),
        "stops": int(res.meta.get("stops", 0)),
        "boot": {},
        "fees": [],
        "delays": [],
        "params": [],
    }
    if robustness:
        start, end = first, last + pd.Timedelta(hours=1)
        data["boot"] = {**bootstrap_sharpe(res.equity), **bootstrap_excess(res.equity, res.benchmark)}
        if "fuera de muestra" in parts:
            o = parts["fuera de muestra"]
            data["boot_oos"] = {**bootstrap_sharpe(o.equity), **bootstrap_excess(o.equity, o.benchmark)}
        data["fees"] = validation.fee_sensitivity(cfg, bars, (0.0005, 0.0010, 0.0026, 0.0040, 0.0060), start, end)
        data["delays"] = validation.delay_sensitivity(cfg, bars, (0, 1, 6, 24), start, end)
        data["params"] = validation.parameter_sensitivity(cfg, bars, start, end)
    return _clean(data)


def render(data: dict, standalone: bool = True) -> str:
    """HTML del informe. ``standalone=False`` devuelve solo el contenido (sin <html>/<head>)."""
    tpl = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    page = tpl.replace("/*__DATA__*/null", payload)
    if not standalone:
        return page
    head = (
        '<!doctype html>\n<html lang="es">\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    )
    return head + page


def write(path: str | Path, cfg: Config, bars: pd.DataFrame, res: BacktestResult, robustness: bool = True) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render(build_data(cfg, bars, res, robustness)), encoding="utf-8")
    return p
