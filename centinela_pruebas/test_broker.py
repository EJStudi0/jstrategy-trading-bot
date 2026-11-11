"""Brokers: el simulado y el real (este último contra un exchange falso, sin red)."""

import math

import pytest

from centinela.config import ExecConfig
from centinela.live import broker as B
from centinela.live.broker import BrokerError, CcxtBroker, PaperBroker, Quote, Rules

Q = Quote(bid=49_990.0, ask=50_010.0, ts_ms=0)


def paper(initial=10_000.0, **kw):
    saved = {}
    cfg = ExecConfig(fee=0.001, slippage=0.0005, **kw)
    br = PaperBroker(cfg, initial, load=lambda: saved.get("b"), save=lambda b: saved.__setitem__("b", b), quote_source=lambda: Q)
    return br, saved, cfg


# ---------------------------------------------------------------------- papel
def test_paper_buy_pays_ask_plus_slippage_and_fee():
    br, saved, _ = paper()
    fill = br.execute("buy", 0.1, Q)
    px = 50_010 * 1.0005
    assert fill.price == pytest.approx(px) and fill.qty == pytest.approx(0.1)
    assert fill.fee_quote == pytest.approx(0.1 * px * 0.001)
    bal = br.balances()
    assert bal.base == pytest.approx(0.1)
    assert bal.quote == pytest.approx(10_000 - 0.1 * px * 1.001)
    assert saved["b"]["base"] == pytest.approx(0.1)  # persistido


def test_paper_sell_receives_bid_minus_slippage():
    br, _, _ = paper()
    br.execute("buy", 0.1, Q)
    cash = br.balances().quote
    fill = br.execute("sell", 0.1, Q)
    px = 49_990 * 0.9995
    assert fill.price == pytest.approx(px)
    assert br.balances().quote == pytest.approx(cash + 0.1 * px * 0.999)
    assert br.balances().base == 0.0


def test_paper_never_overdraws():
    br, _, _ = paper(1_000.0)
    fill = br.execute("buy", 5.0, Q)  # pide mucho más de lo que puede pagar
    assert fill.qty < 0.02 and br.balances().quote >= 0
    fill = br.execute("sell", 5.0, Q)
    assert br.balances().base == 0.0 and fill.qty <= 0.02


def test_paper_rejects_dust_like_a_real_exchange():
    br, _, _ = paper()
    assert br.execute("buy", 0.00005, Q) is None  # ~2,5 $ < mínimo de 5 $
    assert br.balances().quote == 10_000


def test_paper_state_is_restored():
    br, saved, cfg = paper()
    br.execute("buy", 0.05, Q)
    again = PaperBroker(cfg, 999.0, load=lambda: saved.get("b"), quote_source=lambda: Q)
    assert again.balances().base == pytest.approx(0.05)  # ignora el capital inicial si ya hay estado


def test_bad_quotes_block_trading():
    with pytest.raises(BrokerError, match="cruzado"):
        Quote(101.0, 100.0, 0).validate()
    with pytest.raises(BrokerError, match="spread"):
        Quote(100.0, 105.0, 0).validate()
    with pytest.raises(BrokerError, match="inválida"):
        Quote(0.0, 100.0, 0).validate()
    with pytest.raises(BrokerError, match="inválida"):
        Quote(float("nan"), 100.0, 0).validate()


def test_rules_rounding():
    r = Rules(amount_step=1e-5, min_amount=1e-4, min_cost=5.0, price_tick=0.1)
    assert r.floor_amount(0.123456789) == pytest.approx(0.12345)
    assert r.floor_amount(0.3) == pytest.approx(0.3)  # sin perder un paso por error de coma flotante
    assert not r.tradable(0.00005, 50_000) and r.tradable(0.0002, 50_000)
    assert not r.tradable(0.0001, 10_000)  # 1 $ < coste mínimo


