"""Avisos al operador: siempre al registro, y opcionalmente a Telegram.

Telegram solo se usa si el usuario lo activa y define ``TELEGRAM_BOT_TOKEN`` y
``TELEGRAM_CHAT_ID``. Un fallo al notificar nunca debe interrumpir la operativa.
"""

from __future__ import annotations

import logging
import os
import time

import requests

log = logging.getLogger("centinela.avisos")


class Notifier:
    def __init__(self, telegram: bool = False, min_interval_s: float = 300.0) -> None:
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "") if telegram else ""
        self.chat = os.environ.get("TELEGRAM_CHAT_ID", "") if telegram else ""
        self.enabled = bool(self.token and self.chat)
        if telegram and not self.enabled:
            log.warning("telegram activado pero faltan TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID: solo se registrará en disco")
        self.min_interval_s = min_interval_s
        self._last: dict[str, float] = {}

    def send(self, text: str, level: str = "info", key: str | None = None) -> None:
        """Envía un aviso. ``key`` agrupa avisos repetitivos para no inundar (uno cada 5 min)."""
        getattr(log, "warning" if level == "alerta" else "info")(text)
        if key is not None:
            now = time.time()
            if now - self._last.get(key, 0.0) < self.min_interval_s:
                return
            self._last[key] = now
        if not self.enabled:
            return
        prefix = "🚨 " if level == "alerta" else ""
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat, "text": f"{prefix}Centinela BTC\n{text}", "disable_web_page_preview": True},
                timeout=10,
            )
        except requests.RequestException as exc:
            log.warning("no se pudo enviar el aviso a Telegram: %s", exc)
