"""
BOT DE TRADING AUTÓNOMO — ESTRATEGIA JORGE (DigitalCapitalsTrading)
====================================================================
Sistema: EMA10/55 + Teoría 12 Velas + Squeeze+ADX + VRVP approx + OB + Cobertura + DCA

Los 10 ARGUMENTOS implementados:
  1. Sincronización multi-timeframe (1D + 4H + 1H)
  2. S/R estructural
  3. OB virgen o zona de reacción
  4. Análisis de liquidez
  5. Teoría de las 12 velas (conteo)
  6. Rupturas e imbalances
  7. Regla del 3er/4to toque en resistencia
  8. Datos de volumen (absorción)
  9. EMAs: cruce, compresión, distancia, inclinación
 10. Confirmación multi-temporal (OB 1D refinado en 4H)

Extras: ADX, Telegram, backtest detallado, notificaciones inteligentes

Requiere:
    pip install ccxt pandas numpy requests

Uso:
    python 04_SCRIPT_BOT_PYTHON.py          # trading normal
    python 04_SCRIPT_BOT_PYTHON.py backtest # análisis histórico
    python 04_SCRIPT_BOT_PYTHON.py signal   # solo muestra señal actual, no opera
"""

import ccxt
import csv
import pandas as pd
import numpy as np
import time
import json
import logging
import os
import requests
import sys
import importlib.util
from datetime import datetime
from typing import Optional


# ─── IMPORT DE LA CAPA ADAPTATIVA (archivo con prefijo numérico) ─────────────
def _load_adaptive_layer():
    spec_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "13_ADAPTIVE_LAYER.py")
    if not os.path.exists(spec_path):
        return None
    spec = importlib.util.spec_from_file_location("adaptive_layer", spec_path)
    mod  = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        print(f"⚠️  No se pudo cargar capa adaptativa: {e}")
        return None