# ----------------------------------------------------------------------- real
class FakeExchange:
    """Imita la parte de ccxt que usa el bot. ``fill_ratio`` controla cuánto se ejecuta."""

    precisionMode = 4
    has = {"sandbox": True}

    def __init__(self, base=0.0, quote=10_000.0, fill_ratio=1.0, fee_currency="USDT", report_fee=True):
        self.markets = {"BTC/USDT": {"spot": True, "precision": {"amount": 1e-6, "price": 0.1},
                                     "limits": {"amount": {"min": 1e-5}, "cost": {"min": 5.0}}}}  # fmt: skip
        self.bal = {"BTC": base, "USDT": quote}
        self.fill_ratio, self.fee_currency, self.report_fee = fill_ratio, fee_currency, report_fee
        self.orders, self.created, self.cancelled, self.params = {}, [], [], []
        self.fail_with, self.place_before_failing = None, False

    def load_markets(self):
        return self.markets

    def market(self, symbol):
        return self.markets[symbol]

    def price_to_precision(self, symbol, p):
        return f"{round(p / 0.1) * 0.1:.1f}"

    def amount_to_precision(self, symbol, a):
        return f"{math.floor(a * 1e6 + 1e-9) / 1e6:.6f}"

    def fetch_order_book(self, symbol, limit=5):
        return {"bids": [[49_990.0, 1.0]], "asks": [[50_010.0, 1.0]]}

    def fetch_balance(self):
        return {"total": dict(self.bal), "free": dict(self.bal)}

    def create_order(self, symbol, type_, side, amount, price, params=None):
        if self.fail_with is not None:
            exc, self.fail_with = self.fail_with, None
            if self.place_before_failing:
                self.orders["99"] = {"id": "99", "status": "open", "filled": 0.0, "amount": amount,
                                     "clientOrderId": (params or {}).get("clientOrderId")}  # fmt: skip
            raise exc
        oid = str(len(self.orders) + 1)
        self.created.append((symbol, type_, side, amount, price))
        self.params.append(params or {})
        filled = amount * self.fill_ratio
        px = 50_010.0 if side == "buy" else 49_990.0
        fee = filled * px * 0.001
        if side == "buy":
            self.bal["BTC"] += filled
            self.bal["USDT"] -= filled * px + fee
        else:
            self.bal["BTC"] -= filled
            self.bal["USDT"] += filled * px - fee
        o = {"id": oid, "status": "closed" if self.fill_ratio >= 1 else "open", "filled": filled, "average": px, "amount": amount}
        if self.report_fee:
            o["fee"] = {"cost": fee if self.fee_currency == "USDT" else fee / px, "currency": self.fee_currency}
        self.orders[oid] = o
        return dict(o, status="open")  # como muchos exchanges: la creación no confirma el cierre

    def fetch_order(self, oid, symbol):
        return dict(self.orders[oid])

    def cancel_order(self, oid, symbol):
        self.cancelled.append(oid)
        self.orders[oid]["status"] = "canceled"

    def fetch_open_orders(self, symbol):
        return [o for o in self.orders.values() if o["status"] == "open"]


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(B.time, "sleep", lambda s: None)


def real(ex, **kw):
    mem = {}
    cfg = ExecConfig(**{"fee": 0.001, "max_slippage": 0.003, "order_timeout_s": 0, **kw})
    br = CcxtBroker(cfg, {}, exchange=ex, load_pending=lambda: mem.get("p"), save_pending=lambda v: mem.__setitem__("p", v))
    return br, mem


def test_real_orders_are_price_capped_limits_never_market():
    ex = FakeExchange()
    br, _ = real(ex)
    fill = br.execute("buy", 0.05, br.quote())
    symbol, type_, side, amount, price = ex.created[0]
    assert type_ == "limit" and side == "buy" and symbol == "BTC/USDT"
    assert price == pytest.approx(50_010 * 1.003, abs=0.1)  # tope: ask + 0,3 %
    assert fill.qty == pytest.approx(0.05) and fill.complete
    assert fill.fee_quote == pytest.approx(0.05 * 50_010 * 0.001)

    fill = br.execute("sell", 0.05, br.quote())
    assert ex.created[1][4] == pytest.approx(49_990 * 0.997, abs=0.1)  # suelo: bid - 0,3 %
    assert fill.qty == pytest.approx(0.05)


def test_real_buy_is_sized_to_available_cash():
    ex = FakeExchange(quote=1_000.0)
    br, _ = real(ex)
    br.execute("buy", 1.0, br.quote())
    amount, price = ex.created[0][3], ex.created[0][4]
    assert amount * price * 1.0015 <= 1_000.0 + 1e-6  # cabe incluso al precio tope y con comisión
    assert amount > 0.0195


def test_real_sell_never_exceeds_holdings():
    ex = FakeExchange(base=0.03)
    br, _ = real(ex)
    br.execute("sell", 1.0, br.quote())
    assert ex.created[0][3] == pytest.approx(0.03)


