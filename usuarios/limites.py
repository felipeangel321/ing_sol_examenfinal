"""Límites del microservicio de usuarios (sin depender del código del asistente).

Es la misma idea que backend/seguridad/limitador.py y flujo.py, copiada a propósito:
el microservicio se construye y corre solo, sin el resto del proyecto.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict, deque
from threading import Lock


class Limitador:
    """N pedidos por clave dentro de una ventana de tiempo."""

    def __init__(self, maximo: int, ventana_s: float, reloj=time.monotonic) -> None:
        self.maximo, self.ventana_s, self._reloj = maximo, ventana_s, reloj
        self._pedidos: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _vigentes(self, clave: str, ahora: float) -> int:
        pedidos = self._pedidos.get(clave)
        if pedidos is None:
            return 0
        while pedidos and ahora - pedidos[0] >= self.ventana_s:
            pedidos.popleft()
        if not pedidos:
            del self._pedidos[clave]
        return len(pedidos)

    def queda(self, clave: str) -> bool:
        with self._lock:
            return self._vigentes(clave, self._reloj()) < self.maximo

    def permitir(self, clave: str) -> bool:
        ahora = self._reloj()
        with self._lock:
            if self._vigentes(clave, ahora) >= self.maximo:
                return False
            self._pedidos[clave].append(ahora)
            return True


class FrenoInundacion:
    """Middleware ASGI: más de N peticiones por minuto desde una IP → 429."""

    def __init__(self, app, maximo: int | None = None) -> None:
        self.app = app
        self.limitador = Limitador(maximo or int(os.getenv("LIMITE_PETICIONES_MIN", "120") or 120), 60)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cliente = scope.get("client")
        if self.limitador.permitir(cliente[0] if cliente else "desconocida"):
            return await self.app(scope, receive, send)
        cuerpo = json.dumps({"detail": "Demasiadas solicitudes. Intenta más tarde."}).encode()
        await send({"type": "http.response.start", "status": 429,
                    "headers": [(b"content-type", b"application/json"), (b"retry-after", b"60")]})
        await send({"type": "http.response.body", "body": cuerpo})
