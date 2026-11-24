"""Quién pregunta: la sesión que entrega el microservicio de usuarios (usuarios/).

La app no consulta la base de usuarios: verifica la firma del token (usuarios/tokens.py)
con la clave compartida JWT_SECRETO. Así el chat sigue funcionando aunque el servicio
de usuarios se reinicie, y la base de usuarios solo la toca su propio servicio.

EXIGIR_LOGIN=true (por defecto): el chat y las conversaciones piden sesión → 401 sin ella.
Las pruebas antiguas lo apagan (tests/conftest.py); las de usuarios lo encienden.
"""
from __future__ import annotations

import os

from fastapi import HTTPException, Request

from usuarios.app import token_de
from usuarios.tokens import verificar_token


def login_exigido() -> bool:
    return os.getenv("EXIGIR_LOGIN", "true").strip().lower() != "false"


def usuario_actual(request: Request) -> dict | None:
    """Datos del token ({"sub", "correo", "rol", ...}) o None si no hay sesión válida."""
    return verificar_token(token_de(request))


def exigir_usuario(request: Request) -> dict | None:
    """Dependencia del chat: sin sesión (y con login exigido) responde 401."""
    usuario = usuario_actual(request)
    if usuario is None and login_exigido():
        raise HTTPException(status_code=401, detail="Inicia sesión para usar el asistente.")
    return usuario


def es_corredor(usuario: dict | None) -> bool:
    return bool(usuario) and usuario.get("rol") == "corredor"


def clave_de(usuario: dict | None, ip: str) -> str:
    """A quién se le cuentan el límite por minuto y el cupo: a la cuenta si hay sesión
    (en el WiFi del Duoc todo el curso comparte IP), si no, a la IP."""
    return f"usuario:{usuario['sub']}" if usuario else ip
