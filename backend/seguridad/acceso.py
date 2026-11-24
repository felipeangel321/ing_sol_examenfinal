"""Acceso del dueño de la demo con un link secreto (sin usuario ni contraseña).

  https://<IP>/entrar?clave=<CLAVE_ACCESO>   → deja una cookie y abre el panel.

Con la cookie, el navegador del dueño usa su cupo reservado (cupos.py) y puede ver el
panel y /metricas. Sin CLAVE_ACCESO configurada (uso local) no hay dueño ni cupos: todo
queda abierto, como antes.

Decisiones:
- La cookie no guarda la clave sino un HMAC de ella: si alguien ve la cookie, no
  obtiene el link.
- Se compara en tiempo constante (hmac.compare_digest): no se puede adivinar la clave
  midiendo cuánto tarda la respuesta.
- La clave la genera bootstrap-ec2.sh con `openssl rand -hex 16` (128 bits): probarla a
  fuerza bruta es imposible en la práctica, y además el freno de inundación (flujo.py)
  corta a quien insista.
- HttpOnly (JavaScript no la lee), Secure (solo por HTTPS) y SameSite=Lax.
"""
from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import HTTPException, Request

COOKIE = "acceso"
LARGO_MINIMO = 24  # una clave más corta se ignora: mejor sin dueño que con clave débil


def clave_configurada() -> str:
    clave = os.getenv("CLAVE_ACCESO", "").strip()
    return clave if len(clave) >= LARGO_MINIMO else ""


def ficha_de(clave: str) -> str:
    return hmac.new(clave.encode(), b"proyecto-seguros/dueno", hashlib.sha256).hexdigest()


def clave_correcta(intento: str) -> bool:
    clave = clave_configurada()
    return bool(clave) and hmac.compare_digest(intento.encode(), clave.encode())


def es_dueno(request: Request) -> bool:
    clave = clave_configurada()
    if not clave:
        return False
    cookie = request.cookies.get(COOKIE, "")
    return bool(cookie) and hmac.compare_digest(cookie.encode(), ficha_de(clave).encode())


def exigir_dueno(request: Request) -> None:
    """Dependencia para el panel y /metricas: solo el dueño, si hay clave configurada."""
    if clave_configurada() and not es_dueno(request):
        raise HTTPException(status_code=403, detail="Solo el administrador de la demo puede ver el panel.")
