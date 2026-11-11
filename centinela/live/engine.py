"""Bucle de operativa en vivo.

Cada hora, pocos segundos después del cierre de la vela:

    datos -> señales -> saldo real -> límites de riesgo -> (quizá) una orden -> registro

Filosofía de fallo: **ante la duda, no operar**. Cualquier anomalía (datos viejos,
precio del exchange que no cuadra con la referencia, libro vacío, interruptor
manual) bloquea las compras; las ventas que reducen riesgo siguen permitidas.
"""

from __future__ import annotations

import logging
import math
import signal
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable

import pandas as pd

from .. import pipeline, strategy
from ..config import Config
from ..data import binance, extra
from ..data.store import HOUR_MS, KLINES, DataStore, assemble
from ..risk import RiskManager, RiskState, is_full_exit, should_rebalance
from .broker import Broker, Fill, Quote
from .notify import Notifier
from .state import StateStore, is_stopped

log = logging.getLogger("centinela.vivo")


class StartupError(RuntimeError):
    """El bot no puede arrancar de forma segura; el mensaje explica qué hacer."""

CONTEXT_REFRESH_S = 6 * 3600  # funding y MVRV son contexto: basta refrescarlos cada 6 h
MAX_ORDER_ATTEMPTS = 3  # intentos de ejecución por ciclo, cada uno con cotización fresca
FLOW_TOLERANCE = 0.002  # diferencias de saldo menores al 0,2 % se consideran redondeos