def test_real_dust_is_not_sent():
    ex = FakeExchange()
    br, _ = real(ex)
    assert br.execute("buy", 0.00002, br.quote()) is None and not ex.created


def test_partial_fill_cancels_the_rest_and_reports_incomplete():
    ex = FakeExchange(fill_ratio=0.4)
    br, mem = real(ex)
    fill = br.execute("buy", 0.05, br.quote())
    assert ex.cancelled == ["1"]
    assert fill.qty == pytest.approx(0.02) and not fill.complete
    assert mem["p"] is None  # orden cerrada: nada pendiente


def test_unfilled_order_returns_none():
    ex = FakeExchange(fill_ratio=0.0)
    br, _ = real(ex)
    assert br.execute("buy", 0.05, br.quote()) is None
    assert ex.cancelled == ["1"]


def test_fee_in_btc_is_converted_and_missing_fee_is_estimated():
    ex = FakeExchange(fee_currency="BTC")
    br, _ = real(ex)
    fill = br.execute("buy", 0.05, br.quote())
    assert fill.fee_quote == pytest.approx(0.05 * 50_010 * 0.001, rel=1e-6)
    ex = FakeExchange(report_fee=False)
    br, _ = real(ex)
    fill = br.execute("buy", 0.05, br.quote())
    assert fill.fee_quote == pytest.approx(0.05 * 50_010 * 0.001)


def test_startup_cleanup_only_touches_the_bots_own_order():
    ex = FakeExchange()
    ex.orders["777"] = {"id": "777", "status": "open", "filled": 0, "amount": 1}  # orden manual del usuario
    ex.orders["888"] = {"id": "888", "status": "open", "filled": 0, "amount": 1}  # orden huérfana del bot
    br, mem = real(ex)
    assert br.cancel_open_orders() == 0  # sin nada anotado no cancela nada
    mem["p"] = {"oid": "888", "cid": None}
    assert br.cancel_open_orders() == 1
    assert ex.cancelled == ["888"] and ex.orders["777"]["status"] == "open"
    assert mem["p"] is None


def test_real_broker_refuses_unknown_or_non_spot_markets():
    ex = FakeExchange()
    ex.markets = {"BTC/EUR": ex.markets["BTC/USDT"]}
    with pytest.raises(BrokerError, match="no lista"):
        CcxtBroker(ExecConfig(), {}, exchange=ex)
    ex = FakeExchange()
    ex.markets["BTC/USDT"]["spot"] = False
    with pytest.raises(BrokerError, match="contado"):
        CcxtBroker(ExecConfig(), {}, exchange=ex)


def test_no_withdrawal_code_exists():
    """El bot no debe contener ninguna llamada de retirada o transferencia de fondos."""
    from pathlib import Path

    import centinela

    src = "\n".join(p.read_text(encoding="utf-8") for p in Path(centinela.__file__).parent.rglob("*.py"))
    for forbidden in ("withdraw(", ".transfer(", "fetch_deposit_address", "create_deposit_address"):
        assert forbidden not in src


def test_filled_order_is_confirmed_by_polling_without_cancelling():
    ex = FakeExchange()
    mem = {}
    cfg = ExecConfig(fee=0.001, order_timeout_s=30)
    br = CcxtBroker(cfg, {}, exchange=ex, load_pending=lambda: mem.get("p"), save_pending=lambda v: mem.__setitem__("p", v))
    fill = br.execute("buy", 0.05, br.quote())
    assert fill.complete and ex.cancelled == [] and mem["p"] is None


def test_client_order_id_is_sent_where_the_exchange_supports_it():
    ex = FakeExchange()
    br, _ = real(ex, exchange="okx")
    br.execute("buy", 0.05, br.quote())
    cid = ex.params[0]["clientOrderId"]
    assert len(cid) == 32 and cid.isalnum()  # formato válido en OKX y Kraken
    ex = FakeExchange()
    br, _ = real(ex, exchange="coinbase")
    br.execute("buy", 0.05, br.quote())
    assert "client_order_id" in ex.params[0]
    ex = FakeExchange()
    br, _ = real(ex, exchange="bitstamp")  # exchange no verificado: no se arriesga un parámetro que podría rechazar
    br.execute("buy", 0.05, br.quote())
    assert ex.params[0] == {}


