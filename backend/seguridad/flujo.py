"""Freno de inundación: corta a una IP que manda demasiadas peticiones de cualquier tipo.

El límite por minuto del chat (limitador.py) cuenta preguntas; esto cuenta TODO (páginas,
/api/metrics, /entrar, conversaciones...) y responde 429 antes de llegar a la app: sin
traza, sin SQLite, sin modelo. Así un script que martilla el servidor no llena el disco
de trazas ni deja la app ocupada para el resto.

Va como middleware ASGI puro (no BaseHTTPMiddleware) para que cada petición rechazada
cueste lo mínimo. La IP es la real del cliente: uvicorn --proxy-headers la toma del
X-Forwarded-For que Caddy reescribe (ver deploy/).
"""
from __future__ import annotations

import json
import os

from backend.seguridad.limitador import LimitadorTasa

RESPUESTA = json.dumps({"detail": "Demasiadas solicitudes. Intenta más tarde."}).encode()


class FrenoInundacion:
    def __init__(self, app, maximo: int | None = None, ventana_s: float = 60.0) -> None:
        self.app = app
        maximo = maximo or int(os.getenv("LIMITE_PETICIONES_MIN", "120") or 120)
        self.limitador = LimitadorTasa(maximo=maximo, ventana_s=ventana_s)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cliente = scope.get("client")
        ip = cliente[0] if cliente else "desconocida"
        if self.limitador.permitir(ip):
            return await self.app(scope, receive, send)
        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": [(b"content-type", b"application/json"), (b"retry-after", b"60")],
        })
        await send({"type": "http.response.body", "body": RESPUESTA})