@dataclass
class Decision:
    """Todo lo que el bot vio y decidió en un ciclo (se guarda íntegro para auditoría)."""

    ts_ms: int
    bar: str
    price: float
    equity: float
    weight_before: float
    raw_target: float
    final_target: float
    action: str = "mantener"
    notes: list[str] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)
    fill: dict | None = None
    weight_after: float | None = None
    stale_hours: float = 0.0
    data_source: str = "binance"
    regime: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class LiveEngine:
    def __init__(
        self,
        cfg: Config,
        broker: Broker,
        store: DataStore,
        state: StateStore,
        notifier: Notifier | None = None,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        dry_run: bool = False,
        adopt_existing: bool = False,
    ) -> None:
        self.cfg = cfg
        self.broker = broker
        self.store = store
        self.state = state
        self.notifier = notifier or Notifier(False)
        self.now = now
        self.sleep = sleep
        self.dry_run = dry_run
        self.adopt_existing = adopt_existing
        self._stop = False
        self._last_context_refresh = 0.0
        self._last_good_data = self.now()

    # ================================================================ datos
    def _expected_bar_ms(self) -> int:
        """Apertura de la última vela horaria que ya debería estar cerrada."""
        return (int(self.now() * 1000) // HOUR_MS) * HOUR_MS - HOUR_MS

    def refresh_data(self) -> tuple[pd.DataFrame, float, str]:
        """Actualiza el histórico y devuelve (velas, horas de retraso, fuente)."""
        expected = self._expected_bar_ms()
        source = "binance"
        klines = None
        for attempt in range(4):
            try:
                klines = self.store.update_klines()
                if int(klines["ts"].iloc[-1]) >= expected:
                    break
            except Exception as exc:
                log.warning("actualización de velas falló (intento %d): %s", attempt + 1, exc)
                klines = None
            self.sleep(5.0)
        if klines is None:
            klines = self.store.load(KLINES)
            if klines is None or klines.empty:
                raise RuntimeError("no hay histórico local y la fuente de datos no responde")
        if int(klines["ts"].iloc[-1]) < expected:
            klines, source = self._fallback(klines, expected)

        if self.now() - self._last_context_refresh > CONTEXT_REFRESH_S:
            for name, fn in (("funding", self.store.update_funding), ("MVRV", self.store.update_mvrv)):
                try:
                    fn()
                except Exception as exc:  # contexto, no señal: su ausencia no bloquea nada
                    log.warning("no se pudo refrescar %s: %s", name, exc)
            self._last_context_refresh = self.now()

        bars = assemble(klines, self.store.load("funding"), self.store.load("mvrv"))
        last = int(bars.index.as_unit("ms").asi8[-1])
        stale = max(0.0, (expected - last) / HOUR_MS)
        if stale == 0:
            self._last_good_data = self.now()
        return bars, stale, source

    def _fallback(self, klines: pd.DataFrame, expected: int) -> tuple[pd.DataFrame, str]:
        """Completa en memoria las velas que falten con la fuente de reserva (OKX)."""
        try:
            alt = extra.fetch_okx_klines()
        except Exception as exc:
            log.warning("fuente de reserva tampoco disponible: %s", exc)
            return klines, "binance (atrasado)"
        last = int(klines["ts"].iloc[-1])
        add = alt[(alt["ts"] > last) & (alt["ts"] <= expected)].copy()
        if add.empty or int(add["ts"].iloc[0]) != last + HOUR_MS:
            return klines, "binance (atrasado)"  # no empalma de forma contigua: mejor no mezclar
        for col in klines.columns:
            if col not in add.columns:
                add[col] = float("nan")
        merged = pd.concat([klines, add[klines.columns]], ignore_index=True)
        log.warning("Binance atrasado: %d vela(s) completadas con OKX solo para esta decisión", len(add))
        return merged, "binance + okx (reserva)"

    # =============================================================== cartera
    def _account(self, quote: Quote) -> tuple[float, float, float, float]:
        """(BTC gestionados, efectivo gestionado, patrimonio, peso en BTC)."""
        bal = self.broker.balances()
        ex = self.cfg.execution
        base = max(0.0, bal.base - ex.reserve_btc)
        cash = max(0.0, bal.quote - ex.reserve_quote)
        equity = base * quote.mid + cash
        weight = base * quote.mid / equity if equity > 0 else 0.0
        return base, cash, equity, weight

    def _detect_flows(self, base: float, cash: float, price: float, rs: RiskState, notes: list[str]) -> None:
        """Ingresos o retiradas hechos fuera del bot: se ajusta el máximo para no falsear la caída."""
        prev = self.state.get("balances")
        if not prev:
            return
        flow = (base - prev["base"]) * price + (cash - prev["quote"])
        before = prev["base"] * price + prev["quote"]
        equity = base * price + cash
        if before > 0 and abs(flow) > max(1.0, FLOW_TOLERANCE * before):
            if rs.peak_equity > 0:
                rs.peak_equity *= equity / before
            msg = f"movimiento externo de fondos detectado ({flow:+,.2f} {self.cfg.execution.quote}); máximo de cartera reajustado"
            notes.append(msg)
            self.state.event("info", msg)

    # ================================================================= ciclo
    def cycle(self) -> Decision:
        """Un ciclo completo de decisión. Idempotente: repetirlo sobre la misma vela no duplica órdenes."""
        cfg = self.cfg
        bars, stale, source = self.refresh_data()
        feats, target_series = pipeline.build_targets(cfg, bars)
        row = len(bars) - 1
        bar_ms = int(bars.index.as_unit("ms").asi8[-1])
        raw = float(target_series.iloc[-1])
        ctx = strategy.context(bars, feats)

        quote = self.broker.quote()
        base, cash, equity, weight = self._account(quote)
        price = quote.mid
        d = Decision(
            ts_ms=int(self.now() * 1000),
            bar=str(bars.index[-1]),
            price=price,
            equity=equity,
            weight_before=weight,
            raw_target=raw,
            final_target=raw,
            stale_hours=stale,
            data_source=source,
            regime=ctx["regime"],
            explanation=strategy.explain(feats.iloc[-1], cfg.strategy),
        )
        if equity <= 0:
            d.action = "sin capital"
            d.notes.append("no hay fondos gestionables en la cuenta")
            self._finish(d, base, cash, None)
            return d

        rs = RiskState.from_dict(self.state.get("risk"))
        self._detect_flows(base, cash, price, rs, d.notes)
        halts_before = rs.halts
        risk = pipeline.make_risk(cfg, bars, feats, rs)

        if math.isnan(raw):
            d.notes.append("la estrategia aún no tiene señal: se mantiene la posición")
            final = weight
            risk.on_close(bar_ms, equity, weight, 0.0, price, row)
        else:
            final = risk.on_close(bar_ms, equity, weight, raw, price, row)
        if rs.last_reason:
            d.notes.append(rs.last_reason)
        if rs.halts > halts_before:
            self.notifier.send(f"Gobernador de caída activado: {rs.last_reason}", "alerta")

        # ---- salvaguardas: solo pueden recortar el objetivo, nunca ampliarlo
        buys_blocked = False
        deviation = self._venue_deviation(price, bars, bar_ms, stale)
        if deviation is not None and deviation > cfg.execution.max_venue_deviation:
            buys_blocked = True
            d.notes.append(f"el precio del exchange difiere {deviation:.2%} de la referencia: compras bloqueadas")
        if stale > cfg.live.max_stale_hours:
            buys_blocked = True
            d.notes.append(f"datos con {stale:.0f} h de retraso: compras bloqueadas")
        blind_h = (self.now() - self._last_good_data) / 3600.0
        if cfg.live.blind_exit_hours and max(stale, blind_h) >= cfg.live.blind_exit_hours:
            final = 0.0
            d.notes.append("demasiado tiempo sin datos fiables: salida preventiva a efectivo")
            self.notifier.send("Sin datos fiables durante demasiado tiempo: salida preventiva a efectivo", "alerta", key="blind")
        if buys_blocked:
            final = min(final, weight)
        stopped = is_stopped(cfg.state_dir)
        if stopped:
            d.notes.append("interruptor STOP activo: no se envían órdenes")
        d.final_target = final

        # ---- ejecución
        # En real, una orden puede quedar sin llenar si el precio se escapa del tope: se
        # vuelve a cotizar y se reintenta en el acto (una salida no puede esperar a la hora siguiente).
        fills: list[Fill] = []
        band = cfg.effective_band
        attempts = 0
        side = ""
        while not stopped and attempts < MAX_ORDER_ATTEMPTS and should_rebalance(final, weight, band):
            side, qty = self._order_size(final, weight, base, cash, equity, quote)
            if qty <= 0:
                if not fills:
                    d.action = "ajuste demasiado pequeño para operar"
                break
            reason = d.notes[-1] if d.notes else d.regime
            if self.dry_run:
                d.action = f"SIMULADO {side} {qty:.6f} BTC"
                break
            attempts += 1
            fill = self.broker.execute(side, qty, quote, reason)
            if fill is not None:
                fills.append(fill)
                self.state.record_fill(fill.ts_ms, fill.order_id, fill.side, fill.qty, fill.price, fill.fee_quote, reason)
            if not self.broker.is_real or (fill is not None and fill.complete):
                base, cash, equity, weight = self._account(quote)
                break
            quote = self.broker.quote()  # no se llenó (o solo en parte): nueva cotización y otro intento
            base, cash, equity, weight = self._account(quote)
        summary: Fill | None = None
        if fills:
            qty_sum = sum(f.qty for f in fills)
            avg = sum(f.qty * f.price for f in fills) / qty_sum
            summary = Fill(fills[-1].order_id, fills[0].side, qty_sum, avg, sum(f.fee_quote for f in fills), fills[-1].ts_ms, fills[-1].complete)
            d.action = f"{'COMPRA' if summary.side == 'buy' else 'VENTA'} {qty_sum:.6f} BTC a {avg:,.2f}"
            d.fill = asdict(summary)
        elif attempts:
            d.action = f"orden no ejecutada tras {attempts} intento(s)"
            if self.broker.is_real:
                self.notifier.send(
                    f"No se pudo ejecutar la {'compra' if side == 'buy' else 'venta'} pendiente tras {attempts} intentos "
                    f"(objetivo {final:.0%}, actual {weight:.0%}). Se reintentará en el próximo ciclo.",
                    "alerta",
                    key="unfilled",
                )
        d.weight_after = weight
        self.state.set("risk", rs.to_dict())
        self._finish(d, base, cash, summary)
        return d

    def _venue_deviation(self, price: float, bars: pd.DataFrame, bar_ms: int, stale: float) -> float | None:
        """Discrepancia entre el precio del exchange y la referencia (Binance). None = no comprobable.

        Protege de operar contra un libro dislocado o un dato corrupto: si el mercado
        donde se va a ejecutar no cuadra con el mercado de referencia, no se compra.
        """
        if not self.broker.is_real:
            return None  # en papel la cotización ya es la de referencia
        ref: float | None = None
        try:
            t = binance.book_ticker("BTCUSDT")
            ref = 0.5 * (t["bid"] + t["ask"])
        except Exception as exc:
            log.debug("referencia en tiempo real no disponible: %s", exc)
            closed_ago_s = self.now() - (bar_ms + HOUR_MS) / 1000.0
            if stale == 0 and closed_ago_s < 300:
                ref = float(bars["close"].iloc[-1])
        if not ref or ref <= 0:
            return None
        return abs(price / ref - 1.0)

    def _order_size(self, target: float, weight: float, base: float, cash: float, equity: float, quote: Quote) -> tuple[str, float]:
        ex = self.cfg.execution
        price = quote.mid
        if target > weight:
            side = "buy"
            want = (target * equity - base * price) / price
            worst = quote.ask * (1.0 + ex.max_slippage) * (1.0 + 1.5 * max(ex.fee, 0.001))
            qty = min(want, cash / worst)
        else:
            side = "sell"
            qty = base if is_full_exit(target, weight) else min(base, (base * price - target * equity) / price)
        if ex.max_order_quote > 0:
            qty = min(qty, ex.max_order_quote / price)
        rules = self.broker.rules()
        qty = rules.floor_amount(max(qty, 0.0))
        return side, (qty if rules.tradable(qty, price) else 0.0)

    def _finish(self, d: Decision, base: float, cash: float, fill: Fill | None) -> None:
        self.state.set("balances", {"base": base, "quote": cash})
        self.state.record_equity(d.ts_ms, d.equity, d.price, d.weight_after if d.weight_after is not None else d.weight_before, d.final_target)
        self.state.record_decision(d.ts_ms, d.to_dict())
        self.state.set("heartbeat", d.ts_ms)
        log.info(
            "%s | BTC %s | cartera %s | peso %.0f%% -> objetivo %.0f%% | %s%s",
            d.bar[:16], f"{d.price:,.0f}", f"{d.equity:,.2f}", d.weight_before * 100, d.final_target * 100, d.action,
            (" | " + "; ".join(d.notes)) if d.notes else "",
        )  # fmt: skip
        if fill is not None:
            self.notifier.send(
                f"{d.action}\nRégimen: {d.regime}\nPeso en BTC: {d.weight_before:.0%} -> {d.weight_after:.0%}\n"
                f"Cartera: {d.equity:,.2f} {self.cfg.execution.quote}"
            )
        today = datetime.fromtimestamp(d.ts_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
        if self.state.get("summary_day") != today:
            first = self.state.get("summary_day") is None
            self.state.set("summary_day", today)
            if not first:
                self.notifier.send(
                    f"Resumen diario {today}\nBTC {d.price:,.0f} · {d.regime}\n"
                    f"Cartera {d.equity:,.2f} {self.cfg.execution.quote} · {d.weight_after or 0:.0%} en BTC · objetivo {d.final_target:.0%}"
                )

    # ============================================================= vigilante
    def guard(self) -> None:
        """Entre decisiones: parada de desplome (si está activada) con precio en tiempo real."""
        if self.cfg.risk.crash_sigmas <= 0 or is_stopped(self.cfg.state_dir) or self.dry_run:
            return
        rs = RiskState.from_dict(self.state.get("risk"))
        lvl = rs.stop_level
        if lvl != lvl:
            return
        quote = self.broker.quote()
        if quote.bid > lvl:
            return
        base, cash, equity, weight = self._account(quote)
        rules = self.broker.rules()
        qty = rules.floor_amount(base)
        if not rules.tradable(qty, quote.bid):
            return
        fill = self.broker.execute("sell", qty, quote, "parada de desplome")
        if fill is None:
            self.notifier.send("Parada de desplome alcanzada pero la venta no se ejecutó", "alerta", key="crash")
            return
        bar_ms = (int(self.now() * 1000) // HOUR_MS) * HOUR_MS
        risk = RiskManager(self.cfg.risk, state=rs)
        risk.on_stop(bar_ms, fill.price)
        self.state.set("risk", rs.to_dict())
        self.state.record_fill(fill.ts_ms, fill.order_id, "sell", fill.qty, fill.price, fill.fee_quote, "parada de desplome")
        base, cash, _, _ = self._account(quote)
        self.state.set("balances", {"base": base, "quote": cash})
        self.notifier.send(f"PARADA DE DESPLOME: vendidos {fill.qty:.6f} BTC a {fill.price:,.2f}", "alerta")

    # ================================================================ bucle
    def startup(self) -> None:
        mode = "REAL" if self.broker.is_real else "papel"
        log.info("Centinela arranca en modo %s sobre %s (%s)", mode, self.broker.name, self.cfg.execution.symbol)
        try:
            drift = abs(binance.server_time_ms() / 1000.0 - self.now())
            if drift > 5:
                log.warning("el reloj local se desvía %.1f s del servidor: sincronízalo (NTP) antes de operar en real", drift)
        except Exception as exc:
            log.warning("no se pudo comprobar el reloj: %s", exc)
        cancelled = self.broker.cancel_open_orders()
        if cancelled:
            log.warning("cancelada %d orden propia que quedó abierta de una ejecución anterior", cancelled)
        self._check_adoption()
        self.state.event("info", f"arranque en modo {mode}")

    def _check_adoption(self) -> None:
        """Primera vez en real: no tocar BTC que ya estuviera en la cuenta sin permiso expreso.

        El bot gestiona todo el BTC de la cuenta (menos la reserva). Si la tendencia es
        bajista, su primera decisión sería venderlo: eso jamás debe ocurrir por sorpresa.
        """
        if not self.broker.is_real or self.state.get("adopted"):
            return
        quote = self.broker.quote()
        base, _cash, equity, _w = self._account(quote)
        value = base * quote.mid
        if value > max(10.0, 0.01 * equity) and not self.adopt_existing:
            ex = self.cfg.execution
            raise StartupError(
                f"La cuenta ya contiene {base:.6f} {ex.base} (~{value:,.0f} {ex.quote}) y Centinela gestiona todo el BTC "
                "de la cuenta: podría venderlo en su primera decisión.\n"
                f"  · Para conservarlo aparte, pon `reserva_btc: {base + ex.reserve_btc:.6f}` en la sección `ejecucion` de config.yaml.\n"
                "  · Para que el bot lo gestione, arranca con --adoptar-saldo."
            )
        self.state.set("adopted", True)

    def request_stop(self, *_args) -> None:
        self._stop = True

    def run_forever(self, install_signals: bool = True) -> None:
        if install_signals:
            signal.signal(signal.SIGINT, self.request_stop)
            signal.signal(signal.SIGTERM, self.request_stop)
        self.startup()
        failures = 0
        next_run = self.now()  # primer ciclo inmediato: la señal tolera horas de retraso
        while not self._stop:
            if self.now() >= next_run:
                try:
                    self.cycle()
                    failures = 0
                    next_run = self._next_decision_time()
                except Exception as exc:
                    failures += 1
                    log.exception("ciclo fallido (%d consecutivos)", failures)
                    self.state.event("error", f"{type(exc).__name__}: {exc}")
                    self.notifier.send(f"Error en el ciclo ({failures} seguidos): {type(exc).__name__}: {exc}", "alerta", key="cycle")
                    # reintentos rápidos y, si persiste, a esperar a la hora siguiente
                    next_run = self.now() + 60.0 if failures <= 5 else self._next_decision_time()
            else:
                try:
                    self.guard()
                except Exception as exc:  # el vigilante nunca debe tumbar el bucle
                    log.warning("vigilante: %s", exc)
            self._nap(min(self.cfg.live.guard_interval_s, max(0.5, next_run - self.now())))
        log.info("Centinela detenido. La posición abierta, si la hay, se conserva tal cual.")
        self.state.event("info", "parada ordenada")

    def _next_decision_time(self) -> float:
        hour = 3600.0
        return (math.floor(self.now() / hour) + 1) * hour + self.cfg.live.delay_s

    def _nap(self, seconds: float) -> None:
        end = self.now() + seconds
        while not self._stop and self.now() < end:
            self.sleep(min(1.0, max(0.05, end - self.now())))


def utc(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
