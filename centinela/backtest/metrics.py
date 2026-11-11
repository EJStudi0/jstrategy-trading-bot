"""Métricas de rendimiento y riesgo, e inferencia estadística sobre ellas."""

from __future__ import annotations

import numpy as np
import pandas as pd

DAYS_PER_YEAR = 365.0  # BTC cotiza todos los días


def daily_returns(equity: pd.Series) -> pd.Series:
    daily = equity.resample("1D").last().dropna()
    return daily.pct_change().dropna()


def max_drawdown(equity: pd.Series) -> tuple[float, pd.Timestamp | None, pd.Timestamp | None, float]:
    """(caída máxima, fecha del pico, fecha del valle, días máximos bajo el agua)."""
    v = equity.to_numpy("float64")
    if len(v) == 0:
        return 0.0, None, None, 0.0
    peak = np.maximum.accumulate(v)
    dd = v / peak - 1.0
    j = int(np.argmin(dd))
    i = int(np.argmax(v[: j + 1])) if j > 0 else 0
    under = dd < -1e-12
    longest = cur = 0
    for flag in under:
        cur = cur + 1 if flag else 0
        longest = max(longest, cur)
    step_days = (equity.index[1] - equity.index[0]).total_seconds() / 86400.0 if len(equity) > 1 else 1.0
    return float(dd[j]), equity.index[i], equity.index[j], longest * step_days


def episodes(weight: pd.Series, equity: pd.Series, threshold: float = 0.02) -> pd.DataFrame:
    """Tramos continuos con posición abierta y su resultado sobre la cartera."""
    w = weight.to_numpy("float64") > threshold
    e = equity.to_numpy("float64")
    rows = []
    i, n = 0, len(w)
    while i < n:
        if w[i]:
            j = i
            while j + 1 < n and w[j + 1]:
                j += 1
            base = e[i - 1] if i > 0 else e[i]
            rows.append((weight.index[i], weight.index[j], j - i + 1, e[j] / base - 1.0))
            i = j + 1
        else:
            i += 1
    return pd.DataFrame(rows, columns=["start", "end", "hours", "ret"])


def compute_metrics(equity: pd.Series, weight: pd.Series | None = None, trades: pd.DataFrame | None = None) -> dict:
    """Resumen estándar a partir de la curva de capital (retornos diarios para los ratios)."""
    years = (equity.index[-1] - equity.index[0]).total_seconds() / (86400.0 * DAYS_PER_YEAR)
    total = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0) if years > 0 and equity.iloc[-1] > 0 else np.nan
    r = daily_returns(equity)
    vol = float(r.std(ddof=1) * np.sqrt(DAYS_PER_YEAR)) if len(r) > 2 else np.nan
    sharpe = float(r.mean() / r.std(ddof=1) * np.sqrt(DAYS_PER_YEAR)) if len(r) > 2 and r.std(ddof=1) > 0 else np.nan
    downside = np.sqrt((np.minimum(r, 0.0) ** 2).mean()) if len(r) > 2 else np.nan
    sortino = float(r.mean() / downside * np.sqrt(DAYS_PER_YEAR)) if downside and downside > 0 else np.nan
    mdd, peak_t, trough_t, under_days = max_drawdown(equity)
    out = {
        "years": years,
        "total_return": total,
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": mdd,
        "dd_peak": peak_t,
        "dd_trough": trough_t,
        "max_underwater_days": under_days,
        "calmar": float(cagr / abs(mdd)) if mdd < 0 and cagr == cagr else np.nan,
        "worst_day": float(r.min()) if len(r) else np.nan,
        "best_day": float(r.max()) if len(r) else np.nan,
    }
    m = equity.resample("ME").last().pct_change().dropna()
    out["worst_month"] = float(m.min()) if len(m) else np.nan
    out["pct_positive_months"] = float((m > 0).mean()) if len(m) else np.nan
    if weight is not None:
        out["avg_exposure"] = float(weight.mean())
        out["time_in_market"] = float((weight > 0.02).mean())
        ep = episodes(weight, equity)
        out["episodes"] = int(len(ep))
        out["episode_win_rate"] = float((ep["ret"] > 0).mean()) if len(ep) else np.nan
        gains = ep.loc[ep["ret"] > 0, "ret"].sum()
        losses = -ep.loc[ep["ret"] < 0, "ret"].sum()
        out["profit_factor"] = float(gains / losses) if losses > 0 else np.nan
        out["avg_episode_days"] = float(ep["hours"].mean() / 24.0) if len(ep) else np.nan
    if trades is not None:
        out["executions"] = int(len(trades))
        out["executions_per_year"] = float(len(trades) / years) if years > 0 else np.nan
        if len(trades):
            turn = float((trades["w_after"] - trades["w_before"]).abs().sum())
            out["turnover_per_year"] = turn / years if years > 0 else np.nan
            out["stops"] = int((trades["kind"] == "stop").sum())
        else:
            out["turnover_per_year"] = 0.0
            out["stops"] = 0
    return out