def test_lost_response_leaves_a_trace_and_the_orphan_is_swept_before_retrying():
    import ccxt

    ex = FakeExchange()
    ex.fail_with, ex.place_before_failing = ccxt.RequestTimeout("sin respuesta"), True
    br, mem = real(ex, exchange="okx")
    with pytest.raises(BrokerError, match="sin confirmar"):
        br.execute("buy", 0.05, br.quote())
    assert mem["p"]["cid"] and mem["p"]["oid"] is None  # anotada aunque no se conozca su id
    assert ex.orders["99"]["status"] == "open"  # la orden existe en el exchange
    fill = br.execute("buy", 0.05, br.quote())  # reintento
    assert ex.cancelled[0] == "99"  # primero barre la huérfana, localizada por su id de cliente
    assert fill is not None and mem["p"] is None


def test_definitive_rejection_clears_the_trace_and_propagates():
    import ccxt

    ex = FakeExchange()
    ex.fail_with = ccxt.InsufficientFunds("saldo insuficiente")
    br, mem = real(ex, exchange="okx")
    with pytest.raises(ccxt.InsufficientFunds):
        br.execute("buy", 0.05, br.quote())
    assert mem["p"] is None and not ex.orders


def test_bitget_orders_carry_a_client_id_and_an_explicit_time_in_force():
    ex = FakeExchange()
    br, _ = real(ex, exchange="bitget")
    br.execute("buy", 0.05, br.quote())
    p = ex.params[0]
    assert len(p["clientOrderId"]) == 32 and p["clientOrderId"].isalnum()
    assert p["timeInForce"] == "GTC"  # no se depende del valor por defecto del exchange
    assert set(p) == {"clientOrderId", "timeInForce"}


def test_bitget_orphan_is_found_by_its_client_id():
    import ccxt

    ex = FakeExchange()
    ex.fail_with, ex.place_before_failing = ccxt.RequestTimeout("sin respuesta"), True
    br, mem = real(ex, exchange="bitget")
    with pytest.raises(BrokerError, match="sin confirmar"):
        br.execute("buy", 0.05, br.quote())
    assert mem["p"]["cid"] and ex.orders["99"]["status"] == "open"
    assert br.cancel_open_orders() == 1 and ex.cancelled == ["99"] and mem["p"] is None


def test_sandbox_is_enabled_only_where_the_exchange_really_has_one():
    """Con las clases reales de ccxt (sin red): Bitget y OKX tienen demo; Kraken, no."""
    ex = B.connect(ExecConfig(exchange="bitget", sandbox=True))
    assert ex.options.get("sandboxMode") is True  # ccxt añade la cabecera de demo a cada petición
    assert B.connect(ExecConfig(exchange="bitget")).options.get("sandboxMode") is False
    assert B.connect(ExecConfig(exchange="okx", sandbox=True)).isSandboxModeEnabled
    with pytest.raises(BrokerError, match="no ofrece entorno de pruebas"):
        B.connect(ExecConfig(exchange="kraken", sandbox=True))
    with pytest.raises(BrokerError, match="desconocido"):
        B.connect(ExecConfig(exchange="Exchange"))  # un atributo de ccxt que no es un exchange


def test_account_fee_is_read_when_the_exchange_exposes_it():
    ex = FakeExchange()
    br, _ = real(ex)
    assert br.account_taker_fee() is None  # el exchange no permite consultarla
    ex.has = {"fetchTradingFee": True}
    ex.fetch_trading_fee = lambda symbol: {"taker": 0.001, "maker": 0.0008}
    assert br.account_taker_fee() == pytest.approx(0.001)

    def boom(symbol):
        raise RuntimeError("sin permiso")

    ex.fetch_trading_fee = boom
    assert br.account_taker_fee() is None  # un fallo aquí nunca bloquea al bot


def test_con_claves_solo_conecta_a_la_demo():
    """Candado del proyecto: con claves y sin `sandbox`, no se conecta (nada de dinero real)."""
    from centinela.live.broker import connect

    with pytest.raises(BrokerError, match="demo"):
        connect(ExecConfig(exchange="bitget", sandbox=False), {"apiKey": "x", "secret": "y"})
    ex = connect(ExecConfig(exchange="bitget", sandbox=True), {"apiKey": "x", "secret": "y"})
    assert ex.options.get("sandboxMode") is True
    assert connect(ExecConfig(exchange="bitget", sandbox=False)) is not None  # solo precios públicos