ADAPTIVE = _load_adaptive_layer()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("jorge_bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ─── HELPERS DE ENTORNO ────────────────────────────────────────────────────────

def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "si"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

CONFIG = {
    # Exchange — seguro por defecto. Solo opera real si paper_trading=False y hay credenciales válidas en entorno.
    "exchange": "binanceusdm",
    "api_key": os.getenv("JORGE_BOT_API_KEY", ""),
    "secret": os.getenv("JORGE_BOT_API_SECRET", ""),
    "testnet": _env_bool("JORGE_BOT_TESTNET", True),

    # Por defecto corre en paper trading. Para operar real/testnet hay que desactivarlo explícitamente.
    "paper_trading": _env_bool("JORGE_BOT_PAPER", True),

    # Par a operar
    "symbol": os.getenv("JORGE_BOT_SYMBOL", "BTC/USDT:USDT"),
    "timeframe_macro": "1d",
    "timeframe_mid": "4h",
    "timeframe_entry": "1h",
    # ── Macro bias 1W: filtro de tendencia mayor ─────────────────────────────
    # Solo opera longs cuando bias 1W es bullish (precio > EMA21W rising)
    # Solo opera shorts cuando bias 1W es bearish. En 1W neutral: solo trades alta convicción.
    "timeframe_macro_high":   "1w",
    # Backtest 2026-02 a 2026-05 mostró que el modulador 1W reduce PnL.
    # Apagado por default; infraestructura disponible para Fase 2 (régimen-aware).
    "macro_high_enabled":     _env_bool("JORGE_BOT_MACRO_HIGH", False),
    "macro_high_ema_period":  21,        # EMA21W: estándar de tendencia macro
    "macro_high_min_candles": 50,        # mínimo de velas semanales para que tenga sentido

    # Capital y riesgo — V10 = V7 (mejor backtest) + detector ruptura activo:
    # - v7 scalp agresivo: +86 USDT/104d, WR 80%, drawdown -4.85% (mejor real)
    # - Detector de ruptura: cuando aparezca trend, entra con 80% capital
    # - Compound activo: equity actual modula sizing
    "total_capital_usdt": _env_float("JORGE_BOT_CAPITAL_USDT", 5000),
    "risk_capital_pct": _env_float("JORGE_BOT_RISK_CAPITAL_PCT", 0.20),   # 20% capital activo
    "leverage": _env_int("JORGE_BOT_LEVERAGE", 5),                        # 5× (mayor amplificación)
    "position_parts": 5,         # 1 entrada inicial + 4 DCA

    # Take profit V2: más realista para intradía/swing corto y para un objetivo diario de 10-20 USDT.
    # ── TPs y runner — V7 SCALP AGRESIVO (validado +86 USDT/104d) ────────────
    # Calibración que SÍ funciona en mercados reales (mostly lateral).
    # Si aparece ruptura estructural → TPs especiales sobrescriben (90% en +35%).
    "tp1_pct": 0.008,            # +0.8% precio → caja rápida
    "tp1_close_pct": 0.30,       # 30%
    "tp2_pct": 0.016,            # +1.6%
    "tp2_close_pct": 0.30,       # 30%
    "tp3_pct": 0.028,            # +2.8%
    "tp3_close_pct": 0.25,       # 25% → deja 15% runner
    "tp_hold_pct": 0.15,         # 15% runner ATR
    "runner_trail_atr_mult": 2.0,

    # ── FASE 2: Régimen-aware execution ──────────────────────────────────────
    # El bot cambia TPs, sizing y filtros según el régimen detectado:
    # - expansion: tendencia fuerte + volatilidad alta → TPs AMPLIOS (deja correr)
    # - trending:  tendencia firme, vol normal → TPs medios
    # - ranging:   sin tendencia, vol normal → TPs AJUSTADOS (scalping mean-reversion)
    # - exhaustion: vol alta sin tendencia → reducir sizing, solo trades A
    # - quiet:     vol baja sin tendencia → NO operar
    "regime_aware_enabled": _env_bool("JORGE_BOT_REGIME_AWARE", True),
    # ── regime_tps v7 (scalp en todos los regímenes) ─────────────────────────
    # v7 backtest +86 USDT/104d. Para captar big moves cuando aparezcan, el
    # detector de RUPTURA ESTRUCTURAL sobreescribe con TPs amplios (10/20/35%)
    # — esto es Jorge swing solo en setups VALIDADOS, no a ciegas por régimen.
    "regime_tps": {
        "expansion":  {"tp1_pct": 0.010, "tp1_close": 0.25, "tp2_pct": 0.020, "tp2_close": 0.30, "tp3_pct": 0.035, "tp3_close": 0.25, "runner": 0.20, "trail_atr": 2.5},
        "trending":   {"tp1_pct": 0.008, "tp1_close": 0.30, "tp2_pct": 0.016, "tp2_close": 0.30, "tp3_pct": 0.028, "tp3_close": 0.25, "runner": 0.15, "trail_atr": 2.0},
        "ranging":    {"tp1_pct": 0.008, "tp1_close": 0.30, "tp2_pct": 0.016, "tp2_close": 0.30, "tp3_pct": 0.028, "tp3_close": 0.25, "runner": 0.15, "trail_atr": 2.0},
        "exhaustion": {"tp1_pct": 0.008, "tp1_close": 0.40, "tp2_pct": 0.014, "tp2_close": 0.35, "tp3_pct": 0.022, "tp3_close": 0.20, "runner": 0.05, "trail_atr": 1.5},
    },
    "regime_sizing": {
        "expansion":  1.00,
        "trending":   1.00,
        "ranging":    0.80,
        "exhaustion": 0.50,
        "quiet":      0.0,    # 0 = no operar
        "warmup":     0.50,
    },
    "regime_block_entries": ["quiet"],          # regímenes donde NO se entra
    "regime_only_high_conviction": ["exhaustion"],  # regímenes que requieren score alto

    # ── FASE 3: Funding rate awareness ───────────────────────────────────────
    # Lee funding rate de Binance Futures y modula sizing:
    # - Funding > 0.05% (longs sobre-apalancados): sesgo SHORT, reduce LONG sizing
    # - Funding < -0.03% (shorts sobre-apalancados): sesgo LONG, reduce SHORT sizing
    # Funding extremo = cascada de liquidación probable → aprovecharla en la dirección correcta
    "funding_aware_enabled":  _env_bool("JORGE_BOT_FUNDING_AWARE", True),
    # Thresholds calibrados al rango histórico real de BTC (mucho menor que altcoins):
    # rango observado 2026-03 a 05: min -0.012%, max +0.008%, std 0.0043%
    "funding_extreme_long":   0.00005,   # 0.005% — long-heavy (percentil ~95 BTC)
    "funding_extreme_short":  -0.00005,  # -0.005% — short-heavy (percentil ~10 BTC)
    "funding_long_penalty":   0.6,       # multiplicador sizing LONG si funding extremo positivo
    "funding_short_penalty":  0.6,       # multiplicador sizing SHORT si funding extremo negativo
    "funding_long_boost":     1.2,       # boost sizing LONG si funding negativo (shorts cargados)
    "funding_short_boost":    1.2,       # boost sizing SHORT si funding positivo (longs cargados)

    # ── VWAP confluence (mean reversion institucional) ──────────────────────
    # VWAP diario (ancla 00:00 UTC) marca el "precio justo" ponderado por volumen.
    # LONG con confluencia: precio toca/cruza VWAP desde abajo → boost sizing
    # SHORT con confluencia: precio toca/cruza VWAP desde arriba → boost sizing
    # Trades contra VWAP (chase): penalización suave
    "vwap_aware_enabled":     _env_bool("JORGE_BOT_VWAP_AWARE", True),
    "vwap_proximity_pct":     0.005,     # 0.5% — distancia para considerar "cerca de VWAP"
    "vwap_confluence_boost":  1.15,      # × sizing si confluencia favorable
    "vwap_chase_penalty":     0.80,      # × sizing si trade contra VWAP lejos

    # ── RUPTURA ESTRUCTURAL — operación excepcional Jorge ────────────────────
    # Cuando se detecta ruptura confirmada: entrar con 80% del capital (4× el normal)
    # TPs cortos: salir 90% en +30-50% de ganancia (operación rápida, no swing)
    # Backtest mostró falsos positivos (-85 USDT en 1 trade con sizing ×4).
    # Necesita más calibración antes de activar. Infraestructura queda lista.
    "structural_break_enabled":  _env_bool("JORGE_BOT_STRUCTURAL_BREAK", False),
    "structural_break_sizing":   4.0,    # 4× el sizing normal (20% × 4 = 80% capital)
    "structural_break_tps": {            # TPs específicos para rupturas (cierre rápido)
        "tp1_pct": 0.10,  "tp1_close": 0.30,    # +10% precio → cerrar 30%
        "tp2_pct": 0.20,  "tp2_close": 0.30,    # +20% → cerrar 30%
        "tp3_pct": 0.35,  "tp3_close": 0.30,    # +35% → cerrar 30% (90% total cerrado)
        "runner": 0.10,
        "trail_atr": 2.0,
    },

    # DCA V2: escalado moderado. Se evita el martingale agresivo.
    # DCAs cortos (v7 calibration validada) — DCAs amplios solo en ruptura estructural
    "dca_levels_pct": [-0.015, -0.03, -0.045, -0.06],
    "dca_size_multipliers": [0.50, 0.75, 1.00, 1.25],

    # Umbrales de análisis
    "compression_threshold_pct": 0.02,
    "max_price_ema10_distance_pct": 0.03,
    "ema55_touch_tolerance": 0.005,
    "ob_zone_tolerance": 0.008,
    "volume_spike_mult": 1.5,

    # Cobertura: desactivada por defecto en V2. Primero se valida edge simple.
    "hedge_enabled": _env_bool("JORGE_BOT_HEDGE_ENABLED", False),
    "hedge_loss_trigger_pct": -0.20,   # -20% caída (antes era -7%, demasiado agresivo)
    "hedge_size_multiplier": 2.0,       # cobertura = 2x tamaño del LONG
    "hedge_close_gain_pct": 0.10,       # cerrar cobertura cuando gana +10%
    "hedge_partial_pct": 0.80,          # cerrar 80% primero, dejar 20% corriendo

    # Invalidación dura V2. Si el setup no responde, se sale.
    "enable_hard_stop": True,
    # Hard stop v7 (con lev 5×): -3% precio = -15% margen, controlado
    "hard_stop_pct": -0.03,
    # Stop dinámico v7: max 4% precio (= -20% margen lev 5), min 1.2%
    "dynamic_stop_enabled":      _env_bool("JORGE_BOT_DYNAMIC_STOP", True),
    "dynamic_stop_lookback":     10,
    "dynamic_stop_atr_mult":     1.0,
    "dynamic_stop_atr_period":   14,
    "dynamic_stop_max_pct":      0.04,
    "dynamic_stop_min_pct":      0.012,

    # Señales — automatización más estricta
    "min_score_to_enter": 8,
    "high_conviction_score": 9,
    "allowed_entry_types": _env_list("JORGE_BOT_ALLOWED_ENTRY_TYPES", ["A", "B", "C"]),

    # Filtros de calidad de entrada
    "weekend_filter": True,        # Sáb/Dom = bajo volumen, movimientos no confiables
    "require_adx_trend": True,     # ADX < 21 = sin tendencia = no entrar
    "require_squeeze_off": True,   # Squeeze ON = acumulando, NO entrar aún (esperar disparo)

    # Filtro de sesión: solo operar en horas de alta liquidez (UTC)
    # Mantenido por compatibilidad con telegram /status — el filtro real es killzones
    "session_filter": True,
    "session_start_utc": 7,
    "session_end_utc": 21,

    # KILLZONES INSTITUCIONALES (UTC) — reemplaza el filtro genérico de sesión.
    # Cada killzone tiene un multiplicador de tamaño (0 = no operar).
    # Asian range = define liquidez para Londres, NO se opera dentro de él.
    # Lunch NY = movimiento incoherente, no operar.
    "killzones_enabled": _env_bool("JORGE_BOT_KILLZONES", True),
    "killzones": [
        # (hora_inicio, hora_fin, nombre, sizing_mult)
        # Si end <= start → la ventana cruza medianoche (ej. 22-04)
        (22,  4, "Asia_Open",   0.7),    # apertura asiática — volatilidad post-weekend
        (7,  10, "London_Open", 1.0),    # apertura Londres — movimiento direccional fuerte
        (13, 16, "NY_AM",       1.0),    # NY AM — el "real move" del día
        (17, 20, "NY_PM",       0.7),    # NY PM — fade/scalping con tamaño reducido
        (20, 21, "Power_Hour",  0.6),    # cierre — fadeo, tamaño aún menor
    ],
    # Filtro día-semana (0=Lun, 1=Mar, ..., 6=Dom). Multiplicador de tamaño por día.
    "dow_multipliers": {
        0: 0.7,   # Lunes — inducement / trampa frecuente, ser conservador
        1: 1.0,   # Martes
        2: 1.0,   # Miércoles
        3: 0.85,  # Jueves — weekly reversal frecuente
        4: 0.6,   # Viernes — cerrar antes de 18:00 UTC
        5: 0.0,   # Sábado — sin liquidez, no operar
        6: 0.6,   # Domingo — solo Asia_Open noche (sizing reducido por baja liquidez weekend)
    },
    "friday_close_hour_utc": 18,    # cerrar todas las posiciones a esta hora los viernes

    # ÓRDENES LÍMITE ANTICIPADAS en OB virgen — captura wicks intra-vela que un muestreo
    # cada 5 min con timeframe 1H se perdería. Se arma una sola orden por dirección dentro
    # de la killzone activa y se cancela al salir de killzone o si el OB se invalida.
    "pending_orders_enabled":     _env_bool("JORGE_BOT_PENDING_ORDERS", True),
    "pending_min_score":          6,        # score mínimo (sobre 13) para armar
    "pending_min_distance_pct":   0.003,    # OB debe estar al menos 0.3% del precio (sino, market mejor)
    "pending_max_distance_pct":   0.025,    # OB a más de 2.5% del precio → improbable de tocar en KZ

    # SMC — Smart Money Concepts
    "smc_enabled": _env_bool("JORGE_BOT_SMC", True),
    "smc_sweep_lookback": 20,           # velas hacia atrás para detectar swing high/low
    "smc_sweep_min_wick_pct": 0.0015,   # mecha mínima 0.15% del precio para considerarse sweep
    "smc_premium_threshold": 0.7,       # >= 0.7 del rango HTF = premium (no longs aquí)
    "smc_discount_threshold": 0.3,      # <= 0.3 del rango HTF = discount (no shorts aquí)
    "smc_htf_range_window": 20,         # velas del 4H para definir rango premium/discount

    # Lado SHORT habilitado (operación standalone, no solo cobertura del long)
    "shorts_enabled": _env_bool("JORGE_BOT_SHORTS", True),
    "min_score_short": _env_int("JORGE_BOT_MIN_SCORE_SHORT", 7),

    # Objetivos diarios — usar como límite operativo, no como obligación.
    "daily_profit_target_usdt": _env_float("JORGE_BOT_DAILY_TARGET_USDT", 15),
    "daily_loss_limit_usdt": _env_float("JORGE_BOT_DAILY_LOSS_LIMIT_USDT", 15),

    # Trailing stop post-TP1: si TP1 fue alcanzado y el precio revierte
    # con tendencia debilitada → cerrar resto para no perder la ganancia asegurada
    "trailing_stop_after_tp1": True,
    "trailing_stop_entry_pct": -0.0025,   # proteger rápidamente cuando el trade ya pagó

    # Multi-symbol infraestructura disponible pero CALIBRACIÓN es para BTC.
    # Backtest comparativo (2026-02 a 05) en mismo periodo:
    #   BTC:  +26.35 USDT ✓
    #   SOL:   +5.66 USDT (marginal)
    #   ETH:  -17.86 USDT (perdedor)
    #   AVAX: -47.49 USDT (pierde fuerte)
    # → Default a BTC solo. Para añadir alts hay que calibrar TPs/stops por
    #   volatilidad propia (TODO: regime_tps_by_symbol o ATR-relative).
    "symbols": _env_list("JORGE_BOT_SYMBOLS", ["BTC/USDT:USDT"]),
    "max_concurrent_positions": _env_int("JORGE_BOT_MAX_POSITIONS", 1),

    # Tolerancia de soporte estructural para DCA
    "dca_structural_tolerance": 0.015,   # ±1.5% de distancia al soporte

    # Telegram
    "telegram_token": os.getenv("JORGE_BOT_TELEGRAM_TOKEN", ""),
    "telegram_chat_id": os.getenv("JORGE_BOT_TELEGRAM_CHAT_ID", ""),

    # Intervalo del loop: 5 min es suficiente (velas de 15m a 4H no requieren polling por segundo)
    "loop_interval_seconds": 300,
    # Cuántos segundos sin una vela nueva antes de considerar los datos viejos.
    # Al triple de esto el bot se declara CIEGO y deja de decir que está activo.
    "blind_after_seconds": _env_float("JORGE_BOT_BLIND_AFTER_SECONDS", 900),
    # Fallos seguidos tras los que se rehace el cliente de exchange.
    "rebuild_client_after_failures": _env_float("JORGE_BOT_REBUILD_AFTER_FAILURES", 3),
    # Panel web (hilo daemon dentro de este mismo proceso). Se sirve solo a la
    # LAN y detrás de token: abre y cierra posiciones, no se deja sin llave.
    "panel_enabled": os.environ.get("JORGE_BOT_PANEL", "1") not in ("0", "false", "no"),
    "panel_host": os.environ.get("JORGE_BOT_PANEL_HOST", "127.0.0.1"),
    "panel_port": int(os.environ.get("JORGE_BOT_PANEL_PORT", "8787")),

    # Persistencia local
    "trade_journal_file": os.getenv("JORGE_BOT_JOURNAL_FILE", "jorge_trade_journal.csv"),
    "metrics_file": os.getenv("JORGE_BOT_METRICS_FILE", "jorge_trade_metrics.json"),

    # Backtest realista
    "backtest_entry_candles": _env_int("JORGE_BOT_BACKTEST_ENTRY_CANDLES", 2500),
    "backtest_mid_candles": _env_int("JORGE_BOT_BACKTEST_MID_CANDLES", 1800),
    "backtest_macro_candles": _env_int("JORGE_BOT_BACKTEST_MACRO_CANDLES", 600),
    "backtest_taker_fee_pct": _env_float("JORGE_BOT_BACKTEST_TAKER_FEE_PCT", 0.0005),
    "backtest_slippage_pct": _env_float("JORGE_BOT_BACKTEST_SLIPPAGE_PCT", 0.0004),
}

# Control de pausa global (modificado desde Telegram con /pause y /resume)
_BOT_PAUSED = [False]

# Salud de la conexión de datos. El bot pasó 20 días imprimiendo "✅ ACTIVO"
# sin recibir una sola vela porque nadie llevaba esta cuenta: los errores se
# tragaban en el try por símbolo y el resumen del ciclo no los miraba.
# Último análisis publicado por el bucle, por símbolo. Lo lee el panel web.
_ULTIMO_ANALISIS: dict = {}

_SALUD: dict = {
    "ultimo_ok_utc":   None,   # última vez que llegaron velas de verdad
    "ultimo_error":    None,
    "fallos_seguidos": 0,
    "fetches_ok":      0,
}

# Rastreador diario: se reinicia automáticamente cada medianoche UTC
_DAILY_TRACKER: dict = {
    "date":          None,   # datetime.date UTC del día actual
    "start_balance": None,   # balance al inicio del día (para calcular PnL diario)
    "realized_pnl":  0.0,    # ganancias realizadas acumuladas del día
    "paused":        False,  # True cuando se alcanzó objetivo o límite de pérdida
}

# Registro compartido de managers en paper trading — usado por _build_pnl_report
# desde hilos de Telegram y daily summary que no tienen acceso directo a run_bot.
_PAPER_MANAGERS: dict = {}


# ─── PERSISTENCIA DE ESTADO ───────────────────────────────────────────────────

STATE_FILE = "jorge_bot_state.json"
TRADE_JOURNAL_FILE = "jorge_trade_journal.csv"
METRICS_FILE = "jorge_trade_metrics.json"

# Schema fijo del journal v2 — orden = orden del CSV header.
# Si se añaden features nuevos, agregar al final para no romper apends.
JOURNAL_FIELDS = [
    # Identidad
    "timestamp", "symbol", "event", "side", "mode",
    # Precio y tamaño
    "price", "size", "margin_used",
    # PnL del trade (en cierres)
    "pnl_pct", "pnl_usdt", "balance",
    # Setup en el momento de la decisión
    "entry_type", "score", "score_adjusted",
    "killzone", "dow", "regime",
    # Contexto de tendencia
    "adx_value", "adx_bull",
    # SMC / HTF
    "htf_range_pos", "htf_label",
    # Squeeze / volatilidad
    "sqz_quadrant", "sqz_on",
    # Order Block
    "ob_bull_dist_pct", "ob_bear_dist_pct",
    # Estructura del precio
    "compression_state", "candle_count",
    # Excursiones (solo en cierres)
    "mae_pct", "mfe_pct", "duration_minutes", "exit_reason",
    # Contexto pending (solo en armado/cancel/fill de límites)
    "ob_width_pct", "pending_distance_pct",
    "note",
]


def _extract_sig_features(sig: Optional[dict]) -> dict:
    """Extrae features predictivos de sig para el journal. Robusto a sig=None / claves faltantes."""
    if not sig:
        return {}
    smc = sig.get("smc", {}) if isinstance(sig.get("smc"), dict) else {}
    adx = sig.get("adx", {}) if isinstance(sig.get("adx"), dict) else {}
    htf_pos = smc.get("htf_range_pos")
    htf_label = (
        "PREM" if smc.get("in_premium_mid") else
        "DISC" if smc.get("in_discount_mid") else
        "MID" if htf_pos is not None else ""
    )
    return {
        "score":             sig.get("score"),
        "score_adjusted":    sig.get("score_adjusted"),
        "regime":            sig.get("regime", ""),
        "adx_value":         adx.get("value"),
        "adx_bull":          adx.get("trend"),
        "htf_range_pos":     htf_pos,
        "htf_label":         htf_label,
        "sqz_quadrant":      sig.get("sqz_quadrant"),
        "sqz_on":            sig.get("squeeze_on"),
        "ob_bull_dist_pct":  sig.get("ob_bull_dist_pct"),
        "ob_bear_dist_pct":  sig.get("ob_bear_dist_pct"),
        "compression_state": sig.get("compression_state", ""),
        "candle_count":      sig.get("candle_count"),
    }


def _infer_exit_reason(event_name: str) -> Optional[str]:
    """Deriva exit_reason del nombre del evento."""
    e = event_name.lower()
    if e.startswith("tp1"):  return "tp1"
    if e.startswith("tp2"):  return "tp2"
    if e.startswith("tp3"):  return "tp3"
    if "hard_stop" in e:     return "hard_stop"
    if "trail" in e:         return "trail"
    if "force_close" in e:   return "force_close"
    if "hedge" in e:         return "hedge_event"
    if "cancelled" in e:     return "cancelled"
    return None


def _append_trade_journal(event: dict, cfg: dict = CONFIG,
                          sig: Optional[dict] = None,
                          pos: Optional[dict] = None) -> None:
    """Append event to journal.
    - `sig` → extrae features predictivos automáticamente (htf, adx, sqz, etc.)
    - `pos` → extrae MAE/MFE/duration de la posición que se cierra (usar en TPs/stops/trail)
    Campos explícitos en `event` sobrescriben extracciones.
    """
    path = cfg.get("trade_journal_file", TRADE_JOURNAL_FILE)
    now = datetime.utcnow()
    row = {f: None for f in JOURNAL_FIELDS}
    row.update({
        "timestamp": now.isoformat(),
        "symbol": cfg.get("symbol", ""),
        "event": event.get("event", ""),
        "side": event.get("side", ""),
        "mode": "paper" if cfg.get("paper_trading", True) else "live",
        "dow": now.weekday(),
    })
    # Features de sig (si está disponible)
    row.update(_extract_sig_features(sig))
    # Metadatos de cierre desde la posición (si está disponible)
    if pos:
        if "mae_pct" in pos: row["mae_pct"] = round(pos["mae_pct"], 3)
        if "mfe_pct" in pos: row["mfe_pct"] = round(pos["mfe_pct"], 3)
        entry_ts = pos.get("entry_ts")
        if entry_ts:
            row["duration_minutes"] = round((time.time() - entry_ts) / 60.0, 1)
    # Inferir exit_reason si no viene explícito
    inferred = _infer_exit_reason(event.get("event", ""))
    if inferred:
        row["exit_reason"] = inferred
    # Campos explícitos del event sobrescriben todo
    for k, v in event.items():
        if k in row and v is not None:
            row[k] = v
    write_header = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=JOURNAL_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


# Eventos que por naturaleza liquidan lo que quede de la posición. Se usan solo
# como red de seguridad: la señal primaria es el tamaño restante, no el nombre.
_FULL_CLOSE_PREFIXES = ("hard_stop", "lock_exit", "trailing_stop", "hedge_close", "hedge_force_close")


def _group_journal_into_trades(df: pd.DataFrame) -> list:
    """Agrupa los eventos del journal en trades siguiendo el TAMAÑO de la posición.

    Deliberadamente no se filtra por lista de nombres de evento. Esa lista se
    desincronizó del journal — `tp1_short`, `hard_stop_short` y `lock_exit`
    nunca entraron en ella — y como las cinco pérdidas del histórico eran todas
    `hard_stop_short`, las métricas reportaban 100% de aciertos sobre una
    estrategia que perdía dinero. Aquí un evento cuenta como salida si trae
    `pnl_usdt`, y el trade se cierra cuando el tamaño restante vuelve a cero:
    dos señales que salen del dato y no del nombre.
    """
    if df.empty or "event" not in df.columns:
        return []

    eventos = df["event"].astype(str)
    col_size = pd.to_numeric(df.get("size"), errors="coerce").fillna(0.0)
    col_pnl = pd.to_numeric(df.get("pnl_usdt"), errors="coerce").fillna(0.0)

    def _campo(nombre: str, i: int):
        if nombre not in df.columns:
            return None
        valor = df[nombre].iat[i]
        return None if pd.isna(valor) else valor

    trades: list = []
    actual: Optional[dict] = None

    for i in range(len(df)):
        evento = eventos.iat[i]
        size = float(col_size.iat[i])
        pnl = float(col_pnl.iat[i])

        if evento.startswith("open_"):
            if actual is not None:
                trades.append(actual)
            actual = {
                "abierto_utc": _campo("timestamp", i),
                "cerrado_utc": None,
                "side": _campo("side", i),
                "score": _campo("score", i),
                "regime": _campo("regime", i),
                "killzone": _campo("killzone", i),
                "tamano_abierto": size,
                "restante": size,
                "pnl_usdt": 0.0,
                "salidas": [],
                "cerrado": False,
            }
            continue

        if actual is None or actual["cerrado"]:
            continue

        # Un DCA amplía la posición: sube el listón de lo que hay que cerrar.
        if evento.startswith("dca"):
            actual["tamano_abierto"] += size
            actual["restante"] += size
            continue

        if pnl == 0.0 and size == 0.0:
            continue  # armados, cancelaciones y demás ruido sin efecto en la posición

        actual["pnl_usdt"] += pnl
        actual["restante"] -= size
        actual["salidas"].append(evento)
        actual["cerrado_utc"] = _campo("timestamp", i)

        tolerancia = max(actual["tamano_abierto"] * 0.005, 1e-9)
        if actual["restante"] <= tolerancia or evento.startswith(_FULL_CLOSE_PREFIXES):
            actual["cerrado"] = True
            actual["restante"] = 0.0

    if actual is not None:
        trades.append(actual)
    return trades


def _bloque_metricas(pnls: list) -> dict:
    """Calcula el bloque de métricas sobre una lista de PnL ya agrupada."""
    ganancias = [p for p in pnls if p > 0]
    perdidas = [p for p in pnls if p < 0]
    n = len(ganancias) + len(perdidas)
    bruto_ganado = float(sum(ganancias))
    bruto_perdido = float(abs(sum(perdidas)))
    media_gana = (bruto_ganado / len(ganancias)) if ganancias else 0.0
    media_pierde = (-bruto_perdido / len(perdidas)) if perdidas else 0.0
    payoff = (media_gana / abs(media_pierde)) if media_pierde else 0.0
    return {
        "closed": n,
        "wins": len(ganancias),
        "losses": len(perdidas),
        "win_rate_pct": round(len(ganancias) / n * 100, 2) if n else 0.0,
        "gross_profit_usdt": round(bruto_ganado, 2),
        "gross_loss_usdt": round(bruto_perdido, 2),
        "profit_factor": (round(bruto_ganado / bruto_perdido, 3) if bruto_perdido > 0
                          else (999.0 if bruto_ganado > 0 else 0.0)),
        "net_pnl_usdt": round(bruto_ganado - bruto_perdido, 2),
        "avg_win_usdt": round(media_gana, 2),
        "avg_loss_usdt": round(media_pierde, 2),
        "payoff_ratio": round(payoff, 3),
        # Con este payoff, el % de aciertos por debajo del cual se pierde dinero.
        "breakeven_win_rate_pct": round(100.0 / (1.0 + payoff), 2) if payoff > 0 else 0.0,
    }


def _compute_trade_metrics(cfg: dict = CONFIG) -> dict:
    """Métricas del journal a DOS niveles.

    Las cifras de cabecera son por TRADE, no por evento. Los TP salen en
    parciales (~30/21/12% de la posición) y los stops se llevan el 100% de
    golpe, así que promediar eventos compara media posición contra posición
    entera y produce un ratio ganancia/pérdida falso. El detalle por salida
    individual sigue disponible bajo la clave `exits`.
    """
    vacio = _bloque_metricas([])
    path = cfg.get("trade_journal_file", TRADE_JOURNAL_FILE)
    if not os.path.exists(path):
        return {
            **vacio,
            "closed_trades": 0,
            "total_events": 0,
            "open_unclosed": 0,
            "exits": dict(vacio),
            "last_updated_utc": datetime.utcnow().isoformat(),
        }

    df = pd.read_csv(path)
    trades = _group_journal_into_trades(df)
    cerrados = [t for t in trades if t["cerrado"]]

    por_trade = _bloque_metricas([t["pnl_usdt"] for t in cerrados])
    por_salida = _bloque_metricas(
        [p for p in pd.to_numeric(df.get("pnl_usdt"), errors="coerce").fillna(0.0).tolist() if p != 0.0]
    )

    return {
        **por_trade,
        "closed_trades": por_trade["closed"],   # nombre heredado, mismo valor
        "total_events": int(len(df)),
        # Trades abiertos que nunca escribieron un cierre: ni ganadores ni
        # perdedores, un agujero en el histórico que hay que ver, no ocultar.
        "open_unclosed": len(trades) - len(cerrados),
        "exits": por_salida,
        "last_updated_utc": datetime.utcnow().isoformat(),
    }


def _save_trade_metrics_snapshot(cfg: dict = CONFIG) -> None:
    metrics = _compute_trade_metrics(cfg)
    path = cfg.get("metrics_file", METRICS_FILE)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(metrics, handle, indent=2)

def save_state(manager) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({
                "active_long":  manager.active_long,
                "active_short": manager.active_short,
                "active_standalone_short": getattr(manager, "active_standalone_short", None),
                "balance":      float(getattr(manager, "balance", 0.0)) if hasattr(manager, "balance") else None,
                "dca_count":    manager.dca_count,
                "tp_count":     manager.tp_count,
                "pending_long":  getattr(manager, "pending_long",  None),
                "pending_short": getattr(manager, "pending_short", None),
            }, f, indent=2)
    except Exception as e:
        logger.warning(f"Error guardando estado: {e}")

def load_state() -> Optional[dict]:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

def send_telegram(message: str, config: dict = CONFIG):
    token = config.get("telegram_token", "")
    chat_id = config.get("telegram_chat_id", "")
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.warning(f"Telegram error: {e}")


def is_session_active(cfg: dict) -> bool:
    """True si la hora UTC actual está dentro de la ventana de alta liquidez.
    Londres abre 07:00 UTC, NY cierra ~20:00 UTC → ventana óptima para trend following."""
    if not cfg.get("session_filter", True):
        return True
    hour  = datetime.utcnow().hour
    start = cfg.get("session_start_utc", 7)
    end   = cfg.get("session_end_utc", 21)
    return start <= hour < end


def get_active_killzone(cfg: dict, now_utc: Optional[datetime] = None) -> Optional[dict]:
    """Devuelve el killzone activo {name, sizing_mult} o None si estamos fuera.

    Combina hora UTC con día de la semana — el sizing final es producto de ambos.
    Soporta ventanas que cruzan medianoche (start > end → wrap).
    Para wrapping: la dow se evalúa contra el día EN EL QUE EMPEZÓ la ventana,
    no contra el día actual (Asia_Open dom 22:00 sigue siendo "domingo" aunque
    a las 02:00 ya sea lunes en UTC).
    """
    if not cfg.get("killzones_enabled", True):
        return {"name": "all_session", "sizing_mult": 1.0}
    now = now_utc or datetime.utcnow()
    hour = now.hour
    dow  = now.weekday()
    dow_mults = cfg.get("dow_multipliers", {})

    for start, end, name, sizing in cfg.get("killzones", []):
        in_window = False
        effective_dow = dow
        if start < end:
            # Ventana normal (ej. 7-10): mismo día
            in_window = start <= hour < end
        else:
            # Ventana cruza medianoche (ej. 22-4)
            if hour >= start:                       # antes de medianoche → día actual
                in_window = True
                effective_dow = dow
            elif hour < end:                        # después de medianoche → día anterior
                in_window = True
                effective_dow = (dow - 1) % 7
        if in_window:
            dow_mult = float(dow_mults.get(effective_dow, 1.0))
            if dow_mult <= 0:
                continue   # buscar siguiente killzone que pueda aplicar
            return {
                "name": name,
                "sizing_mult": float(sizing) * dow_mult,
                "dow_mult":    dow_mult,
                "effective_dow": effective_dow,
            }
    return None


def is_friday_close_time(cfg: dict, now_utc: Optional[datetime] = None) -> bool:
    """True si es viernes a partir de la hora de cierre obligatorio (cerrar todo)."""
    now = now_utc or datetime.utcnow()
    return now.weekday() == 4 and now.hour >= cfg.get("friday_close_hour_utc", 18)


def reset_daily_tracker_if_new_day(current_balance: float) -> None:
    """Reinicia el tracker de P&L diario cuando cambia el día UTC."""
    today = datetime.utcnow().date()
    if _DAILY_TRACKER["date"] != today:
        _DAILY_TRACKER["date"]          = today
        _DAILY_TRACKER["start_balance"] = current_balance
        _DAILY_TRACKER["realized_pnl"]  = 0.0
        _DAILY_TRACKER["paused"]        = False
        logger.info(f"📅 Nuevo día UTC ({today}) — tracker reiniciado | Balance: {current_balance:.2f} USDT")


# ─── CLIENTE EXCHANGE ─────────────────────────────────────────────────────────

def get_exchange(cfg: dict) -> ccxt.Exchange:
    exchange_class = getattr(ccxt, cfg["exchange"])
    paper = cfg.get("paper_trading", True)

    # En paper trading solo necesitamos datos públicos — sin credenciales
    if paper:
        params = {
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        }
        return exchange_class(params)

    # Trading real
    if not cfg.get("api_key") or not cfg.get("secret"):
        raise ValueError(
            "Faltan credenciales. Define JORGE_BOT_API_KEY y JORGE_BOT_API_SECRET o usa paper trading."
        )

    params = {
        "apiKey": cfg["api_key"],
        "secret": cfg["secret"],
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    }
    # set_sandbox_mode está deprecado — sobreescribir todos los grupos de URL directamente
    if cfg.get("testnet") and cfg["exchange"] == "binanceusdm":
        B = "https://testnet.binancefuture.com"
        params["urls"] = {"api": {
            "fapiPublic":    B + "/fapi/v1",
            "fapiPublicV2":  B + "/fapi/v2",
            "fapiPublicV3":  B + "/fapi/v3",
            "fapiPrivate":   B + "/fapi/v1",
            "fapiPrivateV2": B + "/fapi/v2",
            "fapiPrivateV3": B + "/fapi/v3",
            "fapiData":      B + "/futures/data",
            "public":        B + "/api/v3",
            "private":       B + "/api/v3",
        }}
    # Evita llamar al endpoint spot /sapi/v1/capital (bloqueado en algunas regiones)
    params["options"]["fetchCurrencies"] = False
    ex = exchange_class(params)

    # Activar hedge mode para poder tener LONG y SHORT simultáneos
    try:
        ex.fapiPrivatePostPositionSideDual({"dualSidePosition": "true"})
        logger.info("Hedge mode activado")
    except Exception as e:
        logger.info(f"Hedge mode: {e}")

    return ex


# ─── INDICADORES ──────────────────────────────────────────────────────────────

def get_ohlcv(exchange: ccxt.Exchange, symbol: str, timeframe: str,
              limit: int = 300) -> pd.DataFrame:
    # Único punto por el que entran velas al bot: es donde se mide si hay datos.
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    except Exception as e:
        _SALUD["fallos_seguidos"] += 1
        _SALUD["ultimo_error"] = f"{type(e).__name__}: {e}"[:300]
        raise
    _SALUD["ultimo_ok_utc"] = datetime.utcnow().isoformat()
    _SALUD["fallos_seguidos"] = 0
    _SALUD["fetches_ok"] += 1
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    df = _add_all_indicators(df)
    return df


def salud_datos(cfg: dict = CONFIG) -> dict:
    """Cuánto hace que no entra una vela, y si eso ya es ceguera."""
    umbral = float(cfg.get("blind_after_seconds", 900))
    ultimo = _SALUD["ultimo_ok_utc"]
    edad = None
    if ultimo:
        edad = (datetime.utcnow() - datetime.fromisoformat(ultimo)).total_seconds()

    if edad is None:
        estado = "sin_datos" if _SALUD["fallos_seguidos"] else "arrancando"
    elif edad > umbral * 3:
        estado = "ciego"
    elif edad > umbral:
        estado = "viejo"
    else:
        estado = "ok"

    return {
        "estado":          estado,
        "ciego":           estado in ("ciego", "sin_datos"),
        "edad_segundos":   round(edad, 1) if edad is not None else None,
        "ultimo_ok_utc":   ultimo,
        "fallos_seguidos": _SALUD["fallos_seguidos"],
        "fetches_ok":      _SALUD["fetches_ok"],
        "ultimo_error":    _SALUD["ultimo_error"],
    }


def _reconstruir_exchange(exchange: ccxt.Exchange, cfg: dict) -> ccxt.Exchange:
    """Rehace el cliente ccxt después de varios fallos seguidos.

    El cliente se construía una sola vez, fuera del bucle. Cuando la salida de
    la VPN cambiaba, el pool de conexiones keep-alive quedaba muerto y ccxt lo
    seguía reutilizando para siempre: el bot no se recuperaba solo ni cuando la
    red volvía. Así se perdieron 20 días de operativa sin que nada avisara.
    """
    try:
        cerrar = getattr(exchange, "close", None)
        if callable(cerrar):
            cerrar()
    except Exception:
        pass
    logger.warning(
        f"♻️  Reconstruyendo cliente de exchange tras {_SALUD['fallos_seguidos']} fallos seguidos"
    )
    return get_exchange(cfg)


def get_ohlcv_history(exchange: ccxt.Exchange, symbol: str, timeframe: str,
                      candles: int, batch_limit: int = 1000) -> pd.DataFrame:
    """Descarga histórico paginado para backtests más útiles."""
    timeframe_ms = exchange.parse_timeframe(timeframe) * 1000
    chunks: list[list] = []
    remaining = candles
    now_ms = exchange.milliseconds()
    since = now_ms - candles * timeframe_ms

    while remaining > 0:
        batch = min(batch_limit, remaining)
        data = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=batch)
        if not data:
            break
        chunks.extend(data)
        last_ts = data[-1][0]
        since = last_ts + timeframe_ms
        remaining -= len(data)
        if len(data) < batch:
            break

    if not chunks:
        return get_ohlcv(exchange, symbol, timeframe, limit=min(candles, batch_limit))

    df = pd.DataFrame(chunks, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    df = _add_all_indicators(df)
    return df


def _compute_daily_vwap(df: pd.DataFrame) -> pd.Series:
    """Calcula VWAP anclado al inicio del día UTC.

    VWAP = Σ(precio_típico × volumen) / Σ(volumen) acumulado desde 00:00 UTC.
    El precio típico es (H+L+C)/3 — estándar institucional.

    Retorna pd.Series alineada con el index del df (NaN si no hay volumen).
    """
    if df is None or len(df) == 0:
        return pd.Series(dtype=float)
    if not isinstance(df.index, pd.DatetimeIndex):
        return pd.Series(np.nan, index=df.index)

    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["volume"]

    # Agrupar por fecha UTC. Reset cada vez que cambia el día.
    grouper = df.index.normalize()  # trunca a 00:00 UTC
    vwap = pv.groupby(grouper).cumsum() / df["volume"].groupby(grouper).cumsum()
    return vwap


def _add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    h = df["high"]
    lo = df["low"]

    # EMAs principales
    df["ema10"]  = c.ewm(span=10,  adjust=False).mean()
    df["ema55"]  = c.ewm(span=55,  adjust=False).mean()
    df["ema200"] = c.ewm(span=200, adjust=False).mean()
    # EMAs de estructura menor (para confirmar rango vs. cambio)
    df["ema15"] = c.ewm(span=15, adjust=False).mean()
    df["ema30"] = c.ewm(span=30, adjust=False).mean()

    # Compresión EMA10/55
    df["ema_compression"] = (df["ema10"] - df["ema55"]).abs() / df["ema55"]

    # Squeeze Momentum (LazyBear)
    df = _squeeze_momentum(df)

    # ADX (Wilder, período 14)
    df = _adx(df, period=14)

    # Volume
    df["volume_ma20"] = df["volume"].rolling(20).mean()

    # VRVP approx: POC de las últimas 50 velas por precio
    df["vrvp_poc"] = _rolling_poc(df, window=50)

    # Order blocks
    df["ob_bull_high"], df["ob_bull_low"] = _detect_order_blocks(df, direction="bull")
    df["ob_bear_high"], df["ob_bear_low"] = _detect_order_blocks(df, direction="bear")

    # Imbalances (gaps de liquidez)
    df["imbalance_up"]   = (df["low"] > df["high"].shift(1))
    df["imbalance_down"] = (df["high"] < df["low"].shift(1))

    # Toque de EMA55 (cada vez que el precio la cruzó)
    df["touches_ema55"] = _count_ema55_touches(df)

    # SMC — Smart Money Concepts
    df = _detect_smc(df)

    return df


def _detect_smc(df: pd.DataFrame, sweep_lookback: int = 20,
                min_wick_pct: float = 0.0015,
                htf_range_window: int = 20) -> pd.DataFrame:
    """Añade columnas SMC: liquidity sweeps, premium/discount, CHoCH internos.

    sweep_high: True si la vela actual tomó liquidez encima del swing high reciente
                Y cerró DENTRO del rango (mecha barre, cuerpo no confirma) → reversal short
    sweep_low:  True si tomó liquidez debajo del swing low Y cerró dentro → reversal long
    htf_range_pos: posición del precio en el rango HTF [0..1] — 0=mínimo, 1=máximo
    in_premium:    True si htf_range_pos >= 0.7 (top 30%, no abrir longs)
    in_discount:   True si htf_range_pos <= 0.3 (bottom 30%, no abrir shorts)
    choch_bull:    cambio de carácter alcista (LL → HH después de bajada)
    choch_bear:    cambio de carácter bajista (HH → LL después de subida)
    """
    h, l, c = df["high"], df["low"], df["close"]

    # Swing high/low previos (excluyendo la vela actual)
    swing_high = h.rolling(sweep_lookback).max().shift(1)
    swing_low  = l.rolling(sweep_lookback).min().shift(1)

    # Liquidity sweep: la mecha rompe el swing pero el cierre vuelve dentro
    wick_above = (h - swing_high).clip(lower=0)
    wick_below = (swing_low - l).clip(lower=0)
    min_wick   = c * min_wick_pct

    df["sweep_high"] = (h > swing_high) & (c < swing_high) & (wick_above >= min_wick)
    df["sweep_low"]  = (l < swing_low)  & (c > swing_low)  & (wick_below >= min_wick)

    # Sweep "fresco" en últimas 3 velas (para no perder la entrada)
    df["sweep_high_recent"] = df["sweep_high"].rolling(3).max().fillna(0).astype(bool)
    df["sweep_low_recent"]  = df["sweep_low"].rolling(3).max().fillna(0).astype(bool)

    # Premium / Discount basado en el rango de las últimas N velas
    rng_high = h.rolling(htf_range_window).max()
    rng_low  = l.rolling(htf_range_window).min()
    rng_size = (rng_high - rng_low).replace(0, pd.NA)
    df["htf_range_pos"] = ((c - rng_low) / rng_size).fillna(0.5).clip(0, 1)
    df["in_premium"]  = df["htf_range_pos"] >= 0.7
    df["in_discount"] = df["htf_range_pos"] <= 0.3

    # CHoCH simplificado: cambio de carácter en estructura de 3 velas
    # Alcista: vela rompe high de las 2 previas tras venir de mínimos descendentes
    # Bajista: vela rompe low de las 2 previas tras venir de máximos ascendentes
    prev_high2 = h.shift(1).rolling(2).max()
    prev_low2  = l.shift(1).rolling(2).min()
    descending = (l.shift(1) < l.shift(2)) & (l.shift(2) < l.shift(3))
    ascending  = (h.shift(1) > h.shift(2)) & (h.shift(2) > h.shift(3))
    df["choch_bull"] = (h > prev_high2) & descending
    df["choch_bear"] = (l < prev_low2)  & ascending

    # FVG (Fair Value Gap) ya estaba como imbalance_up/down — añadimos persistencia
    df["fvg_up_recent"]   = df["imbalance_up"].rolling(5).max().fillna(0).astype(bool)
    df["fvg_down_recent"] = df["imbalance_down"].rolling(5).max().fillna(0).astype(bool)

    # Régimen de mercado: EXPANSION / TRENDING / RANGING / EXHAUSTION / QUIET
    # Combina ADX (fuerza tendencial) con percentil ATR (volatilidad relativa)
    if "adx" in df.columns:
        atr_now = (h - l).rolling(14).mean()
        atr_pct = atr_now.rolling(50).rank(pct=True)   # percentil 0..1 sobre últimas 50 velas
        adx_v = df["adx"]
        regime = []
        for adx_val, atr_p in zip(adx_v, atr_pct):
            if pd.isna(adx_val) or pd.isna(atr_p):
                regime.append("warmup")
            elif adx_val >= 25 and atr_p >= 0.7:
                regime.append("expansion")    # tendencia fuerte + volatilidad alta = trade limpio
            elif adx_val >= 25:
                regime.append("trending")     # tendencia fuerte, vol normal
            elif atr_p >= 0.85:
                regime.append("exhaustion")   # vol alta sin tendencia = movimientos erráticos, peligro
            elif adx_val < 15 and atr_p < 0.30:
                regime.append("quiet")        # sin tendencia, sin volatilidad → no operar
            else:
                regime.append("ranging")      # vol normal/baja, sin tendencia
        df["regime"]  = regime
        df["atr_pct"] = atr_pct

    # VWAP diario (ancla a inicio UTC) — confluence con HTF para mean reversion
    try:
        df["vwap_daily"]      = _compute_daily_vwap(df)
        df["vwap_dist_pct"]   = (df["close"] - df["vwap_daily"]) / df["vwap_daily"]
    except Exception:
        df["vwap_daily"]      = np.nan
        df["vwap_dist_pct"]   = np.nan

    return df


def _squeeze_momentum(df: pd.DataFrame, bb_len: int = 20,
                       kc_len: int = 20, kc_mult: float = 1.5) -> pd.DataFrame:
    c = df["close"]
    h = df["high"]
    lo = df["low"]

    # Bollinger Bands
    bb_mid = c.rolling(bb_len).mean()
    bb_std = c.rolling(bb_len).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    # True Range y ATR
    prev_c = c.shift(1)
    tr = pd.concat([h - lo, (h - prev_c).abs(), (lo - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.rolling(kc_len).mean()

    # Keltner Channel
    kc_basis = c.ewm(span=kc_len, adjust=False).mean()
    kc_upper = kc_basis + kc_mult * atr
    kc_lower = kc_basis - kc_mult * atr

    # Squeeze ON cuando BB está dentro de KC
    df["sqz_on"]  = (bb_lower > kc_lower) & (bb_upper < kc_upper)
    df["sqz_off"] = (bb_lower < kc_lower) & (bb_upper > kc_upper)
    df["sqz_just_released"] = df["sqz_off"] & ~df["sqz_off"].shift(1).fillna(False)

    # Momentum (regresión lineal del delta de precio)
    hh = h.rolling(kc_len).max()
    ll = lo.rolling(kc_len).min()
    delta = c - ((hh + ll) / 2 + bb_mid) / 2

    # Linreg simplificada con rolling polyfit
    val = delta.rolling(kc_len).apply(
        lambda x: np.polyfit(range(len(x)), x, 1)[0] * (len(x) - 1) + np.polyfit(range(len(x)), x, 1)[1],
        raw=True
    )
    df["sqz_val"] = val

    # Dirección y aceleración
    df["sqz_bullish"]    = val > 0
    df["sqz_increasing"] = val > val.shift(1)

    # Cuadrante: 1=Fuerza Alcista, 2=Impulso Alcista, 3=Fuerza Bajista, 4=Impulso Bajista
    def _quadrant(row):
        v = row["sqz_val"]
        inc = row["sqz_increasing"]
        if pd.isna(v):
            return 0
        if v > 0 and inc:
            return 1   # Verde brillante — Fuerza Alcista (mantener LONG)
        if v > 0 and not inc:
            return 2   # Verde oscuro — Impulso Alcista debilitándose
        if v < 0 and not inc:
            return 3   # Rojo brillante — Fuerza Bajista (mantener SHORT)
        if v < 0 and inc:
            return 4   # Rojo oscuro — Impulso Bajista debilitándose (POSIBLE GIRO)
        return 0

    df["sqz_quadrant"] = df.apply(_quadrant, axis=1)

    # Señal de disparo: squeeze liberado con dirección
    df["sqz_fire_bull"] = df["sqz_just_released"] & (val > 0) & df["sqz_increasing"]
    df["sqz_fire_bear"] = df["sqz_just_released"] & (val < 0) & ~df["sqz_increasing"]

    # "Valle verde toca 0 y no cae" = señal de compra
    df["sqz_valley_buy"] = (
        (val.shift(1) < 0) & (val.shift(1) > val.shift(2)) &
        (val > val.shift(1)) & (val < 0.001)
    )

    return df


def _adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    h = df["high"]
    lo = df["low"]
    c = df["close"]

    tr = pd.concat([h - lo, (h - c.shift(1)).abs(), (lo - c.shift(1)).abs()], axis=1).max(axis=1)
    dm_plus  = pd.Series(np.where((h - h.shift(1)) > (lo.shift(1) - lo),
                                  np.maximum(h - h.shift(1), 0), 0), index=df.index)
    dm_minus = pd.Series(np.where((lo.shift(1) - lo) > (h - h.shift(1)),
                                  np.maximum(lo.shift(1) - lo, 0), 0), index=df.index)

    atr14 = tr.ewm(alpha=1/period, adjust=False).mean()
    di_plus  = 100 * dm_plus.ewm(alpha=1/period, adjust=False).mean() / atr14
    di_minus = 100 * dm_minus.ewm(alpha=1/period, adjust=False).mean() / atr14
    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=1/period, adjust=False).mean()
    df["di_plus"]  = di_plus
    df["di_minus"] = di_minus

    # Tendencia definida cuando ADX >= 21
    df["adx_trend"] = df["adx"] >= 21
    df["adx_bull"]  = (di_plus > di_minus) & (df["adx"] >= 21)
    df["adx_bear"]  = (di_minus > di_plus) & (df["adx"] >= 21)
    # Tendencia fuerte cuando ADX >= 25 (mayor convicción de entrada)
    df["adx_strong_bull"] = (di_plus > di_minus) & (df["adx"] >= 25)
    df["adx_strong_bear"] = (di_minus > di_plus) & (df["adx"] >= 25)

    return df


def _rolling_poc(df: pd.DataFrame, window: int = 50) -> pd.Series:
    """Aproxima el POC del perfil de volumen en una ventana rodante."""
    poc = pd.Series(index=df.index, dtype=float)
    for i in range(window, len(df)):
        sub = df.iloc[i - window:i]
        prices = np.linspace(sub["low"].min(), sub["high"].max(), 50)
        vol_by_price = np.zeros(50)
        for _, row in sub.iterrows():
            mask = (prices >= row["low"]) & (prices <= row["high"])
            if mask.any():
                vol_by_price[mask] += row["volume"] / mask.sum()
        poc.iloc[i] = prices[np.argmax(vol_by_price)]
    return poc


def _detect_order_blocks(df: pd.DataFrame, direction: str = "bull",
                          lookback: int = 5) -> tuple:
    """
    Detecta Order Blocks (última vela opuesta antes de movimiento impulsivo).
    Bull OB: última vela bajista antes de impulso alcista fuerte.
    Bear OB: última vela alcista antes de impulso bajista fuerte.
    Retorna (high series, low series) del OB más reciente activo.
    """
    n = len(df)
    ob_high = pd.Series(np.nan, index=df.index)
    ob_low  = pd.Series(np.nan, index=df.index)

    for i in range(lookback + 3, n):
        if direction == "bull":
            # Buscar vela bajista seguida de 3 velas alcistas fuertes
            if (df["close"].iloc[i - lookback] < df["open"].iloc[i - lookback] and
                    all(df["close"].iloc[i - j] > df["open"].iloc[i - j] for j in range(1, 4)) and
                    df["close"].iloc[i - 1] > df["high"].iloc[i - lookback]):
                ob_high.iloc[i] = df["high"].iloc[i - lookback]
                ob_low.iloc[i]  = df["low"].iloc[i - lookback]
        else:
            # Buscar vela alcista seguida de 3 velas bajistas fuertes
            if (df["close"].iloc[i - lookback] > df["open"].iloc[i - lookback] and
                    all(df["close"].iloc[i - j] < df["open"].iloc[i - j] for j in range(1, 4)) and
                    df["close"].iloc[i - 1] < df["low"].iloc[i - lookback]):
                ob_high.iloc[i] = df["high"].iloc[i - lookback]
                ob_low.iloc[i]  = df["low"].iloc[i - lookback]

    # Propagar el último OB activo hacia adelante (virgen = no tocado)
    ob_high = ob_high.ffill()
    ob_low  = ob_low.ffill()
    return ob_high, ob_low


def _count_ema55_touches(df: pd.DataFrame, tol: float = 0.005) -> pd.Series:
    """
    Cuenta toques acumulados de la EMA55 en ventana de 50 velas.
    Un toque es cuando el precio está dentro del ±tol% de la EMA55.
    """
    is_touch = ((df["close"] - df["ema55"]).abs() / df["ema55"]) < tol
    return is_touch.rolling(50).sum()


# ─── SEÑALES — LOS 10 ARGUMENTOS ──────────────────────────────────────────────

def count_candles_since_cross(df: pd.DataFrame, lookback: int = 30) -> int:
    """Velas transcurridas desde el último cruce alcista EMA10/EMA55."""
    sub = df.tail(lookback).reset_index(drop=True)
    cross_idx = None
    for i in range(1, len(sub)):
        if sub["ema10"].iloc[i - 1] <= sub["ema55"].iloc[i - 1] and \
           sub["ema10"].iloc[i] > sub["ema55"].iloc[i]:
            cross_idx = i
    return (len(sub) - cross_idx) if cross_idx is not None else 0


def check_sr_level(df: pd.DataFrame, tolerance: float = 0.01) -> bool:
    """
    Verifica si el precio está en un nivel S/R fuerte (zona de reacción histórica).
    Simple: ¿el precio está cerca de un máximo/mínimo de las últimas 20 velas?
    """
    last_price = df["close"].iloc[-1]
    recent = df.tail(20)
    key_high = recent["high"].max()
    key_low  = recent["low"].min()
    near_high = abs(last_price - key_high) / key_high < tolerance
    near_low  = abs(last_price - key_low)  / key_low  < tolerance
    return near_high or near_low


def check_ob_virgin(df: pd.DataFrame, tolerance: float = 0.008) -> tuple:
    """
    ¿El precio está cerca de un OB alcista virginal?
    Retorna (bool, zone_type) donde zone_type es 'bull' o 'bear'.
    """
    last = df.iloc[-1]
    price = last["close"]

    if not np.isnan(last["ob_bull_low"]) and not np.isnan(last["ob_bull_high"]):
        mid = (last["ob_bull_high"] + last["ob_bull_low"]) / 2
        if abs(price - mid) / mid < tolerance:
            return True, "bull"

    if not np.isnan(last["ob_bear_low"]) and not np.isnan(last["ob_bear_high"]):
        mid = (last["ob_bear_high"] + last["ob_bear_low"]) / 2
        if abs(price - mid) / mid < tolerance:
            return True, "bear"

    return False, None


def check_liquidity_zone(df: pd.DataFrame) -> bool:
    """
    El precio está cerca de una zona de liquidez (cerca del POC del VRVP approx).
    """
    last = df.iloc[-1]
    if np.isnan(last["vrvp_poc"]):
        return False
    dist = abs(last["close"] - last["vrvp_poc"]) / last["vrvp_poc"]
    return dist < 0.015


def check_12_candle_theory(df: pd.DataFrame) -> dict:
    """
    Evalúa la teoría de las 12 velas según la estrategia del mentor.
    Zona óptima: velas 5-8. Vela 7 = entrada ideal.
    Entrada tardía válida: velas 10-11 si EMA10 está aplanándose (precio ya sobre ambas EMAs).
    Vela 12+ sin superar resistencia = compresión fallida → SHORT.
    """
    count = count_candles_since_cross(df)

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last
    ema10_flat = abs(last["ema10"] - prev["ema10"]) / (prev["ema10"] or 1) < 0.001
    price_above_both_emas = last["close"] > last["ema10"] and last["close"] > last["ema55"]

    # Zona óptima: 5-8; entrada tardía válida: 10-11 con EMA10 plana y precio sobre EMAs
    late_entry    = (10 <= count <= 11) and ema10_flat and price_above_both_emas
    in_entry_zone = (5 <= count <= 8) or late_entry
    near_candle_7 = 6 <= count <= 8
    compression_failed = count >= 12 and check_ema_trend_str(df) == "bearish"

    return {
        "count": count,
        "in_entry_zone": in_entry_zone,
        "near_candle_7": near_candle_7,
        "late_entry": late_entry,
        "compression_failed": compression_failed,
    }


def check_breakout_imbalance(df: pd.DataFrame) -> bool:
    """
    ¿Hay un imbalance reciente que el precio está rellenando o una ruptura activa?
    """
    last = df.iloc[-1]
    recent = df.tail(5)
    has_imbalance = recent["imbalance_up"].any() or recent["imbalance_down"].any()
    return bool(has_imbalance)


def check_ema55_touch_rule(df: pd.DataFrame) -> dict:
    """
    Regla del 3er/4to toque de EMA55.
    3 toques anteriores → la resistencia se debilita.
    4to toque → LONG directo (ya es soporte).
    """
    raw_touches = df["touches_ema55"].iloc[-1]
    touches = 0 if pd.isna(raw_touches) else int(raw_touches)
    third_touch_weakened  = touches >= 3
    fourth_touch_long     = touches >= 4
    return {
        "touches": touches,
        "third_touch_weakened": third_touch_weakened,
        "fourth_touch_long": fourth_touch_long,
    }


def check_volume_signal(df: pd.DataFrame, mult: float = 1.5) -> dict:
    """
    Análisis de volumen según los principios de Jorge.
    Incluye: absorción, volumen de parada (stop candle), subida sin volumen.
    """
    last = df.iloc[-1]
    vol_ratio = last["volume"] / last["volume_ma20"] if last["volume_ma20"] > 0 else 1

    body = abs(last["close"] - last["open"])
    candle_range = last["high"] - last["low"]
    wick_pct = (candle_range - body) / candle_range if candle_range > 0 else 0

    high_volume      = vol_ratio > mult
    absorption       = wick_pct > 0.4 and high_volume  # Mecha larga + alto volumen
    bull_without_vol = last["close"] > last["open"] and vol_ratio < 0.8  # Subida sin volumen = trampa

    # Volumen de Parada (Stop Candle): primera vela con volumen elevado después de caída
    # "El volumen de parada lo ven en la primera vela, paso seguido comienza a hacer rango"
    stop_candle = False
    if len(df) >= 4:
        prev3 = df.iloc[-4:-1]
        # Las 3 velas anteriores deben ser bajistas (caída sostenida)
        all_prev_bearish = all(prev3["close"] < prev3["open"])
        # La vela actual tiene volumen alto, independientemente de dirección
        stop_candle = all_prev_bearish and high_volume

    return {
        "vol_ratio": round(vol_ratio, 2),
        "high_volume": high_volume,
        "absorption": absorption,
        "bull_without_vol": bull_without_vol,
        "stop_candle": stop_candle,  # Primera vela alta-vol después de caída = señal de suelo
    }


def check_ema_conditions(df: pd.DataFrame, cfg: dict) -> dict:
    """
    Evaluación completa de las condiciones de EMAs (argumento 9).
    """
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last

    trend = check_ema_trend_str(df)
    is_compressed  = last["ema_compression"] < cfg["compression_threshold_pct"]
    not_overextended = (
        abs(last["close"] - last["ema10"]) / last["ema10"]
        < cfg["max_price_ema10_distance_pct"]
    )
    near_ema55 = (
        abs(last["close"] - last["ema55"]) / last["ema55"]
        < cfg["ema55_touch_tolerance"]
    )

    # Inclinación: EMA10 sube o baja
    ema10_rising = last["ema10"] > prev["ema10"]
    ema10_flat   = abs(last["ema10"] - prev["ema10"]) / prev["ema10"] < 0.0005

    # Cruce fresco (ocurrió en las últimas 3 velas)
    recent = df.tail(3)
    bullish_cross = any(
        recent["ema10"].iloc[i - 1] <= recent["ema55"].iloc[i - 1]
        and recent["ema10"].iloc[i] > recent["ema55"].iloc[i]
        for i in range(1, len(recent))
    )

    # Pequeños picos: precio entre EMA10 y EMA55 con wicksito sobre EMA55
    small_peak_over_ema55 = (
        last["high"] > last["ema55"]
        and last["close"] < last["ema55"]
        and last["close"] > last["ema10"]
    )

    return {
        "trend": trend,
        "is_bullish": trend == "bullish",
        "is_compressed": is_compressed,
        "not_overextended": not_overextended,
        "near_ema55": near_ema55,
        "ema10_rising": ema10_rising,
        "ema10_flat": ema10_flat,
        "bullish_cross": bullish_cross,
        "small_peak_over_ema55": small_peak_over_ema55,
    }


def check_multi_tf_confirmation(df_macro: pd.DataFrame, df_mid: pd.DataFrame,
                                 df_entry: pd.DataFrame) -> dict:
    """
    Argumento 10: OB virgen en marco mayor, refinado en menor.
    Sincronización de estructura en los 3 timeframes.
    """
    macro_bull = check_ema_trend_str(df_macro) == "bullish"
    mid_bull   = check_ema_trend_str(df_mid)   == "bullish"
    entry_bull = check_ema_trend_str(df_entry) == "bullish"

    # EMA15/30 confirma estructura en timeframe de entrada
    last_entry = df_entry.iloc[-1]
    structure_bull = last_entry["ema15"] > last_entry["ema30"]

    all_aligned = macro_bull and mid_bull and entry_bull
    strong_alignment = all_aligned and structure_bull

    # Squeeze confirma en ambos timeframes
    sqz_mid   = df_mid.iloc[-1]["sqz_bullish"]
    sqz_entry = df_entry.iloc[-1]["sqz_bullish"]
    squeeze_confirmation = bool(sqz_mid and sqz_entry)

    return {
        "macro_bull": macro_bull,
        "mid_bull": mid_bull,
        "entry_bull": entry_bull,
        "structure_bull": structure_bull,
        "all_aligned": all_aligned,
        "strong_alignment": strong_alignment,
        "squeeze_confirmation": squeeze_confirmation,
    }


def check_ema_trend_str(df: pd.DataFrame) -> str:
    last = df.iloc[-1]
    if last["ema10"] > last["ema55"]:
        return "bullish"
    if last["ema10"] < last["ema55"]:
        return "bearish"
    return "neutral"


# ─── DETECTOR DE RUPTURA ESTRUCTURAL (escenario excepcional Jorge 80% capital) ──

def detect_structural_break(df_mid: pd.DataFrame, df_macro: pd.DataFrame,
                            df_entry: pd.DataFrame, cfg: dict) -> dict:
    """Detecta ruptura estructural bajista→alcista según las 4 condiciones de Jorge:

    1. Cierre de vela 4H/1D POR ENCIMA del máximo previo (no solo mecha)
    2. Volumen alto en vela de ruptura (≥ 1.5× promedio 20 velas)
    3. OB virgen o soporte cercano valida el nivel
    4. EMA10 > EMA55 en timeframe inmediato superior (4H si rompemos en 1D)

    Cita Jorge: "Entrar con 80% del capital de futuros (excepcional vs el 20% normal)"
                "TP: cerrar 90-95% en el primer +30-50% de ganancia"

    Returns dict con:
      - detected (bool): si se cumplen todas las condiciones
      - side: "long" (Jorge solo opera rupturas alcistas)
      - confidence: 0..1 score basado en cuántas condiciones se cumplen
      - reasons: lista de razones (debugging)
    """
    result = {"detected": False, "side": "long", "confidence": 0.0, "reasons": []}

    if df_mid is None or len(df_mid) < 25:
        result["reasons"].append("df_mid insufficient")
        return result

    last = df_mid.iloc[-1]
    prev = df_mid.iloc[-2]

    # 1. Cierre de vela 4H sobre máximo previo (rolling 20 velas)
    high_lookback = df_mid["high"].iloc[-21:-1]   # excluye la vela actual
    prev_max = float(high_lookback.max())
    cond1 = float(last["close"]) > prev_max
    if cond1:
        result["confidence"] += 0.30
        result["reasons"].append(f"close {last['close']:.2f} > prev_max {prev_max:.2f}")

    # 2. Volumen alto en vela de ruptura
    vol_avg_20 = float(df_mid["volume"].iloc[-21:-1].mean())
    vol_now = float(last["volume"])
    cond2 = vol_now >= vol_avg_20 * 1.5
    if cond2:
        result["confidence"] += 0.25
        result["reasons"].append(f"vol {vol_now:.0f} >= 1.5x avg {vol_avg_20:.0f}")

    # 3. OB virgen activo (en df_mid, los OB están calculados)
    cond3 = False
    try:
        ob_low = last.get("ob_bull_low")
        ob_high = last.get("ob_bull_high")
        if ob_low is not None and ob_high is not None and not pd.isna(ob_low) and not pd.isna(ob_high):
            # OB activo válido si el precio actual está cerca o por encima
            close = float(last["close"])
            cond3 = close >= float(ob_low) * 0.98   # tolerancia 2%
            if cond3:
                result["confidence"] += 0.20
                result["reasons"].append(f"OB bull virgen [{ob_low:.2f}-{ob_high:.2f}] valida")
    except Exception:
        pass

    # 4. EMA10 > EMA55 en df_macro (timeframe inmediato superior al de ruptura)
    cond4 = False
    if df_macro is not None and len(df_macro) > 0:
        try:
            macro_last = df_macro.iloc[-1]
            ema10 = float(macro_last.get("ema10", 0))
            ema55 = float(macro_last.get("ema55", 0))
            if ema10 > ema55 > 0:
                cond4 = True
                result["confidence"] += 0.25
                result["reasons"].append(f"EMA10 {ema10:.2f} > EMA55 {ema55:.2f} en macro")
        except Exception:
            pass

    # Detección: requiere 3 de 4 condiciones (confidence >= 0.7)
    # OR las 2 críticas (cierre + volumen) + 1 de las 2 secundarias (OB o EMA)
    critical_2 = cond1 and cond2
    secondary_any = cond3 or cond4
    result["detected"] = (result["confidence"] >= 0.70) or (critical_2 and secondary_any)

    return result


# ─── FUNDING RATE AWARENESS ──────────────────────────────────────────────────

def fetch_funding_rate_history(exchange, symbol: str, limit: int = 200) -> pd.DataFrame:
    """Descarga histórico de funding rate (Binance Futures: cada 8h).

    Retorna DataFrame con index = timestamp, columna 'funding_rate'.
    Si falla (sandbox, exchange no soportado), retorna DataFrame vacío.
    """
    try:
        # ccxt unified method (cuando disponible) o fallback al endpoint nativo
        if hasattr(exchange, "fapiPublicGetFundingRate"):
            raw = exchange.fapiPublicGetFundingRate({"symbol": symbol.replace("/", "").replace(":USDT", ""), "limit": limit})
            rows = [(int(r["fundingTime"]), float(r["fundingRate"])) for r in raw]
        else:
            raw = exchange.fetch_funding_rate_history(symbol, limit=limit)
            rows = [(int(r["timestamp"]), float(r["fundingRate"])) for r in raw]
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["timestamp", "funding_rate"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df
    except Exception as e:
        logger.debug(f"fetch_funding_rate: {e}")
        return pd.DataFrame()


def classify_funding_state(funding_value: float, cfg: dict) -> str:
    """Clasifica funding rate en: 'long_loaded' | 'short_loaded' | 'neutral'."""
    if funding_value is None or pd.isna(funding_value):
        return "neutral"
    if funding_value >= cfg.get("funding_extreme_long", 0.0005):
        return "long_loaded"
    if funding_value <= cfg.get("funding_extreme_short", -0.0003):
        return "short_loaded"
    return "neutral"


def compute_funding_sizing(funding_state: str, cfg: dict) -> tuple:
    """Retorna (long_mult, short_mult) según el estado del funding."""
    long_mult, short_mult = 1.0, 1.0
    if funding_state == "long_loaded":
        # Longs sobre-apalancados → cascada de liquidación likely → favor SHORT
        long_mult  = float(cfg.get("funding_long_penalty", 0.6))
        short_mult = float(cfg.get("funding_short_boost",  1.2))
    elif funding_state == "short_loaded":
        # Shorts sobre-apalancados → squeeze likely → favor LONG
        long_mult  = float(cfg.get("funding_long_boost",   1.2))
        short_mult = float(cfg.get("funding_short_penalty", 0.6))
    return long_mult, short_mult


# ─── MACRO BIAS 1W ────────────────────────────────────────────────────────────

def compute_macro_high_bias(df_weekly: pd.DataFrame, cfg: dict) -> dict:
    """Calcula el bias macro semanal: bullish/bearish/neutral basado en EMA21W.

    Returns dict con:
      - bias: "bullish" | "bearish" | "neutral"
      - ema_value: float
      - price: float
      - distance_pct: % del precio respecto a EMA (positivo = arriba, negativo = abajo)
      - ema_slope: dirección de la pendiente de EMA21W (+ rising / - falling / 0 flat)
    """
    period = int(cfg.get("macro_high_ema_period", 21))
    min_candles = int(cfg.get("macro_high_min_candles", 50))

    if df_weekly is None or len(df_weekly) < min_candles:
        return {"bias": "neutral", "reason": "insufficient_data"}

    close = df_weekly["close"]
    ema = close.ewm(span=period, adjust=False).mean()
    if pd.isna(ema.iloc[-1]):
        return {"bias": "neutral", "reason": "ema_nan"}

    price = float(close.iloc[-1])
    ema_val = float(ema.iloc[-1])
    distance_pct = (price - ema_val) / ema_val

    # Pendiente: comparar EMA hace 4 velas (1 mes) vs ahora
    slope_lookback = min(4, len(ema) - 1)
    ema_prev = float(ema.iloc[-slope_lookback - 1])
    slope = (ema_val - ema_prev) / ema_prev   # positivo = rising

    # Reglas de bias:
    # - bullish: precio arriba de EMA + EMA rising (ambas condiciones)
    # - bearish: precio debajo de EMA + EMA falling
    # - neutral: cualquier mix
    if distance_pct > 0 and slope > 0:
        bias = "bullish"
    elif distance_pct < 0 and slope < 0:
        bias = "bearish"
    else:
        bias = "neutral"

    return {
        "bias": bias,
        "ema_value": ema_val,
        "price": price,
        "distance_pct": float(distance_pct),
        "ema_slope": float(slope),
    }


# ─── STOP DINÁMICO ────────────────────────────────────────────────────────────

def compute_dynamic_stop(df_entry: pd.DataFrame, side: str,
                         entry_price: float, cfg: dict,
                         tp1_pct: Optional[float] = None) -> float:
    """Calcula stop dinámico: swing low/high reciente + buffer ATR, clamped por max/min %.

    Long: stop = min(swing_low - ATR×k, entry × (1 - max_pct))
          luego min en absoluto a entry × (1 - min_pct) para no ser demasiado ajustado.
    Short: análogo invertido (swing high + buffer arriba).

    Si tp1_pct se provee, max_pct se ajusta a max(tp1_pct × 2.5, min_pct × 2)
    para garantizar R/R mínimo razonable (no arriesgar 12% para ganar 0.8%).

    Retorna precio absoluto del stop. Si los datos son insuficientes, fallback a
    entry × (1 ∓ hard_stop_pct) — comportamiento legacy.
    """
    lookback = int(cfg.get("dynamic_stop_lookback", 10))
    atr_mult = float(cfg.get("dynamic_stop_atr_mult", 1.0))
    atr_period = int(cfg.get("dynamic_stop_atr_period", 14))
    max_pct = float(cfg.get("dynamic_stop_max_pct", 0.06))
    min_pct = float(cfg.get("dynamic_stop_min_pct", 0.015))
    fallback_pct = abs(float(cfg.get("hard_stop_pct", -0.06)))

    # Si tenemos TP1 del régimen actual, ajustar max_pct para mantener R/R razonable
    if tp1_pct is not None and tp1_pct > 0:
        rr_max = float(tp1_pct) * 2.5     # arriesgar máximo 2.5x el TP1
        max_pct = min(max_pct, rr_max)
        # Pero no bajar de min_pct × 1.5 para no ahogar el trade
        max_pct = max(max_pct, min_pct * 1.5)

    if df_entry is None or len(df_entry) < max(lookback, atr_period) + 1:
        return entry_price * (1 - fallback_pct) if side == "long" else entry_price * (1 + fallback_pct)

    recent = df_entry.tail(lookback)
    # ATR aproximado: True Range medio en últimas atr_period velas
    h = df_entry["high"].tail(atr_period)
    l = df_entry["low"].tail(atr_period)
    c_prev = df_entry["close"].shift(1).tail(atr_period)
    tr = pd.concat([(h - l), (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)
    atr = float(tr.mean())
    if not np.isfinite(atr) or atr <= 0:
        atr = float((h - l).mean())

    if side == "long":
        swing_low = float(recent["low"].min())
        stop = swing_low - atr * atr_mult
        max_stop = entry_price * (1 - min_pct)   # tope superior del stop (más cerca de entry)
        min_stop = entry_price * (1 - max_pct)   # tope inferior (más lejos)
        stop = max(min(stop, max_stop), min_stop)
    else:  # short
        swing_high = float(recent["high"].max())
        stop = swing_high + atr * atr_mult
        min_stop = entry_price * (1 + min_pct)
        max_stop = entry_price * (1 + max_pct)
        stop = min(max(stop, min_stop), max_stop)

    return float(stop)


# ─── EVALUADOR DE SEÑAL PRINCIPAL ─────────────────────────────────────────────

def evaluate_signal(df_macro: pd.DataFrame, df_mid: pd.DataFrame,
                    df_entry: pd.DataFrame, cfg: dict,
                    df_weekly: Optional[pd.DataFrame] = None,
                    df_funding: Optional[pd.DataFrame] = None,
                    current_ts=None) -> dict:
    """
    Evalúa los 10 ARGUMENTOS y retorna el análisis completo.
    Score de 0 a 10; cada argumento vale 1 punto.

    df_weekly: opcional, para el bias macro 1W (Fase 1).
    df_funding: opcional, histórico de funding rate (Fase 3).
    current_ts: timestamp del momento de evaluación (para slicing del funding histórico).
    """
    tf_conf   = check_multi_tf_confirmation(df_macro, df_mid, df_entry)
    sr        = check_sr_level(df_mid)
    ob_active, ob_type = check_ob_virgin(df_mid, cfg["ob_zone_tolerance"])
    liquidity = check_liquidity_zone(df_mid)
    candle12  = check_12_candle_theory(df_mid)
    breakout  = check_breakout_imbalance(df_entry)
    touch_rule = check_ema55_touch_rule(df_mid)
    vol       = check_volume_signal(df_entry, cfg["volume_spike_mult"])
    ema       = check_ema_conditions(df_mid, cfg)
    adx_last  = df_mid.iloc[-1]

    mid_last = df_mid.iloc[-1]

    # ── Los 10 argumentos como bool ──────────────────────────────────────────
    # A8: Jorge dice que los institucionales OCULTAN volumen (suben "sin volumen visible")
    # Por eso A8 solo penaliza si no hay absorción NI volumen alto — no bloquea por subida limpia
    args = {
        "A1_graficos_sincronizados": tf_conf["all_aligned"],
        "A2_soporte_resistencia":    sr,
        "A3_ob_virgen_zona":         ob_active,
        "A4_liquidez":               liquidity,
        "A5_teoria_12_velas":        candle12["in_entry_zone"],
        "A6_ruptura_imbalance":      breakout,
        "A7_regla_3er_4to_toque":    touch_rule["third_touch_weakened"],
        "A8_volumen_absorcion":       vol["high_volume"] or vol["absorption"] or vol["stop_candle"],
        "A9_emas_condiciones":       ema["is_bullish"] and ema["is_compressed"] and ema["not_overextended"],
        "A10_confirmacion_multi_tf": tf_conf["strong_alignment"] and tf_conf["squeeze_confirmation"],
    }

    score = sum(1 for v in args.values() if v)

    # can_long: condiciones estructurales mínimas (el score y los filtros se aplican en run_bot)
    can_long = (
        score >= cfg["min_score_to_enter"]
        and ema["is_bullish"]
        and not candle12["compression_failed"]
    )
    high_conviction = score >= cfg["high_conviction_score"]

    # Tipo de entrada — basado en calidad de la señal
    entry_type = "none"
    squeeze_valley_buy = bool(df_entry.iloc[-1]["sqz_valley_buy"])
    squeeze_fired      = bool(mid_last["sqz_fire_bull"])
    squeeze_on         = bool(mid_last["sqz_on"])
    if can_long:
        # Tipo A: Máxima convicción — requiere ADX >= 25 (fuerte), vela 7, compresión y OB
        if (candle12["near_candle_7"] and ema["is_compressed"] and ob_active
                and bool(adx_last.get("adx_strong_bull", False))):
            entry_type = "A"
        # Tipo B: Alta convicción — squeeze disparado o valle comprador con ADX alcista
        elif adx_last["adx_bull"] and (
            tf_conf["squeeze_confirmation"] or squeeze_fired or squeeze_valley_buy
        ):
            entry_type = "B"
        else:
            entry_type = "C"   # Cauteloso: score mínimo, sin squeeze disparado

    # ── SMC: sweeps, premium/discount, CHoCH ────────────────────────────────
    entry_last = df_entry.iloc[-1]
    smc = {
        "sweep_high_recent": bool(entry_last.get("sweep_high_recent", False)),
        "sweep_low_recent":  bool(entry_last.get("sweep_low_recent", False)),
        "in_premium_mid":    bool(mid_last.get("in_premium", False)),
        "in_discount_mid":   bool(mid_last.get("in_discount", False)),
        "htf_range_pos":     float(mid_last.get("htf_range_pos", 0.5)),
        "choch_bull":        bool(entry_last.get("choch_bull", False)),
        "choch_bear":        bool(entry_last.get("choch_bear", False)),
        "fvg_up_recent":     bool(entry_last.get("fvg_up_recent", False)),
        "fvg_down_recent":   bool(entry_last.get("fvg_down_recent", False)),
    }

    # Bonus SMC al score long (penalizan/bonifican según contexto institucional)
    smc_long_bonus = 0
    if smc["in_discount_mid"]:        smc_long_bonus += 1   # comprar en discount
    if smc["sweep_low_recent"]:       smc_long_bonus += 1   # liquidez barrida abajo → reversal
    if smc["choch_bull"]:             smc_long_bonus += 1   # cambio de carácter alcista
    if smc["in_premium_mid"]:         smc_long_bonus -= 2   # NO comprar en premium HTF
    score_long_adjusted = score + smc_long_bonus
    can_long = (
        score_long_adjusted >= cfg["min_score_to_enter"]
        and ema["is_bullish"]
        and not candle12["compression_failed"]
        and not smc["in_premium_mid"]   # bloqueo duro: no longs en premium
    )
    high_conviction = score_long_adjusted >= cfg["high_conviction_score"]

    # ── EVALUACIÓN LADO SHORT (mirror del long) ─────────────────────────────
    bearish_macro = check_ema_trend_str(df_macro) == "bearish"
    bearish_mid   = not ema["is_bullish"]   # ema10 < ema55 en mid
    short_args = {
        "S1_macro_bajista":      bearish_macro,
        "S2_sr_resistencia":     sr,    # reusamos S/R activo
        "S3_ob_bajista_zona":    (ob_type == "bear") if ob_active else False,
        "S4_liquidez":           liquidity,
        "S5_compression_fail":   bool(candle12["compression_failed"]),
        "S6_fvg_bajista":        smc["fvg_down_recent"],
        "S7_volumen_distribucion": vol["high_volume"] and not vol["bull_without_vol"],
        "S8_squeeze_bajista":    bool(mid_last["sqz_fire_bear"]) or int(mid_last["sqz_quadrant"]) in (3, 4),
        "S9_emas_bajistas":      bearish_mid,
        "S10_adx_bear":          bool(adx_last["adx_bear"]),
    }
    score_short = sum(1 for v in short_args.values() if v)
    smc_short_bonus = 0
    if smc["in_premium_mid"]:    smc_short_bonus += 1
    if smc["sweep_high_recent"]: smc_short_bonus += 1
    if smc["choch_bear"]:        smc_short_bonus += 1
    if smc["in_discount_mid"]:   smc_short_bonus -= 2
    score_short_adj = score_short + smc_short_bonus
    can_short_standalone = (
        cfg.get("shorts_enabled", True)
        and score_short_adj >= cfg.get("min_score_short", 7)
        and bearish_mid
        and bool(adx_last["adx_bear"])
        and not smc["in_discount_mid"]   # bloqueo duro: no shorts en discount
    )

    # Tipo de short: A = sweep + CHoCH + premium, B = bearish completo, C = mínimo
    short_entry_type = "none"
    if can_short_standalone:
        if smc["sweep_high_recent"] and smc["choch_bear"] and smc["in_premium_mid"]:
            short_entry_type = "A_sweep"
        elif bearish_macro and bool(mid_last["sqz_fire_bear"]):
            short_entry_type = "B_squeeze"
        else:
            short_entry_type = "C"

    # Señal SHORT como cobertura del long activo (lógica original — se mantiene)
    can_short = (
        (bearish_macro or candle12["compression_failed"])
        and int(mid_last["sqz_quadrant"]) in (3, 4)
        and adx_last["adx_bear"]
    )

    # Condiciones especiales de compra
    fourth_touch_long  = touch_rule["fourth_touch_long"]

    # Alerta de distribución: máximos más bajos + múltiples toques a EMA10 → inminente caída
    distribution_warning = (
        touch_rule["touches"] >= 5
        and not ema["ema10_rising"]
        and vol["bull_without_vol"]
    )

    sig = {
        "score": score,
        "score_adjusted": score_long_adjusted,
        "smc_long_bonus": smc_long_bonus,
        "total": len(args),
        "can_long": can_long,
        "can_short": can_short,
        "can_short_standalone": can_short_standalone,
        "score_short": score_short,
        "score_short_adjusted": score_short_adj,
        "short_entry_type": short_entry_type,
        "short_arguments": short_args,
        "smc": smc,
        "high_conviction": high_conviction,
        "entry_type": entry_type,
        "arguments": args,
        "candle_count": candle12["count"],
        "candle12": candle12,
        "ema": ema,
        "volume": vol,
        "adx": {
            "value":       round(float(adx_last["adx"] or 0), 1),
            "bull":        bool(adx_last["adx_bull"]),
            "bear":        bool(adx_last["adx_bear"]),
            "trend":       bool(adx_last["adx_trend"]),
            "strong_bull": bool(adx_last.get("adx_strong_bull", False)),   # ADX >= 25
        },
        "squeeze_fired":        squeeze_fired,
        "squeeze_valley_buy":   squeeze_valley_buy,
        "squeeze_on":           squeeze_on,
        "fourth_touch_long":    fourth_touch_long,
        "distribution_warning": distribution_warning,
        "ob_type":    ob_type,
        "touch_count": touch_rule["touches"],
        "tf_sync":    tf_conf,
        "current_price": float(df_entry.iloc[-1]["close"]),
        "ema55_mid":  float(mid_last["ema55"]),
        "ema55_entry": float(df_entry.iloc[-1]["ema55"]),
        "regime":     str(mid_last.get("regime", "unknown")),
        "atr_pct":    float(mid_last.get("atr_pct", 0.5) or 0.5),
    }

    # Stop dinámico precomputado v7 (sin ajuste R/R que rompe el calibration)
    _cp = float(df_entry.iloc[-1]["close"])
    try:
        sig["dynamic_stop_long"]  = compute_dynamic_stop(df_entry, "long",  _cp, cfg)
        sig["dynamic_stop_short"] = compute_dynamic_stop(df_entry, "short", _cp, cfg)
    except Exception:
        sig["dynamic_stop_long"]  = None
        sig["dynamic_stop_short"] = None

    # ── Macro bias 1W (Fase 1: modulador de sizing, NO bloqueo hard) ─────────
    # El backtest mostró que bloquear contra-tendencia hard elimina rebotes
    # técnicos válidos. En su lugar, modulamos sizing:
    # - Trade a favor del bias: sizing × 1.0
    # - Trade contra bias con HTF en extremo (discount profundo / premium extremo): × 0.6
    # - Trade contra bias sin HTF extremo: × 0.3 (no bloqueo, pero size mínimo)
    macro_bias_info = {"bias": "neutral", "reason": "disabled"}
    macro_long_mult, macro_short_mult = 1.0, 1.0
    if cfg.get("macro_high_enabled", True) and df_weekly is not None:
        try:
            macro_bias_info = compute_macro_high_bias(df_weekly, cfg)
            bias = macro_bias_info.get("bias", "neutral")
            htf_pos = smc.get("htf_range_pos", 0.5) if isinstance(smc, dict) else 0.5

            if bias == "bullish":
                # longs en bias bullish: sizing full
                macro_long_mult = 1.0
                # shorts en bias bullish: only OK si HTF en premium extremo
                if htf_pos >= 0.80:
                    macro_short_mult = 0.6   # tomas de ganancia técnicas
                else:
                    macro_short_mult = 0.3   # contra-tendencia sin contexto extremo
            elif bias == "bearish":
                # shorts en bias bearish: sizing full
                macro_short_mult = 1.0
                # longs en bias bearish: only OK si HTF en discount extremo (rebote técnico)
                if htf_pos <= 0.20:
                    macro_long_mult = 0.6
                else:
                    macro_long_mult = 0.3
            # neutral: ambos full
        except Exception as e:
            logger.debug(f"macro_bias error: {e}")

    sig["macro_high_bias"]      = macro_bias_info.get("bias", "neutral")
    sig["macro_high_info"]      = macro_bias_info
    sig["macro_long_sizing"]    = macro_long_mult
    sig["macro_short_sizing"]   = macro_short_mult
    # Compatibilidad con código existente — ya no bloqueamos hard
    sig["block_long_macro"]     = False
    sig["block_short_macro"]    = False

    # ── Fase 3: Funding rate awareness ───────────────────────────────────────
    funding_state = "neutral"
    funding_val   = None
    funding_long_mult, funding_short_mult = 1.0, 1.0
    if cfg.get("funding_aware_enabled", True) and df_funding is not None and len(df_funding) > 0:
        try:
            if current_ts is not None:
                # backtest: slice del funding histórico hasta el ts actual
                df_f_slice = df_funding[df_funding.index <= current_ts]
                if len(df_f_slice) > 0:
                    funding_val = float(df_f_slice["funding_rate"].iloc[-1])
            else:
                # live: último valor del funding
                funding_val = float(df_funding["funding_rate"].iloc[-1])
            if funding_val is not None:
                funding_state = classify_funding_state(funding_val, cfg)
                funding_long_mult, funding_short_mult = compute_funding_sizing(funding_state, cfg)
        except Exception as e:
            logger.debug(f"funding eval: {e}")
    sig["funding_rate"]         = funding_val
    sig["funding_state"]        = funding_state
    sig["funding_long_sizing"]  = funding_long_mult
    sig["funding_short_sizing"] = funding_short_mult

    # ── VWAP confluence ─────────────────────────────────────────────────────
    # LONG con confluencia: precio igual/abajo del VWAP → mean reversion alcista
    # SHORT con confluencia: precio igual/arriba del VWAP → mean reversion bajista
    # Chase (precio muy lejos del VWAP en la dirección que vamos a comprar) → penalty
    vwap_long_mult, vwap_short_mult = 1.0, 1.0
    vwap_dist = None
    if cfg.get("vwap_aware_enabled", True):
        try:
            vwap_dist_raw = df_entry.iloc[-1].get("vwap_dist_pct") if hasattr(df_entry.iloc[-1], "get") else None
            if vwap_dist_raw is not None and not pd.isna(vwap_dist_raw):
                vwap_dist = float(vwap_dist_raw)
                prox = float(cfg.get("vwap_proximity_pct", 0.005))
                boost = float(cfg.get("vwap_confluence_boost", 1.15))
                penalty = float(cfg.get("vwap_chase_penalty", 0.80))

                if vwap_dist <= -prox:        # Precio bajo VWAP → confluencia LONG, chase SHORT
                    vwap_long_mult  = boost
                    vwap_short_mult = penalty
                elif vwap_dist >= prox:       # Precio sobre VWAP → confluencia SHORT, chase LONG
                    vwap_long_mult  = penalty
                    vwap_short_mult = boost
                # En zona neutral (|dist| < prox): ambos × 1.0
        except Exception as e:
            logger.debug(f"vwap eval: {e}")
    sig["vwap_dist_pct"]      = vwap_dist
    sig["vwap_long_sizing"]   = vwap_long_mult
    sig["vwap_short_sizing"]  = vwap_short_mult

    # ── Detector de RUPTURA ESTRUCTURAL (Jorge: 80% capital, TPs cortos) ────
    structural_break = {"detected": False}
    if cfg.get("structural_break_enabled", True):
        try:
            structural_break = detect_structural_break(df_mid, df_macro, df_entry, cfg)
        except Exception as e:
            logger.debug(f"structural_break: {e}")
    sig["structural_break"] = structural_break

    return sig


def format_signal_report(sig: dict, symbol: str) -> str:
    args = sig["arguments"]
    ema  = sig["ema"]
    adx  = sig["adx"]
    vol  = sig["volume"]

    lines = [
        f"<b>📊 ANÁLISIS — {symbol}</b>",
        f"Precio: <b>{sig['current_price']:.2f}</b>",
        f"Score: <b>{sig['score']}/{sig['total']}</b>",
        f"Tendencia: {ema['trend'].upper()} | ADX: {adx['value']} ({'Tendencia' if adx['trend'] else 'Sin tendencia'})",
        f"Vela {sig['candle_count']} del conteo | Toque EMA55: #{sig['touch_count']}",
        f"",
        f"<b>Argumentos:</b>",
    ]
    for k, v in args.items():
        icon = "✅" if v else "❌"
        name = k[3:].replace("_", " ")
        lines.append(f"  {icon} {name}")

    if sig["can_long"]:
        lines.append(f"")
        lines.append(f"🟢 <b>SEÑAL LONG</b> — Tipo {sig['entry_type']}")
        if sig["high_conviction"]:
            lines.append(f"⭐ ALTA CONVICCIÓN — Entrar tamaño completo")
    elif sig["can_short"]:
        lines.append(f"")
        lines.append(f"🔴 <b>SEÑAL SHORT / COBERTURA</b>")

    if sig["squeeze_fired"]:
        lines.append(f"⚡ SQUEEZE LIBERADO ALCISTA")
    if sig["squeeze_valley_buy"]:
        lines.append(f"🟡 VALLE SQUEEZE TOCA CERO → Señal compra")
    if sig["fourth_touch_long"]:
        prefix = "🔁 4TO TOQUE EMA55" if sig["can_long"] else "ℹ️ 4TO TOQUE EMA55"
        suffix = "→ Entrada directa LONG" if sig["can_long"] else "detectado, pero sin filtro completo"
        lines.append(f"{prefix} {suffix}")
    if sig.get("squeeze_on") and not sig["can_long"]:
        lines.append(f"🔵 Squeeze ON — acumulando, aún no disparó")
    if sig.get("distribution_warning"):
        lines.append(f"⚠️ ALERTA DISTRIBUCIÓN — toques excesivos EMA10 + subida sin volumen")
    if sig.get("candle12", {}).get("late_entry"):
        lines.append(f"🕐 Entrada tardía válida: vela {sig['candle_count']} con EMA10 plana")
    if sig.get("volume", {}).get("stop_candle"):
        lines.append(f"🛑 VOLUMEN DE PARADA — primera vela alta-vol post-caída → posible suelo")

    return "\n".join(lines)


# ─── PAPER TRADING (simulación sin órdenes reales) ───────────────────────────

class PaperPositionManager:
    """Simula todas las operaciones localmente. Usa datos reales de mercado."""

    def __init__(self, config: dict):
        self.cfg    = config
        self.symbol = config["symbol"]

        self.balance        = float(config["total_capital_usdt"])
        self.active_long:  Optional[dict] = None
        self.active_short: Optional[dict] = None              # cobertura del long (hedge)
        self.active_standalone_short: Optional[dict] = None   # short independiente (SMC)
        self.pending_long:  Optional[dict] = None             # orden límite anticipada en OB virgen
        self.pending_short: Optional[dict] = None
        self.dca_count  = 0
        self.tp_count   = 0
        self.trade_log  = []
        self._paper_tag = "[PAPER]"
        self._last_price: Optional[float] = None   # se actualiza con la primera lectura de mercado

        # Cargar estado previo (posiciones, balance, pendientes) si existe
        state = load_state()
        if state:
            self.active_long              = state.get("active_long")
            self.active_short             = state.get("active_short")
            self.active_standalone_short  = state.get("active_standalone_short")
            self.pending_long             = state.get("pending_long")
            self.pending_short            = state.get("pending_short")
            self.dca_count                = state.get("dca_count", 0)
            self.tp_count                 = state.get("tp_count", 0)
            saved_balance = state.get("balance")
            if saved_balance is not None:
                self.balance = float(saved_balance)
            logger.info(f"{self._paper_tag} Estado previo cargado | "
                        f"balance: {self.balance:.2f} | "
                        f"long: {'sí' if self.active_long else 'no'} | "
                        f"short: {'sí' if self.active_standalone_short else 'no'} | "
                        f"pending: L={'sí' if self.pending_long else 'no'} S={'sí' if self.pending_short else 'no'}")

    def get_positions(self) -> dict:
        result = {"long": None, "short": None}
        if self.active_long:
            result["long"] = {"contracts": self.active_long["size"], "side": "long"}
        if self.active_short:
            result["short"] = {"contracts": self.active_short["size"], "side": "short"}
        return result

    def get_balance(self) -> float:
        """Balance líquido (sin contar margen comprometido ni unrealized)."""
        return self.balance

    def _journal(self, event: dict, sig: Optional[dict] = None) -> None:
        """Wrapper sobre _append_trade_journal que infiere pos según event['side']."""
        side = event.get("side")
        pos = None
        if side == "long":
            pos = self.active_long
        elif side == "short":
            pos = self.active_standalone_short or self.active_short
        _append_trade_journal(event, self.cfg, sig=sig, pos=pos)

    def get_equity(self, current_price: Optional[float] = None) -> float:
        """Equity = balance líquido + margen comprometido + unrealized PnL.

        Es el equivalente del 'wallet balance' que un exchange real reporta:
        el valor que tendrías si cerraras todas las posiciones al precio actual.
        Si no hay precio disponible (primer ciclo tras restart), retorna solo
        balance + cost (asume posiciones en breakeven).
        """
        equity = float(self.balance)
        price = current_price if current_price is not None else self._last_price

        if self.active_long:
            cost = float(self.active_long.get("cost", 0))
            equity += cost
            if price is not None:
                size = float(self.active_long.get("size", 0))
                entry = float(self.active_long.get("entry_price", price))
                equity += size * (price - entry)

        if self.active_standalone_short:
            cost = float(self.active_standalone_short.get("cost", 0))
            equity += cost
            if price is not None:
                size = float(self.active_standalone_short.get("size", 0))
                entry = float(self.active_standalone_short.get("entry_price", price))
                equity += size * (entry - price)

        if self.active_short and price is not None:   # hedge — sin cost guardado
            size = float(self.active_short.get("size", 0))
            entry = float(self.active_short.get("entry_price", price))
            equity += size * (entry - price)

        return equity

    def _order_size(self, price: float) -> float:
        # COMPOUND: usa equity actual (balance líquido + margen + unrealized) en vez del
        # capital inicial estático. Esto hace que las ganancias se compongan: cuando el
        # balance crece, el tamaño de la próxima posición también crece proporcionalmente.
        # En racha negativa, el sizing baja → reduce drawdown peak natural.
        try:
            capital = self.get_equity()
        except Exception:
            capital = self.balance
        risk = capital * self.cfg["risk_capital_pct"]
        part = risk / self.cfg["position_parts"]
        return round((part * self.cfg["leverage"]) / price, 6)

    def open_long(self, price: float, sig: dict):
        size = self._order_size(price)
        if sig["high_conviction"] and sig["entry_type"] == "A":
            size *= 1.5
        # RUPTURA ESTRUCTURAL: Jorge entra con 80% del capital (4× sizing normal)
        sb = sig.get("structural_break") or {}
        if sb.get("detected"):
            size *= float(self.cfg.get("structural_break_sizing", 4.0))
            logger.info(f"{self._paper_tag} 🚀 RUPTURA ESTRUCTURAL detectada — sizing × {self.cfg.get('structural_break_sizing',4.0)} "
                        f"({', '.join(sb.get('reasons',[]))[:120]})")
        # Sizing combinado killzone × adaptativo, calculado en run_bot
        size *= sig.get("_final_sizing", 1.0)
        size = round(size, 6)
        cost = (size * price) / self.cfg["leverage"]
        self.balance -= cost
        # Stop dinámico (calculado en evaluate_signal). Fallback al estático si está deshabilitado.
        stop_price = None
        if self.cfg.get("dynamic_stop_enabled", True) and sig.get("dynamic_stop_long") is not None:
            stop_price = float(sig["dynamic_stop_long"])

        # Régimen al abrir → snapshot de TPs específicos para este trade
        regime = sig.get("regime", "warmup")
        regime_tps = self.cfg.get("regime_tps", {}).get(regime) if self.cfg.get("regime_aware_enabled", True) else None
        # Si es ruptura estructural, los TPs de ruptura tienen prioridad
        if (sig.get("structural_break") or {}).get("detected"):
            regime_tps = self.cfg.get("structural_break_tps", regime_tps)
            regime = "structural_break"

        self.active_long = {
            "entry_price": price,
            "size": size,
            "cost": cost,
            "dca_done": [],
            "tp_done": [],
            "entry_time": datetime.now().isoformat(),
            "entry_ts":   time.time(),                       # para duration_minutes
            "score": sig["score"],
            "entry_type": sig["entry_type"],
            "mae_pct": 0.0,                                  # peor punto durante el trade
            "mfe_pct": 0.0,                                  # mejor punto durante el trade
            "stop_price": stop_price,                        # None = usa hard_stop_pct legacy
            "regime_at_entry": regime,
            "regime_tps":      regime_tps,                   # None → usa TPs del CONFIG global
            "is_structural_break": bool((sig.get("structural_break") or {}).get("detected")),
        }
        self.dca_count = 0
        msg = (f"{self._paper_tag} ✅ LONG ABIERTO | {self.symbol}\n"
               f"Precio: {price:.2f} | Tamaño: {size:.6f} BTC\n"
               f"Tipo: {sig['entry_type']} | Score: {sig['score']}/10\n"
               f"Balance restante: {self.balance:.2f} USDT")
        logger.info(msg)
        _append_trade_journal({
            "event": "open_long",
            "side": "long",
            "price": price,
            "size": size,
            "margin_used": round(cost, 2),
            "balance": round(self.balance, 2),
            "entry_type": sig["entry_type"],
            "killzone": sig.get("killzone", "n/a"),
            "dow":      sig.get("_dow_override"),
            "note": f"adapt={sig.get('_adapt_mult',1.0):.2f}",
        }, self.cfg, sig=sig)
        _save_trade_metrics_snapshot(self.cfg)
        self.trade_log.append({"event": "open_long", "price": price, "size": size, "time": datetime.now().isoformat()})
        send_telegram(msg, self.cfg)
        return True

    def manage_long(self, current_price: float, df_mid, sig: dict = None, df_entry=None):
        if not self.active_long:
            return
        entry = self.active_long["entry_price"]
        pnl   = (current_price - entry) / entry

        # MAE/MFE tracking (peor y mejor punto del trade)
        self.active_long["mae_pct"] = min(self.active_long.get("mae_pct", 0.0), pnl * 100)
        self.active_long["mfe_pct"] = max(self.active_long.get("mfe_pct", 0.0), pnl * 100)

        # Stop check: dinámico si existe, sino fallback a hard_stop_pct fijo
        stop_price = self.active_long.get("stop_price")
        if self.cfg.get("enable_hard_stop", True) and (
            (stop_price is not None and current_price <= stop_price)
            or (stop_price is None and pnl <= self.cfg.get("hard_stop_pct", -0.06))
        ):
            close_size = self.active_long["size"]
            # Separar margen prorrateado de ganancia/pérdida real para journal correcto
            margin_part = close_size * entry / self.cfg["leverage"]
            real_pnl    = close_size * (current_price - entry)
            recovered   = margin_part + real_pnl
            self.balance += max(recovered, 0)
            # Diferenciar lock_exit (post-TP3 con ganancia) de hard_stop real (pérdida)
            event_name = "hard_stop" if real_pnl < 0 else "lock_exit"
            msg = (f"{self._paper_tag} ❌ HARD STOP | {self.symbol}\n"
                   f"Precio: {current_price:.2f} | PnL: {pnl*100:.1f}%\n"
                   f"Salida defensiva activada para proteger capital.") if real_pnl < 0 else (
                   f"{self._paper_tag} 🔒 LOCK EXIT | {self.symbol}\n"
                   f"Precio: {current_price:.2f} | Stop runner activado | Ganancia: +{real_pnl:.2f}")
            logger.info(msg)
            _append_trade_journal({
                "event": event_name,
                "side": "long",
                "price": current_price,
                "size": close_size,
                "pnl_pct": round(pnl * 100, 2),
                "pnl_usdt": round(real_pnl, 2),
                "balance": round(self.balance, 2),
            }, self.cfg, sig=sig, pos=self.active_long)
            _save_trade_metrics_snapshot(self.cfg)
            send_telegram(msg, self.cfg)
            self.trade_log.append({"event": "hard_stop", "price": current_price, "pnl_pct": round(pnl * 100, 2)})
            self.active_long = None
            return

        # DCA — tamaños doblan en cada nivel (fuente: Excel AUT LONG patrón doblante)
        multipliers = self.cfg.get("dca_size_multipliers", [1, 1, 1, 1])
        for i, level in enumerate(self.cfg["dca_levels_pct"]):
            if pnl <= level and i not in self.active_long["dca_done"]:
                mult = multipliers[i] if i < len(multipliers) else 1.0
                size = round(self._order_size(current_price) * mult, 6)
                cost = (size * current_price) / self.cfg["leverage"]
                self.balance -= cost
                self.active_long["dca_done"].append(i)
                self.active_long["size"] += size
                self.active_long["cost"] += cost
                total_size = self.active_long["size"]
                self.active_long["entry_price"] = (
                    (entry * (total_size - size) + current_price * size) / total_size
                )
                self.dca_count += 1
                msg = (f"{self._paper_tag} 🔄 DCA #{self.dca_count} ({mult}x) | {self.symbol}\n"
                       f"Precio: {current_price:.2f} | Caída: {pnl*100:.1f}%\n"
                       f"Precio prom: {self.active_long['entry_price']:.2f}")
                logger.info(msg)
                _append_trade_journal({
                    "event": f"dca_{self.dca_count}",
                    "side": "long",
                    "price": current_price,
                    "size": size,
                    "margin_used": round(cost, 2),
                    "pnl_pct": round(pnl * 100, 2),
                    "balance": round(self.balance, 2),
                    "note": f"mult={mult}",
                }, self.cfg)
                _save_trade_metrics_snapshot(self.cfg)
                send_telegram(msg, self.cfg)

        # TP parciales — cálculo correcto de ganancia para futuros con apalancamiento
        # Fórmula: margen_devuelto + PnL_realizado
        # = close_size × entry/leverage + close_size × (current_price - entry)
        lev = self.cfg["leverage"]
        # Fase 2: usar TPs específicos del régimen al entrar (snapshot al open)
        regime_tps = self.active_long.get("regime_tps")
        if regime_tps:
            tp_levels = [
                (regime_tps["tp1_pct"], regime_tps["tp1_close"]),
                (regime_tps["tp2_pct"], regime_tps["tp2_close"]),
                (regime_tps["tp3_pct"], regime_tps["tp3_close"]),
            ]
        else:
            tp_levels = [
                (self.cfg["tp1_pct"], self.cfg.get("tp1_close_pct", 0.30)),
                (self.cfg["tp2_pct"], self.cfg.get("tp2_close_pct", 0.30)),
                (self.cfg["tp3_pct"], self.cfg.get("tp3_close_pct", 0.25)),
            ]
        for i, (tp_pct, close_pct) in enumerate(tp_levels):
            if pnl >= tp_pct and i not in self.active_long["tp_done"]:
                close_size = self.active_long["size"] * close_pct
                # Separar margen devuelto (no es ganancia) de ganancia real
                margin_returned = close_size * entry / lev
                real_pnl        = close_size * (current_price - entry)
                self.balance   += margin_returned + real_pnl
                self.active_long["size"] -= close_size
                self.active_long["tp_done"].append(i)
                self.tp_count += 1

                # Stop progression: TP2 → breakeven, TP3 → TP2 price (lock profit del runner)
                if i == 1:   # TP2
                    self.active_long["stop_price"] = float(entry)
                    logger.info(f"{self._paper_tag} 🔒 Stop movido a breakeven ({entry:.2f}) post-TP2")
                elif i == 2:  # TP3
                    tp2_pct_used = regime_tps["tp2_pct"] if regime_tps else self.cfg["tp2_pct"]
                    tp2_price = float(entry * (1 + tp2_pct_used))
                    self.active_long["stop_price"] = tp2_price
                    logger.info(f"{self._paper_tag} 🔒 Stop movido a TP2 ({tp2_price:.2f}) post-TP3 — runner activo")

                margin_ret_pct = round(pnl * lev * 100, 1)
                msg = (f"{self._paper_tag} 💰 TP{i+1} | {self.symbol}\n"
                       f"Precio: {current_price:.2f} | +{pnl*100:.1f}% precio (+{margin_ret_pct}%/margen)\n"
                       f"Cerrado: {int(close_pct*100)}% | Ganancia: +{real_pnl:.2f} USDT | Balance: {self.balance:.2f} USDT")
                logger.info(msg)
                _append_trade_journal({
                    "event": f"tp{i+1}",
                    "side": "long",
                    "price": current_price,
                    "size": close_size,
                    "pnl_pct": round(pnl * 100, 2),
                    "pnl_usdt": round(real_pnl, 2),
                    "balance": round(self.balance, 2),
                }, self.cfg, sig=sig, pos=self.active_long)
                _save_trade_metrics_snapshot(self.cfg)
                send_telegram(msg, self.cfg)
                self.trade_log.append({"event": f"tp{i+1}", "price": current_price,
                                        "pnl_pct": round(pnl*100, 2), "gain_usdt": round(real_pnl, 2)})

        # ── Runner post-TP3: trail dinámico ATR — solo sube, nunca baja
        if (self.active_long and 2 in self.active_long.get("tp_done", [])
                and df_entry is not None and len(df_entry) >= 14):
            # Trail buffer del régimen al entrar (más amplio en expansion, ajustado en ranging)
            tr_mult = float(regime_tps["trail_atr"]) if regime_tps else float(self.cfg.get("runner_trail_atr_mult", 2.0))
            recent_h = df_entry["high"].tail(14)
            recent_l = df_entry["low"].tail(14)
            atr = float((recent_h - recent_l).mean())
            trail_candidate = float(current_price - atr * tr_mult)
            current_stop = float(self.active_long.get("stop_price") or 0)
            if trail_candidate > current_stop:
                self.active_long["stop_price"] = trail_candidate

        # ── Trail post-TP1 (NUEVA lógica): si squeeze cambia, MUEVE stop a entry (no cierra)
        # Esto evita cortar ganadores prematuramente — el stop dinámico hace el resto.
        if (self.active_long
                and self.cfg.get("trailing_stop_after_tp1", True)
                and 0 in self.active_long.get("tp_done", [])
                and 1 not in self.active_long.get("tp_done", [])       # aún no TP2
                and not bool(df_mid.iloc[-1]["adx_bull"])
                and float(self.active_long.get("stop_price") or 0) < entry):
            self.active_long["stop_price"] = float(entry)
            logger.info(f"{self._paper_tag} 🔒 Trail post-TP1: stop movido a entry ({entry:.2f}) — ADX debilitado")

        # ── Trailing stop legacy (fallback): solo si dynamic_stop_enabled=False
        if (not self.cfg.get("dynamic_stop_enabled", True)
                and self.active_long
                and self.cfg.get("trailing_stop_after_tp1", True)
                and 0 in self.active_long.get("tp_done", [])
                and pnl < self.cfg.get("trailing_stop_entry_pct", -0.015)
                and not bool(df_mid.iloc[-1]["adx_bull"])):
            close_size = self.active_long["size"]
            recovered = close_size * entry / lev + close_size * (current_price - entry)
            self.balance += max(recovered, 0)
            msg = (f"{self._paper_tag} 🛑 TRAILING STOP POST-TP1 | {self.symbol}\n"
                   f"TP1 alcanzado, precio cayó {pnl*100:.1f}% bajo entrada promedio\n"
                   f"ADX dejó de ser alcista → cierre protector | Balance: {self.balance:.2f} USDT")
            logger.info(msg)
            _append_trade_journal({
                "event": "trailing_stop",
                "side": "long",
                "price": current_price,
                "size": close_size,
                "pnl_pct": round(pnl * 100, 2),
                "pnl_usdt": round(max(recovered, 0) - close_size * entry / lev, 2),
                "balance": round(self.balance, 2),
            }, self.cfg, sig=sig, pos=self.active_long)
            _save_trade_metrics_snapshot(self.cfg)
            send_telegram(msg, self.cfg)
            self.trade_log.append({"event": "trailing_stop", "price": current_price, "pnl_pct": round(pnl*100, 2)})
            self.active_long = None

    def should_hedge(self, current_price: float, df_mid, sig: dict) -> bool:
        if not self.cfg.get("hedge_enabled", False):
            return False
        if not self.active_long or self.active_short:
            return False
        entry = self.active_long["entry_price"]
        pnl   = (current_price - entry) / entry
        if pnl > self.cfg["hedge_loss_trigger_pct"]:
            return False
        compression_failed = sig["candle12"]["compression_failed"]
        mid_bearish = check_ema_trend_str(df_mid) == "bearish"
        sqz_bearish = int(df_mid.iloc[-1]["sqz_quadrant"]) in (3, 4)
        return compression_failed or (mid_bearish and sqz_bearish)

    def open_hedge(self, price: float):
        if not self.cfg.get("hedge_enabled", False) or self.active_short:
            return
        # Fuente: "si tu long es de 100 USD, la cobertura debe ser de 200" → 2x el LONG
        hedge_mult = self.cfg.get("hedge_size_multiplier", 2.0)
        size = round(self._order_size(price) * hedge_mult, 6)
        self.active_short = {
            "entry_price": price,
            "size": size,
            "initial_size": size,
            "entry_time": datetime.now().isoformat(),
            "partial_closed": False,
        }
        msg = (f"{self._paper_tag} 🛡️ COBERTURA SHORT ({hedge_mult}x) | {self.symbol}\n"
               f"Precio: {price:.2f} | Tamaño: {size:.6f} BTC\n"
               f"Long en pérdida -20% → cobertura activa")
        logger.info(msg)
        _append_trade_journal({
            "event": "open_hedge",
            "side": "short",
            "price": price,
            "size": size,
            "note": f"mult={hedge_mult}",
        }, self.cfg)
        _save_trade_metrics_snapshot(self.cfg)
        send_telegram(msg, self.cfg)

    def manage_hedge(self, current_price: float, df_mid):
        if not self.active_short:
            return
        entry = self.active_short["entry_price"]
        gain  = (entry - current_price) / entry
        sqz_bullish = bool(df_mid.iloc[-1]["sqz_fire_bull"])
        partial_pct = self.cfg.get("hedge_partial_pct", 0.80)

        # Cierre parcial 80%: "cobra 80% de lo que entre"
        if (gain >= self.cfg["hedge_close_gain_pct"]
                and not self.active_short.get("partial_closed")):
            close_size = self.active_short["size"] * partial_pct
            hedge_profit = close_size * entry * gain / self.cfg["leverage"]
            self.balance += hedge_profit
            self.active_short["size"] -= close_size
            self.active_short["partial_closed"] = True
            msg = (f"{self._paper_tag} 💰 COBERTURA PARCIAL ({int(partial_pct*100)}%) | {self.symbol}\n"
                   f"SHORT: {entry:.2f} → {current_price:.2f} | +{gain*100:.1f}%\n"
                   f"20% restante sigue corriendo | Balance: {self.balance:.2f} USDT")
            logger.info(msg)
            _append_trade_journal({
                "event": "hedge_partial",
                "side": "short",
                "price": current_price,
                "size": close_size,
                "pnl_pct": round(gain * 100, 2),
                "pnl_usdt": round(hedge_profit, 2),
                "balance": round(self.balance, 2),
            }, self.cfg)
            _save_trade_metrics_snapshot(self.cfg)
            send_telegram(msg, self.cfg)

        # Cierre total del 20% restante cuando squeeze vuelve alcista
        elif self.active_short.get("partial_closed") and sqz_bullish:
            hedge_profit = self.active_short["size"] * entry * gain / self.cfg["leverage"]
            self.balance += hedge_profit
            msg = (f"{self._paper_tag} 🔓 COBERTURA CERRADA (restante) | {self.symbol}\n"
                   f"Squeeze alcista detectado | Ganancia: +{gain*100:.1f}%\n"
                   f"Balance: {self.balance:.2f} USDT")
            logger.info(msg)
            _append_trade_journal({
                "event": "hedge_close",
                "side": "short",
                "price": current_price,
                "size": self.active_short["size"],
                "pnl_pct": round(gain * 100, 2),
                "pnl_usdt": round(hedge_profit, 2),
                "balance": round(self.balance, 2),
            }, self.cfg)
            _save_trade_metrics_snapshot(self.cfg)
            send_telegram(msg, self.cfg)
            self.active_short = None

        # Cierre forzado si squeeze alcista desde el inicio (sin haber hecho parcial)
        elif not self.active_short.get("partial_closed") and sqz_bullish and gain > 0:
            hedge_profit = self.active_short["size"] * entry * gain / self.cfg["leverage"]
            self.balance += hedge_profit
            msg = (f"{self._paper_tag} 🔓 COBERTURA CERRADA | {self.symbol}\n"
                   f"Squeeze alcista | +{gain*100:.1f}% | Balance: {self.balance:.2f} USDT")
            logger.info(msg)
            _append_trade_journal({
                "event": "hedge_force_close",
                "side": "short",
                "price": current_price,
                "size": self.active_short["size"],
                "pnl_pct": round(gain * 100, 2),
                "pnl_usdt": round(hedge_profit, 2),
                "balance": round(self.balance, 2),
            }, self.cfg)
            _save_trade_metrics_snapshot(self.cfg)
            send_telegram(msg, self.cfg)
            self.active_short = None

    # ─── STANDALONE SHORT (operación independiente, no es cobertura) ─────────
    def open_short_standalone(self, price: float, sig: dict, sizing_mult: float = 1.0):
        """Abre una posición SHORT independiente basada en setup bajista (SMC + score short)."""
        if self.active_standalone_short:
            return False
        size = self._order_size(price) * sizing_mult
        if sig.get("short_entry_type") == "A_sweep":
            size *= 1.3
        size = round(size, 6)
        cost = (size * price) / self.cfg["leverage"]
        self.balance -= cost
        stop_price = None
        if self.cfg.get("dynamic_stop_enabled", True) and sig.get("dynamic_stop_short") is not None:
            stop_price = float(sig["dynamic_stop_short"])

        regime = sig.get("regime", "warmup")
        regime_tps = self.cfg.get("regime_tps", {}).get(regime) if self.cfg.get("regime_aware_enabled", True) else None

        self.active_standalone_short = {
            "entry_price": price,
            "size": size,
            "cost": cost,
            "dca_done": [],
            "tp_done": [],
            "entry_time": datetime.now().isoformat(),
            "entry_ts":   time.time(),
            "score": sig.get("score_short_adjusted", sig.get("score_short", 0)),
            "entry_type": sig.get("short_entry_type", "C"),
            "killzone": sig.get("killzone", "n/a"),
            "mae_pct": 0.0,
            "mfe_pct": 0.0,
            "stop_price": stop_price,
            "regime_at_entry": regime,
            "regime_tps":      regime_tps,
        }
        msg = (f"{self._paper_tag} 🔻 SHORT ABIERTO | {self.symbol}\n"
               f"Precio: {price:.2f} | Tamaño: {size:.6f}\n"
               f"Tipo: {sig.get('short_entry_type','?')} | Score: {sig.get('score_short_adjusted','?')}/10\n"
               f"Killzone: {sig.get('killzone','n/a')} | Sizing: {sizing_mult:.2f}x\n"
               f"Balance restante: {self.balance:.2f} USDT")
        logger.info(msg)
        _append_trade_journal({
            "event": "open_short_standalone",
            "side": "short",
            "price": price,
            "size": size,
            "margin_used": round(cost, 2),
            "balance": round(self.balance, 2),
            "entry_type": sig.get("short_entry_type", "C"),
            "killzone": sig.get("killzone", "n/a"),
            "dow":      sig.get("_dow_override"),
            "note": f"sizing={sizing_mult:.2f}",
        }, self.cfg, sig=sig)
        _save_trade_metrics_snapshot(self.cfg)
        send_telegram(msg, self.cfg)
        return True

    def manage_short_standalone(self, current_price: float, df_mid, sig: dict = None):
        """Gestiona DCA + TPs + hard stop + trailing del SHORT standalone (mirror del long)."""
        pos = self.active_standalone_short
        if not pos:
            return
        entry = pos["entry_price"]
        # Para SHORT: ganancia = (entry - current) / entry
        gain = (entry - current_price) / entry
        lev = self.cfg["leverage"]

        # MAE/MFE tracking (peor y mejor punto del trade)
        pos["mae_pct"] = min(pos.get("mae_pct", 0.0), gain * 100)
        pos["mfe_pct"] = max(pos.get("mfe_pct", 0.0), gain * 100)

        # Hard stop: precio subió mucho → cierre defensivo (dinámico si disponible)
        stop_price = pos.get("stop_price")
        if self.cfg.get("enable_hard_stop", True) and (
            (stop_price is not None and current_price >= stop_price)
            or (stop_price is None and gain <= self.cfg.get("hard_stop_pct", -0.06))
        ):
            close_size = pos["size"]
            margin_part = close_size * entry / lev
            real_pnl    = close_size * (entry - current_price)
            recovered   = margin_part + real_pnl
            self.balance += max(recovered, 0)
            # Diferenciar: es "lock profit exit" (post-TP3) si real_pnl >= 0, sino hard stop real
            event_name = "hard_stop_short" if real_pnl < 0 else "lock_exit_short"
            msg = (f"{self._paper_tag} ❌ HARD STOP SHORT | {self.symbol}\n"
                   f"Precio: {current_price:.2f} | Pérdida: {gain*100:.1f}%") if real_pnl < 0 else (
                   f"{self._paper_tag} 🔒 LOCK EXIT SHORT | {self.symbol}\n"
                   f"Precio: {current_price:.2f} | Stop runner activado | Ganancia: +{real_pnl:.2f}")
            logger.info(msg)
            _append_trade_journal({
                "event": event_name, "side": "short",
                "price": current_price, "size": close_size,
                "pnl_pct": round(gain * 100, 2),
                "pnl_usdt": round(real_pnl, 2),
                "balance": round(self.balance, 2),
            }, self.cfg, sig=sig, pos=pos)
            _save_trade_metrics_snapshot(self.cfg)
            send_telegram(msg, self.cfg)
            self.active_standalone_short = None
            return

        # DCA invertido — si precio sube contra nosotros, añadimos en niveles más altos
        multipliers = self.cfg.get("dca_size_multipliers", [1, 1, 1, 1])
        # Reusamos los mismos niveles del long pero invertidos: -0.015 → +0.015
        for i, neg_level in enumerate(self.cfg["dca_levels_pct"]):
            level = -neg_level   # convertir a positivo (precio subió)
            adverse_pct = (current_price - entry) / entry  # cuánto subió contra el short
            if adverse_pct >= level and i not in pos["dca_done"]:
                mult = multipliers[i] if i < len(multipliers) else 1.0
                size = round(self._order_size(current_price) * mult, 6)
                cost = (size * current_price) / lev
                self.balance -= cost
                pos["dca_done"].append(i)
                pos["size"] += size
                pos["cost"] += cost
                total = pos["size"]
                pos["entry_price"] = (entry * (total - size) + current_price * size) / total
                msg = (f"{self._paper_tag} 🔄 DCA SHORT #{i+1} ({mult}x) | {self.symbol}\n"
                       f"Precio: {current_price:.2f} | Subida: {adverse_pct*100:.1f}%\n"
                       f"Precio prom: {pos['entry_price']:.2f}")
                logger.info(msg)
                _append_trade_journal({
                    "event": f"dca_short_{i+1}", "side": "short",
                    "price": current_price, "size": size,
                    "margin_used": round(cost, 2),
                    "pnl_pct": round(-adverse_pct * 100, 2),
                    "balance": round(self.balance, 2),
                }, self.cfg)
                _save_trade_metrics_snapshot(self.cfg)
                send_telegram(msg, self.cfg)

        # TPs parciales — precio bajó a favor del short (régimen-aware)
        regime_tps = pos.get("regime_tps")
        if regime_tps:
            tp_levels = [
                (regime_tps["tp1_pct"], regime_tps["tp1_close"]),
                (regime_tps["tp2_pct"], regime_tps["tp2_close"]),
                (regime_tps["tp3_pct"], regime_tps["tp3_close"]),
            ]
        else:
            tp_levels = [
                (self.cfg["tp1_pct"], self.cfg.get("tp1_close_pct", 0.30)),
                (self.cfg["tp2_pct"], self.cfg.get("tp2_close_pct", 0.30)),
                (self.cfg["tp3_pct"], self.cfg.get("tp3_close_pct", 0.25)),
            ]
        for i, (tp_pct, close_pct) in enumerate(tp_levels):
            if gain >= tp_pct and i not in pos["tp_done"]:
                close_size = pos["size"] * close_pct
                # Separar margen devuelto (no es ganancia) de ganancia real
                margin_returned = close_size * entry / lev
                real_pnl        = close_size * (entry - current_price)
                self.balance   += margin_returned + real_pnl
                pos["size"] -= close_size
                pos["tp_done"].append(i)
                self.tp_count += 1

                # Stop progression: TP2 → breakeven, TP3 → TP2 price (lock profit del runner)
                if i == 1:   # TP2
                    pos["stop_price"] = float(entry)
                    logger.info(f"{self._paper_tag} 🔒 Stop SHORT movido a breakeven ({entry:.2f}) post-TP2")
                elif i == 2:  # TP3
                    tp2_pct_used = regime_tps["tp2_pct"] if regime_tps else self.cfg["tp2_pct"]
                    tp2_price = float(entry * (1 - tp2_pct_used))
                    pos["stop_price"] = tp2_price
                    logger.info(f"{self._paper_tag} 🔒 Stop SHORT movido a TP2 ({tp2_price:.2f}) post-TP3 — runner activo")

                msg = (f"{self._paper_tag} 💰 TP{i+1} SHORT | {self.symbol}\n"
                       f"Precio: {current_price:.2f} | +{gain*100:.1f}% (favorable)\n"
                       f"Cerrado: {int(close_pct*100)}% | Ganancia: +{real_pnl:.2f} USDT")
                logger.info(msg)
                _append_trade_journal({
                    "event": f"tp{i+1}_short", "side": "short",
                    "price": current_price, "size": close_size,
                    "pnl_pct": round(gain * 100, 2),
                    "pnl_usdt": round(real_pnl, 2),
                    "balance": round(self.balance, 2),
                }, self.cfg, sig=sig, pos=pos)
                _save_trade_metrics_snapshot(self.cfg)
                send_telegram(msg, self.cfg)

        # Runner post-TP3 SHORT: trail ATR — solo BAJA, nunca sube (short)
        # Para short el stop está ARRIBA del precio. Si current baja, podemos bajar el stop.
        # Pero por el lock-in post-TP3, el stop NUNCA debe subir más allá del entry.
        # Implementación: si el lock TP2 ya está activo, calcular trail dinámico hacia abajo.
        # Nota: para shorts el "trail dinámico" es delicado — preferimos el lock fijo en TP2 price.
        # (Decisión: en short el runner queda con stop = TP2 price fijo, sin ATR trail adicional)

        # Trail post-TP1 SHORT (NUEVA lógica): si squeeze alcista emerge, MUEVE stop a entry (no cierra)
        sqz_bullish = bool(df_mid.iloc[-1].get("sqz_fire_bull", False))
        if (pos and 0 in pos.get("tp_done", []) and 1 not in pos.get("tp_done", [])
                and sqz_bullish and float(pos.get("stop_price") or float("inf")) > entry):
            pos["stop_price"] = float(entry)
            logger.info(f"{self._paper_tag} 🔒 Trail SHORT post-TP1: stop movido a entry ({entry:.2f}) — squeeze alcista")

        # Trail legacy (fallback): solo si dynamic_stop_enabled=False
        if (not self.cfg.get("dynamic_stop_enabled", True)
                and pos and 0 in pos.get("tp_done", []) and sqz_bullish):
            close_size = pos["size"]
            if close_size > 0:
                final = close_size * entry / lev + close_size * (entry - current_price)
                self.balance += max(final, 0)
                msg = (f"{self._paper_tag} 🔓 SHORT CERRADO (trail) | {self.symbol}\n"
                       f"Squeeze alcista emergió post-TP1 → cierre total\n"
                       f"Resultado: {gain*100:+.1f}% | Balance: {self.balance:.2f}")
                logger.info(msg)
                _append_trade_journal({
                    "event": "short_trail_close", "side": "short",
                    "price": current_price, "size": close_size,
                    "pnl_pct": round(gain * 100, 2),
                    "pnl_usdt": round(max(final, 0) - close_size * entry / lev, 2),
                    "balance": round(self.balance, 2),
                }, self.cfg, sig=sig, pos=pos)
                _save_trade_metrics_snapshot(self.cfg)
                send_telegram(msg, self.cfg)
            self.active_standalone_short = None

    def force_close_all(self, current_price: float, reason: str = "force_close"):
        """Cierre forzado de TODAS las posiciones (usado en viernes 18:00 UTC, etc.)"""
        if self.active_long:
            entry = self.active_long["entry_price"]
            pnl   = (current_price - entry) / entry
            close_size = self.active_long["size"]
            recovered = close_size * entry / self.cfg["leverage"] + close_size * (current_price - entry)
            self.balance += max(recovered, 0)
            msg = f"{self._paper_tag} 🚪 LONG cerrado forzado ({reason}) | {pnl*100:+.1f}%"
            logger.info(msg); send_telegram(msg, self.cfg)
            self.active_long = None
        if self.active_standalone_short:
            entry = self.active_standalone_short["entry_price"]
            gain  = (entry - current_price) / entry
            close_size = self.active_standalone_short["size"]
            recovered = close_size * entry / self.cfg["leverage"] + close_size * (entry - current_price)
            self.balance += max(recovered, 0)
            msg = f"{self._paper_tag} 🚪 SHORT cerrado forzado ({reason}) | {gain*100:+.1f}%"
            logger.info(msg); send_telegram(msg, self.cfg)
            self.active_standalone_short = None

    def print_summary(self, current_price: float):
        self._last_price = float(current_price)
        # Persistir estado cada ciclo (balance, posiciones, pendings) — barato y robusto
        try:
            save_state(self)
        except Exception as e:
            logger.debug(f"save_state paper: {e}")
        if self.active_long:
            entry = self.active_long["entry_price"]
            pnl   = (current_price - entry) / entry
            pos_value = self.active_long["size"] * current_price / self.cfg["leverage"]
            unrealized = pos_value * pnl * self.cfg["leverage"]
            logger.info(f"[PAPER] 📈 LONG no realizado: {unrealized:+.2f} USDT ({pnl*100:+.2f}%) | "
                        f"Entrada: {entry:.2f} | DCA: {self.dca_count} | TPs: {self.tp_count}")
        if self.active_standalone_short:
            entry = self.active_standalone_short["entry_price"]
            gain  = (entry - current_price) / entry
            pos_value = self.active_standalone_short["size"] * current_price / self.cfg["leverage"]
            unrealized = pos_value * gain * self.cfg["leverage"]
            logger.info(f"[PAPER] 📉 SHORT no realizado: {unrealized:+.2f} USDT ({gain*100:+.2f}%) | "
                        f"Entrada: {entry:.2f}")
        logger.info(f"[PAPER] 💼 Balance: {self.balance:.2f} USDT | "
                    f"Capital inicial: {self.cfg['total_capital_usdt']} USDT")
        if self.pending_long:
            logger.info(f"[PAPER] 📌 Límite LONG pendiente @ {self.pending_long['price']:.2f}")
        if self.pending_short:
            logger.info(f"[PAPER] 📌 Límite SHORT pendiente @ {self.pending_short['price']:.2f}")

    # ─── ÓRDENES LÍMITE ANTICIPADAS (OB virgen) ──────────────────────────────
    def arm_pending_long(self, current_price: float, sig: dict,
                         ob_high: float, ob_low: float, kz_name: str) -> bool:
        """Arma orden límite buy anticipada en el mid del OB bull virgen."""
        if self.pending_long is not None or self.active_long is not None:
            return False
        if ob_high is None or ob_low is None:
            return False
        try:
            ob_high_f = float(ob_high)
            ob_low_f  = float(ob_low)
        except (TypeError, ValueError):
            return False
        if np.isnan(ob_high_f) or np.isnan(ob_low_f) or ob_high_f <= 0 or ob_low_f <= 0:
            return False
        target = (ob_high_f + ob_low_f) / 2.0
        dist = (current_price - target) / current_price
        min_d = self.cfg.get("pending_min_distance_pct", 0.003)
        max_d = self.cfg.get("pending_max_distance_pct", 0.025)
        if dist < min_d or dist > max_d:
            return False
        self.pending_long = {
            "side": "long",
            "price": float(target),
            "ob_high": ob_high_f,
            "ob_low":  ob_low_f,
            "killzone": kz_name,
            "armed_at": datetime.now().isoformat(),
            "sig_snapshot": {
                "score": sig.get("score_adjusted", sig.get("score", 6)),
                "entry_type": sig.get("entry_type", "C"),
                "high_conviction": sig.get("high_conviction", False),
            },
        }
        logger.info(f"📌 {self._paper_tag} LÍMITE LONG armado | {self.symbol} @ {target:.2f} "
                    f"(dist {dist*100:.2f}%) | OB [{ob_low_f:.2f}–{ob_high_f:.2f}] | KZ: {kz_name}")
        ob_width = (ob_high_f - ob_low_f) / target if target > 0 else 0.0
        _append_trade_journal({
            "event": "pending_armed_long",
            "side": "long",
            "price": float(target),
            "killzone": kz_name,
            "ob_width_pct":         round(ob_width * 100, 3),
            "pending_distance_pct": round(dist * 100, 3),
            "note": f"OB [{ob_low_f:.2f}-{ob_high_f:.2f}]",
        }, self.cfg, sig=sig)
        return True

    def arm_pending_short(self, current_price: float, sig: dict,
                          ob_high: float, ob_low: float, kz_name: str) -> bool:
        """Arma orden límite sell anticipada en el mid del OB bear virgen."""
        if self.pending_short is not None or self.active_standalone_short is not None:
            return False
        if ob_high is None or ob_low is None:
            return False
        try:
            ob_high_f = float(ob_high)
            ob_low_f  = float(ob_low)
        except (TypeError, ValueError):
            return False
        if np.isnan(ob_high_f) or np.isnan(ob_low_f) or ob_high_f <= 0 or ob_low_f <= 0:
            return False
        target = (ob_high_f + ob_low_f) / 2.0
        dist = (target - current_price) / current_price
        min_d = self.cfg.get("pending_min_distance_pct", 0.003)
        max_d = self.cfg.get("pending_max_distance_pct", 0.025)
        if dist < min_d or dist > max_d:
            return False
        self.pending_short = {
            "side": "short",
            "price": float(target),
            "ob_high": ob_high_f,
            "ob_low":  ob_low_f,
            "killzone": kz_name,
            "armed_at": datetime.now().isoformat(),
            "sig_snapshot": {
                "score": sig.get("score_short_adjusted", sig.get("score_short", 6)),
                "entry_type": sig.get("short_entry_type", "C"),
                "high_conviction": False,
            },
        }
        logger.info(f"📌 {self._paper_tag} LÍMITE SHORT armado | {self.symbol} @ {target:.2f} "
                    f"(dist {dist*100:.2f}%) | OB [{ob_low_f:.2f}–{ob_high_f:.2f}] | KZ: {kz_name}")
        ob_width = (ob_high_f - ob_low_f) / target if target > 0 else 0.0
        _append_trade_journal({
            "event": "pending_armed_short",
            "side": "short",
            "price": float(target),
            "killzone": kz_name,
            "ob_width_pct":         round(ob_width * 100, 3),
            "pending_distance_pct": round(dist * 100, 3),
            "note": f"OB [{ob_low_f:.2f}-{ob_high_f:.2f}]",
        }, self.cfg, sig=sig)
        return True

    def check_pending_fills(self, df_entry, current_price: float, kz_active: bool) -> None:
        """Verifica fills (paper: vela actual visitó el precio) y cancela si invalidado.

        En paper, si la última vela del timeframe entry visitó el límite,
        simulamos un fill al precio del límite (slippage cero).
        """
        # ── Long pending
        if self.pending_long is not None:
            target = self.pending_long["price"]
            filled = False
            if df_entry is not None and len(df_entry) > 0:
                last_low = float(df_entry.iloc[-1]["low"])
                if last_low <= target:
                    snap = self.pending_long.get("sig_snapshot", {})
                    fake_sig = {
                        "score": snap.get("score", 6),
                        "entry_type": snap.get("entry_type", "C"),
                        "high_conviction": snap.get("high_conviction", False),
                        "candle_count": 0,
                        "adx": {"value": 0.0, "trend": True},
                        "killzone": self.pending_long["killzone"],
                        "_final_sizing": 1.0,
                        "_adapt_mult": 1.0,
                    }
                    logger.info(f"🎯 {self._paper_tag} FILL LÍMITE LONG | {self.symbol} @ {target:.2f} "
                                f"(vela low {last_low:.2f})")
                    self.pending_long = None
                    self.open_long(target, fake_sig)
                    filled = True
            if not filled:
                reason = None
                if not kz_active:
                    reason = "fin_killzone"
                elif current_price < self.pending_long.get("ob_low", 0) * 0.995:
                    reason = "ob_invalidado"
                if reason:
                    pl = self.pending_long
                    logger.info(f"❌ {self._paper_tag} LÍMITE LONG cancelado | {self.symbol} @ "
                                f"{pl['price']:.2f} | razón: {reason}")
                    _append_trade_journal({
                        "event": "pending_cancelled_long",
                        "side": "long",
                        "price": pl["price"],
                        "killzone": pl.get("killzone", ""),
                        "note": reason,
                    }, self.cfg)
                    self.pending_long = None

        # ── Short pending
        if self.pending_short is not None:
            target = self.pending_short["price"]
            filled = False
            if df_entry is not None and len(df_entry) > 0:
                last_high = float(df_entry.iloc[-1]["high"])
                if last_high >= target:
                    snap = self.pending_short.get("sig_snapshot", {})
                    fake_sig = {
                        "score": snap.get("score", 6),
                        "entry_type": snap.get("entry_type", "C"),
                        "short_entry_type": snap.get("entry_type", "C"),
                        "high_conviction": False,
                        "candle_count": 0,
                        "adx": {"value": 0.0, "trend": True},
                        "killzone": self.pending_short["killzone"],
                        "_final_sizing": 1.0,
                        "_adapt_mult": 1.0,
                    }
                    logger.info(f"🎯 {self._paper_tag} FILL LÍMITE SHORT | {self.symbol} @ {target:.2f} "
                                f"(vela high {last_high:.2f})")
                    self.pending_short = None
                    self.open_short_standalone(target, fake_sig)
                    filled = True
            if not filled:
                reason = None
                if not kz_active:
                    reason = "fin_killzone"
                elif current_price > self.pending_short.get("ob_high", float("inf")) * 1.005:
                    reason = "ob_invalidado"
                if reason:
                    ps = self.pending_short
                    logger.info(f"❌ {self._paper_tag} LÍMITE SHORT cancelado | "
                                f"{self.symbol} @ {ps['price']:.2f} | razón: {reason}")
                    _append_trade_journal({
                        "event": "pending_cancelled_short",
                        "side": "short",
                        "price": ps["price"],
                        "killzone": ps.get("killzone", ""),
                        "note": reason,
                    }, self.cfg)
                    self.pending_short = None


# ─── GESTIÓN DE POSICIONES (REAL) ────────────────────────────────────────────

class PositionManager:

    def __init__(self, exchange: ccxt.Exchange, config: dict):
        self.ex     = exchange
        self.cfg    = config
        self.symbol = config["symbol"]

        self.active_long: Optional[dict] = None
        self.active_short: Optional[dict] = None
        self.pending_long:  Optional[dict] = None
        self.pending_short: Optional[dict] = None
        self.dca_count  = 0
        self.tp_count   = 0

        # Cargar estado previo y sincronizar con el exchange
        state = load_state()
        if state:
            self.active_long  = state.get("active_long")
            self.active_short = state.get("active_short")
            self.pending_long  = state.get("pending_long")
            self.pending_short = state.get("pending_short")
            self.dca_count    = state.get("dca_count", 0)
            self.tp_count     = state.get("tp_count", 0)
            logger.info("Estado previo cargado desde disco")
        self._sync_with_exchange()

    def _sync_with_exchange(self):
        """Reconcilia el estado en memoria con las posiciones reales del exchange."""
        try:
            positions = self.ex.fetch_positions([self.symbol])
            long_ex  = next((p for p in positions if p["side"] == "long"  and float(p.get("contracts") or 0) > 0), None)
            short_ex = next((p for p in positions if p["side"] == "short" and float(p.get("contracts") or 0) > 0), None)

            # Exchange tiene LONG pero nosotros no lo rastreamos → reconstruir
            if long_ex and not self.active_long:
                self.active_long = {
                    "entry_price": float(long_ex["entryPrice"]),
                    "size":        float(long_ex["contracts"]),
                    "dca_done":    [],
                    "tp_done":     [],
                    "entry_time":  datetime.now().isoformat(),
                    "score":       0,
                    "entry_type":  "?",
                }
                logger.info(f"LONG sincronizado desde exchange: entrada {self.active_long['entry_price']:.2f}")
                save_state(self)

            # Nosotros rastreamos LONG pero el exchange ya no lo tiene → limpiar
            if not long_ex and self.active_long:
                logger.info("LONG cerrado externamente — limpiando estado")
                self.active_long = None
                save_state(self)

            if short_ex and not self.active_short:
                self.active_short = {
                    "entry_price": float(short_ex["entryPrice"]),
                    "size":        float(short_ex["contracts"]),
                    "entry_time":  datetime.now().isoformat(),
                }
                logger.info(f"SHORT sincronizado desde exchange: entrada {self.active_short['entry_price']:.2f}")
                save_state(self)

            if not short_ex and self.active_short:
                logger.info("SHORT cerrado externamente — limpiando estado")
                self.active_short = None
                save_state(self)

        except Exception as e:
            logger.warning(f"Error sincronizando con exchange: {e}")

    def get_positions(self) -> dict:
        try:
            positions = self.ex.fetch_positions([self.symbol])
            result = {"long": None, "short": None}
            for p in positions:
                if p.get("contracts", 0) and float(p["contracts"]) > 0:
                    if p["side"] == "long":
                        result["long"] = p
                    elif p["side"] == "short":
                        result["short"] = p
            return result
        except Exception as e:
            logger.error(f"Error obteniendo posiciones: {e}")
            return {"long": None, "short": None}

    def get_balance(self) -> float:
        try:
            bal = self.ex.fetch_balance()
            return float(bal["USDT"]["free"])
        except Exception as e:
            logger.error(f"Error balance: {e}")
            return 0.0

    def _order_size(self, price: float) -> float:
        # COMPOUND: usa balance actual del exchange (que ya incluye unrealized via wallet total)
        # en vez del capital inicial estático. Cuando el balance crece, el sizing crece.
        try:
            wallet = self.ex.fetch_balance()
            capital = float(wallet["USDT"]["total"])   # total = libre + comprometido + unrealized
            if capital <= 0:
                capital = float(self.cfg["total_capital_usdt"])
        except Exception:
            capital = float(self.cfg["total_capital_usdt"])
        risk = capital * self.cfg["risk_capital_pct"]
        part = risk / self.cfg["position_parts"]
        return round((part * self.cfg["leverage"]) / price, 4)

    def open_long(self, price: float, sig: dict):
        try:
            size = self._order_size(price)

            # Sizing basado en score (fuente: estrategia mentor)
            # Score 6-7 = entrada cautelosa al 50% → reduce pérdida en setups inciertos
            # Score 8   = tamaño normal (100%)
            # Score 9-10 tipo A = alta convicción (150%)
            score = sig["score"]
            if score <= 7:
                size = round(size * 0.5, 4)
                size_label = "50% (cauteloso)"
            elif score >= 9 and sig["entry_type"] == "A":
                size = round(size * 1.5, 4)
                size_label = "150% (máxima convicción)"
            else:
                size_label = "100% (estándar)"

            self.ex.create_order(
                symbol=self.symbol, type="market", side="buy", amount=size,
                params={"positionSide": "LONG", "leverage": self.cfg["leverage"]}
            )
            stop_price = None
            if self.cfg.get("dynamic_stop_enabled", True) and sig.get("dynamic_stop_long") is not None:
                stop_price = float(sig["dynamic_stop_long"])
            self.active_long = {
                "entry_price": price,
                "size": size,
                "dca_done": [],
                "tp_done": [],
                "entry_time": datetime.now().isoformat(),
                "score": sig["score"],
                "entry_type": sig["entry_type"],
                "stop_price": stop_price,
            }
            self.dca_count = 0
            save_state(self)
            msg = (f"✅ LONG ABIERTO | {self.symbol}\n"
                   f"Precio: {price:.2f} | Tamaño: {size} BTC ({size_label})\n"
                   f"Tipo: {sig['entry_type']} | Score: {sig['score']}/10\n"
                   f"Vela #{sig['candle_count']} | ADX: {sig['adx']['value']}")
            logger.info(msg)
            _append_trade_journal({
                "event": "open_long",
                "side": "long",
                "price": price,
                "size": size,
                "entry_type": sig["entry_type"],
                "score": sig["score"],
            }, self.cfg)
            _save_trade_metrics_snapshot(self.cfg)
            send_telegram(msg, self.cfg)
            return True
        except Exception as e:
            logger.error(f"Error abriendo LONG: {e}")
            return False

    def manage_long(self, current_price: float, df_mid: pd.DataFrame,
                    sig: dict, df_entry: pd.DataFrame = None):
        """DCA y TP de la posición LONG activa."""
        if not self.active_long:
            return

        entry = self.active_long["entry_price"]
        pnl   = (current_price - entry) / entry
        tol   = self.cfg.get("dca_structural_tolerance", 0.015)

        stop_price = self.active_long.get("stop_price")
        if self.cfg.get("enable_hard_stop", True) and (
            (stop_price is not None and current_price <= stop_price)
            or (stop_price is None and pnl <= self.cfg.get("hard_stop_pct", -0.06))
        ):
            try:
                pos = self.get_positions()
                if pos["long"]:
                    contracts = float(pos["long"]["contracts"])
                    self.ex.create_order(
                        symbol=self.symbol, type="market", side="sell",
                        amount=contracts,
                        params={"positionSide": "LONG", "reduceOnly": True}
                    )
                    self.active_long = None
                    save_state(self)
                    msg = (f"❌ HARD STOP | {self.symbol}\n"
                           f"Precio: {current_price:.2f} | PnL: {pnl*100:.1f}%\n"
                           f"Salida defensiva activada para proteger capital.")
                    logger.info(msg)
                    _append_trade_journal({
                        "event": "hard_stop",
                        "side": "long",
                        "price": current_price,
                        "size": contracts,
                        "pnl_pct": round(pnl * 100, 2),
                        "pnl_usdt": round(contracts * (current_price - entry), 2),
                    }, self.cfg)
                    _save_trade_metrics_snapshot(self.cfg)
                    send_telegram(msg, self.cfg)
                    return
            except Exception as e:
                logger.error(f"Error hard stop: {e}")

        # Referencias de soporte estructural para validar DCA
        ema55_4h  = float(df_mid.iloc[-1]["ema55"])
        ema55_1h  = float(df_entry.iloc[-1]["ema55"]) if df_entry is not None else ema55_4h
        ob_active = not np.isnan(float(df_mid.iloc[-1].get("ob_bull_low", float("nan"))))

        def _near(price, level):
            return abs(price - level) / level < tol

        # ── DCA — solo si macro 4H alcista Y precio está en soporte estructural
        # Fuente: "2da recompra en EMA55 1H, 3ra en EMA55 4H, 4ta en OB 1D, 5ta en EMA55 1D"
        macro_alcista = check_ema_trend_str(df_mid) == "bullish"
        structural_supports = [
            _near(current_price, ema55_1h),          # -3%: EMA55 en 1H
            _near(current_price, ema55_4h),           # -7%: EMA55 en 4H
            ob_active or _near(current_price, ema55_4h * 0.97),  # -12%: OB 1D aprox
            _near(current_price, float(df_mid.iloc[-1]["ema55"])),  # -20%: EMA55 1D
        ]

        # DCA — tamaños doblan en cada nivel (fuente: Excel AUT LONG patrón doblante)
        multipliers = self.cfg.get("dca_size_multipliers", [1, 1, 1, 1])
        for i, level in enumerate(self.cfg["dca_levels_pct"]):
            if pnl <= level and i not in self.active_long["dca_done"]:
                if not macro_alcista:
                    logger.info(f"DCA {i+1} omitido: tendencia 4H bajista")
                    continue
                at_support = structural_supports[i] if i < len(structural_supports) else False
                if not at_support:
                    logger.info(f"DCA {i+1} omitido: precio no está en soporte estructural "
                                f"(EMA55-4H={ema55_4h:.0f}, precio={current_price:.0f})")
                    continue
                try:
                    mult = multipliers[i] if i < len(multipliers) else 1.0
                    size = round(self._order_size(current_price) * mult, 4)
                    self.ex.create_order(
                        symbol=self.symbol, type="market", side="buy", amount=size,
                        params={"positionSide": "LONG", "leverage": self.cfg["leverage"]}
                    )
                    self.active_long["dca_done"].append(i)
                    self.dca_count += 1
                    # Recalcular precio promedio
                    total = self.active_long["size"] + size
                    self.active_long["entry_price"] = (
                        (entry * self.active_long["size"] + current_price * size) / total
                    )
                    self.active_long["size"] = total
                    save_state(self)
                    msg = (f"🔄 DCA #{self.dca_count} ({mult}x) | {self.symbol}\n"
                           f"Precio: {current_price:.2f} | Caída desde entrada: {pnl*100:.1f}%\n"
                           f"Nuevo precio prom: {self.active_long['entry_price']:.2f}")
                    logger.info(msg)
                    _append_trade_journal({
                        "event": f"dca_{self.dca_count}",
                        "side": "long",
                        "price": current_price,
                        "size": size,
                        "pnl_pct": round(pnl * 100, 2),
                        "note": f"mult={mult}",
                    }, self.cfg)
                    _save_trade_metrics_snapshot(self.cfg)
                    send_telegram(msg, self.cfg)
                except Exception as e:
                    logger.error(f"Error DCA: {e}")

        # ── TP parciales
        lev = self.cfg["leverage"]
        tp_levels = [
            (self.cfg["tp1_pct"], 0.20, ""),
            (self.cfg["tp2_pct"], 0.20, ""),
            (self.cfg["tp3_pct"], 0.30,
             f"\n🏃 {int(self.cfg.get('tp_hold_pct',0.30)*100)}% restante — dejando correr hasta resistencia mayor"),
        ]
        for i, (tp_pct, close_pct, extra_note) in enumerate(tp_levels):
            if pnl >= tp_pct and i not in self.active_long["tp_done"]:
                try:
                    pos = self.get_positions()
                    if pos["long"]:
                        contracts = float(pos["long"]["contracts"])
                        close_size = round(contracts * close_pct, 4)
                        self.ex.create_order(
                            symbol=self.symbol, type="market", side="sell",
                            amount=close_size,
                            params={"positionSide": "LONG", "reduceOnly": True}
                        )
                        self.active_long["tp_done"].append(i)
                        self.tp_count += 1
                        save_state(self)
                        margin_ret_pct = round(pnl * lev * 100, 1)
                        msg = (f"💰 TP{i+1} | {self.symbol}\n"
                               f"Precio: {current_price:.2f} | +{pnl*100:.1f}% (+{margin_ret_pct}%/margen)\n"
                               f"Cerrado: {int(close_pct*100)}% de la posición{extra_note}")
                        logger.info(msg)
                        est_margin = close_size * entry / lev
                        est_profit = close_size * (current_price - entry)
                        _append_trade_journal({
                            "event": f"tp{i+1}",
                            "side": "long",
                            "price": current_price,
                            "size": close_size,
                            "margin_used": round(est_margin, 2),
                            "pnl_pct": round(pnl * 100, 2),
                            "pnl_usdt": round(est_profit, 2),
                        }, self.cfg)
                        _save_trade_metrics_snapshot(self.cfg)
                        send_telegram(msg, self.cfg)
                except Exception as e:
                    logger.error(f"Error TP: {e}")

        # ── Trailing stop post-TP1: cerrar si TP1 ya fue alcanzado pero el precio revirtió
        # y la tendencia se debilitó → proteger capital en lugar de esperar DCA profundo
        if (self.active_long
                and self.cfg.get("trailing_stop_after_tp1", True)
                and 0 in self.active_long.get("tp_done", [])
                and pnl < self.cfg.get("trailing_stop_entry_pct", -0.015)
                and not bool(df_mid.iloc[-1]["adx_bull"])):
            try:
                pos = self.get_positions()
                if pos["long"]:
                    contracts = float(pos["long"]["contracts"])
                    self.ex.create_order(
                        symbol=self.symbol, type="market", side="sell",
                        amount=contracts,
                        params={"positionSide": "LONG", "reduceOnly": True}
                    )
                    self.active_long = None
                    save_state(self)
                    msg = (f"🛑 TRAILING STOP POST-TP1 | {self.symbol}\n"
                           f"TP1 alcanzado → precio cayó {pnl*100:.1f}% bajo entrada\n"
                           f"ADX dejó de ser alcista — posición cerrada para proteger capital")
                    logger.info(msg)
                    _append_trade_journal({
                        "event": "trailing_stop",
                        "side": "long",
                        "price": current_price,
                        "size": contracts,
                        "pnl_pct": round(pnl * 100, 2),
                        "pnl_usdt": round(contracts * (current_price - entry), 2),
                    }, self.cfg)
                    _save_trade_metrics_snapshot(self.cfg)
                    send_telegram(msg, self.cfg)
            except Exception as e:
                logger.error(f"Error trailing stop: {e}")

    def should_hedge(self, current_price: float, df_mid: pd.DataFrame,
                     sig: dict) -> bool:
        if not self.cfg.get("hedge_enabled", False):
            return False
        if not self.active_long or self.active_short:
            return False

        entry = self.active_long["entry_price"]
        pnl   = (current_price - entry) / entry

        if pnl > self.cfg["hedge_loss_trigger_pct"]:
            return False

        compression_failed = sig["candle12"]["compression_failed"]
        mid_bearish = check_ema_trend_str(df_mid) == "bearish"
        sqz_bearish = int(df_mid.iloc[-1]["sqz_quadrant"]) in (3, 4)

        return compression_failed or (mid_bearish and sqz_bearish)

    def open_hedge(self, price: float):
        if not self.cfg.get("hedge_enabled", False) or self.active_short:
            return
        try:
            # Fuente: "si tu long es de 100 USD, la cobertura debe ser de 200" → 2x el LONG
            hedge_mult = self.cfg.get("hedge_size_multiplier", 2.0)
            size = round(self._order_size(price) * hedge_mult, 4)
            self.ex.create_order(
                symbol=self.symbol, type="market", side="sell", amount=size,
                params={"positionSide": "SHORT", "leverage": self.cfg["leverage"]}
            )
            self.active_short = {
                "entry_price": price,
                "size": size,
                "initial_size": size,
                "entry_time": datetime.now().isoformat(),
                "partial_closed": False,
            }
            save_state(self)
            msg = (f"🛡️ COBERTURA SHORT ({hedge_mult}x) ABIERTA | {self.symbol}\n"
                   f"Precio: {price:.2f} | Tamaño: {size} BTC\n"
                   f"Long en pérdida -20% → cobertura activa")
            logger.info(msg)
            _append_trade_journal({
                "event": "open_hedge",
                "side": "short",
                "price": price,
                "size": size,
                "note": f"mult={hedge_mult}",
            }, self.cfg)
            _save_trade_metrics_snapshot(self.cfg)
            send_telegram(msg, self.cfg)
        except Exception as e:
            logger.error(f"Error hedge: {e}")

    def manage_hedge(self, current_price: float, df_mid: pd.DataFrame):
        if not self.active_short:
            return

        entry = self.active_short["entry_price"]
        gain  = (entry - current_price) / entry
        sqz_bullish = bool(df_mid.iloc[-1]["sqz_fire_bull"])
        partial_pct = self.cfg.get("hedge_partial_pct", 0.80)

        # Cierre parcial 80%: "cobra 80% de lo que entre"
        if (gain >= self.cfg["hedge_close_gain_pct"]
                and not self.active_short.get("partial_closed")):
            try:
                pos = self.get_positions()
                if pos["short"]:
                    contracts = float(pos["short"]["contracts"])
                    close_size = round(contracts * partial_pct, 4)
                    self.ex.create_order(
                        symbol=self.symbol, type="market", side="buy",
                        amount=close_size,
                        params={"positionSide": "SHORT", "reduceOnly": True}
                    )
                    self.active_short["partial_closed"] = True
                    save_state(self)
                    msg = (f"💰 COBERTURA PARCIAL ({int(partial_pct*100)}%) | {self.symbol}\n"
                           f"SHORT: {entry:.2f} → {current_price:.2f} | +{gain*100:.1f}%\n"
                           f"20% restante sigue corriendo")
                    logger.info(msg)
                    _append_trade_journal({
                        "event": "hedge_partial",
                        "side": "short",
                        "price": current_price,
                        "size": close_size,
                        "pnl_pct": round(gain * 100, 2),
                        "pnl_usdt": round(close_size * (entry - current_price), 2),
                    }, self.cfg)
                    _save_trade_metrics_snapshot(self.cfg)
                    send_telegram(msg, self.cfg)
            except Exception as e:
                logger.error(f"Error cierre parcial hedge: {e}")

        # Cierre total del 20% restante cuando squeeze vuelve alcista
        elif self.active_short.get("partial_closed") and sqz_bullish:
            try:
                pos = self.get_positions()
                if pos["short"]:
                    contracts = float(pos["short"]["contracts"])
                    self.ex.create_order(
                        symbol=self.symbol, type="market", side="buy",
                        amount=contracts,
                        params={"positionSide": "SHORT", "reduceOnly": True}
                    )
                    msg = (f"🔓 COBERTURA CERRADA (restante) | {self.symbol}\n"
                           f"Squeeze alcista | +{gain*100:.1f}%")
                    logger.info(msg)
                    _append_trade_journal({
                        "event": "hedge_close",
                        "side": "short",
                        "price": current_price,
                        "size": contracts,
                        "pnl_pct": round(gain * 100, 2),
                        "pnl_usdt": round(contracts * (entry - current_price), 2),
                    }, self.cfg)
                    _save_trade_metrics_snapshot(self.cfg)
                    send_telegram(msg, self.cfg)
                    self.active_short = None
                    save_state(self)
            except Exception as e:
                logger.error(f"Error cerrando hedge restante: {e}")

        # Cierre forzado si squeeze alcista sin haber hecho parcial
        elif not self.active_short.get("partial_closed") and sqz_bullish and gain > 0:
            try:
                pos = self.get_positions()
                if pos["short"]:
                    contracts = float(pos["short"]["contracts"])
                    self.ex.create_order(
                        symbol=self.symbol, type="market", side="buy",
                        amount=contracts,
                        params={"positionSide": "SHORT", "reduceOnly": True}
                    )
                    msg = (f"🔓 COBERTURA CERRADA | {self.symbol}\n"
                           f"Squeeze alcista | +{gain*100:.1f}%")
                    logger.info(msg)
                    _append_trade_journal({
                        "event": "hedge_force_close",
                        "side": "short",
                        "price": current_price,
                        "size": contracts,
                        "pnl_pct": round(gain * 100, 2),
                        "pnl_usdt": round(contracts * (entry - current_price), 2),
                    }, self.cfg)
                    _save_trade_metrics_snapshot(self.cfg)
                    send_telegram(msg, self.cfg)
                    self.active_short = None
                    save_state(self)
            except Exception as e:
                logger.error(f"Error cerrando hedge: {e}")

    # ─── ÓRDENES LÍMITE ANTICIPADAS (OB virgen) ──────────────────────────────
    def _arm_pending_size(self, target_price: float, sig: dict) -> float:
        """Tamaño usando misma fórmula que open_long (sin sizing multiplicador adaptativo aún)."""
        size = self._order_size(target_price)
        score = sig.get("score", 6)
        if score <= 7:
            size = round(size * 0.5, 4)
        elif score >= 9 and sig.get("entry_type") == "A":
            size = round(size * 1.5, 4)
        return size

    def arm_pending_long(self, current_price: float, sig: dict,
                         ob_high: float, ob_low: float, kz_name: str) -> bool:
        if self.pending_long is not None or self.active_long is not None:
            return False
        if ob_high is None or ob_low is None:
            return False
        try:
            ob_high_f = float(ob_high)
            ob_low_f  = float(ob_low)
        except (TypeError, ValueError):
            return False
        if np.isnan(ob_high_f) or np.isnan(ob_low_f) or ob_high_f <= 0 or ob_low_f <= 0:
            return False
        target = (ob_high_f + ob_low_f) / 2.0
        dist = (current_price - target) / current_price
        min_d = self.cfg.get("pending_min_distance_pct", 0.003)
        max_d = self.cfg.get("pending_max_distance_pct", 0.025)
        if dist < min_d or dist > max_d:
            return False
        try:
            size = self._arm_pending_size(target, sig)
            order = self.ex.create_order(
                symbol=self.symbol, type="limit", side="buy", amount=size, price=target,
                params={"positionSide": "LONG", "leverage": self.cfg["leverage"]},
            )
            self.pending_long = {
                "side": "long",
                "order_id": order.get("id"),
                "price": float(target),
                "size":  float(size),
                "ob_high": ob_high_f,
                "ob_low":  ob_low_f,
                "killzone": kz_name,
                "armed_at": datetime.now().isoformat(),
                "sig_snapshot": {
                    "score": sig.get("score_adjusted", sig.get("score", 6)),
                    "entry_type": sig.get("entry_type", "C"),
                    "high_conviction": sig.get("high_conviction", False),
                },
            }
            save_state(self)
            logger.info(f"📌 LÍMITE LONG armado | {self.symbol} @ {target:.2f} "
                        f"(dist {dist*100:.2f}%) | OB [{ob_low_f:.2f}–{ob_high_f:.2f}] | KZ: {kz_name}")
            return True
        except Exception as e:
            logger.error(f"Error armando límite LONG: {e}")
            return False

    def arm_pending_short(self, current_price: float, sig: dict,
                          ob_high: float, ob_low: float, kz_name: str) -> bool:
        if self.pending_short is not None:
            return False
        if ob_high is None or ob_low is None:
            return False
        try:
            ob_high_f = float(ob_high)
            ob_low_f  = float(ob_low)
        except (TypeError, ValueError):
            return False
        if np.isnan(ob_high_f) or np.isnan(ob_low_f) or ob_high_f <= 0 or ob_low_f <= 0:
            return False
        target = (ob_high_f + ob_low_f) / 2.0
        dist = (target - current_price) / current_price
        min_d = self.cfg.get("pending_min_distance_pct", 0.003)
        max_d = self.cfg.get("pending_max_distance_pct", 0.025)
        if dist < min_d or dist > max_d:
            return False
        try:
            size = self._arm_pending_size(target, sig)
            order = self.ex.create_order(
                symbol=self.symbol, type="limit", side="sell", amount=size, price=target,
                params={"positionSide": "SHORT", "leverage": self.cfg["leverage"]},
            )
            self.pending_short = {
                "side": "short",
                "order_id": order.get("id"),
                "price": float(target),
                "size":  float(size),
                "ob_high": ob_high_f,
                "ob_low":  ob_low_f,
                "killzone": kz_name,
                "armed_at": datetime.now().isoformat(),
                "sig_snapshot": {
                    "score": sig.get("score_short_adjusted", sig.get("score_short", 6)),
                    "entry_type": sig.get("short_entry_type", "C"),
                    "high_conviction": False,
                },
            }
            save_state(self)
            logger.info(f"📌 LÍMITE SHORT armado | {self.symbol} @ {target:.2f} "
                        f"(dist {dist*100:.2f}%) | OB [{ob_low_f:.2f}–{ob_high_f:.2f}] | KZ: {kz_name}")
            return True
        except Exception as e:
            logger.error(f"Error armando límite SHORT: {e}")
            return False

    def _cancel_pending(self, side: str, reason: str) -> None:
        pending = self.pending_long if side == "long" else self.pending_short
        if pending is None:
            return
        try:
            self.ex.cancel_order(pending["order_id"], self.symbol)
        except Exception as e:
            logger.warning(f"Cancelando límite {side.upper()} (ya inexistente?): {e}")
        logger.info(f"❌ LÍMITE {side.upper()} cancelado | {self.symbol} @ "
                    f"{pending['price']:.2f} | razón: {reason}")
        if side == "long":
            self.pending_long = None
        else:
            self.pending_short = None
        save_state(self)

    def check_pending_fills(self, df_entry, current_price: float, kz_active: bool) -> None:
        # ── Long
        if self.pending_long is not None:
            order_id = self.pending_long.get("order_id")
            try:
                ord_info = self.ex.fetch_order(order_id, self.symbol)
                status = ord_info.get("status")
                if status in ("closed", "filled"):
                    fill_price = float(ord_info.get("average") or self.pending_long["price"])
                    snap = self.pending_long.get("sig_snapshot", {})
                    fake_sig = {
                        "score": snap.get("score", 6),
                        "entry_type": snap.get("entry_type", "C"),
                        "high_conviction": snap.get("high_conviction", False),
                        "candle_count": 0,
                        "adx": {"value": 0.0, "trend": True},
                        "killzone": self.pending_long["killzone"],
                    }
                    logger.info(f"🎯 FILL LÍMITE LONG | {self.symbol} @ {fill_price:.2f}")
                    self.active_long = {
                        "entry_price": fill_price,
                        "size": float(ord_info.get("amount") or self.pending_long["size"]),
                        "dca_done": [], "tp_done": [],
                        "entry_time": datetime.now().isoformat(),
                        "score": snap.get("score", 6),
                        "entry_type": snap.get("entry_type", "C"),
                    }
                    self.pending_long = None
                    save_state(self)
                    _append_trade_journal({
                        "event": "open_long_limit",
                        "side": "long",
                        "price": fill_price,
                        "size": self.active_long["size"],
                        "entry_type": snap.get("entry_type", "C"),
                        "score": snap.get("score", 6),
                    }, self.cfg)
                    send_telegram(f"✅ LIMIT LONG FILLED | {self.symbol} @ {fill_price:.2f}", self.cfg)
                    return
            except Exception as e:
                logger.debug(f"fetch_order LONG: {e}")
            # No filled aún: ¿cancelar?
            if not kz_active:
                self._cancel_pending("long", "fin_killzone")
            elif current_price < self.pending_long.get("ob_low", 0) * 0.995:
                self._cancel_pending("long", "ob_invalidado")

        # ── Short (mismo flujo)
        if self.pending_short is not None:
            order_id = self.pending_short.get("order_id")
            try:
                ord_info = self.ex.fetch_order(order_id, self.symbol)
                status = ord_info.get("status")
                if status in ("closed", "filled"):
                    fill_price = float(ord_info.get("average") or self.pending_short["price"])
                    snap = self.pending_short.get("sig_snapshot", {})
                    logger.info(f"🎯 FILL LÍMITE SHORT | {self.symbol} @ {fill_price:.2f}")
                    self.active_short = {
                        "entry_price": fill_price,
                        "size": float(ord_info.get("amount") or self.pending_short["size"]),
                        "entry_time": datetime.now().isoformat(),
                        "score": snap.get("score", 6),
                    }
                    self.pending_short = None
                    save_state(self)
                    _append_trade_journal({
                        "event": "open_short_limit",
                        "side": "short",
                        "price": fill_price,
                        "size": self.active_short["size"],
                        "entry_type": snap.get("entry_type", "C"),
                        "score": snap.get("score", 6),
                    }, self.cfg)
                    send_telegram(f"✅ LIMIT SHORT FILLED | {self.symbol} @ {fill_price:.2f}", self.cfg)
                    return
            except Exception as e:
                logger.debug(f"fetch_order SHORT: {e}")
            if not kz_active:
                self._cancel_pending("short", "fin_killzone")
            elif current_price > self.pending_short.get("ob_high", float("inf")) * 1.005:
                self._cancel_pending("short", "ob_invalidado")


# ─── LOOP PRINCIPAL ───────────────────────────────────────────────────────────

def run_bot(cfg: dict = CONFIG):
    paper      = cfg.get("paper_trading", True)
    mode_label = "PAPER TRADING" if paper else "REAL"
    net_label  = "TESTNET" if cfg.get("testnet") else "MAINNET"
    symbols    = cfg.get("symbols", [cfg["symbol"]])
    # Se relee dentro del bucle (abajo) para que el panel pueda cambiarlo en
    # caliente; aquí solo se deja el valor inicial para el log de arranque.
    max_pos    = cfg.get("max_concurrent_positions", 2)

    logger.info("=" * 60)
    logger.info(f"🤖 BOT JORGE — {mode_label} | {net_label}")
    logger.info(f"   Pares: {', '.join(symbols)}")
    logger.info(f"   Capital: {cfg['total_capital_usdt']} USDT | {cfg['leverage']}x | Max posiciones: {max_pos}")
    logger.info(f"   Objetivo diario: +{cfg.get('daily_profit_target_usdt', 10)} USDT | "
                f"Límite pérdida: -{cfg.get('daily_loss_limit_usdt', 25)} USDT")
    logger.info(f"   Sesión activa: {cfg.get('session_start_utc', 7):02d}:00 – {cfg.get('session_end_utc', 21):02d}:00 UTC")
    if paper:
        logger.info("   ⚠️  PAPER TRADING — sin órdenes reales")
    logger.info("=" * 60)

    exchange = get_exchange(cfg)

    # Un manager por símbolo
    managers: dict = {}
    for sym in symbols:
        sym_cfg = {**cfg, "symbol": sym}
        managers[sym] = PaperPositionManager(sym_cfg) if paper else PositionManager(exchange, sym_cfg)

    # Exponer managers a los hilos de Telegram / daily summary (solo paper)
    if paper:
        _PAPER_MANAGERS.clear()
        _PAPER_MANAGERS.update(managers)

    # Panel web. Mismo patrón que el listener de Telegram: un hilo daemon en
    # ESTE proceso, porque el estado que maneja (pausa, tracker diario, los
    # managers) vive en esta memoria y desde fuera no se alcanza.
    try:
        import panel_web
        panel_web.arrancar(sys.modules[__name__], cfg, managers)
    except Exception as e:
        logger.warning(f"Panel web no arrancó: {e}")

    send_telegram(
        f"🤖 <b>Bot Jorge iniciado — {mode_label} | {net_label}</b>\n"
        f"Pares: {', '.join(symbols)}\n"
        f"Capital: {cfg['total_capital_usdt']} USDT | {cfg['leverage']}x\n"
        f"Objetivo diario: <b>+${cfg.get('daily_profit_target_usdt', 10)}/día</b>\n"
        f"Sesión: {cfg.get('session_start_utc', 7):02d}:00–{cfg.get('session_end_utc', 21):02d}:00 UTC",
        cfg
    )

    while True:
        try:
            # Varios ciclos seguidos sin que entre una sola vela significan que
            # el cliente está envenenado — normalmente porque la VPN cambió de
            # salida y su pool de conexiones quedó muerto. Rehacerlo es lo único
            # que lo devuelve a la vida; antes esto no ocurría nunca.
            if _SALUD["fallos_seguidos"] >= int(cfg.get("rebuild_client_after_failures", 3)):
                exchange = _reconstruir_exchange(exchange, cfg)

            # Releído cada ciclo: el panel lo cambia en caliente.
            max_pos = int(cfg.get("max_concurrent_positions", 2))

            # ─── Actualizar equity total y tracker diario
            # Equity = balance líquido + margen comprometido + unrealized PnL, igual que un
            # exchange real. Usar get_balance() aquí (que en paper solo es líquido) hacía que
            # abrir una posición se viera como "pérdida" del margen, autopausando el bot.
            try:
                if paper:
                    equity_total = sum(m.get_equity() for m in managers.values())
                else:
                    equity_total = sum(m.get_balance() for m in managers.values())
                reset_daily_tracker_if_new_day(equity_total)
                daily_pnl = equity_total - (_DAILY_TRACKER["start_balance"] or equity_total)
                _DAILY_TRACKER["realized_pnl"] = daily_pnl
                balance_total = equity_total   # compat con código abajo
            except Exception:
                daily_pnl = 0.0

            # ─── Verificar límites diarios (solo pausar nuevas entradas, no la gestión)
            daily_target = cfg.get("daily_profit_target_usdt", 10)
            daily_limit  = cfg.get("daily_loss_limit_usdt", 25)
            if not _DAILY_TRACKER["paused"]:
                if daily_pnl >= daily_target:
                    _DAILY_TRACKER["paused"] = True
                    send_telegram(
                        f"🎯 <b>Objetivo diario alcanzado: +{daily_pnl:.2f} USDT</b>\n"
                        f"No se abrirán nuevas posiciones hasta mañana (UTC).\n"
                        f"Las posiciones activas siguen siendo gestionadas.", cfg
                    )
                elif daily_pnl <= -daily_limit:
                    _DAILY_TRACKER["paused"] = True
                    send_telegram(
                        f"🛑 <b>Límite diario de pérdida: {daily_pnl:.2f} USDT</b>\n"
                        f"Bot pausado hasta mañana (UTC). Posiciones activas siguen gestionadas.", cfg
                    )

            # ─── Estado de killzone y posiciones activas
            killzone     = get_active_killzone(cfg)
            session_ok   = killzone is not None
            kz_name      = killzone["name"] if killzone else "OFF"
            kz_sizing    = killzone["sizing_mult"] if killzone else 0.0
            active_count = sum(
                1 for m in managers.values()
                if m.active_long or getattr(m, "active_standalone_short", None)
            )

            # Cierre obligatorio viernes a las 18:00 UTC
            if is_friday_close_time(cfg):
                for sym, m in managers.items():
                    if m.active_long or getattr(m, "active_standalone_short", None):
                        try:
                            df_e = get_ohlcv(exchange, sym, cfg["timeframe_entry"])
                            m.force_close_all(float(df_e.iloc[-1]["close"]), "viernes_18utc")
                        except Exception as e:
                            logger.warning(f"force_close {sym}: {e}")

            if not session_ok:
                logger.info(f"🌙 Fuera de killzone ({datetime.utcnow().hour:02d}:xx UTC) | "
                            f"PnL hoy: {daily_pnl:+.2f} USDT | Posiciones: {active_count}")

            # ─── Loop por símbolo
            for sym in symbols:
                manager = managers[sym]
                sym_cfg = {**cfg, "symbol": sym}

                try:
                    df_macro = get_ohlcv(exchange, sym, cfg["timeframe_macro"])
                    df_mid   = get_ohlcv(exchange, sym, cfg["timeframe_mid"])
                    df_entry = get_ohlcv(exchange, sym, cfg["timeframe_entry"])
                    # Fase 1: macro bias 1W
                    df_weekly = None
                    if cfg.get("macro_high_enabled", True):
                        try:
                            df_weekly = get_ohlcv(exchange, sym, cfg.get("timeframe_macro_high", "1w"), limit=100)
                        except Exception as e:
                            logger.debug(f"1W fetch error: {e}")

                    df_funding = None
                    if cfg.get("funding_aware_enabled", True):
                        try:
                            df_funding = fetch_funding_rate_history(exchange, sym, limit=50)
                        except Exception as e:
                            logger.debug(f"funding fetch error: {e}")

                    sig   = evaluate_signal(df_macro, df_mid, df_entry, sym_cfg,
                                            df_weekly=df_weekly, df_funding=df_funding)
                    price = sig["current_price"]

                    # Etiquetar killzone en la signal para los managers
                    sig["killzone"] = kz_name

                    logger.info(
                        f"📊 {sym} | {price:.2f} | "
                        f"L: {sig.get('score_adjusted', sig['score'])}/13 ({sig['entry_type']}) | "
                        f"S: {sig.get('score_short_adjusted', 0)}/13 ({sig.get('short_entry_type','none')}) | "
                        f"ADX: {sig['adx']['value']:.1f} | "
                        f"HTF: {sig['smc']['htf_range_pos']:.2f} "
                        f"({'PREM' if sig['smc']['in_premium_mid'] else 'DISC' if sig['smc']['in_discount_mid'] else '—'}) | "
                        f"KZ: {kz_name}"
                    )

                    # Instantánea del ciclo para el panel web. Se publica aquí y
                    # no se recalcula fuera: lo que ve el panel es exactamente lo
                    # que el bot usó para decidir.
                    _ULTIMO_ANALISIS[sym] = {
                        "utc":          datetime.utcnow().isoformat(),
                        "symbol":       sym,
                        "precio":       float(price),
                        "score_long":   int(sig.get("score_adjusted", sig["score"])),
                        "score_short":  int(sig.get("score_short_adjusted", 0)),
                        "tipo_long":    sig.get("entry_type"),
                        "tipo_short":   sig.get("short_entry_type", "none"),
                        "adx":          float(sig["adx"]["value"]),
                        "adx_bull":     bool(sig["adx"].get("bullish", False)),
                        "htf_range_pos": float(sig["smc"]["htf_range_pos"]),
                        "htf_label":    ("PREM" if sig["smc"]["in_premium_mid"]
                                         else "DISC" if sig["smc"]["in_discount_mid"] else "MID"),
                        "killzone":     kz_name,
                        "regimen":      sig.get("regime"),
                        "score_max":    13,
                    }

                    pos = manager.get_positions()
                    standalone_short_active = getattr(manager, "active_standalone_short", None)

                    # ── Procesar fills/cancelaciones de órdenes límite ANTES de abrir nuevas
                    if cfg.get("pending_orders_enabled", True):
                        try:
                            manager.check_pending_fills(df_entry, price, session_ok)
                        except Exception as e:
                            logger.warning(f"check_pending_fills: {e}")

                    # Re-leer estado (un fill recién detectado pudo cambiar active_long/active_standalone_short)
                    pos = manager.get_positions()
                    standalone_short_active = getattr(manager, "active_standalone_short", None)

                    # ── Apertura de nuevas posiciones (LONG o SHORT, no ambas)
                    can_open = (
                        not pos["long"]
                        and not manager.active_long
                        and not standalone_short_active
                        and not _BOT_PAUSED[0]
                        and not _DAILY_TRACKER["paused"]
                        and session_ok
                        and active_count < max_pos
                    )

                    # ── LONG
                    # Fase 2: gate por régimen
                    regime_now = sig.get("regime", "warmup")
                    regime_block = regime_now in cfg.get("regime_block_entries", [])
                    regime_high_conv_only = regime_now in cfg.get("regime_only_high_conviction", [])
                    regime_size_mult = cfg.get("regime_sizing", {}).get(regime_now, 1.0)

                    if can_open and sig["can_long"]:
                        now = datetime.now()
                        skip_reason = None

                        if regime_block:
                            skip_reason = f"Régimen {regime_now} → no operar"
                        elif regime_high_conv_only and sig.get("entry_type") != "A":
                            skip_reason = f"Régimen {regime_now} solo permite tipo A"
                        elif cfg.get("weekend_filter", True) and now.weekday() >= 5:
                            skip_reason = f"Fin de semana — esperando lunes"
                        elif sig.get("block_long_macro"):
                            skip_reason = f"Macro bias 1W bajista — bloqueando longs no high-conviction"
                        elif sig["entry_type"] not in cfg.get("allowed_entry_types", ["A", "B", "C"]):
                            skip_reason = f"Tipo {sig['entry_type']} fuera de la lista operable"
                        elif cfg.get("require_adx_trend", True) and not sig["adx"]["trend"]:
                            skip_reason = f"ADX {sig['adx']['value']:.1f} < 21 — sin tendencia"
                        elif (cfg.get("require_squeeze_off", True)
                              and sig["squeeze_on"] and sig["entry_type"] == "C"):
                            skip_reason = "Squeeze ON — bloquea tipo C, esperando disparo"
                        elif sig.get("distribution_warning"):
                            skip_reason = "Alerta distribución activa"

                        # Capa adaptativa: bloqueo por mal historial del bucket
                        if not skip_reason and ADAPTIVE is not None and cfg.get("adaptive_enabled", True):
                            try:
                                br = ADAPTIVE.block_reason(
                                    "long", sig["entry_type"], kz_name,
                                    now.weekday(), sig.get("regime", "unknown")
                                )
                                if br:
                                    skip_reason = f"adaptive_block: {br}"
                            except Exception as e:
                                logger.debug(f"adaptive block check error: {e}")

                        if skip_reason:
                            logger.info(f"⏸️ {sym} LONG: omitido — {skip_reason}")
                        else:
                            # Sizing adaptativo: combina killzone × DoW × bucket histórico × drawdown
                            adapt_mult = 1.0
                            if ADAPTIVE is not None and cfg.get("adaptive_enabled", True):
                                try:
                                    dd = ADAPTIVE.compute_recent_drawdown_pct()
                                    adapt_mult = ADAPTIVE.sizing_multiplier(
                                        "long", sig["entry_type"], kz_name,
                                        now.weekday(), sig.get("regime", "unknown"),
                                        current_drawdown_pct=dd,
                                    )
                                except Exception as e:
                                    logger.debug(f"adaptive sizing error: {e}")
                            final_mult = (kz_sizing * adapt_mult * regime_size_mult
                                          * sig.get("macro_long_sizing", 1.0)
                                          * sig.get("funding_long_sizing", 1.0)
                                          * sig.get("vwap_long_sizing", 1.0))
                            sig["_adapt_mult"]   = adapt_mult
                            sig["_final_sizing"] = final_mult
                            lunes = " 🌟 Lunes" if now.weekday() == 0 else ""
                            conv  = "ALTA CONVICCIÓN" if sig["high_conviction"] else "ESTÁNDAR"
                            logger.info(f"🟢 {sym} LONG {conv} | Score: {sig.get('score_adjusted', sig['score'])}/13 | "
                                        f"Tipo {sig['entry_type']} | KZ: {kz_name} ×{kz_sizing:.2f} | "
                                        f"adapt ×{adapt_mult:.2f} → final ×{final_mult:.2f}{lunes}")
                            if manager.open_long(price, sig):
                                active_count += 1

                    # ── SHORT standalone (solo si no hay long y shorts habilitados)
                    elif can_open and sig.get("can_short_standalone") and cfg.get("shorts_enabled", True):
                        now = datetime.now()
                        skip_reason = None
                        st_type = sig.get("short_entry_type", "C")

                        if cfg.get("weekend_filter", True) and now.weekday() >= 5:
                            skip_reason = "Fin de semana"
                        elif sig.get("block_short_macro"):
                            skip_reason = f"Macro bias 1W alcista (precio>EMA21W) — bloqueando shorts no high-conviction"
                        elif sig["smc"]["in_discount_mid"]:
                            skip_reason = "En discount HTF — no abrir shorts"
                        elif kz_sizing < 0.5:
                            skip_reason = f"Killzone {kz_name} sizing×{kz_sizing:.2f} < 0.5"

                        # Capa adaptativa para shorts
                        if not skip_reason and ADAPTIVE is not None and cfg.get("adaptive_enabled", True):
                            try:
                                br = ADAPTIVE.block_reason(
                                    "short", st_type, kz_name,
                                    now.weekday(), sig.get("regime", "unknown")
                                )
                                if br:
                                    skip_reason = f"adaptive_block: {br}"
                            except Exception as e:
                                logger.debug(f"adaptive block error: {e}")

                        if skip_reason:
                            logger.info(f"⏸️ {sym} SHORT: omitido — {skip_reason}")
                        else:
                            adapt_mult = 1.0
                            if ADAPTIVE is not None and cfg.get("adaptive_enabled", True):
                                try:
                                    dd = ADAPTIVE.compute_recent_drawdown_pct()
                                    adapt_mult = ADAPTIVE.sizing_multiplier(
                                        "short", st_type, kz_name,
                                        now.weekday(), sig.get("regime", "unknown"),
                                        current_drawdown_pct=dd,
                                    )
                                except Exception as e:
                                    logger.debug(f"adaptive sizing error: {e}")
                            final_mult = (kz_sizing * adapt_mult * regime_size_mult
                                          * sig.get("macro_short_sizing", 1.0)
                                          * sig.get("funding_short_sizing", 1.0)
                                          * sig.get("vwap_short_sizing", 1.0))
                            logger.info(f"🔻 {sym} SHORT | Score: {sig.get('score_short_adjusted')}/13 | "
                                        f"Tipo {st_type} | KZ: {kz_name} ×{kz_sizing:.2f} | "
                                        f"adapt ×{adapt_mult:.2f} → final ×{final_mult:.2f}")
                            if manager.open_short_standalone(price, sig, sizing_mult=final_mult):
                                active_count += 1

                    # ── Armar órdenes límite anticipadas en OB virgen (si no entró ninguna market)
                    if (cfg.get("pending_orders_enabled", True)
                            and can_open
                            and not manager.active_long
                            and not getattr(manager, "active_standalone_short", None)):
                        min_score = cfg.get("pending_min_score", 6)
                        score_long  = sig.get("score_adjusted", sig.get("score", 0)) or 0
                        score_short = sig.get("score_short_adjusted", sig.get("score_short", 0)) or 0

                        # OB virgen del timeframe mid (4H)
                        ob_bull_high = ob_bull_low = ob_bear_high = ob_bear_low = None
                        try:
                            row = df_mid.iloc[-1]
                            if "ob_bull_high" in df_mid.columns and pd.notna(row["ob_bull_high"]):
                                ob_bull_high = float(row["ob_bull_high"])
                            if "ob_bull_low"  in df_mid.columns and pd.notna(row["ob_bull_low"]):
                                ob_bull_low  = float(row["ob_bull_low"])
                            if "ob_bear_high" in df_mid.columns and pd.notna(row["ob_bear_high"]):
                                ob_bear_high = float(row["ob_bear_high"])
                            if "ob_bear_low"  in df_mid.columns and pd.notna(row["ob_bear_low"]):
                                ob_bear_low  = float(row["ob_bear_low"])
                        except Exception as e:
                            logger.debug(f"OB lookup: {e}")

                        if (manager.pending_long is None
                                and score_long >= min_score
                                and not sig["smc"]["in_premium_mid"]
                                and ob_bull_high is not None and ob_bull_low is not None):
                            try:
                                manager.arm_pending_long(price, sig, ob_bull_high, ob_bull_low, kz_name)
                            except Exception as e:
                                logger.warning(f"arm_pending_long: {e}")

                        if (manager.pending_short is None
                                and score_short >= min_score
                                and not sig["smc"]["in_discount_mid"]
                                and ob_bear_high is not None and ob_bear_low is not None
                                and cfg.get("shorts_enabled", True)):
                            try:
                                manager.arm_pending_short(price, sig, ob_bear_high, ob_bear_low, kz_name)
                            except Exception as e:
                                logger.warning(f"arm_pending_short: {e}")

                    # ── Gestión de LONG activo
                    if pos["long"] or manager.active_long:
                        manager.manage_long(price, df_mid, sig, df_entry)
                        if manager.should_hedge(price, df_mid, sig):
                            logger.info(f"⚠️ {sym}: condiciones de cobertura → abriendo SHORT")
                            manager.open_hedge(price)

                    # ── Gestión de cobertura (hedge)
                    if manager.active_short:
                        manager.manage_hedge(price, df_mid)

                    # ── Gestión de SHORT standalone
                    if getattr(manager, "active_standalone_short", None):
                        manager.manage_short_standalone(price, df_mid, sig)

                    # ── Resumen por símbolo
                    if paper:
                        manager.print_summary(price)
                    else:
                        bal = manager.get_balance()
                        logger.info(f"💼 {sym}: {bal:.2f} USDT | DCA: {manager.dca_count} | TPs: {manager.tp_count}")

                except Exception as sym_err:
                    logger.error(f"Error en {sym}: {sym_err}", exc_info=True)
                    continue

            # ─── Resumen global del loop
            # El estado se decide MIRANDO LOS DATOS primero: un bot que no
            # recibe velas no está activo por mucho que el proceso siga vivo.
            salud = salud_datos(cfg)
            if salud["ciego"]:
                estado_txt = f"🔴 SIN DATOS ({salud['fallos_seguidos']} fallos seguidos)"
            elif salud["estado"] == "viejo":
                estado_txt = f"🟠 DATOS VIEJOS ({salud['edad_segundos']:.0f}s)"
            elif _BOT_PAUSED[0] or _DAILY_TRACKER["paused"]:
                estado_txt = "⏸️ PAUSADO"
            else:
                estado_txt = "✅ ACTIVO"

            pnl_sign = "🟢" if daily_pnl >= 0 else "🔴"
            logger.info(
                f"{pnl_sign} PnL hoy: {daily_pnl:+.2f} USDT | "
                f"Posiciones: {active_count}/{max_pos} | "
                f"Sesión: {'✅' if session_ok else '🌙'} | "
                f"Estado: {estado_txt}"
            )
            _save_trade_metrics_snapshot(cfg)

        except KeyboardInterrupt:
            logger.info("🛑 Bot detenido por usuario")
            break
        except ccxt.NetworkError as e:
            logger.warning(f"Error de red: {e} — reintentando en 30s")
            time.sleep(30)
            continue
        except ccxt.ExchangeError as e:
            logger.error(f"Error exchange: {e}")
            time.sleep(60)
            continue
        except Exception as e:
            logger.error(f"Error inesperado: {e}", exc_info=True)
            time.sleep(30)
            continue

        time.sleep(cfg["loop_interval_seconds"])


# ─── MODO SEÑAL (sin operar) ──────────────────────────────────────────────────

def run_signal_only(cfg: dict = CONFIG):
    """Muestra el análisis completo sin abrir posiciones."""
    exchange = get_exchange(cfg)
    df_macro = get_ohlcv(exchange, cfg["symbol"], cfg["timeframe_macro"])
    df_mid   = get_ohlcv(exchange, cfg["symbol"], cfg["timeframe_mid"])
    df_entry = get_ohlcv(exchange, cfg["symbol"], cfg["timeframe_entry"])

    sig = evaluate_signal(df_macro, df_mid, df_entry, cfg)
    report = format_signal_report(sig, cfg["symbol"])
    print(report.replace("<b>", "").replace("</b>", ""))

    print(f"\n── ADX: {sig['adx']['value']} | {'Tendencia ALCISTA' if sig['adx']['bull'] else 'Tendencia BAJISTA' if sig['adx']['bear'] else 'Sin tendencia'}")
    print(f"── Squeeze cuadrante: {df_mid.iloc[-1]['sqz_quadrant']}")
    print(f"── EMA10/55: {df_mid.iloc[-1]['ema10']:.2f} / {df_mid.iloc[-1]['ema55']:.2f}")
    print(f"── Compresión: {df_mid.iloc[-1]['ema_compression']*100:.2f}%")
    print(f"── POC approx: {df_mid.iloc[-1]['vrvp_poc']:.2f}")

    send_telegram(report, cfg)


# ─── BACKTEST ─────────────────────────────────────────────────────────────────

def run_backtest(cfg: dict = CONFIG, initial_capital: float = 1000):
    """Backtest V2 con más histórico, alineación temporal real, fees y slippage."""
    print("Iniciando backtest — descargando datos...")
    exchange = get_exchange(cfg)
    df_macro = get_ohlcv_history(exchange, cfg["symbol"], cfg["timeframe_macro"], cfg.get("backtest_macro_candles", 600))
    df_mid   = get_ohlcv_history(exchange, cfg["symbol"], cfg["timeframe_mid"],   cfg.get("backtest_mid_candles", 1800))
    df_entry = get_ohlcv_history(exchange, cfg["symbol"], cfg["timeframe_entry"], cfg.get("backtest_entry_candles", 2500))

    capital = initial_capital
    trades  = []
    position = None
    min_idx = 60   # Necesitamos al menos 60 velas para todos los indicadores
    fee_pct = cfg.get("backtest_taker_fee_pct", 0.0005)
    slippage_pct = cfg.get("backtest_slippage_pct", 0.0004)

    print(f"Analizando {len(df_entry)} velas de {cfg['timeframe_entry']}...")

    for i in range(min_idx, len(df_entry)):
        ts = df_entry.index[i - 1]
        dm  = df_macro[df_macro.index <= ts]
        dmi = df_mid[df_mid.index <= ts]
        de  = df_entry.iloc[:i]

        if len(dm) < 20 or len(dmi) < 20:
            continue

        sig = evaluate_signal(dm, dmi, de, cfg)
        price = sig["current_price"]

        if position is None:
            if sig["can_long"] and sig["entry_type"] in cfg.get("allowed_entry_types", ["A", "B", "C"]):
                size_mult = 0.5 if sig["score"] <= 8 else 1.0
                if sig["score"] >= 9 and sig["entry_type"] == "A":
                    size_mult = 1.5
                base_margin = capital * cfg["risk_capital_pct"] / cfg["position_parts"]
                initial_margin = base_margin * size_mult
                if initial_margin <= 0 or initial_margin >= capital:
                    continue
                entry_exec = price * (1 + slippage_pct)
                qty = (initial_margin * cfg["leverage"]) / entry_exec
                entry_fee = qty * entry_exec * fee_pct
                capital -= (initial_margin + entry_fee)
                position = {
                    "entry_price": entry_exec,
                    "qty": qty,
                    "remaining_margin": initial_margin,
                    "base_margin": base_margin,
                    "tp_done": set(),
                    "dca_done": set(),
                    "realized_pnl": 0.0,
                    "fees_paid": entry_fee,
                    "entry_time": str(de.index[-1]),
                    "entry_type": sig["entry_type"],
                    "score": sig["score"],
                }
                trades.append({
                    "type": "entry",
                    "price": entry_exec,
                    "score": sig["score"],
                    "entry_type": sig["entry_type"],
                    "fee": round(entry_fee, 4),
                    "date": str(de.index[-1]),
                })

        else:
            entry_price = position["entry_price"]
            pnl = (price - entry_price) / entry_price

            # DCA moderado
            for j, level in enumerate(cfg["dca_levels_pct"]):
                if pnl <= level and j not in position["dca_done"]:
                    add_margin = position["base_margin"] * cfg["dca_size_multipliers"][j]
                    if add_margin >= capital:
                        continue
                    dca_exec = price * (1 + slippage_pct)
                    add_qty = (add_margin * cfg["leverage"]) / dca_exec
                    dca_fee = add_qty * dca_exec * fee_pct
                    total_qty = position["qty"] + add_qty
                    total_margin = position["remaining_margin"] + add_margin
                    position["entry_price"] = (
                        position["entry_price"] * position["qty"] + dca_exec * add_qty
                    ) / total_qty
                    position["qty"] = total_qty
                    position["remaining_margin"] = total_margin
                    position["fees_paid"] += dca_fee
                    capital -= (add_margin + dca_fee)
                    position["dca_done"].add(j)
                    entry_price = position["entry_price"]
                    pnl = (price - entry_price) / entry_price

            # TP parciales
            tp_levels = [
                (cfg["tp1_pct"], 0.20, "tp1"),
                (cfg["tp2_pct"], 0.20, "tp2"),
                (cfg["tp3_pct"], 0.30, "tp3"),
            ]
            for tp_pct, close_pct, label in tp_levels:
                if pnl >= tp_pct and label not in position["tp_done"] and position["qty"] > 0:
                    exit_exec = price * (1 - slippage_pct)
                    close_qty = position["qty"] * close_pct
                    close_margin = position["remaining_margin"] * close_pct
                    exit_fee = close_qty * exit_exec * fee_pct
                    gross_pnl = close_qty * (exit_exec - entry_price)
                    net_realized = gross_pnl - exit_fee
                    capital += close_margin + net_realized
                    position["qty"] -= close_qty
                    close_margin = position["remaining_margin"] * close_pct
                    position["remaining_margin"] -= close_margin
                    position["realized_pnl"] += net_realized
                    position["fees_paid"] += exit_fee
                    position["tp_done"].add(label)

            # Hard stop V2
            if position and cfg.get("enable_hard_stop", True) and pnl <= cfg.get("hard_stop_pct", -0.06):
                exit_exec = price * (1 - slippage_pct)
                exit_fee = position["qty"] * exit_exec * fee_pct
                gross_pnl = position["qty"] * (exit_exec - entry_price)
                net_realized = gross_pnl - exit_fee
                capital += position["remaining_margin"] + net_realized
                trades.append({
                    "type": "loss",
                    "price": exit_exec,
                    "entry": entry_price,
                    "pnl_pct": round(pnl * 100, 2),
                    "loss": round(position["realized_pnl"] + net_realized, 2),
                    "fees_paid": round(position["fees_paid"] + exit_fee, 2),
                    "date": str(de.index[-1]),
                })
                position = None
                continue

            # Cierre cuando ya realizó TP3 o cuando aparece invalidación bajista fuerte
            if position and (len(position["tp_done"]) == 3 or sig["can_short"]):
                exit_exec = price * (1 - slippage_pct)
                exit_fee = position["qty"] * exit_exec * fee_pct
                gross_pnl = position["qty"] * (exit_exec - entry_price)
                net_realized = gross_pnl - exit_fee
                capital += position["remaining_margin"] + net_realized
                total_trade_pnl = position["realized_pnl"] + net_realized
                trade_type = "win" if total_trade_pnl >= 0 else "loss"
                trades.append({
                    "type": trade_type,
                    "price": exit_exec,
                    "entry": entry_price,
                    "pnl_pct": round(pnl * 100, 2),
                    "profit": round(total_trade_pnl, 2),
                    "fees_paid": round(position["fees_paid"] + exit_fee, 2),
                    "date": str(de.index[-1]),
                })
                position = None

    if position:
        final_price = float(df_entry["close"].iloc[-1])
        exit_exec = final_price * (1 - slippage_pct)
        exit_fee = position["qty"] * exit_exec * fee_pct
        gross_pnl = position["qty"] * (exit_exec - position["entry_price"])
        net_realized = gross_pnl - exit_fee
        capital += position["remaining_margin"] + net_realized
        total_trade_pnl = position["realized_pnl"] + net_realized
        trades.append({
            "type": "open_mark_to_market",
            "price": exit_exec,
            "entry": position["entry_price"],
            "pnl_pct": round(((final_price - position["entry_price"]) / position["entry_price"]) * 100, 2),
            "profit": round(total_trade_pnl, 2),
            "fees_paid": round(position["fees_paid"] + exit_fee, 2),
            "date": str(df_entry.index[-1]),
        })

    wins   = [t for t in trades if t["type"] == "win"]
    losses = [t for t in trades if t["type"] == "loss"]
    total_closed = len(wins) + len(losses)
    winrate = len(wins) / total_closed if total_closed > 0 else 0
    ret = (capital - initial_capital) / initial_capital

    result = {
        "symbol": cfg["symbol"],
        "initial_capital": initial_capital,
        "final_capital": round(capital, 2),
        "total_return_pct": round(ret * 100, 2),
        "total_trades": total_closed,
        "wins": len(wins),
        "losses": len(losses),
        "winrate_pct": round(winrate * 100, 1),
        "avg_win_pct": round(np.mean([t["pnl_pct"] for t in wins]), 2) if wins else 0,
        "avg_loss_pct": round(np.mean([t["pnl_pct"] for t in losses]), 2) if losses else 0,
        "fees_model": {
            "taker_fee_pct": fee_pct,
            "slippage_pct": slippage_pct,
        },
        "last_10_trades": trades[-10:],
    }

    with open("jorge_backtest_result.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, default=str)
    pd.DataFrame(trades).to_csv("jorge_backtest_trades.csv", index=False)

    print(json.dumps(result, indent=2, default=str))
    return result


# ─── SEED BUCKETS — backtest que llena el journal adaptativo ─────────────────

def run_seed_buckets(cfg: dict = CONFIG):
    """Replay histórico con la lógica V3 (killzones + SMC + shorts).

    Escribe TODOS los eventos al journal `jorge_backtest_journal.csv` con tags
    (killzone, dow, regime). La capa adaptativa puede leer este archivo como
    cold-start hasta que haya suficiente data live.

    Para cada vela del entry tf:
      - Calcula killzone/dow/regime
      - Si hay setup long/short válido y no hay posición activa → abre
      - Si hay posición activa → simula DCA/TP/hard-stop walk-forward

    Nota: usa thresholds RELAJADOS (min_score=5 vs 7 en producción) para
    poblar más buckets durante el cold-start. Los buckets resultantes son
    sesgados optimistamente — solo úsalos para forma, no para rendimiento exacto.
    """
    print("─" * 60)
    print("SEED BUCKETS — replay histórico con lógica V3 (modo cold-start)")
    print("─" * 60)
    bt_journal = "jorge_backtest_journal.csv"
    bt_cfg = {**cfg,
              "trade_journal_file": bt_journal,
              "metrics_file": "jorge_backtest_metrics.json",
              "paper_trading": True,
              "telegram_token": "",        # silenciar telegram durante backtest
              "telegram_chat_id": "",
              # Thresholds relajados para generar más muestras
              "min_score_to_enter": 5,
              "min_score_short": 5,
              # Más histórico
              "backtest_entry_candles": 5000,
              "backtest_mid_candles":   2500,
              "backtest_macro_candles": 800,
              "adaptive_enabled": False}

    # Limpiar journal previo del backtest
    if os.path.exists(bt_journal):
        os.rename(bt_journal, bt_journal + ".bak")
        print(f"  Backup previo: {bt_journal}.bak")

    print(f"  Descargando histórico para {cfg['symbol']}...")
    exchange = get_exchange(cfg)
    df_macro = get_ohlcv_history(exchange, cfg["symbol"], cfg["timeframe_macro"], cfg.get("backtest_macro_candles", 600))
    df_mid   = get_ohlcv_history(exchange, cfg["symbol"], cfg["timeframe_mid"],   cfg.get("backtest_mid_candles", 1800))
    df_entry = get_ohlcv_history(exchange, cfg["symbol"], cfg["timeframe_entry"], cfg.get("backtest_entry_candles", 2500))
    df_weekly = None
    if bt_cfg.get("macro_high_enabled", True):
        try:
            df_weekly = get_ohlcv_history(exchange, cfg["symbol"], bt_cfg.get("timeframe_macro_high", "1w"), 200)
            print(f"  Velas 1W para macro bias: {len(df_weekly)}")
        except Exception as e:
            print(f"  ⚠️  No se pudo cargar 1W para macro bias: {e}")

    df_funding = None
    if bt_cfg.get("funding_aware_enabled", True):
        try:
            df_funding = fetch_funding_rate_history(exchange, cfg["symbol"], limit=500)
            if len(df_funding) > 0:
                print(f"  Funding rate histórico: {len(df_funding)} entries (cada 8h)")
            else:
                print("  ⚠️  Funding rate vacío — saltando feature")
        except Exception as e:
            print(f"  ⚠️  No se pudo cargar funding rate: {e}")

    print(f"  Velas entry: {len(df_entry)} | mid: {len(df_mid)} | macro: {len(df_macro)}")

    manager = PaperPositionManager(bt_cfg)
    manager._paper_tag = "[BT]"   # tag distinto en logs

    n_long = n_short = n_skipped_kz = 0
    min_idx = 60
    last_log = 0

    for i in range(min_idx, len(df_entry)):
        ts = df_entry.index[i - 1]
        try:
            dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else datetime.fromisoformat(str(ts))
        except Exception:
            continue

        # Progreso cada 200 velas
        if i - last_log >= 200:
            print(f"    [{i}/{len(df_entry)}] {dt.strftime('%Y-%m-%d %H:%M')} "
                  f"| L: {n_long} | S: {n_short} | bal: {manager.balance:.2f}")
            last_log = i

        kz = get_active_killzone(bt_cfg, dt)
        dm  = df_macro[df_macro.index <= ts]
        dmi = df_mid[df_mid.index <= ts]
        de  = df_entry.iloc[:i]

        if len(dm) < 20 or len(dmi) < 20:
            continue

        # Macro bias 1W (Fase 1): cortar df_weekly al timestamp actual del backtest
        dw = None
        if df_weekly is not None:
            dw = df_weekly[df_weekly.index <= ts]
        try:
            sig = evaluate_signal(dm, dmi, de, bt_cfg, df_weekly=dw,
                                  df_funding=df_funding, current_ts=ts)
        except Exception:
            continue
        sig["killzone"] = kz["name"] if kz else "OFF"
        sig["_dow_override"] = dt.weekday()    # del candle histórico, no de ahora
        price = sig["current_price"]

        # Manejar posiciones activas siempre (DCA/TP/stop), independiente del killzone
        if manager.active_long:
            try:
                manager.manage_long(price, dmi, sig, de)
            except Exception as e:
                pass
        if manager.active_standalone_short:
            try:
                manager.manage_short_standalone(price, dmi, sig)
            except Exception:
                pass

        # Solo abrir nuevas si killzone activa
        if kz is None:
            n_skipped_kz += 1
            continue

        kz_sizing = kz["sizing_mult"]
        can_open = (
            not manager.active_long
            and not manager.active_standalone_short
        )
        if not can_open:
            continue

        # Fase 2: filtro régimen + multiplicador de sizing
        regime_now = sig.get("regime", "warmup")
        regime_block = regime_now in bt_cfg.get("regime_block_entries", [])
        regime_high_conv_only = regime_now in bt_cfg.get("regime_only_high_conviction", [])
        regime_size_mult = bt_cfg.get("regime_sizing", {}).get(regime_now, 1.0)

        if regime_block:
            continue   # quiet régime → no operar

        # LONG (régimen + macro 1W + killzone + funding + VWAP)
        if (sig["can_long"]
                and sig["entry_type"] in cfg.get("allowed_entry_types", ["A", "B", "C"])
                and not (regime_high_conv_only and sig.get("entry_type") != "A")):
            sig["_adapt_mult"]   = 1.0
            sig["_final_sizing"] = (
                kz_sizing
                * sig.get("macro_long_sizing", 1.0)
                * regime_size_mult
                * sig.get("funding_long_sizing", 1.0)
                * sig.get("vwap_long_sizing", 1.0)
            )
            try:
                if manager.open_long(price, sig):
                    n_long += 1
            except Exception:
                pass
        # SHORT
        elif (sig.get("can_short_standalone") and bt_cfg.get("shorts_enabled", True)
                and not (regime_high_conv_only and sig.get("short_entry_type") != "A_sweep")):
            short_size = (
                kz_sizing
                * sig.get("macro_short_sizing", 1.0)
                * regime_size_mult
                * sig.get("funding_short_sizing", 1.0)
                * sig.get("vwap_short_sizing", 1.0)
            )
            try:
                if manager.open_short_standalone(price, sig, sizing_mult=short_size):
                    n_short += 1
            except Exception:
                pass

    # Forzar cierre al final del backtest (precio final)
    if df_entry is not None and len(df_entry) > 0:
        manager.force_close_all(float(df_entry.iloc[-1]["close"]), reason="backtest_end")

    print()
    print("─" * 60)
    print(f"✅ Backtest completo")
    print(f"   Longs abiertos:  {n_long}")
    print(f"   Shorts abiertos: {n_short}")
    print(f"   Velas omitidas (fuera de killzone): {n_skipped_kz}")
    print(f"   Balance final: {manager.balance:.2f} USDT (inicial {bt_cfg['total_capital_usdt']})")
    print(f"   PnL: {manager.balance - bt_cfg['total_capital_usdt']:+.2f} USDT "
          f"({(manager.balance/bt_cfg['total_capital_usdt']-1)*100:+.2f}%)")
    print(f"   Journal escrito: {bt_journal}")
    print("─" * 60)

    # Resumen de buckets generados
    if ADAPTIVE is not None:
        print("\n📊 BUCKETS GENERADOS:")
        bt_adaptive_cfg = {**ADAPTIVE.ADAPTIVE_CONFIG, "trade_journal_file": bt_journal}
        try:
            print(ADAPTIVE.summarize(bt_adaptive_cfg))
        except Exception as e:
            print(f"  (error generando resumen: {e})")

    return manager.balance


# ─── MONITOR PnL EN VIVO ─────────────────────────────────────────────────────

def _build_pnl_report(exchange: ccxt.Exchange, cfg: dict) -> str:
    paper = cfg.get("paper_trading", True)

    ticker = exchange.fetch_ticker(cfg["symbol"])
    price  = ticker["last"]

    # Posiciones y balance: en paper se leen de los managers en memoria;
    # en real se piden al exchange (requiere apiKey).
    if paper:
        mgr = _PAPER_MANAGERS.get(cfg["symbol"])
        positions_view = []
        total_balance  = 0.0
        if mgr is not None:
            total_balance = float(getattr(mgr, "balance", cfg["total_capital_usdt"]))
            if mgr.active_long:
                positions_view.append({
                    "side": "long",
                    "contracts": float(mgr.active_long.get("size", 0)),
                    "entry": float(mgr.active_long.get("entry_price", price)),
                })
            if getattr(mgr, "active_standalone_short", None):
                positions_view.append({
                    "side": "short",
                    "contracts": float(mgr.active_standalone_short.get("size", 0)),
                    "entry": float(mgr.active_standalone_short.get("entry_price", price)),
                })
        usdt_free  = total_balance
        usdt_total = total_balance
    else:
        bal = exchange.fetch_balance()
        usdt_free  = bal["USDT"]["free"]
        usdt_total = bal["USDT"]["total"]
        ex_positions = exchange.fetch_positions([cfg["symbol"]])
        positions_view = []
        for p in ex_positions:
            contracts = float(p.get("contracts") or 0)
            if contracts <= 0:
                continue
            positions_view.append({
                "side": p["side"],
                "contracts": contracts,
                "entry": float(p["entryPrice"]),
                "unrealized": float(p.get("unrealizedPnl") or 0),
                "liq": float(p.get("liquidationPrice") or 0),
                "leverage": int(float(p.get("leverage") or cfg["leverage"])),
            })

    tag = "[PAPER]" if paper else ""
    lines = [
        f"📊 <b>PnL EN VIVO — {cfg['symbol']}</b> {tag}".strip(),
        f"Precio actual: <b>{price:,.2f} USDT</b>",
        f"",
    ]

    has_pos = False
    for pv in positions_view:
        has_pos = True
        side     = pv["side"].upper()
        entry    = pv["entry"]
        contracts = pv["contracts"]
        leverage = pv.get("leverage", cfg["leverage"])
        pnl_pct  = ((price - entry) / entry * 100) if side == "LONG" else ((entry - price) / entry * 100)
        # En paper, no hay unrealized del exchange — lo calculamos
        pnl_usdt = pv.get("unrealized")
        if pnl_usdt is None:
            pnl_usdt = contracts * (price - entry) if side == "LONG" else contracts * (entry - price)
        liq      = pv.get("liq", 0.0)
        arrow    = "🟢" if pnl_usdt >= 0 else "🔴"

        lines += [
            f"{arrow} <b>{side}</b> | {contracts} BTC × {leverage}x",
            f"  Entrada:      {entry:,.2f}",
            f"  PnL:          <b>{pnl_usdt:+.2f} USDT  ({pnl_pct:+.2f}%)</b>",
        ]
        if liq:
            lines.append(f"  Liquidación:  {liq:,.2f}")
        lines.append("")

        # Próximos DCA (solo LONG)
        if side == "LONG":
            multipliers = cfg.get("dca_size_multipliers", [1, 1, 1, 1])
            dca_hits = []
            for j, lvl in enumerate(cfg["dca_levels_pct"]):
                dca_price = entry * (1 + lvl)
                dist = ((price - dca_price) / price) * 100
                mult = multipliers[j] if j < len(multipliers) else 1.0
                dca_hits.append(f"    DCA{j+1} {int(lvl*100)}% ({mult}x)  →  {dca_price:,.0f}  (faltan {dist:.1f}%)")
            lines.append("  Niveles DCA:")
            lines += dca_hits
            lines.append("")

        # Próximos TP (solo LONG)
        if side == "LONG":
            lev = cfg["leverage"]
            tp_data = [
                (cfg["tp1_pct"], 20, "TP1"),
                (cfg["tp2_pct"], 20, "TP2"),
                (cfg["tp3_pct"], 30, "TP3"),
            ]
            lines.append("  Take Profits:")
            for tp_pct, close_pct, label in tp_data:
                tp_price = entry * (1 + tp_pct)
                dist = ((tp_price - price) / price) * 100
                margin_ret = int(tp_pct * lev * 100)
                lines.append(f"    {label} +{int(tp_pct*100)}% ({margin_ret}%/margen)  →  {tp_price:,.0f}  ({dist:+.1f}%)")
            lines.append("")

            # Nivel de cobertura
            hedge_price = entry * (1 + cfg.get("hedge_loss_trigger_pct", -0.20))
            hedge_dist  = ((hedge_price - price) / price) * 100
            lines.append(f"  🛡️ Cobertura activa si cae a: {hedge_price:,.0f} ({hedge_dist:+.1f}%)")
            lines.append("")

    if not has_pos:
        lines.append("Sin posiciones abiertas")
        lines.append("")

    # Órdenes límite pendientes (capa de pending orders en OB virgen)
    if paper:
        mgr = _PAPER_MANAGERS.get(cfg["symbol"])
        if mgr is not None:
            if getattr(mgr, "pending_long", None):
                pl = mgr.pending_long
                lines.append(f"📌 Límite LONG  pendiente @ {pl['price']:,.2f} | KZ: {pl.get('killzone','?')}")
            if getattr(mgr, "pending_short", None):
                ps = mgr.pending_short
                lines.append(f"📌 Límite SHORT pendiente @ {ps['price']:,.2f} | KZ: {ps.get('killzone','?')}")
            if mgr.pending_long or mgr.pending_short:
                lines.append("")

    # PnL del día (desde _DAILY_TRACKER)
    if _DAILY_TRACKER.get("start_balance") is not None:
        daily_pnl = usdt_total - _DAILY_TRACKER["start_balance"]
        sign = "🟢" if daily_pnl >= 0 else "🔴"
        lines.append(f"{sign} PnL hoy: <b>{daily_pnl:+.2f} USDT</b>")

    lines += [
        f"💼 Balance libre:  <b>{usdt_free:,.2f} USDT</b>",
        f"   Balance total:  {usdt_total:,.2f} USDT",
    ]
    return "\n".join(lines)


def run_pnl_monitor(cfg: dict = CONFIG):
    """Muestra el PnL en vivo en terminal, refresca cada 5 s. Ctrl+C para salir."""
    exchange = get_exchange(cfg)
    print("Monitoreando PnL — Ctrl+C para salir\n")
    try:
        while True:
            report = _build_pnl_report(exchange, cfg)
            # Limpiar pantalla y mostrar
            print("\033[2J\033[H", end="")
            print(report.replace("<b>", "").replace("</b>", ""))
            print(f"\n  Actualizado: {datetime.now().strftime('%H:%M:%S')}  (refresca cada 5s)")
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nMonitor detenido.")


# ─── TELEGRAM COMMAND LISTENER ────────────────────────────────────────────────

def _close_all_positions(cfg: dict) -> str:
    """Cierra todas las posiciones abiertas. Retorna resumen de lo cerrado."""
    try:
        exchange = get_exchange(cfg)
        positions = exchange.fetch_positions([cfg["symbol"]])
        closed = []
        for p in positions:
            contracts = float(p.get("contracts") or 0)
            if contracts <= 0:
                continue
            side = p["side"]
            if side == "long":
                exchange.create_order(cfg["symbol"], "market", "sell", contracts,
                                      params={"positionSide": "LONG", "reduceOnly": True})
                closed.append(f"LONG {contracts} BTC")
            elif side == "short":
                exchange.create_order(cfg["symbol"], "market", "buy", contracts,
                                      params={"positionSide": "SHORT", "reduceOnly": True})
                closed.append(f"SHORT {contracts} BTC")
        # Limpiar estado en disco
        try:
            import os; os.remove(STATE_FILE)
        except Exception:
            pass
        return "\n".join(closed) if closed else "Sin posiciones abiertas"
    except Exception as e:
        return f"Error: {e}"


def start_daily_summary(cfg: dict):
    """Hilo que envía resumen a las 8:00 AM cada día."""
    import threading

    def _daily():
        last_sent_date = None
        while True:
            now = datetime.now()
            if now.hour == 8 and now.minute == 0 and now.date() != last_sent_date:
                try:
                    exchange = get_exchange(cfg)
                    report   = _build_pnl_report(exchange, cfg)
                    send_telegram(f"☀️ <b>Resumen diario — {now.strftime('%d/%m/%Y')}</b>\n\n{report}", cfg)
                    last_sent_date = now.date()
                except Exception as e:
                    logger.warning(f"Error resumen diario: {e}")
            time.sleep(30)

    threading.Thread(target=_daily, daemon=True).start()


def start_telegram_listener(cfg: dict):
    """
    Hilo que escucha comandos Telegram:
      /pnl     → posición actual y PnL en vivo
      /signal  → análisis de señal actual (sin operar)
      /close   → cierra todas las posiciones
      /pause   → pausa apertura de nuevas posiciones
      /resume  → reanuda el bot
      /status  → estado del bot
      /help    → lista de comandos
    """
    import threading

    token   = cfg.get("telegram_token", "")
    chat_id = str(cfg.get("telegram_chat_id", ""))
    if not token or not chat_id:
        return

    offset       = [0]
    pending_close = [False]   # confirmación pendiente de /close

    def _listen():
        while True:
            try:
                url = f"https://api.telegram.org/bot{token}/getUpdates"
                r = requests.get(url, params={"offset": offset[0], "timeout": 20}, timeout=25)
                updates = r.json().get("result", [])
                for upd in updates:
                    offset[0] = upd["update_id"] + 1
                    msg     = upd.get("message", {})
                    from_id = str(msg.get("chat", {}).get("id", ""))
                    text    = msg.get("text", "").strip().lower()
                    if from_id != chat_id:
                        continue

                    if text == "/pnl":
                        try:
                            exchange = get_exchange(cfg)
                            report   = _build_pnl_report(exchange, cfg)
                            send_telegram(report, cfg)
                        except Exception as e:
                            send_telegram(f"Error obteniendo PnL: {e}", cfg)

                    elif text in ("/signal", "/analisis"):
                        try:
                            syms = cfg.get("symbols", [cfg["symbol"]])
                            send_telegram(f"⏳ Analizando {len(syms)} par(es)...", cfg)
                            exchange_tmp = get_exchange(cfg)
                            for s in syms:
                                try:
                                    s_cfg    = {**cfg, "symbol": s}
                                    df_macro = get_ohlcv(exchange_tmp, s, cfg["timeframe_macro"])
                                    df_mid   = get_ohlcv(exchange_tmp, s, cfg["timeframe_mid"])
                                    df_entry = get_ohlcv(exchange_tmp, s, cfg["timeframe_entry"])
                                    sig      = evaluate_signal(df_macro, df_mid, df_entry, s_cfg)
                                    report   = format_signal_report(sig, s)
                                    send_telegram(report, cfg)
                                except Exception as se:
                                    send_telegram(f"Error analizando {s}: {se}", cfg)
                        except Exception as e:
                            send_telegram(f"Error en análisis: {e}", cfg)

                    elif text == "/pause":
                        _BOT_PAUSED[0] = True
                        send_telegram(
                            "⏸️ <b>Bot en pausa</b>\n"
                            "No se abrirán nuevas posiciones.\n"
                            "Las posiciones activas siguen siendo gestionadas.\n"
                            "Usa /resume para reactivar.",
                            cfg
                        )

                    elif text == "/resume":
                        _BOT_PAUSED[0] = False
                        send_telegram("▶️ <b>Bot reactivado</b> — volviendo a buscar entradas.", cfg)

                    elif text == "/close":
                        pending_close[0] = True
                        send_telegram(
                            "⚠️ <b>¿Cerrar todas las posiciones?</b>\n"
                            "Responde /confirmar para ejecutar o /cancelar para abortar.",
                            cfg
                        )

                    elif text == "/confirmar" and pending_close[0]:
                        pending_close[0] = False
                        resultado = _close_all_positions(cfg)
                        send_telegram(f"🔴 <b>Posiciones cerradas:</b>\n{resultado}", cfg)

                    elif text == "/cancelar":
                        pending_close[0] = False
                        send_telegram("Operación cancelada.", cfg)

                    elif text == "/status":
                        paused_reason = ""
                        if _BOT_PAUSED[0]:
                            estado = "⏸️ EN PAUSA (manual)"
                        elif _DAILY_TRACKER.get("paused"):
                            pnl_val = _DAILY_TRACKER.get("realized_pnl", 0)
                            target  = cfg.get("daily_profit_target_usdt", 10)
                            estado  = f"⏸️ PAUSADO — {'🎯 objetivo alcanzado' if pnl_val >= target else '🛑 límite pérdida'}"
                        else:
                            estado = "✅ ACTIVO"
                        pnl     = _DAILY_TRACKER.get("realized_pnl", 0)
                        target  = cfg.get("daily_profit_target_usdt", 10)
                        syms    = cfg.get("symbols", [cfg["symbol"]])
                        session = "✅ activa" if is_session_active(cfg) else "🌙 fuera de sesión"
                        send_telegram(
                            f"<b>Estado del bot</b>\n"
                            f"{estado}\n"
                            f"Pares: {', '.join(syms)}\n"
                            f"Capital: {cfg['total_capital_usdt']} USDT | {cfg['leverage']}x\n"
                            f"PnL hoy: <b>{pnl:+.2f} USDT</b> / objetivo {target} USDT\n"
                            f"Sesión: {session}\n"
                            f"Usa /pnl para posiciones | /signal para análisis",
                            cfg
                        )

                    elif text == "/adaptive":
                        if ADAPTIVE is None:
                            send_telegram("Capa adaptativa no disponible.", cfg)
                        else:
                            try:
                                send_telegram(ADAPTIVE.summarize(), cfg)
                            except Exception as e:
                                send_telegram(f"Error capa adaptativa: {e}", cfg)

                    elif text == "/killzone":
                        kz = get_active_killzone(cfg)
                        if kz:
                            send_telegram(
                                f"📍 Killzone activa: <b>{kz['name']}</b>\n"
                                f"Sizing total: ×{kz['sizing_mult']:.2f}\n"
                                f"DoW mult: ×{kz.get('dow_mult', 1.0):.2f}",
                                cfg
                            )
                        else:
                            now = datetime.utcnow()
                            send_telegram(
                                f"🌙 Fuera de killzone — {now.strftime('%H:%M UTC')} ({['Lun','Mar','Mié','Jue','Vie','Sáb','Dom'][now.weekday()]})",
                                cfg
                            )

                    elif text == "/regime":
                        try:
                            ex_tmp = get_exchange(cfg)
                            syms = cfg.get("symbols", [cfg["symbol"]])
                            lines = ["<b>📈 Régimen actual por par:</b>"]
                            for s in syms:
                                df_mid = get_ohlcv(ex_tmp, s, cfg["timeframe_mid"])
                                df_e   = get_ohlcv(ex_tmp, s, cfg["timeframe_entry"])
                                last_m = df_mid.iloc[-1]
                                last_e = df_e.iloc[-1]
                                regime = str(last_m.get("regime", "unknown"))
                                atr_p  = float(last_m.get("atr_pct", 0) or 0)
                                htf    = float(last_m.get("htf_range_pos", 0.5) or 0.5)
                                pd_zone = "PREMIUM" if last_m.get("in_premium") else "DISCOUNT" if last_m.get("in_discount") else "MID"
                                sweep  = ("⬆️sweep_high" if last_e.get("sweep_high_recent") else
                                          "⬇️sweep_low"  if last_e.get("sweep_low_recent")  else "—")
                                emoji = {"expansion":"🚀","trending":"📈","ranging":"↔️","exhaustion":"💀","warmup":"⏳"}.get(regime, "❓")
                                lines.append(
                                    f"<b>{s}</b>: {emoji} {regime.upper()}\n"
                                    f"  ATR pct: {atr_p:.0%} | HTF: {htf:.2f} ({pd_zone}) | Sweep: {sweep}"
                                )
                            send_telegram("\n".join(lines), cfg)
                        except Exception as e:
                            send_telegram(f"Error /regime: {e}", cfg)

                    elif text == "/buckets":
                        if ADAPTIVE is None:
                            send_telegram("Capa adaptativa no disponible.", cfg)
                        else:
                            try:
                                buckets = ADAPTIVE.load_buckets()
                                if not buckets:
                                    send_telegram("📊 Sin trades cerrados aún en la ventana.", cfg)
                                else:
                                    rows = sorted(buckets.values(),
                                                  key=lambda b: (b.trades, b.expectancy_usdt),
                                                  reverse=True)
                                    lines = [f"<b>📊 Todos los buckets ({len(rows)}):</b>"]
                                    for b in rows[:20]:
                                        block = ADAPTIVE.block_reason(
                                            b.side, b.entry_type, b.killzone,
                                            int(b.dow) if b.dow.isdigit() else 0, b.regime
                                        )
                                        flag = "🚫" if block else "✅"
                                        lines.append(
                                            f"{flag} {b.side[:1]}/{b.entry_type}/{b.killzone[:6]}/dow={b.dow}/{b.regime[:5]}: "
                                            f"{b.trades}t WR{b.win_rate:.0%} PF{b.profit_factor:.2f} "
                                            f"exp{b.expectancy_usdt:+.1f}"
                                        )
                                    send_telegram("\n".join(lines), cfg)
                            except Exception as e:
                                send_telegram(f"Error /buckets: {e}", cfg)

                    elif text == "/diag":
                        try:
                            now = datetime.utcnow()
                            kz  = get_active_killzone(cfg)
                            kz_name = kz["name"] if kz else "OFF"
                            kz_size = kz["sizing_mult"] if kz else 0.0
                            dow_names = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]
                            dd = ADAPTIVE.compute_recent_drawdown_pct() if ADAPTIVE else 0.0
                            buckets_count = len(ADAPTIVE.load_buckets()) if ADAPTIVE else 0
                            n_managers = len(cfg.get("symbols", [cfg["symbol"]]))
                            lines = [
                                f"<b>🔧 DIAGNÓSTICO COMPLETO</b>",
                                f"",
                                f"<b>⏰ Tiempo</b>",
                                f"  UTC: {now.strftime('%Y-%m-%d %H:%M')} ({dow_names[now.weekday()]})",
                                f"  Killzone: {kz_name} (×{kz_size:.2f})",
                                f"  Es viernes cierre: {'sí' if is_friday_close_time(cfg) else 'no'}",
                                f"",
                                f"<b>💰 Capital</b>",
                                f"  Capital base: {cfg['total_capital_usdt']} USDT",
                                f"  Leverage: {cfg['leverage']}x",
                                f"  Drawdown 7d: {dd:.2f}%",
                                f"  PnL hoy: {_DAILY_TRACKER.get('realized_pnl', 0):+.2f} USDT",
                                f"  Objetivo: +{cfg.get('daily_profit_target_usdt',15)} | Límite: -{cfg.get('daily_loss_limit_usdt',15)}",
                                f"",
                                f"<b>🎯 Filtros activos</b>",
                                f"  Killzones: {'✅' if cfg.get('killzones_enabled') else '❌'}",
                                f"  SMC: {'✅' if cfg.get('smc_enabled') else '❌'}",
                                f"  Shorts: {'✅' if cfg.get('shorts_enabled') else '❌'}",
                                f"  Adaptativa: {'✅' if cfg.get('adaptive_enabled', True) and ADAPTIVE else '❌'}",
                                f"  Min score long: {cfg.get('min_score_to_enter')}",
                                f"  Min score short: {cfg.get('min_score_short', 7)}",
                                f"",
                                f"<b>📊 Estado</b>",
                                f"  Pares monitoreados: {n_managers}",
                                f"  Buckets en journal: {buckets_count}",
                                f"  Bot pausado manual: {'sí' if _BOT_PAUSED[0] else 'no'}",
                                f"  Bot pausado diario: {'sí' if _DAILY_TRACKER.get('paused') else 'no'}",
                            ]
                            send_telegram("\n".join(lines), cfg)
                        except Exception as e:
                            send_telegram(f"Error /diag: {e}", cfg)

                    elif text == "/help":
                        send_telegram(
                            "<b>Comandos disponibles:</b>\n"
                            "<b>Posiciones:</b>\n"
                            "/pnl       — posición actual y PnL\n"
                            "/signal    — análisis de señal actual\n"
                            "/close     — cerrar todas las posiciones\n"
                            "<b>Control:</b>\n"
                            "/pause     — pausar apertura de nuevas posiciones\n"
                            "/resume    — reactivar el bot\n"
                            "/status    — estado del bot\n"
                            "<b>Análisis V3:</b>\n"
                            "/regime    — régimen de mercado por par\n"
                            "/killzone  — killzone activa ahora\n"
                            "/adaptive  — top/worst buckets adaptativos\n"
                            "/buckets   — todos los buckets detallados\n"
                            "/diag      — diagnóstico completo\n"
                            "/help      — esta ayuda",
                            cfg
                        )
            except Exception:
                pass
            time.sleep(1)

    threading.Thread(target=_listen, daemon=True).start()


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "live"

    if mode == "backtest":
        run_backtest(CONFIG)
    elif mode == "seed_buckets":
        run_seed_buckets(CONFIG)
    elif mode == "signal":
        run_signal_only(CONFIG)
    elif mode == "pnl":
        run_pnl_monitor(CONFIG)
    elif mode == "dry-run":
        run_bot(CONFIG)
    else:
        start_telegram_listener(CONFIG)
        start_daily_summary(CONFIG)
        # Wrapper de auto-recuperación: si run_bot cae por excepción (ej. geo-block
        # persistente, network drop), espera 60s y reinicia el loop. Solo se rinde
        # con KeyboardInterrupt explícito del usuario.
        crash_count = 0
        last_crash_time = 0
        while True:
            try:
                run_bot(CONFIG)
                break   # exit limpio
            except KeyboardInterrupt:
                logger.info("🛑 Bot detenido por usuario (Ctrl-C)")
                break
            except Exception as fatal_err:
                now_ts = time.time()
                # Si hubo crash hace <5 min, contar como racha
                if now_ts - last_crash_time < 300:
                    crash_count += 1
                else:
                    crash_count = 1
                last_crash_time = now_ts
                logger.error(f"💥 run_bot crashed (#{crash_count}): {fatal_err}", exc_info=True)
                try:
                    send_telegram(
                        f"⚠️ <b>Bot crash #{crash_count}</b>\n"
                        f"{type(fatal_err).__name__}: {fatal_err}\n"
                        f"Reiniciando en 60s...",
                        CONFIG
                    )
                except Exception:
                    pass
                # Backoff exponencial si las caídas se repiten rápido
                wait_s = min(600, 60 * (2 ** min(crash_count - 1, 4)))
                logger.info(f"⏳ Esperando {wait_s}s antes de reintentar...")
                time.sleep(wait_s)
