"""Brokers: la única pieza del bot que toca dinero.

* ``PaperBroker`` — cartera simulada contra el libro real (para probar sin riesgo).
* ``CcxtBroker``  — exchange real a través de ccxt (Bitget, OKX, Kraken, Coinbase, ...).

Principios de diseño:

* **El saldo del exchange es la verdad.** El bot no lleva una contabilidad paralela
  que pueda desviarse: tras cada orden vuelve a leer el saldo.
* **Toda orden real lleva tope de precio.** Se envían límites «cruzando» el spread
  con un margen máximo; nunca órdenes a mercado sin protección, porque en un
  desplome de BTC el libro se vacía y un «market» puede ejecutarse a cualquier precio.
* **Nunca se retira.** Este módulo no contiene ninguna llamada de retirada ni de
  transferencia; la clave de API debe crearse sin ese permiso.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Protocol

from ..config import ExecConfig
from ..data import binance

log = logging.getLogger(__name__)


class BrokerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    ts_ms: int

    @property
    def mid(self) -> float:
        return 0.5 * (self.bid + self.ask)

    def validate(self) -> "Quote":
        if not (self.bid > 0 and self.ask > 0 and math.isfinite(self.bid) and math.isfinite(self.ask)):
            raise BrokerError(f"cotización inválida: bid={self.bid} ask={self.ask}")
        if self.ask < self.bid:
            raise BrokerError(f"libro cruzado: bid={self.bid} > ask={self.ask}")
        if (self.ask - self.bid) / self.mid > 0.02:
            raise BrokerError(f"spread anómalo ({(self.ask - self.bid) / self.mid:.2%}): no se opera")
        return self


@dataclass(frozen=True)
class Balances:
    base: float  # BTC totales de la cuenta
    quote: float  # efectivo total de la cuenta (USDT, USD, ...)
    free_base: float
    free_quote: float


@dataclass(frozen=True)
class Rules:
    amount_step: float
    min_amount: float
    min_cost: float
    price_tick: float

    def floor_amount(self, qty: float) -> float:
        if self.amount_step <= 0:
            return qty
        return math.floor(qty / self.amount_step + 1e-9) * self.amount_step

    def tradable(self, qty: float, price: float) -> bool:
        return qty > 0 and qty >= self.min_amount and qty * price >= self.min_cost


@dataclass(frozen=True)
class Fill:
    order_id: str
    side: str  # "buy" | "sell"
    qty: float  # BTC ejecutados
    price: float  # precio medio de ejecución
    fee_quote: float  # comisión expresada en la moneda de cotización
    ts_ms: int
    complete: bool  # False si quedó parte sin ejecutar


class Broker(Protocol):
    name: str
    is_real: bool

    def rules(self) -> Rules: ...
    def quote(self) -> Quote: ...
    def balances(self) -> Balances: ...
    def execute(self, side: str, qty: float, quote: Quote, reason: str = "") -> Fill | None: ...
    def cancel_open_orders(self) -> int: ...


# =============================================================================
# Papel
# =============================================================================
def binance_quote() -> Quote:
    t = binance.book_ticker("BTCUSDT")
    return Quote(t["bid"], t["ask"], int(time.time() * 1000))


class PaperBroker:
    """Cartera simulada. Compra al ask y vende al bid reales, con comisión y deslizamiento."""

    is_real = False

    def __init__(
        self,
        cfg: ExecConfig,
        initial_quote: float,
        load: Callable[[], dict | None] | None = None,
        save: Callable[[dict], None] | None = None,
        quote_source: Callable[[], Quote] = binance_quote,
    ) -> None:
        self.cfg = cfg
        self.name = "papel"
        self._save = save
        self._quote_source = quote_source
        saved = load() if load else None
        if saved:
            self._base = float(saved["base"])
            self._quote = float(saved["quote"])
        else:
            self._base, self._quote = 0.0, float(initial_quote)
            self._persist()
        self._n = 0

    def _persist(self) -> None:
        if self._save:
            self._save({"base": self._base, "quote": self._quote})

    def rules(self) -> Rules:
        # Filtros reales de BTCUSDT en Binance spot: un papel realista rechaza lo mismo que el mercado.
        return Rules(amount_step=1e-5, min_amount=1e-5, min_cost=5.0, price_tick=0.01)

    def quote(self) -> Quote:
        return self._quote_source().validate()

    def balances(self) -> Balances:
        return Balances(self._base, self._quote, self._base, self._quote)

    def execute(self, side: str, qty: float, quote: Quote, reason: str = "") -> Fill | None:
        rules = self.rules()
        qty = rules.floor_amount(qty)
        fee, slip = self.cfg.fee, self.cfg.slippage
        if side == "buy":
            px = quote.ask * (1.0 + slip)
            qty = min(qty, rules.floor_amount(self._quote / (px * (1.0 + fee))))
            if not rules.tradable(qty, px):
                return None
            cost = qty * px
            f = cost * fee
            self._quote -= cost + f
            self._base += qty
        elif side == "sell":
            px = quote.bid * (1.0 - slip)
            qty = min(qty, rules.floor_amount(self._base))
            if not rules.tradable(qty, px):
                return None
            proceeds = qty * px
            f = proceeds * fee
            self._quote += proceeds - f
            self._base -= qty
            if self._base < rules.amount_step / 2:
                self._base = 0.0
        else:
            raise BrokerError(f"lado de orden desconocido: {side}")
        self._persist()
        self._n += 1
        ts = int(time.time() * 1000)
        return Fill(f"papel-{ts}-{self._n}", side, qty, px, f, ts, True)

    def cancel_open_orders(self) -> int:
        return 0


# =============================================================================
# Real (ccxt)
# =============================================================================
# Parámetro con el que cada exchange acepta un identificador de orden elegido por el cliente.
# Permite localizar una orden propia aunque la respuesta del envío se pierda por la red.
_CLIENT_ID_PARAM = {
    "bitget": "clientOrderId",  # ccxt lo envía como `clientOid` y lo devuelve en órdenes abiertas
    "okx": "clientOrderId",
    "kraken": "clientOrderId",
    "coinbase": "client_order_id",
}
# Parámetros que se añaden a toda orden en un exchange concreto.
# Bitget: ccxt no envía la vigencia del límite si no se le indica; se fija «válida hasta
# cancelar» en vez de depender del valor por defecto del exchange (el bot cancela la orden
# él mismo al vencer `espera_orden_s`).
_ORDER_PARAMS: dict[str, dict] = {"bitget": {"timeInForce": "GTC"}}
_DONE = ("closed", "canceled", "cancelled", "rejected", "expired")


def _has_sandbox(exchange) -> bool:
    """¿Ofrece el exchange un entorno de pruebas al contado?

    ccxt no lo declara igual en todos: OKX lo marca en ``has``; Bitget, solo en ``features``.
    """
    if exchange.has.get("sandbox"):
        return True
    spot = (getattr(exchange, "features", None) or {}).get("spot") or {}
    return bool(spot.get("sandbox"))


def connect(cfg: ExecConfig, credentials: dict[str, str] | None = None):
    """Cliente ccxt del exchange configurado, ya en su entorno de pruebas si se pidió.

    Lo usan el broker real y ``centinela doctor``, para que ambos hablen exactamente con
    el mismo entorno. Sin credenciales solo sirve para consultas públicas.
    """
    try:
        import ccxt
    except ImportError as exc:  # pragma: no cover - depende de la instalación
        raise BrokerError("falta ccxt: instala con `pip install ccxt` para operar en real") from exc
    if cfg.exchange not in ccxt.exchanges:
        raise BrokerError(f"exchange desconocido para ccxt: {cfg.exchange}")
    # Candado de este proyecto (regla 1 de CLAUDE.md): con claves, solo el entorno demo del exchange.
    # Sin claves sigue sirviendo para leer precios públicos.
    if credentials and not cfg.sandbox:
        raise BrokerError("en este proyecto solo se opera en el entorno demo del exchange (sandbox: true)")
    exchange = getattr(ccxt, cfg.exchange)(
        {**(credentials or {}), "enableRateLimit": True, "timeout": 20000, "options": {"defaultType": "spot"}}
    )
    if cfg.sandbox:
        if not _has_sandbox(exchange):
            raise BrokerError(f"{cfg.exchange} no ofrece entorno de pruebas (sandbox)")
        try:
            exchange.set_sandbox_mode(True)
        except Exception as exc:
            raise BrokerError(f"no se pudo activar el entorno de pruebas de {cfg.exchange}: {exc}") from exc
    return exchange


def _is_definitive_rejection(exc: Exception) -> bool:
    """True si el exchange respondió rechazando la orden (seguro que no existe).

    Un fallo de red o un timeout es ambiguo: la orden puede haberse creado igualmente.
    """
    try:
        import ccxt
    except ImportError:  # pragma: no cover
        return False
    return isinstance(exc, ccxt.ExchangeError)


class CcxtBroker:
    """Exchange real mediante ccxt. Solo mercado al contado, solo el par BTC configurado."""

    is_real = True

    def __init__(
        self,
        cfg: ExecConfig,
        credentials: dict[str, str],
        exchange=None,
        load_pending: Callable[[], dict | None] | None = None,
        save_pending: Callable[[dict | None], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.symbol = cfg.symbol
        # Orden en vuelo ({"oid", "cid"}), persistida ANTES de enviarla para poder limpiarla
        # tras una caída del proceso o una respuesta perdida.
        self._load_pending = load_pending or (lambda: None)
        self._save_pending = save_pending or (lambda _p: None)
        self._cid_param = _CLIENT_ID_PARAM.get(cfg.exchange)
        self._order_params = dict(_ORDER_PARAMS.get(cfg.exchange, {}))
        self.ex = exchange if exchange is not None else connect(cfg, credentials)
        self.name = f"{cfg.exchange}{' (demo)' if cfg.sandbox else ''}"
        self.ex.load_markets()
        if self.symbol not in self.ex.markets:
            raise BrokerError(f"{cfg.exchange} no lista {self.symbol}")
        self.market = self.ex.market(self.symbol)
        if not self.market.get("spot", True):
            raise BrokerError(f"{self.symbol} no es un mercado al contado en {cfg.exchange}")

    # ------------------------------------------------------------- consulta
    def rules(self) -> Rules:
        m = self.market
        prec = m.get("precision") or {}
        lim = m.get("limits") or {}
        step = float(prec.get("amount") or 1e-8)
        tick = float(prec.get("price") or 0.01)
        if step >= 1:  # algunos exchanges expresan la precisión en decimales, no en tamaño de paso
            step = 10.0 ** (-step)
        if tick >= 1 and self.ex.precisionMode != 4:
            tick = 10.0 ** (-tick)
        min_amount = float((lim.get("amount") or {}).get("min") or step)
        min_cost = float((lim.get("cost") or {}).get("min") or 0.0)
        return Rules(step, min_amount, max(min_cost, 1.0), tick)

    def quote(self) -> Quote:
        ob = self.ex.fetch_order_book(self.symbol, limit=5)
        if not ob.get("bids") or not ob.get("asks"):
            raise BrokerError("libro de órdenes vacío")
        return Quote(float(ob["bids"][0][0]), float(ob["asks"][0][0]), int(time.time() * 1000)).validate()

    def balances(self) -> Balances:
        b = self.ex.fetch_balance()
        base, quote = self.cfg.base, self.cfg.quote

        def pick(kind: str, cur: str) -> float:
            return float((b.get(kind) or {}).get(cur) or 0.0)

        return Balances(pick("total", base), pick("total", quote), pick("free", base), pick("free", quote))

    def account_taker_fee(self) -> float | None:
        """Comisión «taker» que el exchange aplica a ESTA cuenta, si permite consultarla.

        Las órdenes del bot cruzan el spread, así que pagan la tarifa taker. La cifra pública
        de un mercado puede no coincidir con la de la cuenta (nivel VIP, descuentos).
        """
        if not self.ex.has.get("fetchTradingFee"):
            return None
        try:
            taker = (self.ex.fetch_trading_fee(self.symbol) or {}).get("taker")
            return float(taker) if taker is not None else None
        except Exception as exc:
            log.info("no se pudo consultar la comisión de la cuenta: %s", exc)
            return None

    # ------------------------------------------------------------ ejecución
    def execute(self, side: str, qty: float, quote: Quote, reason: str = "") -> Fill | None:
        if side not in ("buy", "sell"):
            raise BrokerError(f"lado de orden desconocido: {side}")
        self.cancel_open_orders()  # nunca dos órdenes propias vivas a la vez
        rules = self.rules()
        cap = self.cfg.max_slippage
        limit_px = quote.ask * (1.0 + cap) if side == "buy" else quote.bid * (1.0 - cap)
        limit_px = float(self.ex.price_to_precision(self.symbol, limit_px))
        bal = self.balances()
        if side == "buy":
            # el exchange bloquea fondos al precio límite: se dimensiona con él y un colchón de comisión
            affordable = bal.free_quote / (limit_px * (1.0 + max(self.cfg.fee, 0.001) * 1.5))
            qty = min(qty, affordable)
        else:
            qty = min(qty, bal.free_base)
        qty = float(self.ex.amount_to_precision(self.symbol, rules.floor_amount(qty)))
        if not rules.tradable(qty, limit_px):
            log.info("orden %s descartada: %.8f BTC por debajo del mínimo del exchange", side, qty)
            return None
        log.info("ORDEN REAL %s %.8f %s límite %.2f (%s)", side, qty, self.symbol, limit_px, reason)
        cid = uuid.uuid4().hex if self._cid_param else None
        params = {**self._order_params, **({self._cid_param: cid} if cid else {})}
        self._save_pending({"oid": None, "cid": cid})
        try:
            order = self.ex.create_order(self.symbol, "limit", side, qty, limit_px, params)
        except Exception as exc:
            if _is_definitive_rejection(exc):
                self._save_pending(None)  # el exchange la rechazó: no existe
                raise
            # Respuesta perdida: la orden puede existir. Queda anotada y se barrerá antes de la siguiente.
            raise BrokerError(f"envío de orden sin confirmar ({type(exc).__name__}: {exc}); se verificará antes de reintentar") from exc
        oid = str(order.get("id"))
        self._save_pending({"oid": oid, "cid": cid})
        final = self._await(oid, order)
        if (final.get("status") or "").lower() in _DONE:
            self._save_pending(None)  # si no se pudo confirmar el cierre, sigue anotada y se barrerá
        filled = float(final.get("filled") or 0.0)
        if filled <= 0:
            return None
        avg = float(final.get("average") or final.get("price") or limit_px)
        return Fill(oid, side, filled, avg, self._fee_in_quote(final, filled, avg), int(time.time() * 1000), filled >= qty * 0.999)

    def _await(self, oid: str, order: dict) -> dict:
        """Espera a que la orden se complete; si no, cancela el resto y devuelve el estado final."""
        deadline = time.time() + self.cfg.order_timeout_s
        cur = order
        while time.time() < deadline:
            if (cur.get("status") or "").lower() in _DONE:
                return cur
            time.sleep(1.5)
            try:
                cur = self.ex.fetch_order(oid, self.symbol)
            except Exception as exc:  # consulta fallida: se reintenta hasta el plazo
                log.warning("no se pudo consultar la orden %s: %s", oid, exc)
        try:
            self.ex.cancel_order(oid, self.symbol)
        except Exception as exc:
            log.warning("cancelación de %s falló (puede haberse completado ya): %s", oid, exc)
        for _ in range(4):
            try:
                return self.ex.fetch_order(oid, self.symbol)
            except Exception as exc:
                log.warning("estado final de %s no disponible todavía: %s", oid, exc)
                time.sleep(1.5)
        return cur

    def _fee_in_quote(self, order: dict, filled: float, avg: float) -> float:
        fees = order.get("fees") or ([order["fee"]] if order.get("fee") else [])
        total, known = 0.0, False
        for f in fees:
            cost = f.get("cost")
            if cost is None:
                continue
            cost = abs(float(cost))
            cur = f.get("currency")
            if cur == self.cfg.quote:
                total += cost
                known = True
            elif cur == self.cfg.base:
                total += cost * avg
                known = True
        return total if known else filled * avg * self.cfg.fee  # estimación si el exchange no la informa

    def cancel_open_orders(self) -> int:
        """Cancela la orden que el bot dejó en vuelo si el proceso murió a media ejecución.

        Solo toca la orden cuyo identificador guardó el propio bot: las órdenes que el
        usuario tenga puestas a mano en la cuenta no se cancelan jamás.
        """
        pending = self._load_pending()
        if not pending:
            return 0
        oid, cid = pending.get("oid"), pending.get("cid")
        if not oid and not cid:
            log.warning("hubo un envío de orden sin confirmar y este exchange no permite identificarla: "
                        "revisa a mano las órdenes abiertas de %s", self.symbol)  # fmt: skip
            self._save_pending(None)
            return 0
        n = 0
        for o in self.ex.fetch_open_orders(self.symbol):
            mine = (oid and str(o.get("id")) == oid) or (cid and o.get("clientOrderId") == cid)
            if mine:
                # si la cancelación falla se propaga: no se opera sin saber qué hay abierto
                self.ex.cancel_order(o["id"], self.symbol)
                n += 1
        self._save_pending(None)
        return n