def yearly_table(equity: pd.Series, benchmark: pd.Series) -> pd.DataFrame:
    """Rentabilidad por año natural de la estrategia frente a comprar y mantener."""

    def by_year(s: pd.Series) -> pd.Series:
        last = s.resample("YE").last()
        first = pd.concat([pd.Series([s.iloc[0]], index=[s.index[0]]), last]).iloc[:-1].to_numpy()
        return pd.Series(last.to_numpy() / first - 1.0, index=last.index.year)

    def dd_by_year(s: pd.Series) -> pd.Series:
        return s.groupby(s.index.year).apply(lambda x: float((x / x.cummax() - 1.0).min()))

    return pd.DataFrame(
        {
            "estrategia": by_year(equity),
            "btc_hold": by_year(benchmark),
            "dd_estrategia": dd_by_year(equity),
            "dd_btc": dd_by_year(benchmark),
        }
    )


def bootstrap_sharpe(equity: pd.Series, n_boot: int = 2000, block_days: int = 20, seed: int = 7) -> dict:
    """Intervalo de confianza del Sharpe por *bootstrap* de bloques circulares.

    Los bloques preservan la autocorrelación y los racimos de volatilidad de BTC;
    un bootstrap i.i.d. daría intervalos engañosamente estrechos.
    """
    r = daily_returns(equity).to_numpy("float64")
    n = len(r)
    if n < 60:
        return {"sharpe_p05": np.nan, "sharpe_p50": np.nan, "sharpe_p95": np.nan, "prob_sharpe_gt_0": np.nan}
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block_days))
    starts = rng.integers(0, n, size=(n_boot, n_blocks))
    offsets = np.arange(block_days)
    pos = (starts[:, :, None] + offsets[None, None, :]) % n
    samples = r[pos.reshape(n_boot, -1)[:, :n]]
    sd = samples.std(axis=1, ddof=1)
    sh = np.where(sd > 0, samples.mean(axis=1) / sd * np.sqrt(DAYS_PER_YEAR), 0.0)
    return {
        "sharpe_p05": float(np.percentile(sh, 5)),
        "sharpe_p50": float(np.percentile(sh, 50)),
        "sharpe_p95": float(np.percentile(sh, 95)),
        "prob_sharpe_gt_0": float((sh > 0).mean()),
    }


def bootstrap_excess(equity: pd.Series, benchmark: pd.Series, n_boot: int = 2000, block_days: int = 20, seed: int = 7) -> dict:
    """Probabilidad de que la estrategia supere a comprar-y-mantener en Sharpe y en caída máxima.

    Remuestrea conjuntamente (mismos bloques) los retornos de ambas curvas.
    """
    a = daily_returns(equity)
    b = daily_returns(benchmark).reindex(a.index).fillna(0.0)
    ra, rb = a.to_numpy("float64"), b.to_numpy("float64")
    n = len(ra)
    if n < 60:
        return {"prob_sharpe_beats_hold": np.nan, "prob_dd_beats_hold": np.nan}
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block_days))
    starts = rng.integers(0, n, size=(n_boot, n_blocks))
    pos = ((starts[:, :, None] + np.arange(block_days)[None, None, :]) % n).reshape(n_boot, -1)[:, :n]
    sa, sb = ra[pos], rb[pos]

    def sharpe(x):
        sd = x.std(axis=1, ddof=1)
        return np.where(sd > 0, x.mean(axis=1) / sd, 0.0)

    def mdd(x):
        curve = np.cumprod(1.0 + x, axis=1)
        return (curve / np.maximum.accumulate(curve, axis=1) - 1.0).min(axis=1)

    return {
        "prob_sharpe_beats_hold": float((sharpe(sa) > sharpe(sb)).mean()),
        "prob_dd_beats_hold": float((mdd(sa) > mdd(sb)).mean()),
    }
