"""Motor en vivo: paridad con el backtest, idempotencia y salvaguardas."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from centinela import pipeline, strategy
from centinela.config import Config, ExecConfig, LiveConfig
from centinela.data.store import HOUR_MS, KLINES, DataStore
from centinela.live.broker import PaperBroker, Quote
from centinela.live.engine import LiveEngine, StartupError
from centinela.live.state import StateStore, is_stopped, set_stopped
from centinela.risk import RiskConfig, RiskState
from centinela.strategy import StrategyConfig

from conftest import make_klines


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t


class SimStore(DataStore):
    """Almacén que solo «conoce» las velas ya cerradas según el reloj simulado."""

    def __init__(self, klines: pd.DataFrame, clock: Clock, lag_hours: int = 0):
        super().__init__("no-usado")
        self.k, self.clock, self.lag_hours = klines, clock, lag_hours

    def _visible(self) -> pd.DataFrame:
        last_closed = (int(self.clock() * 1000) // HOUR_MS) * HOUR_MS - HOUR_MS - self.lag_hours * HOUR_MS
        return self.k[self.k["ts"] <= last_closed]

    def update_klines(self, on_progress=None):
        return self._visible()

    def update_funding(self):
        return None

    def update_mvrv(self):
        return None

    def load(self, name):
        return self._visible() if name == KLINES else None


def make_engine(tmp_path, klines, start_hours, *, cfg=None, lag_hours=0, dry_run=False):
    cfg = cfg or Config(
        strategy=StrategyConfig(warmup_days=30),
        execution=ExecConfig(fee=0.001, slippage=0.0002),
        live=LiveConfig(delay_s=5),
        state_dir=str(tmp_path / "state"),
    )
    t0 = int(klines["ts"].iloc[0])
    clock = Clock((t0 + start_hours * HOUR_MS) / 1000 + cfg.live.delay_s)
    store = SimStore(klines, clock, lag_hours)
    state = StateStore(cfg.state_dir, "papel", durable=False)
    opens = dict(zip(klines["ts"].tolist(), klines["open"].tolist()))

    def quote() -> Quote:
        hour = (int(clock() * 1000) // HOUR_MS) * HOUR_MS
        px = opens[hour]  # precio «ahora» = apertura de la vela en curso
        return Quote(px, px, int(clock() * 1000))

    broker = PaperBroker(cfg.execution, cfg.paper_capital, load=lambda: state.get("paper_balances"),
                         save=lambda b: state.set("paper_balances", b), quote_source=quote)  # fmt: skip
    eng = LiveEngine(cfg, broker, store, state, now=clock, sleep=lambda s: None, dry_run=dry_run)
    return eng, clock, state, broker, cfg


@pytest.fixture(scope="module")
def k():
    return make_klines(n=24 * 420, seed=11)


@pytest.fixture()
def fast_context(monkeypatch):
    """El contexto informativo es costoso y no afecta a las decisiones: se sustituye en los tests largos."""
    monkeypatch.setattr(strategy, "context", lambda bars, feats: {"regime": "prueba"})


def test_live_trading_reproduces_the_backtest(tmp_path, k, fast_context):
    """Operar hora a hora con el motor en vivo debe dar lo mismo que el backtest."""
    start, hours = 24 * 330, 24 * 80
    eng, clock, state, broker, cfg = make_engine(tmp_path, k, start)
    live_actions = 0
    for _ in range(hours):
        d = eng.cycle()
        live_actions += d.fill is not None
        clock.t += 3600
    bal = broker.balances()
    last_px = float(k["open"].iloc[start + hours - 1])
    live_equity = bal.base * last_px + bal.quote

    bars = SimStore(k, Clock((int(k["ts"].iloc[0]) + (start + hours - 1) * HOUR_MS) / 1000 + 5)).market()
    feats, target = pipeline.build_targets(cfg, bars)
    from centinela.backtest.engine import run_backtest

    res = run_backtest(bars, target, cfg.backtest_config(), risk=pipeline.make_risk(cfg, bars, feats), start=bars.index[start - 2])
    assert live_actions >= 5, "el tramo simulado debe contener operaciones para que la comparación signifique algo"
    assert len(res.trades) == live_actions
    assert live_equity == pytest.approx(float(res.equity.iloc[-1]), rel=2e-3)
    live_w = bal.base * last_px / live_equity
    assert live_w == pytest.approx(float(res.weight.iloc[-1]), abs=0.01)


def test_cycle_is_idempotent_within_the_same_bar(tmp_path, k, fast_context):
    eng, clock, state, broker, _ = make_engine(tmp_path, k, 24 * 330)
    traded = False
    for _ in range(24 * 60):
        d = eng.cycle()
        if d.fill is not None:
            traded = True
            again = eng.cycle()  # reinicio del bot en la misma hora
            assert again.fill is None and again.action == "mantener"
            break
        clock.t += 3600
    assert traded


@pytest.fixture(scope="module")
def buy_hour(k, tmp_path_factory):
    """Hora (índice) en la que el bot haría su primera compra partiendo de efectivo."""
    feats, target = pipeline.build_targets(Config(strategy=StrategyConfig(warmup_days=30)), SimStore(k, Clock(1e12)).market())
    t = target.to_numpy()
    for i in range(24 * 330, len(t) - 24 * 30):
        if t[i - 1] >= 0.15 and (t[i - 30 : i - 1] < 0.15).all():
            return i  # la vela i-1 da la señal y el bot la ve al empezar la hora i
    raise AssertionError("sin compras en el tramo")


def test_stop_switch_blocks_all_orders(tmp_path, k, fast_context, buy_hour):
    h = buy_hour
    eng, clock, state, broker, cfg = make_engine(tmp_path, k, h)
    set_stopped(cfg.state_dir, True)
    d = eng.cycle()
    assert d.fill is None and any("STOP" in n for n in d.notes)
    assert broker.balances().base == 0.0
    set_stopped(cfg.state_dir, False)
    assert not is_stopped(cfg.state_dir)
    assert eng.cycle().fill is not None


def test_dry_run_sends_nothing(tmp_path, k, fast_context, buy_hour):
    h = buy_hour
    eng, clock, state, broker, _ = make_engine(tmp_path, k, h, dry_run=True)
    d = eng.cycle()
    assert d.action.startswith("SIMULADO buy") and broker.balances().base == 0.0


def test_stale_data_blocks_buys_but_not_exits(tmp_path, k, fast_context, buy_hour):
    h = buy_hour
    eng, clock, state, broker, _ = make_engine(tmp_path, k, h + 6, lag_hours=6)  # la fuente lleva 6 h parada
    d = eng.cycle()
    assert d.stale_hours == 6 and d.fill is None
    assert any("retraso" in n for n in d.notes)
    assert d.final_target <= d.weight_before + 1e-12


def test_prolonged_blindness_exits_to_cash(tmp_path, k, fast_context, buy_hour):
    h = buy_hour
    eng, clock, state, broker, cfg = make_engine(tmp_path, k, h)
    assert eng.cycle().fill is not None and broker.balances().base > 0
    eng.store.lag_hours = 60  # la fuente de datos desaparece más de 48 h
    clock.t += 60 * 3600
    d = eng.cycle()
    assert any("salida preventiva" in n for n in d.notes)
    assert d.fill is not None and d.fill["side"] == "sell" and broker.balances().base == 0.0


def test_external_deposit_does_not_fake_a_drawdown_recovery(tmp_path, k, fast_context):
    eng, clock, state, broker, _ = make_engine(tmp_path, k, 24 * 330)
    eng.cycle()
    rs = RiskState.from_dict(state.get("risk"))
    assert rs.peak_equity == pytest.approx(10_000)
    broker._quote += 5_000  # ingreso hecho por el usuario fuera del bot
    clock.t += 3600
    d = eng.cycle()
    assert any("movimiento externo" in n for n in d.notes)
    rs = RiskState.from_dict(state.get("risk"))
    assert rs.peak_equity == pytest.approx(15_000, rel=1e-3)  # el máximo se reescala; la caída relativa no cambia


def test_withdrawal_does_not_trigger_the_drawdown_governor(tmp_path, k, fast_context):
    eng, clock, state, broker, _ = make_engine(tmp_path, k, 24 * 330)
    eng.cycle()
    broker._quote -= 6_000  # retirada del 60 %: sin el ajuste parecería una caída del 60 %
    clock.t += 3600
    d = eng.cycle()
    rs = RiskState.from_dict(state.get("risk"))
    assert rs.halts == 0 and rs.peak_equity == pytest.approx(4_000, rel=1e-3)
    assert not any("gobernador" in n for n in d.notes)


def test_reserves_are_never_touched(tmp_path, k, fast_context, buy_hour):
    h = buy_hour
    cfg = Config(
        strategy=StrategyConfig(warmup_days=30),
        execution=ExecConfig(fee=0.001, slippage=0.0002, reserve_quote=4_000.0),
        live=LiveConfig(delay_s=5),
        state_dir=str(tmp_path / "state"),
    )
    eng, clock, state, broker, _ = make_engine(tmp_path, k, h, cfg=cfg)
    for _ in range(24 * 20):
        eng.cycle()
        assert broker.balances().quote >= 4_000.0 - 1e-6
        clock.t += 3600


def test_crash_guard_sells_when_price_breaks_the_stop(tmp_path, k, fast_context, buy_hour):
    h = buy_hour
    cfg = Config(
        strategy=StrategyConfig(warmup_days=30),
        risk=RiskConfig(crash_sigmas=3.0, crash_cooldown_h=24),
        execution=ExecConfig(fee=0.001, slippage=0.0002),
        live=LiveConfig(delay_s=5),
        state_dir=str(tmp_path / "state"),
    )
    eng, clock, state, broker, _ = make_engine(tmp_path, k, h, cfg=cfg)
    assert eng.cycle().fill is not None
    lvl = RiskState.from_dict(state.get("risk")).stop_level
    assert lvl == lvl and lvl > 0
    eng.guard()
    assert broker.balances().base > 0  # precio normal: no pasa nada
    broker._quote_source = lambda: Quote(lvl * 0.98, lvl * 0.98, 0)  # desplome
    eng.guard()
    assert broker.balances().base == 0.0
    rs = RiskState.from_dict(state.get("risk"))
    assert rs.stops == 1 and rs.cooldown_until_ms > 0
    broker._quote_source = lambda: Quote(lvl, lvl, 0)
    clock.t += 3600
    d = eng.cycle()
    assert d.fill is None and d.final_target == 0.0  # en enfriamiento no recompra


def test_real_context_is_computed_and_decision_is_logged(tmp_path, k):
    eng, clock, state, broker, _ = make_engine(tmp_path, k, 24 * 400)
    d = eng.cycle()
    assert d.regime and d.explanation
    saved = state.last_decision()
    assert saved["bar"] == d.bar and saved["price"] == d.price
    assert state.equity_history()[-1][1] == pytest.approx(d.equity)
    assert state.get("heartbeat") == d.ts_ms


def test_decision_uses_only_closed_bars(tmp_path, k, fast_context):
    eng, clock, *_ = make_engine(tmp_path, k, 24 * 350)
    d = eng.cycle()
    now_hour = (int(clock() * 1000) // HOUR_MS) * HOUR_MS
    assert pd.Timestamp(d.bar).value // 10**6 == now_hour - HOUR_MS  # la vela usada es la última cerrada


# ------------------------------------------------------------- arranque seguro
class RealishBroker(PaperBroker):
    """Broker simulado que se declara «real» para ejercitar las salvaguardas del modo real."""

    is_real = True


def realish_engine(tmp_path, k, hours, monkeypatch, *, base=0.0, reserve_btc=0.0, adopt=False):
    cfg = Config(
        strategy=StrategyConfig(warmup_days=30),
        execution=ExecConfig(fee=0.001, slippage=0.0002, reserve_btc=reserve_btc),
        live=LiveConfig(delay_s=5),
        state_dir=str(tmp_path / "state"),
    )
    t0 = int(k["ts"].iloc[0])
    clock = Clock((t0 + hours * HOUR_MS) / 1000 + 5)
    state = StateStore(cfg.state_dir, "real", durable=False)
    opens = dict(zip(k["ts"].tolist(), k["open"].tolist()))

    def quote() -> Quote:
        px = opens[(int(clock() * 1000) // HOUR_MS) * HOUR_MS]
        return Quote(px, px, 0)

    broker = RealishBroker(cfg.execution, 10_000.0, quote_source=quote)
    broker._base = base
    from centinela.data import binance

    monkeypatch.setattr(binance, "server_time_ms", lambda: int(clock() * 1000))
    monkeypatch.setattr(binance, "book_ticker", lambda symbol="BTCUSDT": {"bid": quote().bid, "ask": quote().ask})
    eng = LiveEngine(cfg, broker, SimStore(k, clock), state, now=clock, sleep=lambda s: None, adopt_existing=adopt)
    return eng, clock, state, broker


def test_first_real_start_refuses_to_touch_preexisting_btc(tmp_path, k, fast_context, monkeypatch):
    eng, clock, state, broker = realish_engine(tmp_path, k, 24 * 350, monkeypatch, base=0.25)
    with pytest.raises(StartupError, match="reserva_btc: 0.250000"):
        eng.startup()
    assert broker.balances().base == 0.25 and state.get("adopted") is None


def test_preexisting_btc_is_managed_only_with_explicit_consent(tmp_path, k, fast_context, monkeypatch):
    eng, clock, state, broker = realish_engine(tmp_path, k, 24 * 350, monkeypatch, base=0.25, adopt=True)
    eng.startup()
    assert state.get("adopted") is True


def test_reserved_btc_is_invisible_to_the_bot(tmp_path, k, fast_context, monkeypatch):
    eng, clock, state, broker = realish_engine(tmp_path, k, 24 * 350, monkeypatch, base=0.25, reserve_btc=0.25)
    eng.startup()  # nada gestionable: arranca sin pedir permiso
    for _ in range(24 * 15):
        eng.cycle()
        assert broker.balances().base >= 0.25 - 1e-9  # la reserva nunca se vende
        clock.t += 3600


def test_dislocated_venue_price_blocks_buys(tmp_path, k, fast_context, monkeypatch, buy_hour):
    eng, clock, state, broker = realish_engine(tmp_path, k, buy_hour, monkeypatch)
    from centinela.data import binance

    real_px = broker.quote().mid
    monkeypatch.setattr(binance, "book_ticker", lambda symbol="BTCUSDT": {"bid": real_px * 1.05, "ask": real_px * 1.05})
    d = eng.cycle()
    assert d.fill is None and any("difiere" in n for n in d.notes)
    monkeypatch.setattr(binance, "book_ticker", lambda symbol="BTCUSDT": {"bid": real_px, "ask": real_px})
    assert eng.cycle().fill is not None


# ----------------------------------------------------------------- planificador
def test_scheduler_decides_once_per_hour_shortly_after_the_close(tmp_path, k, fast_context):
    eng, clock, state, broker, cfg = make_engine(tmp_path, k, 24 * 340)
    clock.t += 1234  # el bot arranca a mitad de hora
    stamps = []
    original = eng.cycle

    def spy():
        stamps.append(clock.t)
        if len(stamps) >= 5:
            eng.request_stop()
        return original()

    def sleep(sec):
        clock.t += sec

    eng.cycle, eng.sleep = spy, sleep
    eng.broker.cancel_open_orders = lambda: 0
    from centinela.data import binance

    binance_time = binance.server_time_ms
    binance.server_time_ms = lambda: int(clock.t * 1000)
    try:
        eng.run_forever(install_signals=False)
    finally:
        binance.server_time_ms = binance_time
    assert len(stamps) == 5
    assert stamps[0] == pytest.approx((int(k["ts"].iloc[0]) + 24 * 340 * HOUR_MS) / 1000 + 5 + 1234)  # primer ciclo inmediato
    for s_ in stamps[1:]:
        into_hour = s_ % 3600
        assert cfg.live.delay_s <= into_hour < cfg.live.delay_s + 2  # después: hh:00 + retardo
    assert np.allclose(np.diff(stamps[1:]), 3600, atol=2)


def test_a_failing_cycle_is_retried_and_never_kills_the_loop(tmp_path, k, fast_context):
    eng, clock, state, broker, cfg = make_engine(tmp_path, k, 24 * 340)
    calls = []
    original = eng.cycle

    def flaky():
        calls.append(clock.t)
        if len(calls) <= 2:
            raise RuntimeError("fuente de datos caída")
        eng.request_stop()
        return original()

    def sleep(sec):
        clock.t += sec

    eng.cycle, eng.sleep = flaky, sleep
    eng.startup = lambda: None
    eng.run_forever(install_signals=False)
    assert len(calls) == 3
    assert calls[1] - calls[0] == pytest.approx(60, abs=2) and calls[2] - calls[1] == pytest.approx(60, abs=2)
    assert [e[1] for e in state.events()].count("error") == 2


# ------------------------------------------------- reintentos de ejecución en real
class StubbornBroker(RealishBroker):
    """No llena las primeras ``misses`` órdenes y llena a medias las ``partials`` siguientes."""

    misses = 0
    partials = 0
    attempts = 0

    def execute(self, side, qty, quote, reason=""):
        type(self).attempts += 1
        if type(self).misses > 0:
            type(self).misses -= 1
            return None
        if type(self).partials > 0:
            type(self).partials -= 1
            f = super().execute(side, qty * 0.5, quote, reason)
            return None if f is None else type(f)(f.order_id, f.side, f.qty, f.price, f.fee_quote, f.ts_ms, False)
        return super().execute(side, qty, quote, reason)


def stubborn_engine(tmp_path, k, hours, monkeypatch, misses, partials=0):
    eng, clock, state, broker = realish_engine(tmp_path, k, hours, monkeypatch)
    StubbornBroker.misses, StubbornBroker.partials, StubbornBroker.attempts = misses, partials, 0
    broker.__class__ = StubbornBroker
    return eng, clock, state, broker


def test_unfilled_real_order_is_requoted_and_retried_within_the_cycle(tmp_path, k, fast_context, monkeypatch, buy_hour):
    eng, clock, state, broker = stubborn_engine(tmp_path, k, buy_hour, monkeypatch, misses=2)
    d = eng.cycle()
    assert StubbornBroker.attempts == 3 and d.fill is not None and broker.balances().base > 0


def test_partial_fills_are_completed_and_reported_as_one(tmp_path, k, fast_context, monkeypatch, buy_hour):
    eng, clock, state, broker = stubborn_engine(tmp_path, k, buy_hour, monkeypatch, misses=0, partials=1)
    d = eng.cycle()
    assert StubbornBroker.attempts >= 1 and d.fill is not None
    assert d.fill["qty"] == pytest.approx(broker.balances().base)  # el resumen suma todas las ejecuciones
    assert len(state.fills(10)) == StubbornBroker.attempts  # cada ejecución queda registrada


def test_retries_are_bounded_and_the_operator_is_alerted(tmp_path, k, fast_context, monkeypatch, buy_hour):
    eng, clock, state, broker = stubborn_engine(tmp_path, k, buy_hour, monkeypatch, misses=99)
    alerts = []
    eng.notifier.send = lambda text, level="info", key=None: alerts.append((level, text))
    d = eng.cycle()
    assert StubbornBroker.attempts == 3 and d.fill is None
    assert "no ejecutada tras 3" in d.action
    assert any(level == "alerta" and "No se pudo ejecutar" in text for level, text in alerts)
