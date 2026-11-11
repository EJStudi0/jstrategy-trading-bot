"""Cliente HTTP mínimo con reintentos y espera exponencial para APIs públicas."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

_session: requests.Session | None = None


class HttpError(RuntimeError):
    """Fallo definitivo al consultar una fuente de datos."""


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        # Nombre de cliente genérico: no se envía ningún dato del usuario.
        s.headers.update({"User-Agent": "centinela-btc/1.0"})
        _session = s
    return _session


def get(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float = 20.0,
    retries: int = 4,
    backoff: float = 1.0,
    ok_404: bool = False,
) -> requests.Response | None:
    """GET con reintentos ante errores de red, 429/418 y 5xx.

    Devuelve ``None`` únicamente si ``ok_404`` y el recurso no existe.
    Los errores 4xx restantes se consideran definitivos (no se reintentan).
    """
    last: Exception | None = None
    for attempt in range(retries + 1):
        wait = backoff * (2**attempt)
        try:
            r = session().get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:  # red caída, timeout, DNS...
            last = exc
        else:
            if r.status_code == 200:
                return r
            if r.status_code == 404 and ok_404:
                return None
            if r.status_code in (418, 429) or r.status_code >= 500:
                last = HttpError(f"HTTP {r.status_code} en {url}")
                retry_after = r.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = max(wait, float(retry_after))
                    except ValueError:
                        pass
            else:
                raise HttpError(f"HTTP {r.status_code} en {url}: {r.text[:200]}")
        if attempt < retries:
            log.debug("reintento %d/%d para %s (%s)", attempt + 1, retries, url, last)
            time.sleep(min(wait, 60.0))
    raise HttpError(f"sin respuesta válida tras {retries + 1} intentos: {url} ({last})")
