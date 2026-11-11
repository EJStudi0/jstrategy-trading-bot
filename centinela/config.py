"""Configuración: un YAML en español, validado de forma estricta.

Cualquier clave desconocida es un error (una errata no puede cambiar en silencio el
comportamiento de un bot que mueve dinero). Las claves de API **nunca** van en el
YAML: se leen del entorno o de un fichero ``.env`` que git ignora.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from .backtest.engine import BacktestConfig
from .risk import RiskConfig
from .strategy import StrategyConfig


class ConfigError(ValueError):
    pass


# Perfiles de riesgo. ``allocation`` es la fracción del capital que sigue a la
# estrategia (el resto permanece siempre en efectivo): reduce a la mitad retorno y
# caída sin alterar la calidad de la señal.
#
# ``dd_halt`` es el cortafuegos de cada perfil: se sitúa justo por fuera de la peor
# caída que ese perfil sufrió en el periodo de diseño (13,5 %, 26,0 % y 35,1 %). Así
# no interfiere en condiciones normales y salta solo si ocurre algo nunca visto.
PROFILES: dict[str, dict] = {
    "conservador": {"target_vol": 0.50, "full_forecast": 0.40, "allocation": 0.5, "dd_halt": 0.15},
    "equilibrado": {"target_vol": 0.50, "full_forecast": 0.40, "allocation": 1.0, "dd_halt": 0.30},
    "agresivo": {"target_vol": 0.80, "full_forecast": 0.30, "allocation": 1.0, "dd_halt": 0.40},
}


@dataclass(frozen=True)
class ExecConfig:
    exchange: str = "okx"  # identificador ccxt del exchange donde se opera en real
    symbol: str = "BTC/USDT"
    sandbox: bool = False  # entorno de pruebas del exchange, si lo ofrece
    fee: float = 0.0010  # comisión por lado (papel y backtest)
    slippage: float = 0.0002  # deslizamiento por lado (papel y backtest)
    max_slippage: float = 0.0030  # tope de precio de las órdenes reales frente al mejor bid/ask
    order_timeout_s: int = 45  # espera máxima a que una orden real se complete
    max_order_quote: float = 0.0  # tope de nominal por orden (0 = sin tope)
    reserve_btc: float = 0.0  # BTC de la cuenta que el bot no debe tocar
    reserve_quote: float = 0.0  # efectivo de la cuenta que el bot no debe tocar
    max_venue_deviation: float = 0.015  # discrepancia máxima tolerada entre el exchange y la referencia

    def __post_init__(self) -> None:
        if "/" not in self.symbol or not self.symbol.upper().startswith("BTC/"):
            raise ConfigError("Centinela solo opera Bitcoin: el símbolo debe ser BTC/<moneda>, p. ej. BTC/USDT")
        for name in ("fee", "slippage", "max_slippage", "max_order_quote", "reserve_btc", "reserve_quote"):
            if getattr(self, name) < 0:
                raise ConfigError(f"ejecucion.{name} no puede ser negativo")
        if self.fee > 0.02 or self.slippage > 0.02:
            raise ConfigError("comisión/deslizamiento se expresan en tanto por uno (0.001 = 0,1 %)")

    @property
    def base(self) -> str:
        return self.symbol.split("/")[0]

    @property
    def quote(self) -> str:
        return self.symbol.split("/")[1]


@dataclass(frozen=True)
class LiveConfig:
    delay_s: int = 20  # segundos tras el cierre de la vela antes de decidir
    guard_interval_s: int = 30  # cadencia del vigilante entre decisiones
    max_stale_hours: int = 3  # con datos más viejos que esto no se abren ni amplían posiciones
    blind_exit_hours: int = 48  # sin datos fiables durante tanto tiempo -> salir a efectivo (0 = nunca)

    def __post_init__(self) -> None:
        if self.delay_s < 2 or self.delay_s > 1800:
            raise ConfigError("vivo.retardo_s debe estar entre 2 y 1800")
        if self.guard_interval_s < 5:
            raise ConfigError("vivo.intervalo_vigilancia_s debe ser >= 5")


@dataclass(frozen=True)
class Config:
    profile: str = "equilibrado"
    mode: str = "papel"  # papel | real
    paper_capital: float = 10_000.0
    allocation: float = 1.0
    band: float = 0.15
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=lambda: RiskConfig(dd_halt=0.30, dd_cooldown_h=24 * 30))
    execution: ExecConfig = field(default_factory=ExecConfig)
    live: LiveConfig = field(default_factory=LiveConfig)
    data_dir: str = "data"
    state_dir: str = "state"
    reports_dir: str = "reports"
    telegram: bool = False

    def __post_init__(self) -> None:
        if self.mode not in ("papel", "real"):
            raise ConfigError("modo debe ser «papel» o «real»")
        if not 0 < self.allocation <= 1:
            raise ConfigError("la asignación debe estar en (0, 1]")
        if not 0.01 <= self.band <= 0.5:
            raise ConfigError("banda debe estar entre 0.01 y 0.5")
        if self.paper_capital <= 0:
            raise ConfigError("capital_papel debe ser positivo")

    @property
    def effective_band(self) -> float:
        """La banda de no-operación escala con la fracción de capital asignada."""
        return self.band * self.allocation

    def backtest_config(self, **overrides) -> BacktestConfig:
        base = BacktestConfig(
            initial_capital=self.paper_capital,
            fee=self.execution.fee,
            slippage=self.execution.slippage,
            band=self.effective_band,
            max_exposure=self.strategy.max_exposure,
        )
        return replace(base, **overrides) if overrides else base


# --------------------------------------------------------------------- carga
_TOP = {"perfil", "modo", "capital_papel", "banda", "estrategia", "riesgo", "ejecucion", "vivo", "directorios", "telegram"}
_STRATEGY = {
    "volatilidad_objetivo": "target_vol",
    "prevision_plena": "full_forecast",
    "exposicion_maxima": "max_exposure",
    "velocidades_tendencia_dias": "trend_speeds_days",
    "vol_semivida_rapida_h": "vol_fast_halflife_h",
    "vol_semivida_lenta_h": "vol_slow_halflife_h",
    "vol_suelo": "vol_floor_frac",
    "calentamiento_dias": "warmup_days",
}
_RISK = {
    "parada_caida": "dd_halt",
    "reduccion_caida": "dd_reduce",
    "enfriamiento_dias": None,  # se convierte a horas
    "parada_desplome_sigmas": "crash_sigmas",
    "desplome_ventana_h": "crash_lookback_h",
    "desplome_enfriamiento_h": "crash_cooldown_h",
}
_EXEC = {
    "exchange": "exchange",
    "simbolo": "symbol",
    "sandbox": "sandbox",
    "comision": "fee",
    "deslizamiento": "slippage",
    "deslizamiento_maximo": "max_slippage",
    "espera_orden_s": "order_timeout_s",
    "orden_maxima": "max_order_quote",
    "reserva_btc": "reserve_btc",
    "reserva_efectivo": "reserve_quote",
    "desviacion_maxima_exchange": "max_venue_deviation",
}
_LIVE = {
    "retardo_s": "delay_s",
    "intervalo_vigilancia_s": "guard_interval_s",
    "max_horas_datos_viejos": "max_stale_hours",
    "horas_ciego_para_salir": "blind_exit_hours",
}
_DIRS = {"datos": "data_dir", "estado": "state_dir", "informes": "reports_dir"}


def _section(raw: dict, name: str, mapping: dict) -> dict:
    sec = raw.get(name) or {}
    if not isinstance(sec, dict):
        raise ConfigError(f"la sección «{name}» debe ser un bloque de claves")
    unknown = set(sec) - set(mapping)
    if unknown:
        raise ConfigError(f"claves desconocidas en «{name}»: {sorted(unknown)}. Válidas: {sorted(mapping)}")
    return sec


def from_dict(raw: dict | None) -> Config:
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ConfigError("el fichero de configuración debe ser un mapa YAML")
    unknown = set(raw) - _TOP
    if unknown:
        raise ConfigError(f"claves desconocidas: {sorted(unknown)}. Válidas: {sorted(_TOP)}")
    profile = str(raw.get("perfil", "equilibrado")).lower()
    if profile not in PROFILES:
        raise ConfigError(f"perfil desconocido «{profile}». Opciones: {', '.join(PROFILES)}")
    preset = PROFILES[profile]
    try:
        s_sec = _section(raw, "estrategia", _STRATEGY)
        s_kwargs: dict = {"target_vol": preset["target_vol"], "full_forecast": preset["full_forecast"]}
        for es, val in s_sec.items():
            en = _STRATEGY[es]
            s_kwargs[en] = tuple(float(x) for x in val) if en == "trend_speeds_days" else val
        strategy = StrategyConfig(**s_kwargs)

        r_sec = _section(raw, "riesgo", _RISK)
        r_kwargs: dict = {"dd_halt": preset["dd_halt"], "dd_cooldown_h": 24 * 30}
        for es, en in _RISK.items():
            if es in r_sec:
                if es == "enfriamiento_dias":
                    r_kwargs["dd_cooldown_h"] = int(float(r_sec[es]) * 24)
                else:
                    r_kwargs[en] = r_sec[es]
        risk = RiskConfig(**r_kwargs)

        e_sec = _section(raw, "ejecucion", _EXEC)
        execution = ExecConfig(**{_EXEC[k]: v for k, v in e_sec.items()})
        l_sec = _section(raw, "vivo", _LIVE)
        live = LiveConfig(**{_LIVE[k]: v for k, v in l_sec.items()})
        d_sec = _section(raw, "directorios", _DIRS)
        dirs = {_DIRS[k]: str(v) for k, v in d_sec.items()}
        return Config(
            profile=profile,
            mode=str(raw.get("modo", "papel")).lower(),
            paper_capital=float(raw.get("capital_papel", 10_000.0)),
            allocation=float(preset["allocation"]),
            band=float(raw.get("banda", 0.15)),
            strategy=strategy,
            risk=risk,
            execution=execution,
            live=live,
            telegram=bool(raw.get("telegram", False)),
            **dirs,
        )
    except TypeError as exc:
        raise ConfigError(f"valor de configuración inválido: {exc}") from exc
    except ValueError as exc:
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError(str(exc)) from exc


def load(path: str | Path | None = None) -> Config:
    """Carga ``config.yaml`` (o el fichero indicado). Sin fichero, valores por defecto."""
    if path is None:
        default = Path("config.yaml")
        if not default.exists():
            return from_dict({})
        path = default
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"no existe el fichero de configuración: {p}")
    with p.open(encoding="utf-8") as fh:
        try:
            raw = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ConfigError(f"YAML inválido en {p}: {exc}") from exc
    return from_dict(raw)


def load_env(path: str | Path = ".env") -> None:
    """Carga variables de un ``.env`` sencillo (CLAVE=valor) sin pisar las ya definidas."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def api_credentials() -> dict[str, str]:
    """Credenciales del exchange desde el entorno. Solo hacen falta en modo real."""
    key = os.environ.get("CENTINELA_API_KEY", "")
    secret = os.environ.get("CENTINELA_API_SECRET", "")
    if not key or not secret:
        raise ConfigError(
            "faltan CENTINELA_API_KEY / CENTINELA_API_SECRET en el entorno o en .env "
            "(crea la clave SOLO con permiso de trading, nunca de retirada)"
        )
    out = {"apiKey": key, "secret": secret}
    password = os.environ.get("CENTINELA_API_PASSWORD", "")
    if password:
        out["password"] = password
    return out
