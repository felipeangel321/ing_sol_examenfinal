"""Tokens de sesión con formato JWT (HS256), solo con la librería estándar.

El servicio de usuarios los firma al iniciar sesión; la app del asistente los verifica
con la misma clave (JWT_SECRETO) sin consultar la base de usuarios: así cada servicio
es dueño de sus datos y la app no depende de que el otro responda en cada pregunta.

Decisiones de seguridad:
- Solo se acepta "alg": "HS256". Un token con "alg": "none" (sin firma) se rechaza.
- La firma se compara en tiempo constante (hmac.compare_digest).
- Todo token vence ("exp"); por defecto a las 8 horas.
- Sin JWT_SECRETO (uso local) se genera una clave al azar al arrancar: las sesiones no
  sobreviven a un reinicio, pero nunca hay una clave fija escrita en el código.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

DURACION_S = 8 * 3600
LARGO_MINIMO_SECRETO = 32
_SECRETO_LOCAL = secrets.token_hex(32)


def _secreto() -> bytes:
    secreto = os.getenv("JWT_SECRETO", "").strip()
    return (secreto if len(secreto) >= LARGO_MINIMO_SECRETO else _SECRETO_LOCAL).encode()


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def _de_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _firma(mensaje: str) -> str:
    return _b64(hmac.new(_secreto(), mensaje.encode(), hashlib.sha256).digest())


def crear_token(usuario_id: int, correo: str, rol: str, duracion_s: int = DURACION_S) -> str:
    ahora = int(time.time())
    cabecera = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    datos = {"sub": str(usuario_id), "correo": correo, "rol": rol, "iat": ahora, "exp": ahora + duracion_s}
    cuerpo = _b64(json.dumps(datos, separators=(",", ":")).encode())
    return f"{cabecera}.{cuerpo}.{_firma(f'{cabecera}.{cuerpo}')}"


def verificar_token(token: str | None) -> dict | None:
    """Los datos del token si es válido y no venció; None en cualquier otro caso."""
    if not token or token.count(".") != 2 or len(token) > 2048:
        return None
    cabecera, cuerpo, firma = token.split(".")
    try:
        if json.loads(_de_b64(cabecera)).get("alg") != "HS256":
            return None
        if not hmac.compare_digest(firma.encode(), _firma(f"{cabecera}.{cuerpo}").encode()):
            return None
        datos = json.loads(_de_b64(cuerpo))
    except (ValueError, TypeError, AttributeError):
        return None
    if not isinstance(datos, dict) or not isinstance(datos.get("exp"), int) or datos["exp"] < time.time():
        return None
    return datos
