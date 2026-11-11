"""Interfaz de línea de comandos de Centinela.

    centinela datos        descarga / actualiza el histórico de BTC
    centinela estado       radiografía de BTC ahora mismo y qué haría el bot
    centinela backtest     simulación histórica (y, con --informe, informe HTML)
    centinela validar      pruebas de robustez y resultado fuera de muestra
    centinela papel        opera en vivo con dinero simulado
    centinela real         opera en vivo con dinero real (requiere confirmación explícita)
    centinela parar        activa el interruptor de emergencia (no se envían órdenes)
    centinela reanudar     desactiva el interruptor
    centinela liquidar     vende todo el BTC gestionado y deja el bot parado
    centinela probar-orden compra un importe mínimo y lo revende, para verificar el envío de órdenes
    centinela doctor       comprueba que todo está listo para operar
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__, btc, pipeline, strategy
from .backtest import report, validation
from .backtest.metrics import bootstrap_excess, bootstrap_sharpe, compute_metrics, yearly_table
from .config import PROFILES, Config, ConfigError, api_credentials, load, load_env
from .data import binance
from .data.store import BITSTAMP, DataStore, describe_gaps
from .risk import RiskState

console = Console()
log = logging.getLogger("centinela")


# ----------------------------------------------------------------- formato
def pct(v, d: int = 1, signed: bool = False) -> str:
    if v is None or v != v:
        return "n/d"
    s = f"{v * 100:+.{d}f}" if signed else f"{v * 100:.{d}f}"
    return s.replace(".", ",") + " %"


def num(v, d: int = 2) -> str:
    if v is None or v != v:
        return "n/d"
    return f"{v:,.{d}f}".replace(",", " ").replace(".", ",")


def setup_logging(verbose: bool, log_dir: str | None = None) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for hdl in list(root.handlers):
        root.removeHandler(hdl)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(Path(log_dir) / "centinela.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("ccxt").setLevel(logging.WARNING)


def with_profile(cfg: Config, profile: str | None) -> Config:
    """Aplica un perfil indicado por línea de comandos sobre la configuración cargada."""
    if not profile or profile == cfg.profile:
        return cfg
    from dataclasses import replace

    p = PROFILES[profile]
    return replace(
        cfg,
        profile=profile,
        allocation=p["allocation"],
        strategy=replace(cfg.strategy, target_vol=p["target_vol"], full_forecast=p["full_forecast"]),
        risk=replace(cfg.risk, dd_halt=p["dd_halt"]),
    )


def load_bars(cfg: Config, extended: bool | None = None) -> pd.DataFrame:
    store = DataStore(cfg.data_dir)
    if extended is None:
        extended = store.path(BITSTAMP).exists()
    return store.market(extended=extended)


# =================================================================== datos
def cmd_datos(cfg: Config, args) -> int:
    store = DataStore(cfg.data_dir)
    with console.status("Descargando velas horarias de BTC/USDT (Binance, datos públicos)…"):
        k = store.update_klines()
    console.print(f"  velas 1h      {len(k):>7,} filas   {_d(k['ts'].iloc[0])} → {_d(k['ts'].iloc[-1])}")
    with console.status("Descargando funding del perpetuo (Binance + OKX)…"):
        f = store.update_funding()
    console.print(f"  funding       {len(f):>7,} filas   {_d(f['ts'].iloc[0])} → {_d(f['ts'].iloc[-1])}")
    try:
        with console.status("Descargando MVRV on-chain (CoinMetrics)…"):
            m = store.update_mvrv()
        console.print(f"  MVRV          {len(m):>7,} filas   {_d(m['ts'].iloc[0])} → {_d(m['ts'].iloc[-1])}")
    except Exception as exc:
        console.print(f"  [yellow]MVRV no disponible ({exc}); es solo contexto, se puede seguir[/]")
    if not args.sin_extendido:
        with console.status("Descargando histórico previo a 2017 (Bitstamp)…"):
            b = store.update_bitstamp()
        console.print(f"  Bitstamp 1h   {len(b):>7,} filas   {_d(b['ts'].iloc[0])} → {_d(b['ts'].iloc[-1])}")
    bars = store.market()
    gaps = [g for g in describe_gaps(bars) if g[1] >= 4]
    console.print(f"\nDatos listos en [bold]{store.root}/[/]. Paradas del mercado ≥ 4 h en el histórico: {len(gaps)} (se tratan como horas no operables).")
    return 0


def _d(ts_ms) -> str:
    return datetime.fromtimestamp(int(ts_ms) / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


# ================================================================== estado
def cmd_estado(cfg: Config, args) -> int:
    store = DataStore(cfg.data_dir)
    if not args.sin_actualizar:
        try:
            with console.status("Actualizando datos…"):
                store.update_klines()
                store.update_funding()
                try:
                    store.update_mvrv()
                except Exception:
                    pass
        except Exception as exc:
            console.print(f"[yellow]No se pudo actualizar ({exc}); se muestra el último dato local.[/]")
    bars = store.market()
    feats, target = pipeline.build_targets(cfg, bars)
    ctx = strategy.context(bars, feats)
    if not args.sin_actualizar:
        from .data import extra

        height = extra.fetch_block_height()  # afina la fecha estimada del próximo halving
        if height:
            ctx["cycle"] = btc.cycle_info(bars.index[-1].to_pydatetime(), height)
    row = feats.iloc[-1]
    age_h = (datetime.now(timezone.utc) - (bars.index[-1].to_pydatetime() + pd.Timedelta(hours=1))).total_seconds() / 3600

    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim", no_wrap=True)
    t.add_column()
    t.add_row("Precio", f"[bold]{num(ctx['price'], 0)} $[/]   24 h {pct(ctx['ret_24h'], 1, True)} · 7 d {pct(ctx['ret_7d'], 1, True)} · 30 d {pct(ctx['ret_30d'], 1, True)}")
    t.add_row("Desde máximos", f"{pct(ctx['drawdown_from_ath'], 1)} respecto al máximo histórico")
    t.add_row("Régimen", f"[bold]{ctx['regime']}[/]")
    t.add_row("Volatilidad", f"{pct(ctx['vol'], 0)} anualizada prevista (percentil {pct(ctx['vol_rank_1y'], 0)} del último año)")
    t.add_row("Sesión", f"{ctx['session']}{' · fin de semana (libro más fino)' if ctx['weekend'] else ''}")
    console.print(Panel(t, title=f"BTC · vela {bars.index[-1]:%Y-%m-%d %H:%M} UTC (cerró hace {num(max(age_h, 0.0), 1)} h)", border_style="cyan"))

    d = Table.grid(padding=(0, 2))
    d.add_column()
    for line in strategy.explain(row, cfg.strategy):
        d.add_row(line)
    final = float(target.iloc[-1])
    if cfg.allocation < 1 and final == final:
        d.add_row(f"Perfil {cfg.profile}: solo el {cfg.allocation:.0%} del capital sigue la señal → peso final {final:.0%}.")
    console.print(Panel(d, title=f"Decisión del bot (perfil {cfg.profile})", border_style="green"))

    c = Table.grid(padding=(0, 2))
    c.add_column(style="dim", no_wrap=True)
    c.add_column()
    missing = "[dim]sin datos (ejecuta `centinela datos`)[/]"
    if ctx["funding_8h"] == ctx["funding_8h"]:
        stale = " [yellow](dato atrasado)[/]" if ctx["funding_stale"] else ""
        rate = f"{ctx['funding_8h'] * 100:+.4f}".replace(".", ",")
        c.add_row("Funding perpetuo", f"{rate} % cada 8 h → {pct(ctx['funding_annualized'], 1, True)} anual (percentil {pct(ctx['funding_rank_1y'], 0)} del año){stale}")
    else:
        c.add_row("Funding perpetuo", missing)
    if ctx["mvrv"] == ctx["mvrv"]:
        stale = " [yellow](dato atrasado)[/]" if ctx["mvrv_stale"] else ""
        c.add_row("MVRV on-chain", f"{num(ctx['mvrv'])} (precio de mercado / coste medio de todas las monedas; <1 = el titular medio pierde){stale}")
    else:
        c.add_row("MVRV on-chain", missing)
    c.add_row("Múltiplo de Mayer", f"{num(ctx['mayer_multiple'])} (precio / media de 200 días)")
    c.add_row("Ciclo", ctx["cycle"].describe())
    console.print(Panel(c, title="Contexto propio de Bitcoin (informativo: no mueve la posición)", border_style="dim"))

    for mode in ("papel", "real", "real-demo"):
        db = Path(cfg.state_dir) / f"{mode}.db"
        if db.exists():
            _print_portfolio(cfg, mode)
    from .live.state import is_stopped

    if is_stopped(cfg.state_dir):
        console.print("[bold red]Interruptor STOP activo:[/] el bot no enviará órdenes hasta `centinela reanudar`.")
    return 0


def _print_portfolio(cfg: Config, mode: str) -> None:
    from .live.state import StateStore

    st = StateStore(cfg.state_dir, mode)
    try:
        hist = st.equity_history()
        last = st.last_decision()
        if not hist or not last:
            return
        first_eq, last_eq = hist[0][1], hist[-1][1]
        rs = RiskState.from_dict(st.get("risk"))
        t = Table.grid(padding=(0, 2))
        t.add_column(style="dim", no_wrap=True)
        t.add_column()
        t.add_row("Patrimonio", f"[bold]{num(last_eq, 2)} {cfg.execution.quote}[/]  ({pct(last_eq / first_eq - 1, 2, True)} desde {_d(hist[0][0])})")
        t.add_row("Posición", f"{pct(last.get('weight_after') or last.get('weight_before') or 0, 0)} en BTC · objetivo {pct(last.get('final_target') or 0, 0)}")
        if rs.peak_equity > 0:
            t.add_row("Caída actual", f"{pct(last_eq / rs.peak_equity - 1, 1)} desde el máximo de la cartera (el gobernador actúa al {pct(-cfg.risk.dd_halt, 0)})")
        t.add_row("Última decisión", f"{_d(last['ts_ms'])} UTC · {last.get('action', '')}")
        beat = st.get("heartbeat")
        if beat:
            mins = (time.time() * 1000 - beat) / 60000
            late = mins > 75  # el bot decide cada hora: más de 75 min sin latido es que no está corriendo
            t.add_row("Último latido", f"hace {mins:.0f} min" + (" [yellow]· el bot no parece estar en marcha[/]" if late else ""))
        for note in last.get("notes") or []:
            t.add_row("", f"[yellow]{note}[/]")
        fills = st.fills(5)
        if fills:
            t.add_row("Últimas órdenes", "")
            for ts, side, qty, price, fee, _reason in fills:
                t.add_row("", f"{_d(ts)}  {'COMPRA' if side == 'buy' else 'VENTA '}  {qty:.6f} BTC a {num(price, 2)}  (comisión {num(fee, 2)})")
        label = "real · entorno demo del exchange (dinero ficticio)" if mode == "real-demo" else mode
        console.print(Panel(t, title=f"Cartera en modo {label}", border_style="magenta" if mode == "real" else "blue"))
    finally:
        st.close()


# ================================================================ backtest
def _metrics_table(title: str, res) -> Table:
    m = compute_metrics(res.equity, res.weight, res.trades)
    b = compute_metrics(res.benchmark)
    t = Table(title=title, title_justify="left", header_style="bold")
    t.add_column("")
    t.add_column("Centinela", justify="right")
    t.add_column("Comprar y mantener BTC", justify="right")
    rows = [
        ("Rentabilidad total", pct(m["total_return"], 1, True), pct(b["total_return"], 1, True)),
        ("Rentabilidad anual", pct(m["cagr"], 1, True), pct(b["cagr"], 1, True)),
        ("Volatilidad anual", pct(m["vol"]), pct(b["vol"])),
        ("Ratio de Sharpe", num(m["sharpe"]), num(b["sharpe"])),
        ("Ratio de Sortino", num(m["sortino"]), num(b["sortino"])),
        ("Peor caída", pct(m["max_drawdown"]), pct(b["max_drawdown"])),
        ("Días máx. bajo máximos", num(m["max_underwater_days"], 0), num(b["max_underwater_days"], 0)),
        ("Peor mes", pct(m["worst_month"]), pct(b["worst_month"])),
        ("Meses en positivo", pct(m["pct_positive_months"], 0), pct(b["pct_positive_months"], 0)),
        ("Exposición media a BTC", pct(m["avg_exposure"], 0), "100 %"),
        ("Órdenes por año", num(m["executions_per_year"], 0), "0"),
        ("Rotación anual", num(m["turnover_per_year"], 1) + "×", "0"),
        ("Tramos con posición", f"{m['episodes']} ({pct(m['episode_win_rate'], 0)} ganadores)", "—"),
    ]
    for r in rows:
        t.add_row(*r)
    return t


def _default_start(bars: pd.DataFrame, cfg: Config) -> pd.Timestamp:
    first_valid = bars.index[0] + pd.Timedelta(days=cfg.strategy.warmup_days)
    return max(first_valid, pd.Timestamp(validation.DEFAULT_START, tz="UTC"))


def cmd_backtest(cfg: Config, args) -> int:
    from dataclasses import replace

    cfg = with_profile(cfg, args.perfil)
    if args.comision is not None:
        cfg = replace(cfg, execution=replace(cfg.execution, fee=args.comision))
    bars = load_bars(cfg)
    start = pd.Timestamp(args.desde, tz="UTC") if args.desde else _default_start(bars, cfg)
    end = pd.Timestamp(args.hasta, tz="UTC") if args.hasta else None
    with console.status("Simulando…"):
        res = pipeline.backtest(cfg, bars, start=start, end=end)
    console.print(
        f"\nPerfil [bold]{cfg.profile}[/] · comisión {pct(cfg.execution.fee, 2)} + deslizamiento {pct(cfg.execution.slippage, 2)} por lado · "
        f"banda {cfg.effective_band:.0%} · {res.equity.index[0]:%Y-%m-%d} → {res.equity.index[-1]:%Y-%m-%d}\n"
    )
    console.print(_metrics_table("Periodo completo", res))
    for name, part in validation.split_design_holdout(res).items():
        console.print(_metrics_table(f"Tramo «{name}»", part))
    yt = yearly_table(res.equity, res.benchmark)
    t = Table(title="Año a año", title_justify="left", header_style="bold")
    for col in ("Año", "Centinela", "BTC", "Peor caída Centinela", "Peor caída BTC"):
        t.add_column(col, justify="right")
    for y, r in yt.iterrows():
        t.add_row(str(y), pct(r["estrategia"], 1, True), pct(r["btc_hold"], 1, True), pct(r["dd_estrategia"]), pct(r["dd_btc"]))
    console.print(t)
    halts = res.meta.get("halts", 0)
    if halts:
        console.print(f"El gobernador de caída se activó {halts} {'vez' if halts == 1 else 'veces'} en la simulación.")
    if args.informe:
        path = Path(args.informe if isinstance(args.informe, str) else Path(cfg.reports_dir) / "backtest.html")
        with console.status("Generando informe (incluye pruebas de robustez, ~1 min)…"):
            report.write(path, cfg, bars, res, robustness=not args.sin_robustez)
        console.print(f"\nInforme escrito en [bold]{path}[/] (ábrelo en el navegador).")
    return 0


# ================================================================= validar
def cmd_validar(cfg: Config, args) -> int:
    cfg = with_profile(cfg, args.perfil)
    bars = load_bars(cfg)
    start = _default_start(bars, cfg)
    with console.status("Backtest base…"):
        res = pipeline.backtest(cfg, bars, start=start)
    parts = validation.split_design_holdout(res)
    t = Table(title="Diseño frente a fuera de muestra", title_justify="left", header_style="bold")
    for col in ("Tramo", "Rentab. anual", "BTC anual", "Sharpe", "Sharpe BTC", "Peor caída", "Peor caída BTC"):
        t.add_column(col, justify="right")
    for name, part in [("todo", res), *parts.items()]:
        m, b = compute_metrics(part.equity, part.weight, part.trades), compute_metrics(part.benchmark)
        t.add_row(name, pct(m["cagr"], 1, True), pct(b["cagr"], 1, True), num(m["sharpe"]), num(b["sharpe"]), pct(m["max_drawdown"]), pct(b["max_drawdown"]))
    console.print(t)
    console.print(
        f"[dim]El diseño se congeló con datos hasta 2024. Todo lo posterior al {validation.HOLDOUT_START} es fuera de muestra: "
        "el bot nunca «vio» ese tramo al ser diseñado.[/]\n"
    )

    bs = bootstrap_sharpe(res.equity)
    be = bootstrap_excess(res.equity, res.benchmark)
    console.print(
        f"Bootstrap de bloques (2.000 remuestreos): Sharpe en [{num(bs['sharpe_p05'])}, {num(bs['sharpe_p95'])}] al 90 %; "
        f"P(Sharpe > 0) = {pct(bs['prob_sharpe_gt_0'], 0)}; P(mejor Sharpe que mantener BTC) = {pct(be['prob_sharpe_beats_hold'], 0)}; "
        f"P(menor caída máxima que BTC) = {pct(be['prob_dd_beats_hold'], 0)}.\n"
    )
    end = res.equity.index[-1] + pd.Timedelta(hours=1)

    def show(title: str, first_col: str, rows: list[dict], key, fmt) -> None:
        tb = Table(title=title, title_justify="left", header_style="bold")
        tb.add_column(first_col)
        for col in ("Rentab. anual", "Sharpe", "Peor caída"):
            tb.add_column(col, justify="right")
        for r in rows:
            tb.add_row(fmt(r[key]), pct(r["cagr"], 1, True), num(r["sharpe"]), pct(r["max_drawdown"]))
        console.print(tb)

    with console.status("Sensibilidad a comisiones…"):
        rows = validation.fee_sensitivity(cfg, bars, (0.0005, 0.0010, 0.0026, 0.0040, 0.0060), start, end)
    show("Si las comisiones fueran otras", "Comisión por lado", rows, "fee", lambda v: pct(v, 2))
    with console.status("Sensibilidad a retrasos…"):
        rows = validation.delay_sensitivity(cfg, bars, (0, 1, 6, 24, 48), start, end)
    show("Si cada orden llegara tarde", "Retraso", rows, "delay_h", lambda v: "sin retraso" if v == 0 else f"{v} h")
    with console.status("Sensibilidad a parámetros…"):
        rows = validation.parameter_sensitivity(cfg, bars, start, end)
    show("Si los parámetros fueran otros", "Variante", rows, "variant", str)
    return 0


# ============================================================ papel / real
def _state_name(cfg: Config, mode: str) -> str:
    """Nombre del fichero de estado de cada cartera.

    El entorno demo del exchange es otra cuenta, con otro saldo: lleva su propio estado para
    que una prueba con dinero ficticio no contamine el máximo de cartera, el cortafuegos ni
    el historial de la cuenta de verdad.
    """
    return "real-demo" if mode == "real" and cfg.execution.sandbox else mode


def _lock(cfg: Config, mode: str):
    """Impide dos instancias sobre el mismo estado (duplicarían órdenes)."""
    import fcntl

    name = _state_name(cfg, mode)
    Path(cfg.state_dir).mkdir(parents=True, exist_ok=True)
    fh = open(Path(cfg.state_dir) / f"{name}.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise SystemExit(f"Ya hay un Centinela en modo {name} usando {cfg.state_dir}/. No se arranca un segundo.")
    return fh


def _real_broker(cfg: Config, state):
    """Broker del exchange, con la orden en vuelo anotada en el estado (se barre tras una caída)."""
    from .live.broker import CcxtBroker

    return CcxtBroker(
        cfg.execution,
        api_credentials(),
        load_pending=lambda: state.get("pending_order"),
        save_pending=lambda p: state.set("pending_order", p),
    )


def _build_engine(cfg: Config, mode: str, dry_run: bool = False, adopt: bool = False):
    from .live.broker import PaperBroker
    from .live.engine import LiveEngine
    from .live.notify import Notifier
    from .live.state import StateStore

    state = StateStore(cfg.state_dir, _state_name(cfg, mode))
    if mode == "papel":
        broker = PaperBroker(
            cfg.execution,
            cfg.paper_capital,
            load=lambda: state.get("paper_balances"),
            save=lambda b: state.set("paper_balances", b),
        )
    else:
        broker = _real_broker(cfg, state)
    store = DataStore(cfg.data_dir)
    return LiveEngine(cfg, broker, store, state, Notifier(cfg.telegram), dry_run=dry_run, adopt_existing=adopt), state


def _run_live(cfg: Config, mode: str, args) -> int:
    setup_logging(args.verbose, "logs")
    from .live.engine import StartupError

    lock = _lock(cfg, mode)
    engine, state = _build_engine(cfg, mode, dry_run=getattr(args, "simular", False), adopt=getattr(args, "adoptar_saldo", False))
    try:
        if args.una_vez:
            engine.startup()
            d = engine.cycle()
            console.print(Panel("\n".join([d.action, *d.explanation, *[f"[yellow]{n}[/]" for n in d.notes]]), title=f"Ciclo único · {d.bar[:16]} UTC"))
            return 0
        engine.run_forever()
        return 0
    except StartupError as exc:
        console.print(f"[red]No se arranca:[/] {exc}")
        return 2
    finally:
        state.close()
        lock.close()


def cmd_papel(cfg: Config, args) -> int:
    console.print(
        f"[bold]Modo papel[/]: dinero simulado ({num(cfg.paper_capital, 0)} {cfg.execution.quote} iniciales), precios reales. "
        "Ctrl+C para detener; el estado se conserva."
    )
    return _run_live(cfg, "papel", args)


def cmd_real(cfg: Config, args) -> int:
    if cfg.mode != "real":
        console.print("[red]La configuración dice `modo: papel`.[/] Para operar con dinero real cambia a `modo: real` en config.yaml.")
        return 2
    if not args.confirmo_dinero_real:
        console.print(
            "[red]Falta la confirmación explícita.[/] Operar en real exige `modo: real` en la configuración "
            "[bold]y[/] el indicador --confirmo-dinero-real. Prueba antes con --simular (no envía órdenes)."
        )
        return 2
    if cfg.execution.sandbox:
        console.print(
            Panel(
                f"Entorno DEMO de {cfg.execution.exchange} ({cfg.execution.symbol}): órdenes de verdad contra el exchange, "
                "pero con dinero ficticio.\nSirve para probar el envío de órdenes. Su estado se guarda aparte del de la cuenta real.",
                title="MODO REAL · DEMO",
                border_style="yellow",
            )
        )
        return _run_live(cfg, "real", args)
    console.print(
        Panel(
            f"Vas a operar con DINERO REAL en {cfg.execution.exchange} ({cfg.execution.symbol}).\n"
            "El bot gestiona todo el BTC y el efectivo de la cuenta salvo las reservas configuradas.\n"
            "Puedes perder dinero. Interruptor de emergencia: `centinela parar`.",
            title="MODO REAL",
            border_style="red",
        )
    )
    return _run_live(cfg, "real", args)


# ============================================== parar / reanudar / liquidar
def cmd_parar(cfg: Config, args) -> int:
    from .live.state import set_stopped

    set_stopped(cfg.state_dir, True, f"detenido manualmente el {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n")
    console.print("Interruptor STOP activado: el bot sigue vivo y vigilando, pero [bold]no enviará órdenes[/]. La posición actual se mantiene.")
    return 0


def cmd_reanudar(cfg: Config, args) -> int:
    from .live.state import set_stopped

    set_stopped(cfg.state_dir, False)
    console.print("Interruptor STOP desactivado: el bot volverá a operar en su próximo ciclo.")
    return 0


def cmd_liquidar(cfg: Config, args) -> int:
    from .live.state import set_stopped

    mode = "real" if args.real else "papel"
    if mode == "real" and (cfg.mode != "real" or not args.confirmo_dinero_real):
        console.print("[red]Liquidar en real exige `modo: real` en la configuración y --confirmo-dinero-real.[/]")
        return 2
    setup_logging(args.verbose, "logs")
    set_stopped(cfg.state_dir, True, "liquidación manual\n")  # primero se bloquea al bot en marcha
    engine, state = _build_engine(cfg, mode)
    try:
        engine.broker.cancel_open_orders()
        quote = engine.broker.quote()
        base, cash, equity, _w = engine._account(quote)
        rules = engine.broker.rules()
        qty = rules.floor_amount(base)
        if not rules.tradable(qty, quote.bid):
            console.print("No hay BTC gestionado que vender. El interruptor STOP queda activado.")
            return 0
        fill = engine.broker.execute("sell", qty, quote, "liquidación manual")
        if fill is None:
            console.print("[red]La venta no se ejecutó.[/] Revisa la cuenta. El interruptor STOP queda activado.")
            return 1
        state.record_fill(fill.ts_ms, fill.order_id, "sell", fill.qty, fill.price, fill.fee_quote, "liquidación manual")
        base, cash, _e, _w = engine._account(quote)
        state.set("balances", {"base": base, "quote": cash})
        console.print(f"Vendidos {fill.qty:.6f} BTC a {num(fill.price, 2)}. El interruptor STOP queda activado (`centinela reanudar` para volver a operar).")
        return 0
    finally:
        state.close()


# ============================================================== probar-orden
MAX_TEST_QUOTE = 50.0  # tope del importe de la prueba: es una verificación, no una forma de operar


def cmd_probar_orden(cfg: Config, args) -> int:
    """Compra un importe mínimo de BTC y lo revende enseguida.

    Verifica de punta a punta lo único que el papel no puede probar: que el exchange acepta,
    ejecuta y liquida las órdenes del bot. La estrategia no interviene, así que sirve también
    cuando el bot está fuera del mercado. Cuesta las dos comisiones y el spread del importe.
    """
    q = cfg.execution.quote
    if cfg.mode != "real" or not args.confirmo_dinero_real:
        console.print("[red]La prueba envía órdenes de verdad:[/] exige `modo: real` en la configuración y --confirmo-dinero-real.")
        return 2
    amount = float(args.importe)
    if not 0 < amount <= MAX_TEST_QUOTE:
        console.print(f"[red]El importe debe estar entre 0 y {MAX_TEST_QUOTE:.0f} {q}.[/] Es una prueba, no una forma de operar.")
        return 2
    setup_logging(args.verbose, "logs")
    from .live.state import StateStore

    lock = _lock(cfg, "real")  # nunca a la vez que el bot: compartirían la orden en vuelo
    state = StateStore(cfg.state_dir, _state_name(cfg, "real"))
    buy = None
    try:
        broker = _real_broker(cfg, state)
        broker.cancel_open_orders()
        rules, quote, before = broker.rules(), broker.quote(), broker.balances()
        minimum = 2.0 * rules.min_cost  # margen para que la venta de vuelta también supere el mínimo
        if amount < minimum:
            console.print(f"[red]Importe demasiado pequeño:[/] {broker.name} exige al menos {num(rules.min_cost, 2)} {q} por orden; usa --importe {minimum:.0f} o más.")
            return 2
        free = before.free_quote - cfg.execution.reserve_quote
        if free < amount * 1.01:
            console.print(
                f"[red]Saldo insuficiente para la prueba:[/] hay {num(max(free, 0.0), 2)} {q} disponibles en la cuenta al contado "
                f"de {broker.name} y hacen falta {num(amount * 1.01, 2)}. No se ha enviado nada."
            )
            return 1
        qty = rules.floor_amount(amount / quote.ask)
        console.print(f"Prueba de orden en [bold]{broker.name}[/]: compra de ~{num(amount, 2)} {q} de BTC y venta inmediata.")
        buy = broker.execute("buy", qty, quote, "prueba de orden")
        if buy is None:
            console.print("[red]La compra no se ejecutó[/] (no se casó dentro del tope de precio y se canceló). No se ha gastado nada.")
            return 1
        state.record_fill(buy.ts_ms, buy.order_id, "buy", buy.qty, buy.price, buy.fee_quote, "prueba de orden")
        console.print(f"  [green]✔[/] Compra: {buy.qty:.6f} BTC a {num(buy.price, 2)} · comisión {num(buy.fee_quote, 4)} {q}")

        # Se vende lo que de verdad llegó: algunos exchanges (Bitget, OKX) cobran la comisión en BTC.
        got = 0.0
        for _ in range(6):
            got = max(0.0, broker.balances().free_base - before.free_base)
            if got > 0:
                break
            time.sleep(1.0)  # el saldo puede tardar un instante en reflejar la compra
        quote = broker.quote()
        sell_qty = rules.floor_amount(min(buy.qty, got))
        sell = broker.execute("sell", sell_qty, quote, "prueba de orden") if rules.tradable(sell_qty, quote.bid) else None
        if sell is None:
            console.print(
                f"  [red]✘ La venta de vuelta no se ejecutó.[/] Quedan ~{got:.6f} BTC de la prueba en la cuenta: "
                "véndelos a mano o deja que el bot los gestione."
            )
            return 1
        state.record_fill(sell.ts_ms, sell.order_id, "sell", sell.qty, sell.price, sell.fee_quote, "prueba de orden")
        console.print(f"  [green]✔[/] Venta:  {sell.qty:.6f} BTC a {num(sell.price, 2)} · comisión {num(sell.fee_quote, 4)} {q}")

        end = broker.balances()
        dust = max(0.0, end.base - before.base)
        console.print(f"  [green]✔[/] Órdenes propias aún abiertas: {broker.cancel_open_orders()}")
        console.print(
            f"\nCoste de la prueba: {num(before.quote - end.quote, 4)} {q} (dos comisiones y el spread)."
            + (f" Quedan {dust:.8f} BTC de resto, por debajo del mínimo vendible." if dust > 0 else "")
            + "\n[green]El envío de órdenes funciona de punta a punta.[/]"
        )
        return 0
    except ConfigError:
        raise
    except Exception as exc:  # error del exchange o de red: se explica en vez de volcar una traza
        console.print(f"[red]La prueba falló:[/] {type(exc).__name__}: {exc}")
        if buy is not None:
            console.print(
                f"[yellow]La compra sí se había ejecutado:[/] pueden quedar ~{buy.qty:.6f} BTC de la prueba en la cuenta. "
                "Véndelos a mano o deja que el bot los gestione."
            )
        return 1
    finally:
        state.close()
        lock.close()


# ================================================================== doctor
def cmd_doctor(cfg: Config, args) -> int:
    ok_all = True

    def check(name: str, fn) -> None:
        nonlocal ok_all
        try:
            detail = fn()
            console.print(f"  [green]✔[/] {name}" + (f"  [dim]{detail}[/]" if detail else ""))
        except Exception as exc:
            ok_all = False
            console.print(f"  [red]✘[/] {name}  [red]{type(exc).__name__}: {exc}[/]")

    demo = " · entorno DEMO del exchange (dinero ficticio)" if cfg.execution.sandbox else ""
    console.print(f"Centinela {__version__} · perfil {cfg.profile} · modo {cfg.mode}{demo}\n")

    def data_ok():
        bars = DataStore(cfg.data_dir).market()
        age = (datetime.now(timezone.utc) - bars.index[-1].to_pydatetime()).total_seconds() / 3600 - 1
        if age > 3:
            raise RuntimeError(f"histórico con {age:.0f} h de retraso: ejecuta `centinela datos`")
        return f"{len(bars):,} velas, última cerrada hace {age:.1f} h"

    def clock_ok():
        drift = abs(binance.server_time_ms() / 1000 - time.time())
        if drift > 5:
            raise RuntimeError(f"reloj desviado {drift:.1f} s: sincroniza con NTP")
        return f"desvío {drift:.2f} s"

    def ref_ok():
        t = binance.book_ticker()
        return f"bid {num(t['bid'], 2)} / ask {num(t['ask'], 2)}"

    def fallback_ok():
        from .data import extra

        k = extra.fetch_okx_klines(limit=5)
        if k.empty:
            raise RuntimeError("sin velas")
        return f"última vela {_d(k['ts'].iloc[-1])}"

    def state_ok():
        p = Path(cfg.state_dir)
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".probe"
        probe.write_text("ok")
        probe.unlink()
        from .live.state import is_stopped

        return "STOP ACTIVO" if is_stopped(cfg.state_dir) else "escribible, sin STOP"

    def exchange_ok():
        from .live.broker import connect

        ex = connect(cfg.execution)  # mismo entorno (real o demo) que usará el broker
        ex.load_markets()
        m = ex.market(cfg.execution.symbol)
        taker = m.get("taker")
        note = f"comisión genérica publicada {pct(taker, 2)}" if taker else "comisión no publicada"
        if taker and taker > cfg.execution.fee * 1.5:
            note += f" [yellow](mayor que la configurada, {pct(cfg.execution.fee, 2)}; la que cuenta es la de tu cuenta, más abajo)[/]"
        lim = m.get("limits") or {}
        min_cost = (lim.get("cost") or {}).get("min")
        minimum = f"orden mínima {num(min_cost, 2)} {cfg.execution.quote}" if min_cost else f"mínimo {(lim.get('amount') or {}).get('min')} BTC"
        return f"{cfg.execution.symbol} disponible · {minimum} · {note}"

    def creds_ok():
        from .live.broker import CcxtBroker

        b = CcxtBroker(cfg.execution, api_credentials())
        bal = b.balances()
        out = f"autenticación correcta · {bal.base:.6f} BTC · {num(bal.quote, 2)} {cfg.execution.quote}"
        taker = b.account_taker_fee()
        if taker is not None:
            out += f" · comisión real de tu cuenta {pct(taker, 2)}"
            if taker > cfg.execution.fee * 1.05:
                out += f" [yellow](mayor que la configurada, {pct(cfg.execution.fee, 2)}: sube `ejecucion.comision`)[/]"
            elif taker < cfg.execution.fee * 0.95:
                out += f" [dim](menor que la configurada, {pct(cfg.execution.fee, 2)}: puedes bajar `ejecucion.comision`)[/]"
        return out

    check("Datos locales", data_ok)
    check("Reloj del sistema", clock_ok)
    check("Referencia de precio (Binance, datos públicos)", ref_ok)
    check("Fuente de reserva (OKX)", fallback_ok)
    check("Directorio de estado", state_ok)
    check(f"Exchange de ejecución ({cfg.execution.exchange})", exchange_ok)
    if cfg.mode == "real":
        check("Credenciales de API", creds_ok)
    elif os.environ.get("CENTINELA_API_KEY"):
        # En papel no hacen falta, pero si ya están puestas se comprueban (solo lectura): así se sabe
        # que la clave funciona antes de pasar a real. Un fallo aquí no impide operar en papel.
        was_ok = ok_all
        check("Credenciales de API (solo lectura; el papel no las usa)", creds_ok)
        ok_all = was_ok
    else:
        console.print("  [dim]·[/] Credenciales de API  [dim]no hacen falta en modo papel[/]")
    console.print("\n" + ("[green]Todo en orden.[/]" if ok_all else "[red]Hay comprobaciones fallidas: corrígelas antes de operar.[/]"))
    return 0 if ok_all else 1


# ==================================================================== main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="centinela", description="Bot de trading sistemático especializado en Bitcoin.")
    p.add_argument("--config", help="ruta del fichero de configuración (por defecto ./config.yaml si existe)")
    p.add_argument("-v", "--verbose", action="store_true", help="registro detallado")
    p.add_argument("--version", action="version", version=f"centinela {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="orden")

    s = sub.add_parser("datos", help="descarga o actualiza el histórico de BTC")
    s.add_argument("--sin-extendido", action="store_true", help="no descargar el histórico previo a 2017 (Bitstamp)")
    s.set_defaults(fn=cmd_datos)

    s = sub.add_parser("estado", help="radiografía de BTC y decisión actual del bot")
    s.add_argument("--sin-actualizar", action="store_true", help="usar solo los datos locales")
    s.set_defaults(fn=cmd_estado)

    s = sub.add_parser("backtest", help="simulación histórica")
    s.add_argument("--desde", help="fecha inicial AAAA-MM-DD")
    s.add_argument("--hasta", help="fecha final AAAA-MM-DD")
    s.add_argument("--perfil", choices=list(PROFILES), help="perfil de riesgo a simular")
    s.add_argument("--comision", type=float, help="comisión por lado en tanto por uno (0.001 = 0,1 %%)")
    s.add_argument("--informe", nargs="?", const=True, help="escribe un informe HTML (ruta opcional)")
    s.add_argument("--sin-robustez", action="store_true", help="informe rápido, sin pruebas de robustez")
    s.set_defaults(fn=cmd_backtest)

    s = sub.add_parser("validar", help="pruebas de robustez y resultado fuera de muestra")
    s.add_argument("--perfil", choices=list(PROFILES))
    s.set_defaults(fn=cmd_validar)

    s = sub.add_parser("papel", help="opera en vivo con dinero simulado")
    s.add_argument("--una-vez", action="store_true", help="ejecuta un único ciclo y termina")
    s.set_defaults(fn=cmd_papel)

    s = sub.add_parser("real", help="opera en vivo con dinero real")
    s.add_argument("--confirmo-dinero-real", action="store_true", help="confirmación explícita obligatoria")
    s.add_argument("--simular", action="store_true", help="calcula las órdenes pero no las envía")
    s.add_argument("--una-vez", action="store_true", help="ejecuta un único ciclo y termina")
    s.add_argument("--adoptar-saldo", action="store_true", help="permite al bot gestionar el BTC que ya haya en la cuenta")
    s.set_defaults(fn=cmd_real)

    s = sub.add_parser("parar", help="activa el interruptor de emergencia")
    s.set_defaults(fn=cmd_parar)
    s = sub.add_parser("reanudar", help="desactiva el interruptor de emergencia")
    s.set_defaults(fn=cmd_reanudar)

    s = sub.add_parser("liquidar", help="vende todo el BTC gestionado y deja el bot parado")
    s.add_argument("--real", action="store_true", help="liquidar la cuenta real (por defecto, la de papel)")
    s.add_argument("--confirmo-dinero-real", action="store_true")
    s.set_defaults(fn=cmd_liquidar)

    s = sub.add_parser("probar-orden", help="compra un importe mínimo de BTC y lo revende, para verificar el envío de órdenes")
    s.add_argument("--importe", type=float, default=10.0, help=f"importe de la prueba en la moneda de cotización (por defecto 10, máximo {MAX_TEST_QUOTE:.0f})")
    s.add_argument("--confirmo-dinero-real", action="store_true")
    s.set_defaults(fn=cmd_probar_orden)

    s = sub.add_parser("doctor", help="comprueba que todo está listo para operar")
    s.set_defaults(fn=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)
    load_env()
    try:
        cfg = load(args.config)
        return int(args.fn(cfg, args) or 0)
    except ConfigError as exc:
        console.print(f"[red]Configuración inválida:[/] {exc}")
        return 2
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        return 2
    except KeyboardInterrupt:
        console.print("\nInterrumpido.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
