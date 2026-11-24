"""Contraseñas: nunca se guardan; se guarda un hash scrypt con sal propia (librería estándar).

scrypt es lento a propósito y usa memoria: probar millones de contraseñas contra una base
robada sale caro. Ese mismo costo es un riesgo de DoS (cada intento gasta CPU), por eso el
inicio de sesión tiene límite de intentos (app.py).
"""
from __future__ import annotations

import hashlib
import hmac
import os

N, R, P = 2**14, 8, 1  # ~16 MB y unas decenas de ms por intento
LARGO_CLAVE = 32


def hashear(contrasena: str) -> str:
    sal = os.urandom(16)
    h = hashlib.scrypt(contrasena.encode(), salt=sal, n=N, r=R, p=P, dklen=LARGO_CLAVE)
    return f"scrypt${N}${R}${P}${sal.hex()}${h.hex()}"


def verificar(contrasena: str, guardado: str) -> bool:
    try:
        _, n, r, p, sal, h = guardado.split("$")
        calculado = hashlib.scrypt(contrasena.encode(), salt=bytes.fromhex(sal), n=int(n), r=int(r),
                                   p=int(p), dklen=len(bytes.fromhex(h)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculado.hex(), h)


# Si el correo no existe se verifica igual contra este hash: la respuesta tarda lo mismo
# y no delata qué correos tienen cuenta.
HASH_FALSO = hashear(os.urandom(16).hex())
