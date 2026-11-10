"""Cartera simulada: contado + perpetuos, con comisiones, deslizamiento y financiación.

Es la contabilidad del bot en modo simulación. La regla es que nada se regale:
cada operación paga comisión y deslizamiento, y cada corto o largo en perpetuo
paga o cobra la financiación real. La simulación anterior no descontaba nada de
eso, y por eso sus números eran mejores que los que habría dado una cuenta.

Patrimonio = USDT + valor del contado + ganancia no realizada de los perpetuos.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# Por lado, sobre el nocional. Mismos números que la investigación.
COMISION_CONTADO = 0.0010
COMISION_PERP = 0.0005
DESLIZAMIENTO = 0.0002

CAMPOS_DIARIO = ["utc", "simbolo", "pata", "lado", "cantidad", "precio", "nocional",
                 "comision", "pnl_realizado", "motivo", "usdt", "patrimonio"]


@dataclass
class Perp:
    cantidad: float = 0.0        # con signo: negativo = corto
    entrada: float = 0.0         # precio medio de entrada


@dataclass
class Cartera:
    usdt: float
    contado: dict = field(default_factory=dict)      # simbolo -> cantidad
    perp: dict = field(default_factory=dict)         # simbolo -> Perp
    capital_inicial: float = 0.0
    comisiones: float = 0.0
    financiacion: float = 0.0                        # neta COBRADA (negativa = pagada)
    pnl_realizado: float = 0.0
    ultimo_funding_ms: dict = field(default_factory=dict)
    ruta_diario: Optional[str] = None
    creada_utc: str = ""

    # ── valoración ────────────────────────────────────────────────────────────

    def no_realizado(self, precios: dict) -> float:
        return sum(p.cantidad * (precios[s] - p.entrada)
                   for s, p in self.perp.items() if p.cantidad and s in precios)

    def valor_contado(self, precios: dict) -> float:
        return sum(q * precios[s] for s, q in self.contado.items() if q and s in precios)

    def patrimonio(self, precios: dict) -> float:
        return self.usdt + self.valor_contado(precios) + self.no_realizado(precios)

    def pesos(self, precios: dict) -> dict:
        """Peso de cada pata sobre el patrimonio: {simbolo: (contado, perp)}."""
        pat = self.patrimonio(precios)
        if pat <= 0:
            return {}
        out = {}
        for s in set(self.contado) | set(self.perp):
            if s not in precios:
                continue
            q = self.contado.get(s, 0.0)
            p = self.perp.get(s, Perp()).cantidad
            out[s] = (q * precios[s] / pat, p * precios[s] / pat)
        return out

    def nocional_perp(self, precios: dict) -> float:
        return sum(abs(p.cantidad) * precios[s] for s, p in self.perp.items() if s in precios)

    def colchon_margen(self, precios: dict) -> float:
        """Garantía disponible para los perpetuos, como fracción de su nocional.

        La garantía son los USDT más lo que los perpetuos llevan ganado o perdido.
        Por debajo de ~0,1 una cuenta real estaría cerca de la liquidación.
        """
        noc = self.nocional_perp(precios)
        if noc <= 0:
            return float("inf")
        return (self.usdt + self.no_realizado(precios)) / noc

    # ── operaciones ───────────────────────────────────────────────────────────

    def operar_contado(self, simbolo: str, cantidad: float, precio: float, motivo: str,
                       precios: Optional[dict] = None) -> dict:
        """Compra (cantidad > 0) o vende contado a mercado."""
        if cantidad == 0:
            return {}
        tengo = self.contado.get(simbolo, 0.0)
        if cantidad < 0:
            cantidad = -min(-cantidad, tengo)      # no se vende lo que no hay
            if cantidad == 0:
                return {}
        ejec = precio * (1 + DESLIZAMIENTO) if cantidad > 0 else precio * (1 - DESLIZAMIENTO)
        nocional = abs(cantidad) * ejec
        comision = nocional * COMISION_CONTADO
        if cantidad > 0 and nocional + comision > self.usdt:
            # Sin USDT suficientes se compra lo que alcance.
            factor = max(self.usdt, 0.0) / (nocional + comision)
            cantidad *= factor
            nocional *= factor
            comision *= factor
            if nocional < 1e-9:
                return {}
        self.usdt -= cantidad * ejec + comision
        nueva = tengo + cantidad
        self.contado[simbolo] = nueva if abs(nueva) > 1e-12 else 0.0
        self.comisiones += comision
        return self._anotar(simbolo, "contado", cantidad, ejec, comision, 0.0, motivo, precios)

    def operar_perp(self, simbolo: str, cantidad: float, precio: float, motivo: str,
                    precios: Optional[dict] = None, t_ms: Optional[int] = None) -> dict:
        """Compra (cantidad > 0) o vende perpetuo. Vender sin posición abre un corto."""
        if cantidad == 0:
            return {}
        ejec = precio * (1 + DESLIZAMIENTO) if cantidad > 0 else precio * (1 - DESLIZAMIENTO)
        comision = abs(cantidad) * ejec * COMISION_PERP
        pos = self.perp.setdefault(simbolo, Perp())
        realizado = 0.0
        if pos.cantidad == 0:
            # Posición nueva: solo le toca la financiación que se liquide a partir de ahora.
            self.ultimo_funding_ms[simbolo] = int(time.time() * 1000) if t_ms is None else int(t_ms)
        if pos.cantidad == 0 or (pos.cantidad > 0) == (cantidad > 0):
            # Abre o amplía: nuevo precio medio.
            total = pos.cantidad + cantidad
            pos.entrada = (pos.entrada * abs(pos.cantidad) + ejec * abs(cantidad)) / abs(total)
            pos.cantidad = total
        else:
            cierra = min(abs(cantidad), abs(pos.cantidad))
            signo = 1.0 if pos.cantidad > 0 else -1.0
            realizado = signo * cierra * (ejec - pos.entrada)
            resto = abs(cantidad) - cierra
            pos.cantidad -= signo * cierra
            if abs(pos.cantidad) < 1e-12:
                pos.cantidad = 0.0
                pos.entrada = 0.0
            if resto > 1e-12:                       # se dio la vuelta
                pos.cantidad = -signo * resto
                pos.entrada = ejec
        self.usdt += realizado - comision
        self.pnl_realizado += realizado
        self.comisiones += comision
        return self._anotar(simbolo, "perp", cantidad, ejec, comision, realizado, motivo, precios)

    def aplicar_financiacion(self, simbolo: str, tasa: float, precio: float, t_ms: int) -> float:
        """Liquida un evento de financiación. Devuelve lo cobrado (negativo = pagado)."""
        if t_ms <= self.ultimo_funding_ms.get(simbolo, 0):
            return 0.0
        self.ultimo_funding_ms[simbolo] = int(t_ms)
        pos = self.perp.get(simbolo)
        if not pos or pos.cantidad == 0:
            return 0.0
        cobro = -pos.cantidad * precio * tasa       # el largo paga si la tasa es positiva
        self.usdt += cobro
        self.financiacion += cobro
        return cobro

    # ── diario ────────────────────────────────────────────────────────────────

    def _anotar(self, simbolo, pata, cantidad, precio, comision, realizado, motivo, precios) -> dict:
        fila = {
            "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "simbolo": simbolo, "pata": pata,
            "lado": "compra" if cantidad > 0 else "venta",
            "cantidad": round(abs(cantidad), 8), "precio": round(precio, 8),
            "nocional": round(abs(cantidad) * precio, 2), "comision": round(comision, 4),
            "pnl_realizado": round(realizado, 4), "motivo": motivo,
            "usdt": round(self.usdt, 2),
            "patrimonio": round(self.patrimonio(precios), 2) if precios else "",
        }
        if self.ruta_diario:
            nuevo = not os.path.exists(self.ruta_diario)
            with open(self.ruta_diario, "a", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=CAMPOS_DIARIO)
                if nuevo:
                    w.writeheader()
                w.writerow(fila)
        return fila

    # ── persistencia ──────────────────────────────────────────────────────────

    def a_dict(self) -> dict:
        return {
            "version": 2,
            "usdt": self.usdt,
            "contado": {s: q for s, q in self.contado.items() if q},
            "perp": {s: {"cantidad": p.cantidad, "entrada": p.entrada}
                     for s, p in self.perp.items() if p.cantidad},
            "capital_inicial": self.capital_inicial,
            "comisiones": self.comisiones,
            "financiacion": self.financiacion,
            "pnl_realizado": self.pnl_realizado,
            "ultimo_funding_ms": self.ultimo_funding_ms,
            "creada_utc": self.creada_utc,
        }

    def guardar(self, ruta: str) -> None:
        """Escritura atómica: o queda el estado nuevo entero o el anterior."""
        carpeta = os.path.dirname(os.path.abspath(ruta))
        fd, tmp = tempfile.mkstemp(dir=carpeta, prefix=".estado_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.a_dict(), fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, ruta)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    @classmethod
    def cargar(cls, ruta: str, ruta_diario: Optional[str] = None) -> "Cartera":
        with open(ruta, encoding="utf-8") as fh:
            d = json.load(fh)
        c = cls(usdt=float(d["usdt"]), ruta_diario=ruta_diario)
        c.contado = {s: float(q) for s, q in d.get("contado", {}).items()}
        c.perp = {s: Perp(float(p["cantidad"]), float(p["entrada"]))
                  for s, p in d.get("perp", {}).items()}
        c.capital_inicial = float(d.get("capital_inicial", c.usdt))
        c.comisiones = float(d.get("comisiones", 0.0))
        c.financiacion = float(d.get("financiacion", 0.0))
        c.pnl_realizado = float(d.get("pnl_realizado", 0.0))
        c.ultimo_funding_ms = {s: int(t) for s, t in d.get("ultimo_funding_ms", {}).items()}
        c.creada_utc = d.get("creada_utc", "")
        return c

    @classmethod
    def nueva(cls, capital: float, ruta_diario: Optional[str] = None) -> "Cartera":
        return cls(usdt=float(capital), capital_inicial=float(capital), ruta_diario=ruta_diario,
                   creada_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def ordenes(cartera: Cartera, precios: dict, base: dict, neto: dict, banda_base: float,
            banda_cobertura: float, minimo_usdt: float, modo: str = "base_cubierta",
            forzar: bool = False, banda_sin_base: float = 0.20) -> list:
    """Órdenes para llevar la cartera a los pesos objetivo.

    `base` y `neto` son pesos objetivo por símbolo. Devuelve una lista de
    (pata, simbolo, cantidad con signo). Primero van las ventas de contado, para
    que haya USDT cuando lleguen las compras.

    La cobertura se pide como fracción del contado que REALMENTE hay (el que
    quedará tras reajustar la base), no de su objetivo: «cubre el 60 % de lo que
    tengo». Así, con la tendencia plena la cobertura es exactamente cero aunque
    la base se haya desviado dentro de su banda, y con la tendencia en contra
    cubre todo lo que hay y no una cifra teórica.

    La cobertura se reajusta cuando la exposición se aparta de su objetivo más de
    `banda_cobertura` × el contado de esa moneda (`estrategia.hay_que_cubrir`).
    """
    from bot.estrategia import hay_que_cubrir, hay_que_mover   # import local: evita ciclo

    pat = cartera.patrimonio(precios)
    if pat <= 0:
        return []
    out_contado, out_perp = [], []
    for s in sorted(set(base) | set(neto) | set(cartera.contado) | set(cartera.perp)):
        if s not in precios or precios[s] <= 0:
            continue
        px = precios[s]
        w_base = base.get(s, 0.0) if modo == "base_cubierta" else 0.0
        w_neto = neto.get(s, 0.0)
        w_contado = cartera.contado.get(s, 0.0) * px / pat
        w_perp = cartera.perp.get(s, Perp()).cantidad * px / pat

        if forzar or bool(hay_que_mover([w_contado], [w_base], banda_base)[0]):
            delta = (w_base - w_contado) * pat
            if abs(delta) >= minimo_usdt:
                out_contado.append(("contado", s, delta / px))
                w_contado = w_base

        if w_base > 0:
            expuesto = w_neto / w_base              # fracción de la base que debe quedar expuesta
            w_perp_obj = -(1.0 - expuesto) * w_contado
        else:
            w_perp_obj = w_neto                     # sin base: la exposición va entera en perpetuo
        if abs(w_perp_obj) * pat < minimo_usdt:
            w_perp_obj = 0.0
        if w_base > 0:
            mover = hay_que_cubrir([w_perp], [w_perp_obj], [w_contado], [w_neto == 0.0], banda_cobertura)[0]
        else:
            mover = hay_que_mover([w_perp], [w_perp_obj], banda_sin_base)[0]
        if forzar or bool(mover):
            delta = (w_perp_obj - w_perp) * pat
            if abs(delta) >= minimo_usdt:
                out_perp.append(("perp", s, delta / px))

    ventas = [o for o in out_contado if o[2] < 0]
    compras = [o for o in out_contado if o[2] > 0]
    return ventas + out_perp + compras
