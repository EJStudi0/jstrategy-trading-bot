"""Avisos al operador: siempre al registro, y opcionalmente a Telegram.

Telegram solo se usa si el usuario lo activa y define ``TELEGRAM_BOT_TOKEN`` y
``TELEGRAM_CHAT_ID``. Un fallo al notificar nunca debe interrumpir la operativa.
"""

from __future__ import annotations

import json
import logging
import os
import time

import requests

log = logging.getLogger("centinela.avisos")


RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _json(nombre: str) -> dict:
    try:
        with open(os.path.join(RAIZ, nombre), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


class Notifier:
    """Con ``telegram`` activado usa las variables de entorno o, si no hay, el Telegram que el dueño
    conectó desde el panel (``telegram.json``; se relee en cada aviso, así no hace falta reiniciar)."""

    def __init__(self, telegram: bool = False, min_interval_s: float = 300.0) -> None:
        self.telegram = telegram
        self._env = (os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")) if telegram else ("", "")
        self.min_interval_s = min_interval_s
        self._last: dict[str, float] = {}

    def _destino(self) -> tuple:
        if not self.telegram:
            return "", ""
        if all(self._env):
            return self._env
        g = _json("telegram.json")
        if not g.get("token") or not g.get("chat"):
            return "", ""
        if not (_json("estado_asistente.json").get("prefs", {}).get("telegram", {}).get("activo", True)):
            return "", ""   # el dueño apagó los avisos a Telegram desde el panel
        return g["token"], g["chat"]

    @property
    def enabled(self) -> bool:
        return all(self._destino())

    def send(self, text: str, level: str = "info", key: str | None = None) -> None:
        """Envía un aviso. ``key`` agrupa avisos repetitivos para no inundar (uno cada 5 min)."""
        getattr(log, "warning" if level == "alerta" else "info")(text)
        if key is not None:
            now = time.time()
            if now - self._last.get(key, 0.0) < self.min_interval_s:
                return
            self._last[key] = now
        token, chat = self._destino()
        if not token:
            return
        prefix = "🚨 " if level == "alerta" else ""
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": f"{prefix}Centinela BTC\n{text}", "disable_web_page_preview": True},
                timeout=10,
            )
        except requests.RequestException as exc:   # sin el texto: lleva la dirección, y la dirección lleva la clave
            log.warning("no se pudo enviar el aviso a Telegram: %s", type(exc).__name__)
